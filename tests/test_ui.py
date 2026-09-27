"""Local web UI (#26): launch token to cookie, Host/Origin checks, confirmed POST-only writes,
session expiry on idle and on screen lock, audit rows, and no capture imports."""
import asyncio
import subprocess
import sys
import httpx
import pytest
from test_core import settings
from screen_context import audit, ui

PORT = 51234
BASE = f"http://127.0.0.1:{PORT}"
ORIGIN = {"Origin": BASE}


class World:
    """A fake clock and lock state for Sessions."""
    def __init__(self): self.now, self.is_locked = 1000.0, False
    def clock(self): return self.now
    def locked(self): return self.is_locked


@pytest.fixture
def world(): return World()


@pytest.fixture
def sessions(settings, world):
    return ui.Sessions(locked=world.locked, clock=world.clock,
                       on_end=lambda reason: audit.record(settings, "user", ui.CLIENT, "ui.close", params={"reason": reason}))


def call(settings, sessions, steps):
    """Run `steps(client)` against the app with a client that keeps cookies, like a browser."""
    app = ui.create_app(settings, sessions, PORT)
    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as client:
            return await steps(client)
    return asyncio.run(go())


async def opened(client, sessions):
    response = await client.get("/launch", params={"t": sessions.launch_token()})
    assert response.status_code == 303 and response.headers["location"] == "/"
    return response


def actions(settings):
    """The UI's own session and write rows (page reads are audited too, under their tool names)."""
    return [r["action"] for r in reversed(audit.rows(settings, client=ui.CLIENT)) if r["action"].startswith("ui.")]


def last(settings, action): return next(r for r in audit.rows(settings, client=ui.CLIENT) if r["action"] == action)


def test_launch_token_becomes_an_httponly_strict_cookie_once(settings, sessions):
    async def steps(client):
        token = sessions.launch_token()
        response = await client.get("/launch", params={"t": token})
        cookie = response.headers["set-cookie"].lower()
        assert response.status_code == 303 and "httponly" in cookie and "samesite=strict" in cookie and token.lower() not in cookie
        page = await client.get("/")
        assert page.status_code == 200 and 'data-action="pause"' in page.text
        again = await httpx.AsyncClient(transport=client._transport, base_url=BASE).get("/launch", params={"t": token})
        assert again.status_code == 403                                  # used
        assert (await client.get("/launch")).status_code == 403          # missing
        assert (await client.get("/launch", params={"t": "sc_forged"})).status_code == 403
    call(settings, sessions, steps)
    assert actions(settings) == ["ui.open"]


def test_launch_token_expires(settings, sessions, world):
    token = sessions.launch_token()
    world.now += ui.LAUNCH_TTL + 1
    assert sessions.exchange(token) is None


def test_pages_need_a_session(settings, sessions):
    async def steps(client):
        assert (await client.get("/")).status_code == 401
        assert (await client.get("/state")).status_code == 401
        client.cookies.set(ui.COOKIE, "forged")
        assert (await client.get("/")).status_code == 401
    call(settings, sessions, steps)


@pytest.mark.parametrize("host", ["evil.example", f"evil.example:{PORT}", "127.0.0.1:1", f"127.0.0.2:{PORT}"])
def test_wrong_host_is_refused(settings, sessions, host):
    async def steps(client):
        await opened(client, sessions)
        return await client.get("/", headers={"Host": host})
    assert call(settings, sessions, steps).status_code == 421


def test_security_headers_and_no_cors(settings, sessions):
    async def steps(client):
        page = await client.get("/")
        preflight = await client.options("/api/pause", headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "POST"})
        return page, preflight
    page, preflight = call(settings, sessions, steps)
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"] and page.headers["cache-control"] == "no-store"
    assert page.headers["referrer-policy"] == "no-referrer"
    assert preflight.status_code == 405 and "access-control-allow-origin" not in preflight.headers


def test_write_needs_same_origin_post_json_and_a_confirmation(settings, sessions):
    paused = settings.root / "paused"
    async def steps(client):
        await opened(client, sessions)
        assert (await client.get("/api/pause")).status_code == 405                                            # GET for a write
        assert (await client.post("/api/pause", json={})).status_code == 403                                  # no Origin
        assert (await client.post("/api/pause", json={}, headers={"Origin": "http://evil.example"})).status_code == 403
        assert (await client.post("/api/pause", data={"confirm": "x"}, headers=ORIGIN)).status_code == 415   # a plain form post
        assert (await client.post("/api/pause", content=b"[]", headers={**ORIGIN, "Content-Type": "application/json"})).status_code == 400
        assert (await client.post("/api/wipe", json={}, headers=ORIGIN)).status_code == 404
        ask = (await client.post("/api/pause", json={}, headers=ORIGIN)).json()
        assert ask["confirm"] and "Pause" in ask["message"] and not paused.exists()
        assert (await client.post("/api/pause", json={"confirm": "wrong"}, headers=ORIGIN)).status_code == 403
        other = (await client.post("/api/resume", json={}, headers=ORIGIN)).json()["confirm"]
        assert (await client.post("/api/pause", json={"confirm": other}, headers=ORIGIN)).status_code == 403  # nonce for another action
        ask = (await client.post("/api/pause", json={}, headers=ORIGIN)).json()
        done = await client.post("/api/pause", json={"confirm": ask["confirm"]}, headers=ORIGIN)
        assert done.status_code == 200 and done.json()["paused"] is True and paused.exists()
        assert (await client.post("/api/pause", json={"confirm": ask["confirm"]}, headers=ORIGIN)).status_code == 403  # used once
        assert 'data-action="resume"' in (await client.get("/")).text
    call(settings, sessions, steps)
    assert actions(settings) == ["ui.open", "ui.pause"]
    assert last(settings, "ui.pause")["params"] == {"paused": True}


def test_confirmation_is_bound_to_the_session(settings, sessions):
    async def steps(client):
        await opened(client, sessions)
        nonce = (await client.post("/api/pause", json={}, headers=ORIGIN)).json()["confirm"]
        async with httpx.AsyncClient(transport=client._transport, base_url=BASE) as other:
            await opened(other, sessions)
            return await other.post("/api/pause", json={"confirm": nonce}, headers=ORIGIN)
    assert call(settings, sessions, steps).status_code == 403 and not (settings.root / "paused").exists()


def test_session_expires_after_idle_and_polling_does_not_extend_it(settings, sessions, world):
    async def steps(client):
        await opened(client, sessions)
        world.now += ui.IDLE - 10
        assert (await client.get("/")).status_code == 200    # a real request counts as activity
        world.now += ui.IDLE - 10
        assert (await client.get("/state")).status_code == 200
        world.now += 20                                       # polling above did not reset the clock
        assert (await client.get("/state")).status_code == 401
        assert (await client.get("/")).status_code == 401
    call(settings, sessions, steps)
    assert actions(settings) == ["ui.open", "ui.close"]
    assert last(settings, "ui.close")["params"] == {"reason": "idle"}


def test_screen_lock_ends_every_session_at_once(settings, sessions, world):
    async def steps(client):
        await opened(client, sessions)
        pending = sessions.launch_token()
        world.is_locked = True
        assert sessions.sweep() is False                      # sessions and pending launch links are gone
        world.is_locked = False
        assert (await client.get("/")).status_code == 401     # unlocking does not bring the session back
        assert (await client.get("/launch", params={"t": pending})).status_code == 403
    call(settings, sessions, steps)
    assert last(settings, "ui.close")["params"] == {"reason": "locked"}


def test_lock_refuses_requests_before_the_sweep_runs(settings, sessions, world):
    async def steps(client):
        await opened(client, sessions)
        pending = sessions.launch_token()
        world.is_locked = True
        return await client.get("/"), await client.get("/launch", params={"t": pending})
    page, launch = call(settings, sessions, steps)
    assert page.status_code == 401 and launch.status_code == 403


def test_sweep_keeps_the_process_while_a_session_or_launch_link_is_live(sessions, world):
    token = sessions.launch_token()
    assert sessions.sweep() is True
    world.now += ui.LAUNCH_TTL + 1
    assert sessions.sweep() is False
    token = sessions.launch_token()
    sessions.exchange(token)
    world.now += ui.IDLE - 1
    assert sessions.sweep() is True


def test_page_text_follows_the_language(settings, sessions):
    settings.set_language("ja")
    async def steps(client):
        await opened(client, sessions)
        return (await client.get("/")).text
    page = call(settings, sessions, steps)
    assert '<html lang="ja">' in page and "撮影を一時停止" in page and "<script>" not in page  # the CSP allows no inline script


def test_ui_process_does_not_import_capture_code():
    code = ("import sys, screen_context.ui, screen_context.cli; "
            "bad = sorted(m for m in sys.modules if m.startswith(('screen_context.capture', 'screen_context.platforms', "
            "'screen_context.broker', 'screen_context.indexer', 'screen_context.mcp_server'))); print(bad)")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout.strip()
    assert out == "[]"


def test_process_exits_when_no_session_or_launch_link_is_left(tmp_path):
    """The real server: prints a one-time link, and exits by itself once the link expires unused."""
    code = ("import sys; from pathlib import Path; from screen_context import ui, store; from screen_context.config import Settings; "
            "ui.LAUNCH_TTL = 1; s = Settings(Path(sys.argv[1]), plaintext=True); store.initialize(s); ui.run(s, open_browser=False)")
    done = subprocess.run([sys.executable, "-c", code, str(tmp_path)], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    assert "http://127.0.0.1:" in done.stderr and "/launch?t=" in done.stderr
