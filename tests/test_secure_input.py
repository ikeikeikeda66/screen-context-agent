"""#16: no capture while a secure text field has focus. Fake adapters only; nothing is captured."""
import json
import time
import pytest
from PIL import Image
from test_core import settings
from screen_context import capture, store
from screen_context.broker import process_requests


def foreground():
    return dict(app_bundle="Chrome", app_name="Chrome", window_title="Docs", window_id=1)


class Adapter:
    """Fake adapter with secure_input; `secure` is a bool, or an Exception to raise."""
    def __init__(self, secure=False, on_approve=None, on_capture=None):
        self.secure, self.on_approve, self.on_capture = secure, on_approve, on_capture
        self.probes, self.approvals, self.captures = 0, 0, 0

    def foreground(self):
        self.probes += 1
        return foreground()

    def idle_seconds(self): return 0

    def secure_input(self):
        if isinstance(self.secure, Exception): raise self.secure
        return self.secure

    def approve_current(self):
        self.approvals += 1
        if self.on_approve: self.on_approve(self)
        return True

    def capture(self, front):
        self.captures += 1
        if self.on_capture: self.on_capture(self)
        return Image.new("RGB", (100, 100)), {"display_id": "1"}


class Plain:
    """Platform without secure_input: must behave as before."""
    def foreground(self): return foreground()
    def idle_seconds(self): return 0
    def approve_current(self): return True
    def capture(self, front): return Image.new("RGB", (100, 100)), {"display_id": "1"}


@pytest.fixture
def skips(monkeypatch):
    calls = []
    monkeypatch.setattr(store, "record_skip", lambda settings, reason: calls.append(reason), raising=False)
    return calls


def frames(settings):
    return list((settings.root / "spool").glob("*.frame"))


def test_secure_input_probe_result(monkeypatch):
    assert capture.secure_input(object()) is False
    assert capture.secure_input(Adapter(secure=True)) is True
    assert capture.secure_input(Adapter(secure=False)) is False
    assert capture.secure_input(Adapter(secure=RuntimeError("probe failed"))) is True  # fail-closed


def test_once_skips_capture_while_secure_then_resumes(settings, skips, monkeypatch):
    adapter = Adapter(secure=True)
    monkeypatch.setattr(capture, "backend", lambda: adapter)
    assert capture.run(settings, once=True) == {"status": "secure_input"}
    assert adapter.captures == 0
    assert frames(settings) == []
    assert skips == ["secure_input"]
    status = json.loads((settings.root / "capture-status.json").read_text())
    assert status["status"] == "secure_input"
    assert set(status) == {"ts", "status"}  # no app name, title, or other key

    adapter.secure = False
    assert capture.run(settings, once=True)["status"] == "spooled"
    assert adapter.captures == 1
    assert len(frames(settings)) == 1
    assert skips == ["secure_input"]  # not recorded again once the field is no longer secure


def test_loop_skips_each_probe_while_secure(settings, skips, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(capture.time, "monotonic", lambda: clock[0])
    class Stop:
        cycles = 0
        def is_set(self): return self.cycles >= 40
        def wait(self, seconds): self.cycles += 1; clock[0] += seconds
    adapter = Adapter(secure=True)
    monkeypatch.setattr(capture, "backend", lambda: adapter)
    capture.run(settings, stop=Stop())
    assert adapter.captures == 0
    assert frames(settings) == []
    assert adapter.probes >= 2  # the loop really probed more than once
    assert skips == ["secure_input"] * adapter.probes  # one record per capture cycle


def test_probe_exception_fails_closed(settings, skips, monkeypatch):
    adapter = Adapter(secure=OSError("accessibility unavailable"))
    monkeypatch.setattr(capture, "backend", lambda: adapter)
    assert capture.run(settings, once=True) == {"status": "secure_input"}
    assert adapter.captures == 0
    assert frames(settings) == []


def test_probe_failure_status_names_only_the_error_type(settings, skips, monkeypatch):
    adapter = Adapter(secure=OSError("accessibility unavailable"))
    monkeypatch.setattr(capture, "backend", lambda: adapter)
    capture.run(settings, once=True)
    text = (settings.root / "capture-status.json").read_text()
    status = json.loads(text)
    assert status["status"] == "secure_input"
    assert status["error_type"] == "OSError"
    assert "accessibility unavailable" not in text  # the message is never written


def test_secure_field_during_capture_discards_the_image(settings, skips, monkeypatch):
    def focus_secure_field(adapter): adapter.secure = True
    adapter = Adapter(secure=False, on_capture=focus_secure_field)
    monkeypatch.setattr(capture, "backend", lambda: adapter)
    assert capture.run(settings, once=True) == {"status": "secure_input"}
    assert adapter.captures == 1  # the field appeared after the capture started
    assert frames(settings) == []
    assert skips == ["secure_input"]
    assert json.loads((settings.root / "capture-status.json").read_text())["status"] == "secure_input"


def test_adapter_without_method_captures_as_before(settings, skips, monkeypatch):
    monkeypatch.setattr(capture, "backend", lambda: Plain())
    assert capture.run(settings, once=True)["status"] == "spooled"
    assert len(frames(settings)) == 1
    assert skips == []


def write_request(settings):
    path = settings.root / "requests" / "secure.request"
    path.write_text(json.dumps({"expires": time.time() + 30}))
    return path


def test_current_screen_request_denied_while_secure(settings):
    adapter = Adapter(secure=True)
    request = write_request(settings)
    process_requests(settings, adapter)
    assert json.loads(request.with_suffix(".reply").read_text()) == {"status": "denied"}
    assert adapter.approvals == 0
    assert adapter.captures == 0
    assert frames(settings) == []


def test_secure_field_during_capture_is_not_spooled(settings):
    def focus_secure_field(adapter): adapter.secure = True
    adapter = Adapter(secure=False, on_capture=focus_secure_field)
    request = write_request(settings)
    process_requests(settings, adapter)
    assert json.loads(request.with_suffix(".reply").read_text()) == {"status": "denied"}
    assert adapter.captures == 1
    assert frames(settings) == []


def test_secure_field_appearing_during_dialog_denies(settings):
    def focus_secure_field(adapter): adapter.secure = True
    adapter = Adapter(secure=False, on_approve=focus_secure_field)
    request = write_request(settings)
    process_requests(settings, adapter)
    assert json.loads(request.with_suffix(".reply").read_text()) == {"status": "denied"}
    assert adapter.approvals == 1
    assert adapter.captures == 0
    assert frames(settings) == []


def test_current_screen_request_approved_when_not_secure(settings):
    adapter = Adapter(secure=False)
    request = write_request(settings)
    process_requests(settings, adapter)
    reply = json.loads(request.with_suffix(".reply").read_text())
    assert reply["status"] == "approved" and "frame_id" in reply
    assert adapter.captures == 1
    assert len(frames(settings)) == 1


def test_skip_reaches_the_skip_counter(settings, monkeypatch):
    # The real store.record_skip, end to end: one count by reason, no frame.
    monkeypatch.setattr(capture, "backend", lambda: Adapter(secure=True))
    capture.run(settings, once=True)
    with store.connect(settings, readonly=True) as con:
        assert [tuple(r) for r in con.execute("SELECT category, count FROM skip_counts")] == [("secure_input", 1)]
        assert con.execute("SELECT COUNT(*) FROM frames").fetchone()[0] == 0
