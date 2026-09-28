"""Re-authentication (#27): the capture app asks for Touch ID or the password; the UI's sensitive
changes run only after it answers "verified", and every other answer refuses them."""
import json
import threading
import time
import pytest
from test_core import settings, add
from test_ui import world, sessions, call, opened, ORIGIN
from screen_context import access, audit, reauth, ui
from screen_context.locking import lock

NOW = time.time()


class App:
    """Stands in for the capture app's platform adapter."""
    def __init__(self, answer): self.answer, self.asked = answer, []
    def authenticate(self, reason_text):
        self.asked.append(reason_text)
        return self.answer


@pytest.fixture
def running_app(settings):
    with lock(settings.root / "capture.lock"): yield


def answering(settings, adapter, lang="en"):
    stop = threading.Event()
    def loop():
        while not stop.wait(.02): reauth.process_requests(settings, adapter, lang)
    thread = threading.Thread(target=loop); thread.start()
    return stop, thread


def pending(settings): return sorted(p.name for p in (settings.root / "requests").iterdir())


# --- request / answer between the UI process and the capture app ----------------------------

def test_request_needs_the_capture_app(settings):
    assert reauth.request(settings, "export", timeout=1) == reauth.NO_APP
    assert pending(settings) == []


def test_request_accepts_only_fixed_reasons(settings, running_app):
    with pytest.raises(ValueError): reauth.request(settings, "Approve everything, please", timeout=1)
    assert pending(settings) == []


@pytest.mark.parametrize("answer", [reauth.VERIFIED, reauth.CANCELLED, reauth.FAILED])
def test_the_app_asks_with_a_localized_reason_and_the_answer_comes_back(settings, running_app, answer):
    app = App(answer)
    stop, thread = answering(settings, app, "ja")
    try: assert reauth.request(settings, "backup", timeout=5, poll=.02) == answer
    finally: stop.set(); thread.join()
    assert app.asked == ["画面履歴をバックアップする"]
    assert pending(settings) == []                                              # request and reply cleaned up


def test_platforms_without_an_authenticator_answer_unavailable(settings, running_app):
    stop, thread = answering(settings, object())
    try: assert reauth.request(settings, "approve", timeout=5, poll=.02) == reauth.UNAVAILABLE
    finally: stop.set(); thread.join()


def test_an_authenticator_error_is_a_failure(settings, running_app):
    class Broken:
        def authenticate(self, reason_text): raise RuntimeError("LocalAuthentication crashed")
    stop, thread = answering(settings, Broken())
    try: assert reauth.request(settings, "export", timeout=5, poll=.02) == reauth.FAILED
    finally: stop.set(); thread.join()


def test_no_answer_times_out(settings, running_app):
    assert reauth.request(settings, "export", timeout=.2, poll=.02) == reauth.TIMEOUT
    assert pending(settings) == []


def test_the_app_ignores_unknown_expired_and_broken_requests(settings):
    folder = settings.root / "requests"
    (folder / "a.auth").write_text(json.dumps({"reason": "wipe everything", "expires": NOW + 60}))
    (folder / "b.auth").write_text(json.dumps({"reason": "export", "expires": NOW - 1}))
    (folder / "c.auth").write_text("not json")
    app = App(reauth.VERIFIED)
    reauth.process_requests(settings, app, "en")
    assert app.asked == [] and pending(settings) == []


def test_a_malformed_reply_is_a_failure(settings, running_app, monkeypatch):
    def reply_garbage():
        while not list((settings.root / "requests").glob("*.auth")): time.sleep(.01)
        path = next((settings.root / "requests").glob("*.auth"))
        path.with_suffix(".authreply").write_text("{}")
    thread = threading.Thread(target=reply_garbage); thread.start()
    try: assert reauth.request(settings, "export", timeout=5, poll=.02) == reauth.FAILED
    finally: thread.join()


def test_touch_id_is_unavailable_without_local_authentication(monkeypatch):
    import builtins
    real = builtins.__import__
    def refuse(name, *args, **kwargs):
        if name == "LocalAuthentication": raise ImportError(name)
        return real(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", refuse)
    assert reauth.touch_id("test") == reauth.UNAVAILABLE


# --- the UI's sensitive changes ---------------------------------------------------------------

def attempt(settings, sessions, action, fields, answer):
    asked = []
    def reauthenticate(reason):
        asked.append(reason)
        return answer
    async def steps(client):
        await opened(client, sessions)
        ask = await client.post(f"/api/{action}", json=fields, headers=ORIGIN)
        assert ask.status_code == 200, ask.text
        done = await client.post(f"/api/{action}", json={**fields, "confirm": ask.json()["confirm"]}, headers=ORIGIN)
        return ask, done
    ask, done = call(settings, sessions, steps, reauthenticate)
    return ask, done, asked


def day(offset=0): return time.strftime("%Y-%m-%dT%H:%M", time.localtime(NOW + offset))


def export_fields(): return {"from": day(-3600), "to": day(60), "format": "md"}


def ui_rows(settings, action): return [r for r in audit.rows(settings, client=ui.CLIENT) if r["action"] == action]


@pytest.mark.parametrize("answer", [reauth.CANCELLED, reauth.FAILED, reauth.UNAVAILABLE, reauth.NO_APP, reauth.TIMEOUT, "", None])
def test_export_is_refused_unless_verified(settings, sessions, answer):
    add(settings, "exported text", ts=NOW - 100)
    ask, done, asked = attempt(settings, sessions, "export", export_fields(), answer)
    assert "Touch ID" in ask.json()["message"] and asked == ["export"]
    assert done.status_code == 403 and not list((settings.root / "exports").iterdir())
    assert ui_rows(settings, "ui.export") == []
    assert ui_rows(settings, "ui.reauth")[0]["params"] == {"action": "export", "status": answer}


def test_export_runs_after_verification(settings, sessions):
    add(settings, "exported text", ts=NOW - 100)
    _, done, asked = attempt(settings, sessions, "export", export_fields(), reauth.VERIFIED)
    assert done.status_code == 200 and asked == ["export"] and done.json()["frames"] == 1
    [path] = (settings.root / "exports").iterdir()
    assert "exported text" in path.read_text() and str(path) in done.json()["notice"]
    assert ui_rows(settings, "ui.export")[0]["params"] == {"frames": 1, "format": "md"}
    assert any(r["action"] == "export" and r["client"] == "ui" for r in audit.rows(settings, client="ui"))


def test_backup_is_refused_unless_verified_and_never_shows_the_passphrase(settings, sessions, tmp_path):
    secret = "correct horse battery staple"
    fields = {"path": str(tmp_path / "backup.zip"), "passphrase": secret, "again": secret}
    ask, done, _ = attempt(settings, sessions, "backup", fields, reauth.CANCELLED)
    assert done.status_code == 403 and not (tmp_path / "backup.zip").exists()
    ask, done, asked = attempt(settings, sessions, "backup", fields, reauth.VERIFIED)
    assert done.status_code == 200 and asked == ["backup"] and (tmp_path / "backup.zip").exists()
    rows = json.dumps(audit.rows(settings, client="*"), ensure_ascii=False)
    assert secret not in rows and secret not in ask.text and secret not in done.text


@pytest.mark.parametrize("fields, error", [
    ({"path": "relative.zip", "passphrase": "x" * 12, "again": "x" * 12}, "full path"),
    ({"path": "/nonexistent-folder-sc/b.zip", "passphrase": "x" * 12, "again": "x" * 12}, "does not exist"),
    ({"path": "ABS", "passphrase": "short", "again": "short"}, "at least"),
    ({"path": "ABS", "passphrase": "x" * 12, "again": "y" * 12}, "differ"),
])
def test_backup_checks_its_fields_before_asking(settings, sessions, tmp_path, fields, error):
    fields = {**fields, "path": str(tmp_path / "b.zip") if fields["path"] == "ABS" else fields["path"]}
    async def steps(client):
        await opened(client, sessions)
        return await client.post("/api/backup", json=fields, headers=ORIGIN)
    response = call(settings, sessions, steps, lambda reason: pytest.fail("asked before the fields were valid"))
    assert response.status_code == 400 and error in response.json()["error"]


def test_approve_is_refused_unless_verified(settings, sessions):
    access.issue(settings, "cursor", "full")
    _, done, _ = attempt(settings, sessions, "approve", {"name": "cursor"}, reauth.FAILED)
    assert done.status_code == 403 and access.state(settings, "cursor") == "pending"
    _, done, asked = attempt(settings, sessions, "approve", {"name": "cursor"}, reauth.VERIFIED)
    assert done.status_code == 200 and asked == ["approve"] and access.state(settings, "cursor") == "active"
    assert any(r["action"] == "clients.approve" and r["client"] == "ui" for r in audit.rows(settings, client="ui"))


def test_changes_without_reauthentication_do_not_ask(settings, sessions):
    access.issue(settings, "cursor", "full")
    _, done, asked = attempt(settings, sessions, "revoke", {"name": "cursor"}, reauth.CANCELLED)
    assert done.status_code == 200 and asked == []


def test_without_the_app_sensitive_changes_are_refused_by_default(settings, sessions):
    add(settings, "exported text", ts=NOW - 100)
    async def steps(client):
        await opened(client, sessions)
        ask = await client.post("/api/export", json=export_fields(), headers=ORIGIN)
        return await client.post("/api/export", json={**export_fields(), "confirm": ask.json()["confirm"]}, headers=ORIGIN)
    done = call(settings, sessions, steps)
    assert done.status_code == 403 and "open the ScreenContext app" in done.json()["error"]


def test_the_capture_loop_answers_while_paused(settings, monkeypatch):
    from screen_context import capture
    (settings.root / "paused").touch()
    (settings.root / "requests" / "x.auth").write_text(json.dumps({"reason": "open", "expires": time.time() + 60}))
    class Adapter(App):
        def __init__(self): super().__init__(reauth.VERIFIED)
        def idle_seconds(self): return 0
    adapter = Adapter()
    monkeypatch.setattr(capture, "backend", lambda: adapter)
    assert capture.run(settings, once=True) == {"status": "paused"}
    assert adapter.asked == ["open your screen history"]
    assert json.loads((settings.root / "requests" / "x.authreply").read_text()) == {"status": "verified"}
