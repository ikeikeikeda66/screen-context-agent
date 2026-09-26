"""First-connection approval: a new token waits for the user's answer in the capture app."""
import json
import threading
import time
import pytest
from test_core import settings
from screen_context import access, audit, capture
from screen_context.broker import process_client_requests
from screen_context.locking import lock


class App:
    """Stands in for the menu bar app / control window answering the dialog."""
    def __init__(self, answer): self.answer, self.asked = answer, []
    def approve_client(self, name, profile):
        self.asked.append((name, profile))
        return self.answer


def answering(settings, app):
    stop = threading.Event()
    def loop():
        while not stop.wait(.02): process_client_requests(settings, app)
    thread = threading.Thread(target=loop); thread.start()
    return stop, thread


@pytest.fixture
def running_app(settings):
    with lock(settings.root / "capture.lock"): yield


def requests(settings): return list((settings.root / "requests").glob("*.client"))


def test_new_client_is_approved_once_in_the_app(settings, running_app):
    token = access.issue(settings, "cursor", "full")
    assert access.state(settings, "cursor") == "pending"
    app = App(True)
    stop, thread = answering(settings, app)
    try:
        assert access.authorize(settings, token, "standard", timeout=5) == "cursor"
        assert access.authorize(settings, token, "standard", timeout=5) == "cursor"  # no second dialog
    finally: stop.set(); thread.join()
    assert app.asked == [("cursor", "full")] and access.state(settings, "cursor") == "active"
    assert audit.rows(settings, client="app")[0]["action"] == "clients.approve" and not requests(settings)


def test_denied_client_is_refused_without_asking_again(settings, running_app):
    token = access.issue(settings, "unknown-tool")
    app = App(False)
    stop, thread = answering(settings, app)
    try:
        with pytest.raises(PermissionError, match="not allowed"): access.authorize(settings, token, "standard", timeout=5)
        with pytest.raises(PermissionError, match="not allowed"): access.admit(settings, "unknown-tool", timeout=5)
    finally: stop.set(); thread.join()
    assert len(app.asked) == 1 and access.state(settings, "unknown-tool") == "denied"
    with pytest.raises(PermissionError): access.authenticate(settings, token, "standard")
    new = access.issue(settings, "unknown-tool")  # a new token asks again
    assert access.state(settings, "unknown-tool") == "pending" and access.authenticate(settings, new, "standard") == "unknown-tool"


def test_concurrent_calls_share_one_dialog(settings, running_app):
    access.issue(settings, "agent")
    app = App(True)
    results = []
    callers = [threading.Thread(target=lambda: results.append(access.admit(settings, "agent", timeout=5))) for _ in range(3)]
    for c in callers: c.start()
    time.sleep(.2)
    stop, thread = answering(settings, app)
    try:
        for c in callers: c.join()
    finally: stop.set(); thread.join()
    assert results == ["agent"] * 3 and len(app.asked) == 1


def test_without_the_app_the_call_fails_fast_with_the_fix(settings):
    access.issue(settings, "cursor")
    started = time.monotonic()
    with pytest.raises(PermissionError, match="clients approve cursor"): access.admit(settings, "cursor", timeout=5)
    assert time.monotonic() - started < 1 and not requests(settings)


def test_unanswered_request_times_out_and_is_withdrawn(settings, running_app):
    access.issue(settings, "cursor")
    with pytest.raises(PermissionError, match="waiting for your approval"): access.admit(settings, "cursor", timeout=.3)
    assert not requests(settings) and access.state(settings, "cursor") == "pending"


def test_shorter_timeout_caller_does_not_withdraw_the_request_for_a_longer_one(settings, running_app):
    access.issue(settings, "agent")
    results = {}
    def short():
        try: access.admit(settings, "agent", timeout=.2)
        except PermissionError as error: results["short"] = str(error)
    def waits_longer():
        results["long"] = access.admit(settings, "agent", timeout=2)
    t_short = threading.Thread(target=short); t_short.start()
    time.sleep(.05)
    t_long = threading.Thread(target=waits_longer); t_long.start()
    time.sleep(.4)  # the short caller's own deadline has passed
    assert requests(settings), "the shared request must survive a shorter-timeout caller's own deadline"
    app = App(True)
    stop, thread = answering(settings, app)
    try:
        t_short.join(); t_long.join()
    finally: stop.set(); thread.join()
    assert results["long"] == "agent"


def test_request_file_cannot_choose_the_profile_or_approve_other_clients(settings):
    access.issue(settings, "cursor")  # standard
    active = access.issue(settings, "trusted", "full"); access.decide(settings, "trusted", True, "cli")
    folder = settings.root / "requests"
    (folder / "a.client").write_text(json.dumps({"name": "cursor", "profile": "full", "expires": time.time() + 30}))
    (folder / "b.client").write_text(json.dumps({"name": "trusted", "expires": time.time() + 30}))
    (folder / "c.client").write_text("not json")
    app = App(True)
    process_client_requests(settings, app)
    assert app.asked == [("cursor", "standard")] and not requests(settings)
    assert access.authenticate(settings, active, "full") == "trusted"


def test_capture_app_answers_while_paused(settings, monkeypatch):
    access.issue(settings, "cursor")
    (settings.root / "requests" / "x.client").write_text(json.dumps({"name": "cursor", "expires": time.time() + 30}))
    (settings.root / "paused").touch()
    app = App(True)
    monkeypatch.setattr(capture, "backend", lambda: app)
    assert capture.run(settings, once=True) == {"status": "paused"}
    assert access.state(settings, "cursor") == "active"


def test_cli_approve_only_pending_clients(settings):
    access.issue(settings, "cursor")
    access.decide(settings, "cursor", True, "cli")
    with pytest.raises(ValueError): access.decide(settings, "cursor", True, "cli")
    with pytest.raises(ValueError): access.decide(settings, "missing", True, "cli")
