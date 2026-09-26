import json
import shlex
import subprocess
import sys
import tomllib
import pytest
from screen_context import i18n
from screen_context.clients import CLIENTS, render
from screen_context.config import Settings
from screen_context.service import Service


def test_catalogs_cover_the_same_keys():
    assert set(i18n.MESSAGES["en"]) == set(i18n.MESSAGES["ja"])


def test_resolution_order(tmp_path, monkeypatch):
    settings = Settings(tmp_path)
    monkeypatch.delenv("SCREEN_CONTEXT_LANG", raising=False)
    monkeypatch.setattr(i18n, "system_language", lambda: "en")
    assert i18n.resolve(settings) == "en"
    settings.set_language("ja")
    assert i18n.resolve(settings) == "ja"
    monkeypatch.setenv("SCREEN_CONTEXT_LANG", "en_US.UTF-8")
    assert i18n.resolve(settings) == "en"
    monkeypatch.delenv("SCREEN_CONTEXT_LANG")
    settings.set_language("system")
    assert i18n.resolve(settings) == "en"


def test_language_option_keeps_interval(tmp_path):
    settings = Settings(tmp_path)
    settings.set_capture_interval(60)
    settings.set_language("ja")
    assert settings.capture_interval() == 60 and settings.language() == "ja"
    with pytest.raises(ValueError): settings.set_language("fr")
    assert settings.language() == "ja"


@pytest.mark.parametrize("value,expected", [("ja-JP", "ja"), ("ja_JP.UTF-8", "ja"), ("en", "en"), ("fr_FR", None), ("", None), (None, None)])
def test_normalize(value, expected):
    assert i18n.normalize(value) == expected


def test_labels():
    assert i18n.interval_label(15, "en") == "15 sec" and i18n.interval_label(120, "ja") == "2分"
    assert i18n.t("menu.title.recording", "ja") == "SC 撮影"
    assert i18n.t("menu.title.recording", "xx") == "SC Rec"


def test_client_snippets_are_valid(tmp_path):
    settings = Settings(tmp_path / "data dir")
    command = [r"C:\Program Files\ScreenContext\screen-context.exe"]
    for client in CLIENTS:
        text = render(client, command, settings, "sc_example")
        if client == "claude-code":
            parts = shlex.split(text)
            assert parts[:4] == ["claude", "mcp", "add", "--scope"] and parts[-4:] == [command[0], "serve", "--profile", "standard"]
        elif client == "codex":
            entry = tomllib.loads(text)["mcp_servers"]["screen-context"]
            assert entry["command"] == command[0] and entry["env"]["SCREEN_CONTEXT_HOME"] == str(settings.root)
        elif client == "vscode":
            assert json.loads(text)["servers"]["screen-context"]["type"] == "stdio"
        else:
            assert json.loads(text)["mcpServers"]["screen-context"]["args"] == ["serve", "--profile", "standard"]
    with pytest.raises(ValueError): render("unknown", command, settings, "sc_example")


def test_cli_mcp_config_and_language(tmp_path):
    env = {"SCREEN_CONTEXT_HOME": str(tmp_path), "SCREEN_CONTEXT_PLAINTEXT": "1", "PATH": "/usr/bin:/bin"}
    run = lambda *args: subprocess.run([sys.executable, "-m", "screen_context.cli", *args], env=env, capture_output=True, text=True, check=True).stdout
    run("init")
    entry = json.loads(run("mcp-config", "--client", "cursor", "--profile", "openclaw"))["mcpServers"]["screen-context"]
    assert entry["args"][-2:] == ["--profile", "full"] and entry["env"]["SCREEN_CONTEXT_CLIENT_TOKEN"].startswith("sc_")
    assert "SCREEN_CONTEXT_CLIENT" not in entry["env"]
    assert json.loads(run("language", "ja")) == {"language": "ja", "effective": "ja"}
    assert json.loads(run("language"))["language"] == "ja"


def test_unknown_profile_rejected(tmp_path):
    with pytest.raises(ValueError): Service(Settings(tmp_path), "admin")
    assert Service(Settings(tmp_path), "openclaw").profile == "full"


def test_material_and_proposal_follow_language(tmp_path, monkeypatch):
    import time
    from datetime import datetime, timedelta
    from test_core import add
    from screen_context import runner, store
    from screen_context.material import diary_markdown
    settings = Settings(tmp_path, plaintext=True); store.initialize(settings)
    day = datetime(2026, 9, 13, 10)
    texts = ["Reading the API specification", "Weather forecast for Tokyo", "Comparing laptop stand prices", "Past exam questions list", "Train timetable lookup"]
    for i, text in enumerate(texts): add(settings, text, ts=(day + timedelta(minutes=i)).timestamp(), title=f"T{i}")
    text = diary_markdown(settings, "2026-09-13", lang="en")
    assert text.startswith("# Screen history material 2026-09-13") and "T0 / T1 / T2 and 2 more" in text
    monkeypatch.setattr(runner, "health", lambda s, now=None: {"state": "active"})
    monkeypatch.setenv("SCREEN_CONTEXT_LANG", "en")
    now = time.time()
    frame = add(settings, "Deadline for the release checklist is Friday", ts=now - 10)
    outcome, material = runner.prepare(settings, now=now, run_id="r1")
    assert outcome == "ready" and runner.material_markdown(material, "en").startswith("# Screen observations")
    result = runner.submit(settings, "r1", "Review the checklist", "Open it", "release checklist is Friday", [frame["id"]], delivery="mock", now=now)
    assert "Evidence:" in result["message"] and "Next step: Open it" in result["message"]
