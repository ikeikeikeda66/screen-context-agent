import json
import os
import stat
import sys
import tomllib
import pytest
from test_core import settings
from screen_context import access, client_config as cc

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions and symlinks")


@pytest.fixture(autouse=True)
def fake_home(tmp_path, monkeypatch):
    home = tmp_path / "home"; home.mkdir()
    monkeypatch.setattr(cc.Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(cc, "PLATFORM", "darwin")
    return home


COMMAND = ["/Applications/ScreenContext.app/Contents/MacOS/screen-context"]
JSON_CLIENTS = {"claude-desktop": ("Library/Application Support/Claude/claude_desktop_config.json", "mcpServers"),
                "cursor": (".cursor/mcp.json", "mcpServers"), "gemini": (".gemini/settings.json", "mcpServers"),
                "vscode": ("Library/Application Support/Code/User/mcp.json", "servers")}
CODEX = ".codex/config.toml"


def target(home, rel):
    path = home / rel; path.parent.mkdir(parents=True, exist_ok=True); return path


def run(settings, client, **kw):
    change = cc.plan(settings, client, command=COMMAND, **kw)
    return change, (cc.apply(change) if change.action in ("add", "update", "unchanged") else None)


def backups(path): return sorted(path.parent.glob(path.name + ".screen-context-*.bak"))


@pytest.mark.parametrize("client", JSON_CLIENTS)
def test_json_client_add_keeps_other_servers_and_order_and_is_idempotent(settings, fake_home, client):
    rel, key = JSON_CLIENTS[client]; path = target(fake_home, rel)
    original = json.dumps({"theme": "dark", key: {"zeta": {"command": "z"}, "alpha": {"command": "a", "env": {"K": "v"}}}, "tail": [1]}, indent=4)
    path.write_text(original); path.chmod(0o640)
    change, result = run(settings, client)
    assert change.action == "add" and result["token_issued"] and len(backups(path)) == 1
    assert backups(path)[0].read_bytes() == original.encode() and stat.S_IMODE(backups(path)[0].stat().st_mode) == 0o600
    data = json.loads(path.read_text())
    assert list(data) == ["theme", key, "tail"] and list(data[key]) == ["zeta", "alpha", "screen-context"]
    assert data[key]["alpha"] == {"command": "a", "env": {"K": "v"}} and stat.S_IMODE(path.stat().st_mode) == 0o640
    entry = data[key]["screen-context"]
    assert entry["command"] == COMMAND[0] and entry["env"]["SCREEN_CONTEXT_HOME"] == str(settings.root)
    assert (entry.get("type") == "stdio") == (client == "vscode")
    assert access.authenticate(settings, entry["env"][access.TOKEN_ENV], "standard") == client
    first = path.read_bytes()
    again, result = run(settings, client)
    assert again.action == "unchanged" and result["backup"] is None and path.read_bytes() == first and len(backups(path)) == 1
    assert "sc_" not in again.before + again.after


def test_new_file_is_created_0600_and_missing_folder_is_not_installed(settings, fake_home):
    assert cc.plan(settings, "cursor", command=COMMAND).reason == "not_installed"
    (fake_home / ".cursor").mkdir()
    change, result = run(settings, "cursor")
    assert change.action == "add" and result["backup"] is None
    assert stat.S_IMODE((fake_home / ".cursor/mcp.json").stat().st_mode) == 0o600


@pytest.mark.parametrize("text", ['{"mcpServers": {} // c\n}', "{broken", "[1]", '{"mcpServers": []}', '{"a": 1, "a": 2}'])
def test_unreadable_or_commented_json_is_manual_and_untouched(settings, fake_home, text):
    path = target(fake_home, ".cursor/mcp.json"); path.write_text(text)
    change = cc.plan(settings, "cursor", command=COMMAND)
    assert change.action == "manual" and change.reason in ("unreadable", "unsupported") and "<token>" in change.manual
    assert path.read_text() == text and not backups(path) and access.clients(settings) == []


@pytest.mark.parametrize("client", ["claude-code", "generic"])
def test_clients_without_a_file_are_manual(settings, client):
    assert cc.plan(settings, client, command=COMMAND).reason == "manual_only"


def test_other_platform_is_manual(settings, fake_home, monkeypatch):
    monkeypatch.setattr(cc, "PLATFORM", "win32"); (fake_home / ".cursor").mkdir()
    assert cc.plan(settings, "cursor", command=COMMAND).reason == "platform"


def test_symlink_writes_the_target_and_keeps_the_link(settings, fake_home):
    real = target(fake_home, "dotfiles/mcp.json"); real.write_text('{"mcpServers": {}}')
    link = target(fake_home, ".cursor/mcp.json"); link.symlink_to(real)
    change, _ = run(settings, "cursor")
    assert link.is_symlink() and "screen-context" in json.loads(real.read_text())["mcpServers"] and len(backups(real)) == 1


def test_other_data_folder_is_a_conflict_until_confirmed(settings, fake_home, tmp_path):
    path = target(fake_home, ".cursor/mcp.json")
    path.write_text(json.dumps({"mcpServers": {"screen-context": {"command": "x", "env": {"SCREEN_CONTEXT_HOME": str(tmp_path / "elsewhere"), access.TOKEN_ENV: "sc_old"}}}}))
    before = path.read_bytes()
    change = cc.plan(settings, "cursor", command=COMMAND)
    assert change.action == "conflict" and change.other_home.endswith("elsewhere")
    with pytest.raises(RuntimeError): cc.apply(change)
    assert path.read_bytes() == before
    forced = cc.plan(settings, "cursor", command=COMMAND, force=True)
    assert forced.action == "update"; cc.apply(forced)
    assert json.loads(path.read_text())["mcpServers"]["screen-context"]["env"]["SCREEN_CONTEXT_HOME"] == str(settings.root)


def test_valid_token_is_reused_and_a_stale_one_is_replaced(settings, fake_home):
    path = target(fake_home, ".cursor/mcp.json"); path.write_text("{}")
    run(settings, "cursor")
    token = json.loads(path.read_text())["mcpServers"]["screen-context"]["env"][access.TOKEN_ENV]
    # same token, different command: the entry changes, the token stays
    change = cc.plan(settings, "cursor", command=["/new/screen-context"])
    assert change.action == "update" and change.reuse_token == token
    assert cc.apply(change)["token_issued"] is False
    assert json.loads(path.read_text())["mcpServers"]["screen-context"]["env"][access.TOKEN_ENV] == token
    access.revoke(settings, "cursor")
    change, result = run(settings, "cursor")
    assert change.reuse_token == "" and result["token_issued"]
    assert json.loads(path.read_text())["mcpServers"]["screen-context"]["env"][access.TOKEN_ENV] != token
    # a different profile cannot reuse the token
    assert cc.plan(settings, "cursor", command=COMMAND, profile="full").reuse_token == ""


def test_failed_write_revokes_the_token_just_issued(settings, fake_home, monkeypatch):
    path = target(fake_home, ".cursor/mcp.json"); path.write_text("{}")
    change = cc.plan(settings, "cursor", command=COMMAND)
    monkeypatch.setattr(cc.os, "replace", lambda *a: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError): cc.apply(change)
    assert path.read_text() == "{}" and not list(path.parent.glob("*.tmp"))
    assert [c["state"] for c in access.clients(settings)] == ["revoked"]


def test_file_changed_after_plan_is_refused(settings, fake_home):
    path = target(fake_home, ".cursor/mcp.json"); path.write_text("{}")
    change = cc.plan(settings, "cursor", command=COMMAND); path.write_text('{"x": 1}')
    with pytest.raises(RuntimeError): cc.apply(change)
    assert path.read_text() == '{"x": 1}' and access.clients(settings) == []


def test_only_the_newest_five_backups_are_kept(settings, fake_home):
    path = target(fake_home, ".cursor/mcp.json"); path.write_text("{}")
    foreign = path.parent / "mcp.json.bak"; foreign.write_text("mine")
    for i in range(7):
        path.write_text(json.dumps({"n": i})); run(settings, "cursor")
        access.revoke(settings, "cursor")  # forces a new token, so the next run rewrites the file
        path.write_text(json.dumps({"n": i}))
    assert len(backups(path)) == 5 and foreign.read_text() == "mine"
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in backups(path))


# ---- Codex (TOML) -------------------------------------------------------------------------------------

CODEX_CASES = {
    "empty": "",
    "comments": '# my settings\nmodel = "o3"  # keep\n\n[mcp_servers.other]\ncommand = "x"  # note\nargs = ["a"]\n',
    "no_servers": 'model = "o3"\n[profiles.a]\nx = 1\n',
    "existing_table": 'a = 1\n\n[mcp_servers.screen-context]\ncommand = "old"  # c\nstartup_timeout_sec = 30\n\n[mcp_servers.screen-context.env]\nEXTRA = "1"\n\n[mcp_servers.z]\ncommand = "z"\n',
    "inline_entry": '[mcp_servers]\nscreen-context = { command = "old", startup_timeout_sec = 5 }\nother = { command = "x" }\n',
    "crlf": 'a = 1\r\n[mcp_servers.o]\r\ncommand = "x"\r\n',
}


@pytest.mark.parametrize("case", CODEX_CASES)
def test_codex_toml_edit_keeps_everything_else(settings, fake_home, case):
    path = target(fake_home, CODEX); text = CODEX_CASES[case]; path.write_bytes(text.encode())
    before = tomllib.loads(text)
    change, result = run(settings, "codex")
    assert change.action in ("add", "update")
    after = tomllib.loads(path.read_text())
    entry = after["mcp_servers"].pop("screen-context")
    before.get("mcp_servers", {}).pop("screen-context", None)
    if not after["mcp_servers"]: del after["mcp_servers"]
    if "mcp_servers" in before and not before["mcp_servers"]: del before["mcp_servers"]
    assert after == before
    assert entry["command"] == COMMAND[0] and entry["env"]["SCREEN_CONTEXT_HOME"] == str(settings.root)
    if text: assert backups(path)[0].read_bytes() == text.encode()
    for kept in ("# my settings", "# keep", "# note"):
        if kept in text: assert kept in path.read_text()
    if case == "existing_table": assert entry["startup_timeout_sec"] == 30 and entry["env"]["EXTRA"] == "1"
    if case == "crlf": assert "\n" not in path.read_text(newline="").replace("\r\n", "")
    first = path.read_bytes(); n = len(backups(path))
    again, _ = run(settings, "codex")
    assert again.action == "unchanged" and path.read_bytes() == first and len(backups(path)) == n


@pytest.mark.parametrize("text", ["a = ", 'mcp_servers.screen-context.command = "x"\nmcp_servers.o.command = "y"\n', 'mcp_servers = { other = { command = "x" } }\n',
                                  '[[mcp_servers]]\nname = "x"\n'])
def test_codex_unusual_toml_is_manual_and_untouched(settings, fake_home, text):
    path = target(fake_home, CODEX); path.write_text(text)
    change = cc.plan(settings, "codex", command=COMMAND)
    assert change.action == "manual" and "[mcp_servers.screen-context]" in change.manual
    assert path.read_text() == text and not backups(path)


# ---- removal ------------------------------------------------------------------------------------------

def test_remove_takes_out_only_screen_context(settings, fake_home):
    path = target(fake_home, ".cursor/mcp.json")
    path.write_text(json.dumps({"mcpServers": {"a": {"command": "a"}, "sc-work": {"command": "x", "env": {access.TOKEN_ENV: "sc_zzzzzzzzzz"}}}}))
    run(settings, "cursor")
    plan = cc.remove_plan("cursor")
    assert plan.action == "remove" and plan.related == ["sc-work"]
    result = cc.remove(plan)
    assert list(json.loads(path.read_text())["mcpServers"]) == ["a", "sc-work"] and result["backup"]
    assert cc.remove_plan("cursor").action == "absent"


def test_remove_from_codex_keeps_the_rest(settings, fake_home):
    path = target(fake_home, CODEX); path.write_text(CODEX_CASES["comments"]); run(settings, "codex")
    cc.remove(cc.remove_plan("codex"))
    assert tomllib.loads(path.read_text()) == tomllib.loads(CODEX_CASES["comments"])
    path.write_text(""); run(settings, "codex"); cc.remove(cc.remove_plan("codex"))
    assert tomllib.loads(path.read_text()) in ({}, {"mcp_servers": {}})


def test_remove_when_no_file_or_folder(settings, fake_home):
    assert cc.remove_plan("cursor").reason == "not_installed"
    (fake_home / ".cursor").mkdir()
    assert cc.remove_plan("cursor").action == "absent"


@pytest.mark.skipif(sys.platform != "darwin", reason="runs the CLI with the macOS paths")
def test_cli_write_and_dry_run(settings, fake_home):
    import subprocess, sys
    (fake_home / ".cursor").mkdir()
    env = {"SCREEN_CONTEXT_HOME": str(settings.root), "SCREEN_CONTEXT_PLAINTEXT": "1", "SCREEN_CONTEXT_LANG": "en", "PATH": "/usr/bin:/bin", "HOME": str(fake_home)}
    cli = lambda *a: subprocess.run([sys.executable, "-m", "screen_context.cli", "mcp-config", "--client", "cursor", *a], env=env, capture_output=True, text=True, encoding="utf-8")
    dry = cli("--write", "--dry-run")
    assert dry.returncode == 0 and "Dry run" in dry.stdout and "+" in dry.stdout and "sc_" not in dry.stdout
    assert not (fake_home / ".cursor/mcp.json").exists() and access.clients(settings) == []
    done = cli("--write")
    assert done.returncode == 0 and "Added" in done.stdout and (fake_home / ".cursor/mcp.json").exists()
    assert "Nothing was changed" in cli("--write").stdout
    assert cli("--dry-run").returncode == 2  # argparse error
    assert json.loads(cli().stdout)["mcpServers"]["screen-context"]["env"][access.TOKEN_ENV].startswith("sc_")  # old behaviour


@pytest.mark.skipif(sys.platform != "darwin", reason="runs the CLI with the macOS paths")
def test_cli_write_dry_run_on_a_manual_client_issues_no_token(settings, fake_home):
    import subprocess, sys
    env = {"SCREEN_CONTEXT_HOME": str(settings.root), "SCREEN_CONTEXT_PLAINTEXT": "1", "SCREEN_CONTEXT_LANG": "en", "PATH": "/usr/bin:/bin", "HOME": str(fake_home)}
    done = subprocess.run([sys.executable, "-m", "screen_context.cli", "mcp-config", "--client", "claude-code", "--write", "--dry-run"], env=env, capture_output=True, text=True, encoding="utf-8")
    assert done.returncode == 0 and "<token>" in done.stdout and access.clients(settings) == []


# ---- review fixes -------------------------------------------------------------------------------------

LEAK = "sc_LEAKLEAKLEAKLEAK_0123456789"


def test_dry_run_text_never_shows_a_token_from_headers(settings, fake_home):
    path = target(fake_home, ".cursor/mcp.json")
    path.write_text(json.dumps({"mcpServers": {"screen-context": {"url": "http://127.0.0.1:8765/mcp", "headers": {"Authorization": "Bearer " + LEAK}}}}))
    change = cc.plan(settings, "cursor", command=COMMAND, force=True)
    assert change.action == "update"
    assert "LEAK" not in change.before + change.after and '"Authorization": "***"' in change.before


def test_dry_run_text_never_shows_a_token_from_args(settings, fake_home):
    path = target(fake_home, ".cursor/mcp.json")
    path.write_text(json.dumps({"mcpServers": {"screen-context": {"command": "x", "args": ["--token", LEAK]}}}))
    change = cc.plan(settings, "cursor", command=COMMAND)
    assert change.action == "update"
    assert "LEAK" not in change.before + change.after and "sc_***" in change.before


def test_http_entry_is_a_conflict_until_forced(settings, fake_home):
    path = target(fake_home, ".cursor/mcp.json")
    path.write_text(json.dumps({"mcpServers": {"screen-context": {"url": "http://127.0.0.1:8765/mcp"}}}))
    before = path.read_bytes()
    change = cc.plan(settings, "cursor", command=COMMAND)
    assert change.action == "conflict" and change.reason == "http"
    with pytest.raises(RuntimeError): cc.apply(change)
    assert path.read_bytes() == before and access.clients(settings) == []
    forced = cc.plan(settings, "cursor", command=COMMAND, force=True)
    assert forced.action == "update"
    cc.apply(forced)
    entry = json.loads(path.read_text())["mcpServers"]["screen-context"]
    assert "url" not in entry and entry["command"] == COMMAND[0]


@pytest.mark.parametrize("text, reason", [('{"mcpServers": {"x": {"n": 1e400}}}', "unsupported"),
                                          ('{"mcpServers": {"x": {"n": NaN}}}', "unreadable"),
                                          ('{"mcpServers": {"x": {"n": -Infinity}}}', "unreadable")])
def test_non_finite_numbers_are_manual_and_untouched(settings, fake_home, text, reason):
    path = target(fake_home, ".cursor/mcp.json"); path.write_text(text)
    change = cc.plan(settings, "cursor", command=COMMAND)
    assert change.action == "manual" and change.reason == reason and "<token>" in change.manual
    assert path.read_text() == text and not backups(path) and access.clients(settings) == []


def test_token_of_another_client_is_named_when_replaced(settings, fake_home):
    path = target(fake_home, ".cursor/mcp.json"); path.write_text("{}")
    run(settings, "cursor")
    change, result = run(settings, "cursor", name="cursor-full", profile="full")
    assert change.action == "update" and change.reuse_token == "" and change.previous_owner == "cursor"
    assert result["token_issued"] is True


def test_revoked_token_of_another_client_is_not_named(settings, fake_home):
    path = target(fake_home, ".cursor/mcp.json"); path.write_text("{}")
    run(settings, "cursor")
    access.revoke(settings, "cursor")
    assert cc.plan(settings, "cursor", command=COMMAND, name="cursor-full", profile="full").previous_owner == ""


def test_home_written_with_a_tilde_is_the_same_folder(settings, fake_home, monkeypatch):
    monkeypatch.setenv("HOME", str(settings.root.parent))
    path = target(fake_home, ".cursor/mcp.json")
    entry = {"command": "x", "env": {"SCREEN_CONTEXT_HOME": "~/" + settings.root.name, access.TOKEN_ENV: "sc_old"}}
    path.write_text(json.dumps({"mcpServers": {"screen-context": entry}}))
    assert cc.plan(settings, "cursor", command=COMMAND).action == "update"
    entry["env"]["SCREEN_CONTEXT_HOME"] = "~/elsewhere"
    path.write_text(json.dumps({"mcpServers": {"screen-context": entry}}))
    assert cc.plan(settings, "cursor", command=COMMAND).action == "conflict"


def test_mixed_line_endings_are_manual_in_json_and_toml(settings, fake_home):
    for rel, text in ((".cursor/mcp.json", '{\r\n"mcpServers": {}\n}'), (".codex/config.toml", 'a = 1\r\n[mcp_servers.o]\ncommand = "x"\r\n')):
        path = target(fake_home, rel); path.write_bytes(text.encode())
        change = cc.plan(settings, "cursor" if rel.endswith("json") else "codex", command=COMMAND)
        assert change.action == "manual" and change.reason == "unsupported" and path.read_bytes() == text.encode()


def test_all_crlf_json_is_written_back_as_crlf(settings, fake_home):
    path = target(fake_home, ".cursor/mcp.json"); path.write_bytes(b'{\r\n  "mcpServers": {}\r\n}\r\n')
    change, _ = run(settings, "cursor")
    assert change.action == "add"
    data = path.read_bytes()
    assert b"screen-context" in data and data.count(b"\n") == data.count(b"\r\n")


@pytest.mark.skipif(sys.platform != "darwin", reason="runs the CLI with the macOS paths")
def test_cli_write_failure_is_one_line_and_exit_1(settings, fake_home):
    import subprocess, sys
    folder = fake_home / ".cursor"; folder.mkdir(); folder.chmod(0o500)
    env = {"SCREEN_CONTEXT_HOME": str(settings.root), "SCREEN_CONTEXT_PLAINTEXT": "1", "SCREEN_CONTEXT_LANG": "en", "PATH": "/usr/bin:/bin", "HOME": str(fake_home)}
    try:
        done = subprocess.run([sys.executable, "-m", "screen_context.cli", "mcp-config", "--client", "cursor", "--write"], env=env, capture_output=True, text=True, encoding="utf-8")
    finally:
        folder.chmod(0o700)
    assert done.returncode == 1 and "Traceback" not in done.stderr and len(done.stderr.strip().splitlines()) == 1
    assert not (folder / "mcp.json").exists()


def test_dry_run_action_and_unreadable_reason_are_translated():
    from screen_context.i18n import t
    assert t("cfg.action.add", "ja") == "追加" and t("cfg.action.update", "ja") == "更新"
    assert t("cfg.action.add", "en") == "add" and t("cfg.action.update", "en") == "update"
    for lang in ("en", "ja"):
        assert t("cfg.reason.unreadable", lang, client="cursor") != "cfg.reason.unreadable"
    assert all(word in t("cfg.reason.unreadable", "en", client="cursor") for word in ("duplicate", "BOM", "UTF-8"))
    assert all(word in t("cfg.reason.unreadable", "ja", client="cursor") for word in ("重複", "BOM", "UTF-8"))
