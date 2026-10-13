"""Menu bar uninstall flow (#37-B). The dialogs are a fake; the data, client files and home live under tmp_path."""
import threading
import pytest
from test_lifecycle import keyring            # noqa: F401  (fixture)
from test_uninstall import home, isolated, snapshot, world, make_plan, servers   # noqa: F401  (fixtures and helpers)
from screen_context import uninstall, uninstall_flow
from screen_context.config import Settings
from screen_context.i18n import t
from screen_context.locking import lock


class Ui:
    """confirm answers come from `confirms` in order; `word` is what the user types (None: cancel)."""
    def __init__(self, confirms=(True,), word=None):
        self.confirms, self.word, self.calls, self.reports = list(confirms), word, [], []
    def confirm(self, title, body, ok, cancel):
        self.calls.append(("confirm", title, body, ok, cancel)); return self.confirms.pop(0)
    def ask_word(self, title, body, ok, cancel):
        self.calls.append(("word", title, body, ok, cancel)); return self.word
    def report(self, title, body): self.reports.append((title, body))


def asking(world, ui, lang="en"):
    return uninstall_flow.ask(world.settings, ui, lang, plan=lambda s, wipe=False: make_plan(world, wipe=wipe))


def test_cancel_changes_nothing_and_stops_at_the_first_dialog(world, tmp_path):
    before = snapshot(tmp_path)
    ui = Ui(confirms=[False])
    assert asking(world, ui) is None
    assert [c[0] for c in ui.calls] == ["confirm"] and ui.reports == []
    assert ui.calls[0][3:] == ("Uninstall", "Cancel")
    assert snapshot(tmp_path) == before


def test_asking_never_applies(world, tmp_path, monkeypatch):
    monkeypatch.setattr(uninstall, "apply", lambda *a, **k: pytest.fail("apply ran while asking"))
    before = snapshot(tmp_path)
    for ui in (Ui([True, False]), Ui([True, True], word="ERASE"), Ui([True, True], word="nope"), Ui([True, True], word=None)):
        asking(world, ui)
    assert snapshot(tmp_path) == before


def test_keeping_the_data_is_the_second_dialogs_default(world):
    ui = Ui(confirms=[True, False])
    plan = asking(world, ui)
    assert plan.wipe is False and [c[0] for c in ui.calls] == ["confirm", "confirm"]
    assert ui.calls[1][3:] == ("Erase Data…", "Keep My Data")     # ok, cancel: the harmless button is the cancel (default) one


def test_erase_needs_the_word_in_a_third_dialog(world):
    ui = Ui(confirms=[True, True], word=" ERASE ")
    plan = asking(world, ui)
    assert plan.wipe is True and [c[0] for c in ui.calls] == ["confirm", "confirm", "word"]
    assert "ERASE" in ui.calls[2][2] and ui.calls[2][3:] == ("Uninstall and Erase", "Cancel")


@pytest.mark.parametrize("typed", ["erase", "UNINSTALL", "", "ERASE now"])
def test_a_wrong_word_cancels_everything(world, tmp_path, typed):
    before = snapshot(tmp_path)
    ui = Ui(confirms=[True, True], word=typed)
    assert asking(world, ui) is None
    assert ui.reports == [(t("uninstall.not_confirmed", "en"), "")]
    assert snapshot(tmp_path) == before


def test_cancelling_the_word_dialog_cancels_everything_quietly(world):
    ui = Ui(confirms=[True, True], word=None)
    assert asking(world, ui) is None and ui.reports == []


def test_without_a_data_folder_there_is_nothing_to_erase(world, tmp_path):
    empty = Settings(tmp_path / "nothing here", plaintext=True)
    ui = Ui(confirms=[True])
    plan = uninstall_flow.ask(empty, ui, "en", plan=lambda s, wipe=False: uninstall.plan(s, home=world.home, wipe=wipe, service=None, run=make_plan(world).run))
    assert plan.wipe is False and [c[0] for c in ui.calls] == ["confirm"]


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_the_first_dialog_names_the_range(world, lang):
    ui = Ui(confirms=[False])
    asking(world, ui, lang)
    _, title, body, ok, cancel = ui.calls[0]
    for path in (world.cursor, world.codex, world.logs, world.settings.root):
        assert str(path) in body
    assert t("uninstall.remains.header", lang) in body and t("uninstall.manual.header", lang) in body    # what stays, what you do yourself
    assert t("uninstall.remains.app", lang) in body
    assert (ok, cancel) == (t("uninstall.confirm", lang), t("uninstall.cancel", lang))
    assert title == t("uninstall.title", lang)


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_the_erase_dialogs_name_the_key_the_data_and_the_exports(world, lang):
    ui = Ui(confirms=[True, True], word="ERASE")
    asking(world, ui, lang)
    for index in (1, 2):                                          # dialog 2 and dialog 3
        body = ui.calls[index][2]
        assert t("uninstall.do.wipe", lang, path=world.settings.root) in body
        assert t("uninstall.do.exports", lang, path=world.settings.root / "exports") in body
    third = ui.calls[2]
    assert third[1] == t("uninstall.title.wipe", lang) and t("uninstall.word.hint", lang, word="ERASE", ok=t("uninstall.confirm.wipe", lang)) in third[2]
    assert t("uninstall.confirm.wipe", lang) in third[2]                       # the hint names the button to press
    assert str(world.cursor) in third[2] and t("uninstall.remains.backups", lang) in third[2]


def test_the_menu_flow_removes_entries_after_the_locks_are_free(world):
    plan = asking(world, Ui(confirms=[True, False]))
    app_lock = lock(world.settings.root / "capture.lock")         # what mac_app.main holds during the capture loop
    app_lock.__enter__()
    try:
        ui = Ui()
        result = uninstall_flow.finish(plan, ui, "en")
        assert result.aborted and "screen-context" in servers(world.cursor)         # nothing changed while the app still holds capture.lock
        assert ui.reports == [(t("uninstall.app_aborted", "en"), "")]
    finally:
        app_lock.__exit__(None, None, None)
    ui = Ui()
    result = uninstall_flow.finish(plan, ui, "en")
    assert result.ok and "screen-context" not in servers(world.cursor) and "first" in servers(world.cursor)
    assert not world.logs.exists() and world.settings.root.exists()                 # no wipe: the data stays
    assert ui.reports[0][0] == t("uninstall.result.done", "en")
    assert t("uninstall.remains.header", "en") in ui.reports[0][1] and str(world.settings.root) in ui.reports[0][1]


def test_erase_removes_the_data_folder(world, tmp_path):
    plan = asking(world, Ui(confirms=[True, True], word="ERASE"))
    ui = Ui()
    assert uninstall_flow.finish(plan, ui, "ja").ok
    assert not world.settings.root.exists() and (world.outside / "history.scbackup").exists()
    assert ui.reports[0][0] == t("uninstall.result.done", "ja")


def test_failed_steps_are_listed_and_a_crash_is_reported(world):
    plan = asking(world, Ui(confirms=[True, False]))
    world.cursor.write_text("{}")                                  # changed after the plan: that step fails, the others still run
    ui = Ui()
    result = uninstall_flow.finish(plan, ui, "en")
    assert not result.ok and "client:cursor" in ui.reports[0][0] and "client:cursor" in ui.reports[0][1]
    ui = Ui()
    assert uninstall_flow.finish(plan, ui, "en", apply=lambda *a, **k: 1 / 0) is None
    assert ui.reports == [(t("error.uninstall", "en", error="ZeroDivisionError"), "")]


def test_an_aborted_run_says_to_reopen_and_retry_not_to_quit(world):
    plan = asking(world, Ui(confirms=[True, False]))
    aborted = uninstall.Result(False, [{"step": "workers", "status": "failed", "detail": "Quit ScreenContext (capture and indexer) first"}])
    for lang in ("en", "ja"):
        ui = Ui()
        assert uninstall_flow.finish(plan, ui, lang, apply=lambda *a, **k: aborted) is aborted
        assert ui.reports == [(t("uninstall.app_aborted", lang), "")]
        assert "Quit" not in ui.reports[0][0] and "終了" not in ui.reports[0][0]          # the CLI wording never reaches the app


def test_a_failing_result_dialog_does_not_end_in_a_traceback(world):
    plan = asking(world, Ui(confirms=[True, False]))
    class BrokenUi(Ui):
        def report(self, title, body): raise RuntimeError("dialog closed")
    done = uninstall.Result(True, [{"step": "workers", "status": "done", "detail": ""}])
    assert uninstall_flow.finish(plan, BrokenUi(), "en", apply=lambda *a, **k: done) is done
    assert uninstall_flow.finish(plan, BrokenUi(), "en", apply=lambda *a, **k: 1 / 0) is None


class FakeButton:
    def __init__(self, title): self.title, self.destructive, self.key = title, False, None
    def setHasDestructiveAction_(self, flag): self.destructive = flag
    def setKeyEquivalent_(self, key): self.key = key


class FakeAlert:
    """Records what UninstallDialogs puts in an NSAlert. Nothing is shown; runModal returns `answer`."""
    answer, made = 1000, []                      # 1000 = NSAlertFirstButtonReturn (Return)
    @classmethod
    def alloc(cls):
        alert = cls(); cls.made.append(alert); return alert
    def __init__(self): self.title = self.body = self.accessory = self.first_responder = None; self._buttons = []
    def init(self): return self
    def setMessageText_(self, text): self.title = text
    def setInformativeText_(self, text): self.body = text
    def addButtonWithTitle_(self, title): self._buttons.append(FakeButton(title))
    def buttons(self): return self._buttons
    def setAccessoryView_(self, view): self.accessory = view
    def window(self): return self
    def setInitialFirstResponder_(self, view): self.first_responder = view
    def runModal(self): return FakeAlert.answer


class FakeField:
    typed = ""
    @classmethod
    def alloc(cls): return cls()
    def initWithFrame_(self, frame): return self
    def stringValue(self): return FakeField.typed


class FakeApp:
    @staticmethod
    def sharedApplication(): return type("App", (), {"activateIgnoringOtherApps_": lambda self, flag: None})()


@pytest.fixture
def dialogs(monkeypatch):
    mac_app = pytest.importorskip("screen_context.mac_app")
    monkeypatch.setattr(mac_app, "NSAlert", FakeAlert)
    monkeypatch.setattr(mac_app, "NSApplication", FakeApp)
    monkeypatch.setattr(mac_app, "NSTextField", FakeField)
    FakeAlert.made.clear(); FakeAlert.answer = 1000; FakeField.typed = ""
    return mac_app


def test_confirm_puts_cancel_first_as_the_default_and_escape_on_it(dialogs):
    FakeAlert.answer = dialogs.NSAlertSecondButtonReturn
    assert dialogs.UninstallDialogs().confirm("T", "B", "Erase", "Keep") is True
    [alert] = FakeAlert.made
    cancel, ok = alert.buttons()
    assert [cancel.title, ok.title] == ["Keep", "Erase"]
    assert ok.destructive is True and cancel.destructive is False
    assert cancel.key == "\x1b"
    FakeAlert.made.clear(); FakeAlert.answer = 1000
    assert dialogs.UninstallDialogs().confirm("T", "B", "Erase", "Keep") is False     # Return = cancel


def test_ask_word_returns_the_typed_text(dialogs):
    FakeAlert.answer, FakeField.typed = dialogs.NSAlertSecondButtonReturn, "ERASE"
    assert dialogs.UninstallDialogs().ask_word("T", "B", "Erase", "Cancel") == "ERASE"
    [alert] = FakeAlert.made
    assert alert.accessory is not None and alert.first_responder is alert.accessory   # the field has the focus
    assert alert.buttons()[0].title == "Cancel" and alert.buttons()[0].key == "\x1b"


def test_ask_word_cancel_returns_none(dialogs):
    FakeField.typed = "ERASE"
    assert dialogs.UninstallDialogs().ask_word("T", "B", "Erase", "Cancel") is None   # typed text is ignored on cancel


def test_menu_does_not_ask_again_while_a_plan_is_pending(monkeypatch):
    mac_app = pytest.importorskip("screen_context.mac_app")
    monkeypatch.setattr(uninstall_flow, "ask", lambda *a, **k: pytest.fail("asked while an uninstall is pending"))
    menu = mac_app.MenuController.alloc().init()           # a real NSObject; pyobjc refuses a plain object as self
    menu.pending, menu.stop = object(), threading.Event()
    menu.uninstall_(None)
    assert not menu.stop.is_set()                          # the capture loop was not stopped a second time


def test_the_menu_text_exists_in_both_languages():
    for lang in ("en", "ja"):
        for key in ("menu.uninstall", "error.uninstall", "uninstall.wipe.title", "uninstall.wipe.body", "uninstall.wipe.keep",
                    "uninstall.wipe.erase", "uninstall.word.hint", "uninstall.not_confirmed", "uninstall.app_aborted"):
            assert t(key, lang, word="ERASE", ok="OK", error="E") != key
