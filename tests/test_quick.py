"""Menu bar shortcuts (#31): quick purge of the last minutes, and opening the Today view."""
import subprocess
import sys
import time
import pytest
from PIL import Image
from test_core import settings, add
from screen_context import audit, capture, purge, quick, store
from screen_context.indexer import drain


def at(monkeypatch, ts):
    monkeypatch.setattr(capture.time, "time", lambda: ts)


def spooled(settings, monkeypatch, ts, text=None):
    """A frame captured at `ts`; OCRed and stored when `text` is given, left in the spool otherwise."""
    at(monkeypatch, ts)
    record = capture.spool(settings, Image.new("RGB", (40, 40), "white"), dict(app_bundle="com.example.App", app_name="App", window_title="t", display_id="1"))
    monkeypatch.undo()
    if text is not None: drain(settings, lambda _: [{"text": text, "bbox": [0, 0, 1, 1]}])
    return record["id"]


def test_quick_purge_removes_frames_previews_and_spool_files_in_the_window_only(settings, monkeypatch):
    now = time.time()
    old = spooled(settings, monkeypatch, now - 20 * 60, "twenty minutes ago")
    recent = spooled(settings, monkeypatch, now - 2 * 60, "two minutes ago")
    pending_old = spooled(settings, monkeypatch, now - 30 * 60)          # not OCRed yet
    pending_new = spooled(settings, monkeypatch, now - 60)
    images = settings.root / "images"
    with store.connect(settings, readonly=True) as con:
        stored = {r["id"]: r["image_path"] for r in con.execute("SELECT id, image_path FROM frames")}
    assert set(stored) == {old, recent} and all((images / p).exists() for p in stored.values())

    result = quick.delete(settings, 5)

    assert result["deleted"] and result["frames"] == 1 and result["spool_files"] == 1
    with store.connect(settings, readonly=True) as con:
        assert [r["id"] for r in con.execute("SELECT id FROM frames")] == [old]
    assert (images / stored[old]).exists() and not (images / stored[recent]).exists()
    assert sorted(p.stem for p in (settings.root / "spool").glob("*.frame")) == [pending_old]
    row = next(r for r in audit.rows(settings) if r["action"] == "purge")
    assert row["client"] == "app" and row["result_count"] == 1


def test_quick_purge_uses_the_selective_purge_path(settings, monkeypatch):
    calls = []
    real = purge.run
    monkeypatch.setattr(purge, "run", lambda *a, **k: calls.append(k) or real(*a, **k))
    quick.delete(settings, 15)
    assert calls == [{"last": "15m", "apply": True, "actor": "app"}]


def test_confirmation_text(settings, monkeypatch):
    assert quick.confirmation(settings, 60, "en") == ("Nothing was recorded in the last hour.", None)
    frame = add(settings, "just now", ts=time.time() - 30)
    audit.record(settings, "agent", "cursor", "search_screen_history", frame_ids=[frame["id"]], count=1)
    title, body = quick.confirmation(settings, 5, "en")
    assert title == "Delete what was recorded in the last 5 min?"
    assert body.startswith("1 screens, 0 not yet processed") and "Already received by cursor" in body
    title, _ = quick.confirmation(settings, 60, "ja")
    assert title == "直近1時間の記録を削除しますか？"
    with store.connect(settings, readonly=True) as con:                     # the dialog text deletes nothing
        assert con.execute("SELECT count(*) FROM frames").fetchone()[0] == 1


def test_open_today_starts_the_ui_as_its_own_process(settings, monkeypatch):
    spawned = []
    assert quick.open_today(settings, lambda: "verified", spawn=lambda cmd, **kw: spawned.append((cmd, kw))) == "verified"
    cmd, kw = spawned[0]
    assert cmd == [sys.executable, "-m", "screen_context.cli", "ui"]
    assert kw["env"]["SCREEN_CONTEXT_HOME"] == str(settings.root) and kw["start_new_session"] is True
    monkeypatch.setattr(sys, "frozen", "macosx_app", raising=False)
    monkeypatch.setenv("EXECUTABLEPATH", "/Applications/ScreenContext.app/Contents/MacOS/ScreenContext")
    assert quick.ui_command() == ["/Applications/ScreenContext.app/Contents/MacOS/ScreenContext", "ui"]


def test_menu_actions_on_macos(settings, monkeypatch):
    pytest.importorskip("AppKit")
    from screen_context import mac_app
    shown = []
    class Alert:
        def __init__(self): self.titles = []
        @classmethod
        def alloc(cls): return cls()
        def init(self): return self
        def setMessageText_(self, text): self.message = text
        def setInformativeText_(self, text): self.info = text
        def addButtonWithTitle_(self, title): self.titles.append(title)
        def buttons(self): return [object(), object()]
        def runModal(self):
            shown.append(self)
            return mac_app.NSAlertSecondButtonReturn if len(self.titles) == 2 else 1000
    monkeypatch.setattr(mac_app, "NSAlert", Alert)
    add(settings, "just now", ts=time.time() - 30)
    controller = mac_app.MenuController.alloc().init()
    controller.settings = settings
    item = type("Item", (), {"tag": lambda self: 5})()
    controller.deleteRecent_(item)
    assert shown[0].titles == ["Cancel", "Delete"] and shown[-1].message == "Deleted 1 screens."
    with store.connect(settings, readonly=True) as con:
        assert con.execute("SELECT count(*) FROM frames").fetchone()[0] == 0


def test_confirmation_counts_frames_not_yet_processed(settings, monkeypatch):
    spooled(settings, monkeypatch, time.time() - 30)                        # captured, OCR still pending
    title, body = quick.confirmation(settings, 5, "en")
    assert body is not None and body.startswith("0 screens, 1 not yet processed")
    assert quick.delete(settings, 5)["spool_files"] == 1 and not list((settings.root / "spool").glob("*.frame"))


@pytest.mark.parametrize("status", ["cancelled", "failed", "unavailable", "", None, "VERIFIED"])
def test_open_today_starts_nothing_unless_verified(settings, status):
    spawned = []
    assert quick.open_today(settings, lambda: status, spawn=lambda cmd, **kw: spawned.append(cmd)) == status
    assert spawned == []
