"""Backend.capture must refuse a stale foreground snapshot instead of shooting the wrong window."""
from types import SimpleNamespace
import pytest

pytest.importorskip("AppKit")
from screen_context.platforms import macos


class Window:
    def __init__(self, window_id, title, bundle_id):
        self._id, self._title, self._bundle = window_id, title, bundle_id

    def windowID(self): return self._id
    def title(self): return self._title
    def owningApplication(self): return SimpleNamespace(bundleIdentifier=lambda: self._bundle)


def make_adapter(windows):
    monkeypatch_content = SimpleNamespace(windows=lambda: windows)
    return macos.Backend.__new__(macos.Backend), monkeypatch_content


def fake_objc(log):
    """Stands in for PyObjC's autorelease_pool; records enter/exit around the ObjC calls made inside it."""
    class Pool:
        def __enter__(self): log.append("enter")
        def __exit__(self, *_): log.append("exit")
    return SimpleNamespace(autorelease_pool=lambda: Pool())


def test_capture_runs_inside_an_autorelease_pool_and_exits_on_error(monkeypatch):
    log = []
    monkeypatch.setattr(macos, "objc", fake_objc(log))
    adapter = macos.Backend.__new__(macos.Backend)
    front = {"app_bundle": "com.apple.finder", "window_title": "Desktop", "window_id": 42}
    def shareable_content():
        log.append("shareable")
        return SimpleNamespace(windows=lambda: [])
    monkeypatch.setattr(macos.sck, "shareable_content", shareable_content)
    with pytest.raises(RuntimeError, match="Foreground window disappeared"):
        adapter.capture(front)
    assert log == ["enter", "shareable", "exit"]


def test_capture_raises_when_no_foreground_window():
    adapter = macos.Backend.__new__(macos.Backend)
    front = {"app_bundle": "com.apple.finder", "window_title": "Desktop", "window_id": None}
    with pytest.raises(RuntimeError, match="No foreground window"):
        adapter.capture(front)


def test_capture_raises_when_window_disappeared(monkeypatch):
    adapter = macos.Backend.__new__(macos.Backend)
    front = {"app_bundle": "com.apple.finder", "window_title": "Desktop", "window_id": 42}
    monkeypatch.setattr(macos.sck, "shareable_content", lambda: SimpleNamespace(windows=lambda: []))
    with pytest.raises(RuntimeError, match="Foreground window disappeared"):
        adapter.capture(front)


def test_capture_raises_when_window_changed_since_foreground_snapshot(monkeypatch):
    adapter = macos.Backend.__new__(macos.Backend)
    front = {"app_bundle": "com.apple.finder", "window_title": "Desktop", "window_id": 42}
    stale_window = Window(42, "Downloads", "com.apple.finder")
    monkeypatch.setattr(macos.sck, "shareable_content", lambda: SimpleNamespace(windows=lambda: [stale_window]))
    with pytest.raises(RuntimeError, match="Window changed during capture request"):
        adapter.capture(front)


def test_secure_input_reports_the_carbon_value():
    adapter = macos.Backend.__new__(macos.Backend)
    adapter._secure_input = lambda: True
    assert adapter.secure_input() is True
    adapter._secure_input = lambda: False
    assert adapter.secure_input() is False


def test_secure_input_raises_when_the_check_is_unavailable():
    adapter = macos.Backend.__new__(macos.Backend)
    adapter._secure_input = OSError("x")
    with pytest.raises(OSError):
        adapter.secure_input()


def test_capture_treats_missing_secure_input_check_as_on():
    from screen_context import capture
    adapter = macos.Backend.__new__(macos.Backend)  # no _secure_input attribute: the method raises
    assert capture.secure_input(adapter) is True


def test_load_secure_input_raises_when_carbon_cannot_be_loaded(monkeypatch):
    import ctypes
    def unavailable(path): raise OSError("no Carbon")
    monkeypatch.setattr(ctypes.cdll, "LoadLibrary", unavailable)
    with pytest.raises(OSError):
        macos.load_secure_input()
