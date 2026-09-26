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
