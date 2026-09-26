"""#47: never start a capture on a locked session, and recover when a worker crashes natively."""
import json
import time
from types import SimpleNamespace
import pytest
from test_core import settings
from test_desktop import Event, Process
from screen_context import capture
from screen_context.broker import process_requests
from screen_context.desktop import Workers
from screen_context.platforms.windows import Backend


class Locked:
    def foreground(self): return dict(app_bundle="chrome.exe", app_name="chrome.exe", window_title="Docs", window_id=1)
    def session_locked(self): return True
    def capture(self, front): raise AssertionError("capture must not start while the session is locked")
    def approve_current(self): raise AssertionError("nobody can approve on a locked screen")
    def idle_seconds(self): return 0


def test_capture_loop_skips_a_locked_session(settings, monkeypatch):
    monkeypatch.setattr(capture, "backend", lambda: Locked())
    assert capture.run(settings, once=True) == {"status": "locked"}
    assert not list((settings.root / "spool").iterdir())


def test_current_screen_requests_are_denied_while_locked(settings):
    request = settings.root / "requests" / "r.request"
    request.write_text(json.dumps({"expires": time.time() + 30}))
    process_requests(settings, Locked())
    assert json.loads(request.with_suffix(".reply").read_text()) == {"status": "denied"}


@pytest.mark.parametrize("desktop, switched, locked", [(0, 1, True), (7, 0, True), (7, 1, False)])
def test_windows_lock_detection(desktop, switched, locked):
    closed = []
    adapter = Backend.__new__(Backend)
    adapter.user = SimpleNamespace(OpenInputDesktop=lambda flags, inherit, access: desktop,
                                   SwitchDesktop=lambda handle: switched, CloseDesktop=closed.append)
    assert adapter.session_locked() is locked
    assert closed == ([desktop] if desktop else [])  # every opened desktop handle is closed


def test_crashed_worker_restarts_within_a_budget(tmp_path):
    from screen_context.config import Settings
    settings = Settings(tmp_path); settings.prepare()
    workers = Workers(settings, SimpleNamespace(Event=Event, Process=Process), max_restarts=2, window=600)
    workers.start()
    for _ in range(2):
        crashed = workers.processes["capture"]
        crashed.alive, crashed.exitcode = False, 0xC0000005  # access violation, as in #47
        assert workers.poll() == {"index": "running", "capture": "running"}
        assert workers.processes["capture"] is not crashed and not workers.stop_event.signaled
    status = json.loads((tmp_path / "capture-status.json").read_text())
    assert status["status"] == "error" and status["error_type"] == "WorkerRestarted"
    workers.processes["capture"].alive, workers.processes["capture"].exitcode = False, 1
    assert workers.poll()["capture"] == "failed" and workers.stop_event.signaled  # budget spent: stop as before


def test_a_clean_exit_or_a_requested_stop_is_not_restarted(tmp_path):
    from screen_context.config import Settings
    workers = Workers(Settings(tmp_path), SimpleNamespace(Event=Event, Process=Process))
    workers.start()
    workers.stop()
    workers.processes["capture"].alive, workers.processes["capture"].exitcode = False, 1
    assert workers.poll()["capture"] == "failed" and not workers.restarts
