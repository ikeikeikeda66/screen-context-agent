"""idle_seconds must query the combined session's real input state; approve_current must gate on the user's alert choice."""
from types import SimpleNamespace
import pytest

pytest.importorskip("AppKit")
import AppKit
from screen_context.platforms import macos


def test_idle_seconds_returns_value_from_combined_session_state(monkeypatch):
    calls = []

    def fake_seconds(state_type, event_type):
        calls.append((state_type, event_type))
        return 42.5

    monkeypatch.setattr(macos.Quartz, "CGEventSourceSecondsSinceLastEventType", fake_seconds)
    adapter = macos.Backend.__new__(macos.Backend)
    assert adapter.idle_seconds() == 42.5
    assert calls == [(macos.Quartz.kCGEventSourceStateCombinedSessionState, macos.Quartz.kCGAnyInputEventType)]


class FakeAlert:
    instances = []

    def __init__(self):
        self.buttons = []
        FakeAlert.instances.append(self)

    def setMessageText_(self, text): self.message = text
    def setInformativeText_(self, text): self.info = text
    def addButtonWithTitle_(self, title): self.buttons.append(title)
    def runModal(self): return self.result


def make_fake_alert_class(result):
    class Alloc:
        def init(self):
            alert = FakeAlert()
            alert.result = result
            return alert
    class Cls:
        @staticmethod
        def alloc(): return Alloc()
    return Cls


def test_approve_current_returns_true_when_allow_clicked(monkeypatch):
    FakeAlert.instances.clear()
    monkeypatch.setattr(AppKit, "NSAlert", make_fake_alert_class(AppKit.NSAlertFirstButtonReturn + 1))
    adapter = macos.Backend.__new__(macos.Backend)
    assert adapter.approve_current() is True
    assert len(FakeAlert.instances[0].buttons) == 2


def test_approve_current_returns_false_when_deny_clicked(monkeypatch):
    FakeAlert.instances.clear()
    monkeypatch.setattr(AppKit, "NSAlert", make_fake_alert_class(AppKit.NSAlertFirstButtonReturn))
    adapter = macos.Backend.__new__(macos.Backend)
    assert adapter.approve_current() is False
