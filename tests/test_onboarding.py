"""First-run guide (#35-C). Permission, init, dialogs and client files are all fakes or temporary folders."""
import argparse
import json
import shlex
import sys
import pytest
from test_core import settings
from screen_context import cli, clients, client_config as cc, onboarding, store
from screen_context.config import Settings
from screen_context.i18n import t


class Ui:
    """The dialogs. `picks` is what the user ticks; None means Skip."""
    def __init__(self, picks=None, open_settings=True):
        self.picks, self.open = picks, open_settings
        self.errors, self.reports, self.offered, self.asked_permission = [], [], None, 0
    def permission(self, lang): self.asked_permission += 1; return self.open
    def error(self, text): self.errors.append(text)
    def choose(self, options, lang): self.offered = options; return [c for c, _ in options if self.picks is None or c in self.picks] if self.picks != [] else []
    def report(self, text, lang): self.reports.append(text)


def none_text():
    """The text for "no assistant found", with the command the guide prints (CLIENT stands for the name)."""
    command = shlex.join([*clients.cli_command(), "mcp-config", "--client", "CLIENT", "--write"])
    return t("setup.clients.none", "en", command=command)


class Parsed(Exception):
    """Raised by the parse spy below, so the CLI stops before it runs anything."""


def cli_args(monkeypatch, command):
    """The CLI's own argparse result for a command the guide printed (shell words, launcher first). Nothing runs."""
    words = shlex.split(command)
    launcher = clients.cli_command()
    assert words[:len(launcher)] == launcher
    monkeypatch.setattr(sys, "argv", ["screen-context", *words[len(launcher):]])
    seen = {}
    real = argparse.ArgumentParser.parse_args
    def spy(self, args=None, namespace=None):
        seen["args"] = real(self, args, namespace)   # a parse error exits here, which fails the test
        raise Parsed
    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", spy)
    with pytest.raises(Parsed): cli._main()
    return seen["args"]


class Mac:
    """preflight / request / open_settings fakes with a call log."""
    def __init__(self, allowed=True): self.allowed, self.calls = allowed, []
    def preflight(self): self.calls.append("preflight"); return self.allowed
    def request(self): self.calls.append("request")
    def open_settings(self): self.calls.append("open_settings")


@pytest.fixture
def fresh(tmp_path):
    return Settings(tmp_path / "data", plaintext=True)


@pytest.fixture
def home(tmp_path, monkeypatch):
    home = tmp_path / "home"; home.mkdir()
    monkeypatch.setattr(cc.Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(cc, "PLATFORM", "darwin")
    return home


def start(settings, ui, mac, **kw):
    settings.root.mkdir(parents=True, exist_ok=True)
    return onboarding.run(settings, ui, "en", preflight=mac.preflight, request=mac.request, open_settings=mac.open_settings, **kw)


def install(home, *names):
    for name in names:
        parts = cc.TARGETS[name][0]
        (home.joinpath(*parts)).parent.mkdir(parents=True, exist_ok=True)


def test_first_run_goes_through_every_stage(fresh, home):
    install(home, "cursor", "codex")
    ui, mac = Ui(picks=["cursor"]), Mac()
    assert start(fresh, ui, mac) == onboarding.READY
    assert fresh.db.exists() and store.peek_version(fresh) == store.SCHEMA_VERSION
    assert [c for c, _ in ui.offered] == ["cursor", "codex"]            # only the installed clients, claude-desktop etc. are absent
    assert json.loads((home / ".cursor" / "mcp.json").read_text())["mcpServers"]["screen-context"]["env"]["SCREEN_CONTEXT_HOME"] == str(fresh.root)
    assert not (home / ".codex" / "config.toml").exists()                # not chosen: not written
    assert onboarding.load(fresh) == "done"
    [report] = ui.reports
    assert t("setup.done", "en") in report and "Cursor" in report and "Restart Cursor" in report
    assert mac.calls == ["preflight"]


def test_permission_denied_does_not_initialise_and_asks_to_reopen(fresh, home):
    ui, mac = Ui(), Mac(allowed=False)
    assert start(fresh, ui, mac) == onboarding.QUIT
    assert mac.calls == ["preflight", "request", "open_settings"]
    assert not fresh.db.exists() and onboarding.load(fresh) is None
    assert ui.asked_permission == 1 and ui.reports == [] and ui.offered is None


def test_permission_dialog_can_decline_to_open_settings(fresh):
    ui, mac = Ui(open_settings=False), Mac(allowed=False)
    assert start(fresh, ui, mac) == onboarding.QUIT
    assert "open_settings" not in mac.calls


def test_after_granting_the_next_launch_continues(fresh, home):
    assert start(fresh, Ui(), Mac(allowed=False)) == onboarding.QUIT
    assert start(fresh, Ui(picks=[]), Mac()) == onboarding.READY
    assert fresh.db.exists() and onboarding.load(fresh) == "done"


def test_resume_after_init_only_offers_clients(fresh, home):
    store.initialize(fresh); onboarding.save(fresh, "clients")
    install(home, "gemini")
    ui, mac = Ui(picks=["gemini"]), Mac(allowed=False)             # permission is not asked again
    calls = []
    assert start(fresh, ui, mac, initialize=lambda s: calls.append("init")) == onboarding.READY
    assert calls == [] and mac.calls == [] and (home / ".gemini" / "settings.json").exists()
    assert onboarding.load(fresh) == "done"


def test_interrupted_init_runs_init_again(fresh, home):
    fresh.root.mkdir(parents=True); onboarding.save(fresh, "init")
    calls = []
    assert start(fresh, Ui(picks=[]), Mac(), initialize=lambda s: calls.append("init") or store.initialize(s)) == onboarding.READY
    assert calls == ["init"] and onboarding.load(fresh) == "done"


def test_second_launch_shows_nothing(fresh, home):
    start(fresh, Ui(picks=[]), Mac())
    ui, mac = Ui(), Mac(allowed=False)
    assert start(fresh, ui, mac) == onboarding.READY
    assert mac.calls == [] and ui.reports == ui.errors == [] and ui.offered is None and ui.asked_permission == 0


def test_an_install_from_before_the_guide_is_left_alone(settings):
    ui, mac = Ui(), Mac(allowed=False)                               # settings fixture already has a database
    assert onboarding.run(settings, ui, "en", preflight=mac.preflight, request=mac.request, open_settings=mac.open_settings) == onboarding.READY
    assert mac.calls == [] and ui.reports == [] and onboarding.load(settings) == "done"


def test_unreadable_state_file_restarts_at_init(fresh):
    fresh.root.mkdir(parents=True); (fresh.root / "setup.json").write_text("{broken")
    assert onboarding.load(fresh) == "init"
    (fresh.root / "setup.json").write_text('{"stage": "bogus"}')
    assert onboarding.load(fresh) == "init"


def test_init_failure_is_shown_and_retried_next_time(fresh):
    def boom(s): raise OSError("disk")
    ui = Ui()
    assert start(fresh, ui, Mac(), initialize=boom) == onboarding.QUIT
    assert ui.errors == [t("setup.init_failed", "en", error="OSError")] and onboarding.load(fresh) == "init"
    assert ui.reports == []


def test_schema_mismatch_uses_the_schema_message(fresh):
    def newer(s): raise store.SchemaMismatch(store.SCHEMA_VERSION + 1, store.SCHEMA_VERSION)
    ui = Ui()
    assert start(fresh, ui, Mac(), initialize=newer) == onboarding.QUIT
    [text] = ui.errors
    assert "newer" in text and str(fresh.db) in text and "Update ScreenContext" in text
    assert onboarding.load(fresh) == "init"


def test_skip_writes_nothing_and_finishes(fresh, home):
    install(home, "cursor")
    ui = Ui(picks=[])
    assert start(fresh, ui, Mac()) == onboarding.READY
    assert not (home / ".cursor" / "mcp.json").exists() and onboarding.load(fresh) == "done"
    assert ui.reports == [t("setup.done", "en")]


def test_no_installed_client_says_so(fresh, home):
    ui = Ui()
    assert start(fresh, ui, Mac()) == onboarding.READY
    assert ui.offered is None and none_text() in ui.reports[0]


def test_conflict_is_reported_and_not_written(fresh, home, monkeypatch):
    install(home, "cursor")
    path = home / ".cursor" / "mcp.json"
    other = json.dumps({"mcpServers": {"screen-context": {"command": "x", "env": {"SCREEN_CONTEXT_HOME": "/elsewhere"}}}})
    path.write_text(other)
    ui = Ui(picks=["cursor"])
    assert start(fresh, ui, Mac()) == onboarding.READY
    assert path.read_text() == other
    assert "/elsewhere" in ui.reports[0] and "Nothing was changed" in ui.reports[0]
    command = shlex.join([*clients.cli_command(), "mcp-config", "--client", "cursor", "--write", "--force"])
    assert t("setup.conflict_hint", "en", command=command) in ui.reports[0]
    assert cli_args(monkeypatch, command).force is True


def test_manual_client_gets_the_reason_and_the_command(fresh, home, monkeypatch):
    install(home, "cursor")
    (home / ".cursor" / "mcp.json").write_text('{\n // comment\n "mcpServers": {}\n}')
    ui = Ui(picks=["cursor"])
    start(fresh, ui, Mac())
    command = shlex.join([*clients.cli_command(), "mcp-config", "--client", "cursor", "--write"])
    assert "comments" in ui.reports[0] and command in ui.reports[0]
    assert "sc_" not in ui.reports[0]
    args = cli_args(monkeypatch, command)
    assert (args.command, args.client, args.write) == ("mcp-config", "cursor", True)


def test_launcher_path_with_spaces_is_quoted_and_still_parses(fresh, home, monkeypatch):
    # The .app launcher lives in a folder with a space; a bare path would split into two words in Terminal.
    monkeypatch.setattr(clients, "cli_command", lambda: ["/Applications/Screen Context.app/Contents/MacOS/ScreenContext"])
    install(home, "cursor")
    (home / ".cursor" / "mcp.json").write_text('{\n // comment\n "mcpServers": {}\n}')
    ui = Ui(picks=["cursor"])
    start(fresh, ui, Mac())
    command = shlex.join(["/Applications/Screen Context.app/Contents/MacOS/ScreenContext", "mcp-config", "--client", "cursor", "--write"])
    assert command in ui.reports[0] and "'/Applications/Screen Context.app" in command
    assert cli_args(monkeypatch, command).client == "cursor"


def test_no_client_hint_names_the_cli_and_a_placeholder(fresh, home):
    ui = Ui()
    start(fresh, ui, Mac())
    command = shlex.join([*clients.cli_command(), "mcp-config", "--client", "CLIENT", "--write"])
    assert command in ui.reports[0] and "screen-context mcp-config CLIENT" not in ui.reports[0]


def test_previous_owner_is_named_after_a_successful_write(fresh, home):
    install(home, "cursor")
    def plan(settings, client, home=None):
        change = cc.plan(settings, client, home=home)
        change.previous_owner = "old-app"
        return change
    ui = Ui(picks=["cursor"])
    start(fresh, ui, Mac(), plan=plan)
    assert json.loads((home / ".cursor" / "mcp.json").read_text())["mcpServers"]["screen-context"]
    assert t("cfg.previous_owner", "en", owner="old-app") in ui.reports[0]
    assert "sc_" not in ui.reports[0]


def test_failed_plan_names_the_client_not_the_path(fresh, home):
    install(home, "cursor")
    count = {"cursor": 0}
    def plan(settings, client, home=None):
        if client == "cursor":
            count["cursor"] += 1
            if count["cursor"] > 1: raise RuntimeError("boom")   # the offer lists it, the write step fails
        return cc.plan(settings, client, home=home)
    ui = Ui(picks=["cursor"])
    start(fresh, ui, Mac(), plan=plan)
    assert "Cursor: " + t("setup.client_failed", "en", client="Cursor", error="RuntimeError") in ui.reports[0]
    assert "Could not write Cursor" not in ui.reports[0]


def test_apply_failure_is_reported_and_setup_still_finishes(fresh, home):
    install(home, "cursor")
    def fail(change): raise RuntimeError("changed")
    ui = Ui(picks=["cursor"])
    assert start(fresh, ui, Mac(), apply=fail) == onboarding.READY
    assert "Could not write" in ui.reports[0] and "RuntimeError" in ui.reports[0]
    assert onboarding.load(fresh) == "done"


def test_unchanged_client_is_not_offered_again(fresh, home):
    install(home, "cursor")
    start(fresh, Ui(picks=["cursor"]), Mac())
    ui = Ui(picks=[])
    text = onboarding.connect_clients(fresh, ui, "en", home=None)
    assert ui.offered is None and text == none_text()


def test_connect_clients_from_the_menu_ignores_unknown_choices(fresh, home):
    store.initialize(fresh); install(home, "cursor")
    class Rogue(Ui):
        def choose(self, options, lang): return ["../etc", "cursor"]
    text = onboarding.connect_clients(fresh, Rogue(), "en")
    assert "Cursor" in text and "../etc" not in text


def test_tokens_never_reach_the_dialogs(fresh, home):
    install(home, "cursor")
    ui = Ui(picks=["cursor"]); start(fresh, ui, Mac())
    assert "sc_" not in "\n".join(ui.reports + ui.errors)


def test_broken_state_file_with_a_database_resumes_at_clients(fresh, home):
    store.initialize(fresh)                                          # the database exists, so init finished before
    fresh.root.mkdir(parents=True, exist_ok=True)
    (fresh.root / "setup.json").write_text("{broken")
    assert onboarding.load(fresh) == "clients"
    (fresh.root / "setup.json").write_text('{"stage": "bogus"}')
    assert onboarding.load(fresh) == "clients"
    calls, mac = [], Mac(allowed=False)
    assert start(fresh, Ui(picks=[]), mac, initialize=lambda s: calls.append("init")) == onboarding.READY
    assert calls == [] and mac.calls == [] and onboarding.load(fresh) == "done"


def test_a_failing_dialog_keeps_the_stage_for_the_next_launch(fresh, home):
    install(home, "cursor")
    class Broken(Ui):
        def choose(self, options, lang): raise RuntimeError("dialog")
    with pytest.raises(RuntimeError):
        start(fresh, Broken(), Mac())
    assert onboarding.load(fresh) == "clients"


def test_approval_is_given_in_the_app_in_both_languages(fresh):
    assert "in the ScreenContext app on its first use" in t("setup.clients.body", "en")
    assert "最初の利用時に ScreenContext アプリで承認します" in t("setup.clients.body", "ja")
    assert t("menu.connect", "en") == "Connect an AI Assistant…"


class FakeAlert:
    """Records what SetupDialogs puts in an NSAlert. Nothing is shown."""
    made = []
    @classmethod
    def alloc(cls):
        alert = cls(); cls.made.append(alert); return alert
    def __init__(self): self.title, self.body, self.buttons = None, None, []
    def init(self): return self
    def setMessageText_(self, text): self.title = text
    def setInformativeText_(self, text): self.body = text
    def addButtonWithTitle_(self, title): self.buttons.append(title)
    def runModal(self): return 1000


class FakeApp:
    @staticmethod
    def sharedApplication(): return type("App", (), {"activateIgnoringOtherApps_": lambda self, flag: None})()


def test_result_dialog_has_a_short_title_and_the_default_ok(monkeypatch):
    mac_app = pytest.importorskip("screen_context.mac_app")
    monkeypatch.setattr(mac_app, "NSAlert", FakeAlert)
    monkeypatch.setattr(mac_app, "NSApplication", FakeApp)
    FakeAlert.made.clear()
    long_text = t("setup.done", "en") + "\n\n" + "Cursor: " + "x" * 500
    mac_app.SetupDialogs().report(long_text, "en")
    [alert] = FakeAlert.made
    assert alert.title == t("setup.report.title", "en") and alert.body == long_text
    assert alert.buttons == []                                       # no literal "OK": AppKit supplies the default button
    FakeAlert.made.clear()
    mac_app.SetupDialogs().error("boom")
    [alert] = FakeAlert.made
    assert alert.buttons == []


def test_setup_crash_is_shown_as_error_start_and_main_returns(monkeypatch):
    mac_app = pytest.importorskip("screen_context.mac_app")
    shown = []
    class Dialogs:
        def error(self, text): shown.append(text)
    class Env:
        def prepare(self): pass
    monkeypatch.setattr(mac_app, "NSApplication", FakeApp)
    monkeypatch.setattr(mac_app.Settings, "environment", staticmethod(lambda: Env()))
    monkeypatch.setattr(mac_app, "screen_recording", lambda: (None, None, None))
    monkeypatch.setattr(mac_app, "resolve", lambda settings: "en")
    monkeypatch.setattr(mac_app, "SetupDialogs", Dialogs)
    def broken(*args, **kwargs): raise RuntimeError("dialog closed")
    monkeypatch.setattr(onboarding, "run", broken)
    assert mac_app.main() is None
    assert shown == [t("error.start", "en", error="RuntimeError")]
