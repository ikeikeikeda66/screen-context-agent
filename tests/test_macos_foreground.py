"""A long-lived NSWorkspace cache must consume application-activation events."""
from types import SimpleNamespace
import pytest

pytest.importorskip("AppKit")
from screen_context.platforms import macos
from screen_context.config import DEFAULT_POLICY
from screen_context.privacy import denied


def test_foreground_tracks_switches_in_a_long_lived_process(monkeypatch):
    class Application:
        def __init__(self, bundle, pid): self.bundle, self.pid = bundle, pid
        def bundleIdentifier(self): return self.bundle
        def localizedName(self): return self.bundle
        def processIdentifier(self): return self.pid

    finder = Application("com.apple.finder", 10)
    browser = Application("com.google.Chrome", 20)
    passwords = Application("com.apple.Passwords", 30)
    state = {"os": finder, "cached": finder}
    workspace = SimpleNamespace(frontmostApplication=lambda: state["cached"])
    monkeypatch.setattr(macos, "NSWorkspace", SimpleNamespace(sharedWorkspace=lambda: workspace))

    def process_events(_deadline): state["cached"] = state["os"]

    # raising=False lets this regression run (and fail) before the fix adds imports.
    monkeypatch.setattr(macos, "NSRunLoop", SimpleNamespace(currentRunLoop=lambda: SimpleNamespace(runUntilDate_=process_events)), raising=False)
    monkeypatch.setattr(macos, "NSDate", SimpleNamespace(dateWithTimeIntervalSinceNow_=lambda _: None), raising=False)
    windows = [{"kCGWindowOwnerPID": app.pid, "kCGWindowLayer": 0, "kCGWindowName": app.bundle, "kCGWindowNumber": app.pid+100, "kCGWindowBounds": {"Width": 800, "Height": 600}} for app in (finder, browser, passwords)]
    windows.insert(0, {"kCGWindowOwnerPID": browser.pid, "kCGWindowLayer": 0, "kCGWindowNumber": 999, "kCGWindowBounds": {"Width": 2, "Height": 2}})
    monkeypatch.setattr(macos.Quartz, "CGWindowListCopyWindowInfo", lambda *_: windows)
    adapter = macos.Backend.__new__(macos.Backend)
    assert adapter.foreground()["app_bundle"] == finder.bundle
    state["os"] = browser
    observed = adapter.foreground()
    assert observed["app_bundle"] == browser.bundle
    assert observed["window_id"] == 120
    document = windows.pop(2)
    assert adapter.foreground()["window_id"] is None
    windows.insert(2, document)
    state["os"] = passwords
    assert denied(DEFAULT_POLICY, adapter.foreground())
