"""Uninstall (#37): plan() reads only; apply() runs in a fixed order and reports each step.
Everything lives under tmp_path: a fake home with client files, a fake launchctl, a fake login item,
a fake keyring. Nothing here touches the real home, Keychain, launchd or login items."""
import hashlib
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
import pytest
from test_lifecycle import filled, keyring            # noqa: F401  (fixture)
from screen_context import access, cli, client_config, i18n, launch, lifecycle, uninstall
from screen_context.config import Settings
from screen_context.locking import lock

TOKEN = access.TOKEN_ENV


class LoginItem:
    """SMAppService as far as uninstall uses it."""
    def __init__(self, status=launch.ENABLED, ok=True): self.current, self.ok, self.unregistered = status, ok, 0
    def status(self): return self.current
    def unregisterAndReturnError_(self, error):
        self.unregistered += 1
        if self.ok: self.current = launch.NOT_REGISTERED
        return self.ok, None


def launchctl(loaded):
    calls = []
    def run(argv, **kwargs):
        calls.append(argv)
        if argv[1] == "bootout": loaded[0] = False
        return SimpleNamespace(returncode=0 if (argv[1] == "print" and loaded[0]) else 113)
    return calls, run


def snapshot(folder):
    """path -> (size, mtime_ns, sha256) of every file and folder under `folder`."""
    out = {}
    for path in sorted(Path(folder).rglob("*")):
        if path.name.endswith(("-shm", "-wal")): continue                # SQLite makes these when anything opens the database, even read-only
        if path.is_symlink() or path.is_dir(): out[str(path)] = ("d",)
        else: out[str(path)] = (path.stat().st_size, path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest())
    return out


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    home = tmp_path / "home"; home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(client_config, "PLATFORM", "darwin")
    def real_launchctl(*a, **k): raise AssertionError("a test reached the real launchctl")
    monkeypatch.setattr(uninstall, "_default_run", real_launchctl)
    monkeypatch.delenv("SCREEN_CONTEXT_KEY", raising=False)
    return home


@pytest.fixture
def home(isolated): return isolated


@pytest.fixture
def world(tmp_path, home):
    """A plaintext data folder with two client tokens, client files with other servers, logs, an old agent,
    and an export and a backup kept outside the data folder."""
    settings = Settings(tmp_path / "data", plaintext=True)
    from screen_context import store
    store.initialize(settings)
    access.issue(settings, "cursor"); access.issue(settings, "codex")
    ours = lambda: {"command": "/x/screen-context", "args": [], "env": {"SCREEN_CONTEXT_HOME": str(settings.root), TOKEN: "sc_" + "a" * 43}}
    cursor = home / ".cursor" / "mcp.json"; cursor.parent.mkdir()
    cursor.write_text(json.dumps({"theme": 1, "mcpServers": {"first": {"command": "f"}, "screen-context": ours(),
                                                            "sc-work": ours(), "plain": {"command": "p"}}}, indent=2))
    codex = home / ".codex" / "config.toml"; codex.parent.mkdir()
    codex.write_text('model = "x"\n\n[mcp_servers.other]\ncommand = "o"\n\n[mcp_servers.screen-context]\ncommand = "/x/screen-context"\n'
                     f'args = []\nenv = {{ SCREEN_CONTEXT_HOME = "{settings.root}", {TOKEN} = "sc_{"b" * 43}" }}\n')
    logs = home / "Library" / "Logs" / "ScreenContext"; logs.mkdir(parents=True); (logs / "indexer.log").write_text("Traceback ...\n")
    (home / "Library" / "LaunchAgents").mkdir(parents=True)
    outside = tmp_path / "outside"; outside.mkdir()
    (outside / "history.scbackup").write_bytes(b"backup"); (outside / "day.jsonl").write_text("{}\n")
    (settings.root / "exports").mkdir(exist_ok=True); (settings.root / "exports" / "inside.jsonl").write_text("{}\n")
    return SimpleNamespace(settings=settings, home=home, cursor=cursor, codex=codex, logs=logs, outside=outside)


def make_plan(w, **kw):
    kw.setdefault("service", None); kw.setdefault("run", launchctl([False])[1])
    return uninstall.plan(w.settings, home=w.home, **kw)


def states(settings): return {c["name"]: c["state"] for c in access.clients(settings)}


def servers(path): return json.loads(path.read_text())["mcpServers"]


def test_plan_changes_nothing(world, tmp_path):
    before = snapshot(tmp_path)
    for kw in ({}, {"wipe": True}, {"include_related": ("sc-work",)}):
        plan = make_plan(world, **kw)
        assert snapshot(tmp_path) == before
    assert [c.client for c in plan.changes] == list(client_config.TARGETS)
    assert plan.logs == world.logs and plan.login == "manual" and plan.legacy_agent is None
    assert {c["name"] for c in plan.clients} == {"cursor", "codex"}


def test_plan_lists_what_stays_and_what_goes(world):
    plan = make_plan(world)
    codes = [r["code"] for r in plan.remains]
    assert "data" in codes and "backups" in codes and "app" in codes and codes.count("config_backup") == 2
    assert {"code": "related", "detail": "cursor: sc-work"} in plan.remains
    assert set(plan.manual) == {"claude-code", "windsurf", "generic"}
    wipe = make_plan(world, wipe=True)
    assert [e["code"] for e in wipe.erase] == ["data", "exports"] and "data" not in [r["code"] for r in wipe.remains]
    assert uninstall.confirmation_word(plan) == "UNINSTALL" and uninstall.confirmation_word(wipe) == "ERASE"


def test_unknown_related_name_is_refused(world):
    with pytest.raises(ValueError, match="nothing-like-it"): make_plan(world, include_related=("nothing-like-it",))
    with pytest.raises(ValueError, match="plain"): make_plan(world, include_related=("plain",))      # not ScreenContext-like


def test_apply_removes_only_screen_context_and_keeps_the_rest(world):
    result = uninstall.apply(make_plan(world))
    assert result.ok and not result.aborted
    assert list(servers(world.cursor)) == ["first", "sc-work", "plain"]           # related stays unless chosen
    assert json.loads(world.cursor.read_text())["theme"] == 1
    toml = world.codex.read_text()
    assert "screen-context" not in toml and "[mcp_servers.other]" in toml and 'model = "x"' in toml
    for path in (world.cursor, world.codex):
        [backup] = path.parent.glob(path.name + ".screen-context-*.bak")
        assert oct(backup.stat().st_mode & 0o777) == "0o600" and "screen-context" in backup.read_text()


def test_related_entry_is_removed_only_when_chosen(world):
    result = uninstall.apply(make_plan(world, include_related=("sc-work",)))
    assert result.ok and list(servers(world.cursor)) == ["first", "plain"]


def test_without_wipe_data_and_key_stay_and_every_client_is_revoked(tmp_path, home, keyring):
    settings = filled(tmp_path / "data"); access.issue(settings, "codex"); access.decide(settings, "codex", True, "cli")
    plan = uninstall.plan(settings, home=home, service=None, run=launchctl([False])[1])
    result = uninstall.apply(plan)
    assert result.ok and states(settings) == {"cursor": "revoked", "codex": "revoked"}
    assert settings.db.exists() and keyring.items and (settings.root / "images" / "p.webp.enc").exists()
    assert [s["step"] for s in result.steps if s["step"].startswith("revoke")] == ["revoke:codex", "revoke:cursor"]
    with pytest.raises(PermissionError): access.authenticate(settings, "sc_not_a_token", "standard")


def test_with_wipe_the_data_and_the_key_go_and_outside_files_stay(tmp_path, home, keyring):
    settings = filled(tmp_path / "data")
    (settings.root / "exports").mkdir(exist_ok=True); (settings.root / "exports" / "inside.jsonl").write_text("{}\n")
    outside = tmp_path / "outside"; outside.mkdir(); (outside / "history.scbackup").write_bytes(b"backup")
    plan = uninstall.plan(settings, home=home, wipe=True, service=None, run=launchctl([False])[1])
    result = uninstall.apply(plan)
    assert result.ok and not settings.root.exists() and keyring.items == {}
    assert result.wiped["wiped"] == str(settings.root) and result.wiped["key_deleted"] is True
    assert [s["step"] for s in result.steps][-2:] == ["logs", "wipe"] and "revoke:cursor" in [s["step"] for s in result.steps]
    assert (outside / "history.scbackup").read_bytes() == b"backup"


def test_wipe_also_removes_the_client_entries_first_and_the_exports_inside(world):
    result = uninstall.apply(make_plan(world, wipe=True))
    assert result.ok and not world.settings.root.exists()
    assert "screen-context" not in world.codex.read_text() and list(servers(world.cursor)) == ["first", "sc-work", "plain"]
    assert (world.outside / "history.scbackup").exists() and (world.outside / "day.jsonl").exists()
    assert [s["status"] for s in result.steps if s["step"].startswith("revoke")] == ["done", "done"]


def test_a_running_worker_means_nothing_changes(world, tmp_path):
    plan = make_plan(world, wipe=True)
    before = snapshot(tmp_path)
    for name in ("capture.lock", "indexer.lock"):
        with lock(world.settings.root / name):
            result = uninstall.apply(plan)
            assert not result.ok and result.aborted and [s["step"] for s in result.steps] == ["workers"]
            assert "Quit ScreenContext" in result.steps[0]["detail"]
            assert "Nothing was changed" in uninstall.result_message(result)
    assert {k: v for k, v in snapshot(tmp_path).items() if not k.endswith(".lock")} == {k: v for k, v in before.items() if not k.endswith(".lock")}
    assert set(states(world.settings).values()) == {"pending"}


def test_a_loaded_old_agent_is_named_when_the_workers_cannot_be_stopped(world):
    loaded = [True]; calls, run = launchctl(loaded)
    plan = make_plan(world, run=run)
    with lock(world.settings.root / "indexer.lock"):
        result = uninstall.apply(plan)
    assert result.aborted and "launchctl bootout" in result.steps[0]["detail"] and not [c for c in calls if c[1] == "bootout"]


def test_logs_are_deleted_and_outside_files_are_not(world):
    result = uninstall.apply(make_plan(world))
    assert not world.logs.exists() and world.logs.parent.exists()                  # Logs/ itself stays
    assert [s for s in result.steps if s["step"] == "logs"][0]["status"] == "done"
    assert (world.outside / "history.scbackup").exists() and (world.settings.root / "exports" / "inside.jsonl").exists()


def test_log_folder_symlink_is_unlinked_not_followed(world, tmp_path):
    target = tmp_path / "elsewhere"; target.mkdir(); (target / "keep.txt").write_text("k")
    import shutil; shutil.rmtree(world.logs); world.logs.symlink_to(target)
    assert uninstall.apply(make_plan(world)).ok
    assert not world.logs.exists() and (target / "keep.txt").read_text() == "k"


def test_login_item_without_a_service_is_a_manual_step(world):
    plan = make_plan(world, service=None)
    result = uninstall.apply(plan)
    step = [s for s in result.steps if s["step"] == "login"][0]
    assert plan.login == "manual" and step["status"] == "manual" and result.ok
    assert any("Login Items" in s for s in uninstall.lines(plan)["manual"])


@pytest.mark.parametrize("status, expected, calls", [(launch.ENABLED, "done", 1), (launch.REQUIRES_APPROVAL, "done", 1),
                                                       (launch.NOT_REGISTERED, "skipped", 0)])
def test_login_item_is_unregistered_when_it_is_registered(world, status, expected, calls):
    service = LoginItem(status)
    result = uninstall.apply(make_plan(world, service=service))
    assert [s for s in result.steps if s["step"] == "login"][0]["status"] == expected and service.unregistered == calls


def test_a_failing_step_does_not_stop_the_later_ones(world):
    service = LoginItem(ok=False)
    plan = make_plan(world, service=service)
    world.cursor.write_text(world.cursor.read_text() + " ")                      # changed after planning
    result = uninstall.apply(plan)
    status = {s["step"]: s["status"] for s in result.steps}
    assert not result.ok and not result.aborted
    assert status["client:cursor"] == "failed" and status["client:codex"] == "done" and status["login"] == "failed"
    assert status["logs"] == "done" and not world.logs.exists()
    assert "screen-context" in world.cursor.read_text() and "client:cursor" in uninstall.result_message(result)


def test_old_launch_agent_is_unloaded_and_renamed(world):
    loaded = [True]; calls, run = launchctl(loaded)
    plist = launch.legacy_plist(world.home); plist.write_text("<plist/>")
    plan = make_plan(world, run=run)
    assert plan.legacy_agent == "loaded"
    result = uninstall.apply(plan)
    assert [s for s in result.steps if s["step"] == "legacy_agent"][0]["status"] == "done"
    assert any(c[1] == "bootout" for c in calls) and not plist.exists() and plist.with_name(plist.name + ".disabled").exists()
    assert any(r["code"] == "legacy_disabled" for r in plan.remains)


def test_wipe_without_a_data_folder_still_deletes_the_key(tmp_path, home, keyring):
    settings = Settings(tmp_path / "gone")
    keyring.items[("screen-context-agent", str(settings.root))] = "ab" * 32
    result = uninstall.apply(uninstall.plan(settings, home=home, wipe=True, service=None, run=launchctl([False])[1]))
    assert result.ok and keyring.items == {} and "the key was deleted" in [s for s in result.steps if s["step"] == "wipe"][0]["detail"]


def test_step_order(world):
    steps = [s["step"] for s in uninstall.apply(make_plan(world, wipe=True)).steps]
    order = ["workers", "client:claude-desktop", "client:cursor", "client:vscode", "client:gemini", "client:codex",
             "revoke:codex", "revoke:cursor", "login", "legacy_agent", "logs", "wipe"]
    assert steps == order


def test_texts_exist_in_both_catalogs_and_name_the_paths(world):
    plan = make_plan(world, wipe=True, include_related=("sc-work",))
    for lang in ("en", "ja"):
        title, body = uninstall.confirmation(plan, lang)
        assert str(world.settings.root) in body and str(world.cursor) in body and "sc-work" in body
    assert i18n.t("uninstall.title.wipe", "en") in uninstall.confirmation(plan)[0]
    assert "Nothing to remove" not in uninstall.confirmation(plan)[1]
    assert set(uninstall.describe(plan)) >= {"clients", "remains", "erase", "confirm_with"} and json.dumps(uninstall.describe(plan))


# --- the command ----------------------------------------------------------------------------------

def run_cli(world, monkeypatch, capsys, *args):
    monkeypatch.setenv("SCREEN_CONTEXT_HOME", str(world.settings.root)); monkeypatch.setenv("SCREEN_CONTEXT_PLAINTEXT", "1")
    monkeypatch.setattr(sys, "argv", ["screen-context", "uninstall", *args])
    monkeypatch.setattr(uninstall, "_default_run", launchctl([False])[1])
    try: cli.main(); code = 0
    except SystemExit as exit: code = exit.code
    out = capsys.readouterr()
    return code, out.out, out.err


def test_cli_dry_run_prints_the_plan_and_changes_nothing(world, tmp_path, monkeypatch, capsys):
    before = snapshot(tmp_path)
    code, out, _ = run_cli(world, monkeypatch, capsys, "--dry-run", "--wipe")
    data = json.loads(out)
    assert code == 0 and data["wipe"] is True and data["confirm_with"] == "ERASE" and snapshot(tmp_path) == before
    assert any(c["related"] == ["sc-work"] for c in data["clients"])


def test_cli_needs_the_right_word(world, tmp_path, monkeypatch, capsys):
    before = snapshot(tmp_path)
    assert run_cli(world, monkeypatch, capsys, "--confirm", "yes")[0] == 2
    assert run_cli(world, monkeypatch, capsys, "--wipe", "--confirm", "UNINSTALL")[0] == 2     # wipe needs ERASE
    monkeypatch.setattr("builtins.input", lambda prompt="": "no")
    code, _, err = run_cli(world, monkeypatch, capsys)
    assert code == 2 and "nothing was changed" in err and snapshot(tmp_path) == before


def test_cli_uninstall_and_include(world, monkeypatch, capsys):
    code, out, err = run_cli(world, monkeypatch, capsys, "--include", "sc-work", "--confirm", "UNINSTALL")
    data = json.loads(out)
    assert code == 0 and data["ok"] and "was uninstalled" in data["message"] and "What stays:" in err
    assert list(servers(world.cursor)) == ["first", "plain"] and world.settings.db.exists() and not world.logs.exists()
    assert run_cli(world, monkeypatch, capsys, "--include", "nope", "--confirm", "UNINSTALL")[0] == 2


def test_cli_exits_1_when_a_step_fails(world, monkeypatch, capsys):
    monkeypatch.setattr(launch, "login_service", lambda: LoginItem(ok=False))
    code, out, _ = run_cli(world, monkeypatch, capsys, "--confirm", "UNINSTALL")
    assert code == 1 and json.loads(out)["ok"] is False


def test_wipe_revokes_every_token_even_when_the_wipe_fails(world, monkeypatch):
    def broken(*args, **kwargs): raise OSError("disk gone")
    monkeypatch.setattr(lifecycle, "wipe", broken)
    result = uninstall.apply(make_plan(world, wipe=True))
    status = {s["step"]: s["status"] for s in result.steps}
    assert not result.ok and status["wipe"] == "failed"
    assert status["revoke:cursor"] == "done" and status["revoke:codex"] == "done"
    assert states(world.settings) == {"cursor": "revoked", "codex": "revoked"}


def test_other_data_folder_entry_is_kept_and_said_so(world, tmp_path):
    other = str(tmp_path / "elsewhere")
    world.cursor.write_text(json.dumps({"mcpServers": {"screen-context": {"command": "x", "env": {"SCREEN_CONTEXT_HOME": other, TOKEN: "sc_" + "a" * 43}},
                                                        "first": {"command": "f"}}}))
    plan = make_plan(world)
    cursor = [c for c in plan.changes if c.client == "cursor"][0]
    assert cursor.action == "conflict" and cursor.reason == "other_home" and cursor.other_home == other
    result = uninstall.apply(plan)
    assert result.ok and list(servers(world.cursor)) == ["screen-context", "first"]
    assert [s["status"] for s in result.steps if s["step"] == "client:cursor"] == ["skipped"]
    for lang in ("en", "ja"):
        assert any("cursor" in s and other in s for s in uninstall.lines(plan, lang)["remains"])
    entry = [c for c in uninstall.describe(plan)["clients"] if c["client"] == "cursor"][0]
    assert entry["action"] == "conflict" and entry["reason"] == "other_home" and entry["other_home"] == other
    assert not any("cursor" in s and "Remove the screen-context" in s for s in uninstall.lines(plan)["do"])


def test_wipe_erases_no_data_when_there_is_no_data_folder(tmp_path, home):
    run = launchctl([False])[1]
    plan = uninstall.plan(Settings(tmp_path / "gone", plaintext=True), home=home, wipe=True, service=None, run=run)
    assert plan.erase == []
    plan = uninstall.plan(Settings(tmp_path / "gone"), home=home, wipe=True, service=None, run=run)
    assert [e["code"] for e in plan.erase] == ["key"]


def test_only_related_entries_are_removed_and_the_text_says_so(world):
    ours = {"command": "/x/screen-context", "args": [], "env": {"SCREEN_CONTEXT_HOME": str(world.settings.root), TOKEN: "sc_" + "a" * 43}}
    world.cursor.write_text(json.dumps({"mcpServers": {"first": {"command": "f"}, "sc-work": ours}}))
    world.codex.write_text('model = "x"\n\n[mcp_servers.other]\ncommand = "o"\n\n[mcp_servers.sc-work]\ncommand = "/x/screen-context"\n'
                           f'args = []\nenv = {{ SCREEN_CONTEXT_HOME = "{world.settings.root}", {TOKEN} = "sc_{"c" * 43}" }}\n')
    plan = make_plan(world, include_related=("sc-work",))
    do = uninstall.lines(plan)["do"]
    assert not any(s.startswith("Remove the screen-context entry") for s in do)
    related = [s for s in do if "sc-work" in s]
    assert len(related) == 2 and str(world.cursor) in related[0] and str(world.codex) in related[1]
    result = uninstall.apply(plan)
    assert result.ok and list(servers(world.cursor)) == ["first"]
    toml = world.codex.read_text()
    assert "sc-work" not in toml and "[mcp_servers.other]" in toml


def test_cli_eof_at_the_prompt_is_a_clean_refusal(world, tmp_path, monkeypatch, capsys):
    before = snapshot(tmp_path)
    def at_eof(prompt=""): raise EOFError
    monkeypatch.setattr("builtins.input", at_eof)
    code, _, err = run_cli(world, monkeypatch, capsys)
    assert code == 2 and "nothing was changed" in err and "Traceback" not in err and snapshot(tmp_path) == before


def test_cli_run_while_a_worker_holds_the_lock_changes_nothing(world, tmp_path, monkeypatch, capsys):
    with lock(world.settings.root / "indexer.lock"):
        before = {k: v for k, v in snapshot(tmp_path).items() if not k.endswith(".lock")}
        code, out, _ = run_cli(world, monkeypatch, capsys, "--confirm", "UNINSTALL")
        after = {k: v for k, v in snapshot(tmp_path).items() if not k.endswith(".lock")}
    assert code == 1 and "Nothing was changed" in out and json.loads(out)["ok"] is False
    assert after == before
