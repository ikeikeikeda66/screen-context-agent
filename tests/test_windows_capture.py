"""Contract tests with simulated Win32/WGC; no real desktop is captured."""
import sys
from types import SimpleNamespace

import pytest

from screen_context.platforms.windows import Backend


TARGET = dict(app_bundle="chrome.exe", app_name="chrome.exe", window_title="Docs",
              window_id=123, process_id=42, process_started_at=100.0)


@pytest.fixture
def adapter():
    value = Backend.__new__(Backend)
    value.window_identity = lambda hwnd: dict(TARGET)
    return value


def fake_wgc(monkeypatch, action):
    instances = []

    class Capture:
        def __init__(self, cursor_capture, window_hwnd):
            assert cursor_capture is False
            assert window_hwnd == TARGET["window_id"]
            self.stopped = False
            instances.append(self)

        def event(self, callback):
            setattr(self, callback.__name__, callback)
            return callback

        def start_free_threaded(self):
            action(self)
            return self

        def stop(self):
            self.stopped = True

    monkeypatch.setitem(sys.modules, "windows_capture", SimpleNamespace(WindowsCapture=Capture))
    return instances


def deliver(capture, data=b"\x00\x00\xff\xff"):
    buffer = SimpleNamespace(copy=lambda: SimpleNamespace(tobytes=lambda: data))
    capture.on_frame_arrived(SimpleNamespace(width=1, height=1, frame_buffer=buffer), None)


def test_exact_target_capture_and_cleanup(adapter, monkeypatch):
    instances = fake_wgc(monkeypatch, deliver)
    image, metadata = adapter.capture(TARGET)
    assert image.getpixel((0, 0)) == (255, 0, 0)
    assert metadata["display_id"] == "foreground-window"
    assert instances[0].stopped


@pytest.mark.parametrize("changed", [{"process_id": 43}, {"process_started_at": 101}, {"window_title": "Other"}])
@pytest.mark.parametrize("during", [False, True])
def test_changed_target_is_rejected(adapter, monkeypatch, changed, during):
    def replace():
        adapter.window_identity = lambda hwnd: {**TARGET, **changed}

    def arrive(capture):
        deliver(capture)
        replace()

    instances = fake_wgc(monkeypatch, arrive)
    if not during: replace()
    with pytest.raises(RuntimeError, match="Window changed"):
        adapter.capture(TARGET)
    assert len(instances) == int(during)
    if during: assert instances[0].stopped


@pytest.mark.parametrize("action, message", [
    (lambda c: c.on_closed(), "Window closed"),
    (lambda c: deliver(c, b""), "frame conversion failed"),
])
def test_failure_releases_capture(adapter, monkeypatch, action, message):
    instances = fake_wgc(monkeypatch, action)
    with pytest.raises(RuntimeError, match=message): adapter.capture(TARGET)
    assert instances[0].stopped


def test_timeout_releases_capture(adapter, monkeypatch):
    instances = fake_wgc(monkeypatch, lambda c: None)
    monkeypatch.setattr("screen_context.platforms.windows.threading.Event",
                        lambda: SimpleNamespace(wait=lambda seconds: False))
    with pytest.raises(TimeoutError): adapter.capture(TARGET)
    assert instances[0].stopped


def test_missing_exact_hwnd_support_fails_closed(adapter, monkeypatch):
    class OldCapture:
        def __init__(self, window_name=None):
            pytest.fail("Must not fall back to title capture")
    monkeypatch.setitem(sys.modules, "windows_capture", SimpleNamespace(WindowsCapture=OldCapture))
    with pytest.raises(RuntimeError, match="exact window_hwnd"):
        adapter.capture(TARGET)


def test_unavailable_foreground_is_not_a_worker_crash(adapter):
    adapter.user = SimpleNamespace(GetForegroundWindow=lambda: 0)
    def unavailable(hwnd): raise RuntimeError("Unavailable")
    adapter.window_identity = unavailable
    assert adapter.foreground()["window_id"] == 0
    with pytest.raises(RuntimeError): adapter.validate_target(adapter.foreground())


def test_win32_identity_includes_process_birth(monkeypatch):
    class User:
        def IsWindow(self, hwnd): return hwnd == 123
        def GetWindowThreadProcessId(self, hwnd, pid):
            pid._obj.value = 42
            return 7
        def GetWindowTextLengthW(self, hwnd): return 4
        def GetWindowTextW(self, hwnd, text, size): text.value = "Docs"

    monkeypatch.setitem(sys.modules, "psutil", SimpleNamespace(
        Error=OSError, Process=lambda pid: SimpleNamespace(name=lambda: "chrome.exe", create_time=lambda: 100.0)))
    adapter = Backend.__new__(Backend)
    adapter.user = User()
    assert adapter.window_identity(123) == TARGET
    with pytest.raises(RuntimeError): adapter.window_identity(0)

