"""Work sessions and the Resume card (#29)."""
import asyncio
import json
import subprocess
import sys
import time
import pytest
from test_core import settings, add, change
from test_ui import world, sessions as ui_sessions, call, opened, ORIGIN
from screen_context import audit, capture, sessions, store, ui
from screen_context.privacy import SELF_TITLE, denied

T0 = 1_800_000_000.0
MIN = 60


def frames(*offsets): return [{"ts": T0 + o, "id": str(o)} for o in offsets]
def cut(parts, events=(), threshold=15 * MIN): return [[f["id"] for f in g] for g in sessions.split(frames(*parts), list(events), threshold, T0 + 10**6)]


# --- splitting on synthetic timelines ---------------------------------------------------------

def test_app_switches_and_short_gaps_stay_in_one_session():
    assert cut([0, 60, 120, 600, 900]) == [["0", "60", "120", "600", "900"]]


def test_a_gap_between_frames_of_the_threshold_splits():
    assert cut([0, 60, 60 + 15 * MIN]) == [["0", "60"], [str(60 + 15 * MIN)]]
    assert cut([0, 60, 60 + 14 * MIN]) == [["0", "60", str(60 + 14 * MIN)]]


def test_any_lock_or_pause_splits_even_a_short_one():
    lock = [(T0 + 70, "locked"), (T0 + 130, "active")]
    assert cut([0, 60, 180], lock) == [["0", "60"], ["180"]]
    pause = [(T0 + 70, "paused"), (T0 + 100, "active")]
    assert cut([0, 60, 180], pause) == [["0", "60"], ["180"]]


def test_idle_splits_only_from_the_threshold():
    # Frames can keep coming while nobody is at the keyboard (a video, notifications).
    short = [(T0 + 100, "idle"), (T0 + 100 + 10 * MIN, "active")]
    long = [(T0 + 100, "idle"), (T0 + 100 + 20 * MIN, "active")]
    timeline = [0, 60, 300, 600, 900, 1200, 1300]
    assert len(cut(timeline, short)) == 1
    assert cut(timeline, long) == [["0", "60"], ["300", "600", "900", "1200", "1300"]]
    assert len(cut(timeline, long, threshold=30 * MIN)) == 1           # a longer threshold keeps it whole


def test_state_carried_in_from_before_the_window(settings):
    sessions.record(settings, "locked", T0 - 500)
    sessions.record(settings, "active", T0 + 10)
    events = sessions.presence(settings, T0, T0 + 100)
    assert events == [(T0 - 500, "locked"), (T0 + 10, "active")]
    assert cut([0, 60], events + [(T0 + 30, "locked"), (T0 + 40, "active")]) == [["0"], ["60"]]


# --- presence recording by the capture process ------------------------------------------------

class Adapter:
    def __init__(self): self.idle, self.lock = 0.0, False
    def idle_seconds(self): return self.idle
    def session_locked(self): return self.lock


def states(settings):
    with store.connect(settings, readonly=True) as con:
        return [(r["ts"], r["state"]) for r in con.execute("SELECT ts, state FROM presence ORDER BY id")]


def test_presence_records_transitions_only(settings):
    adapter, now = Adapter(), [T0]
    tracker = sessions.Presence(settings, adapter, clock=lambda: now[0])
    assert tracker.tick() == "active" and tracker.tick() is None
    now[0] += 200; adapter.idle = 90
    assert tracker.tick() == "idle"
    now[0] += 60; adapter.idle = 150
    assert tracker.tick() is None                                      # still idle: no new row
    now[0] += 10; adapter.lock = True
    assert tracker.tick() == "locked"
    now[0] += 10
    assert tracker.tick(paused=True) == "paused"
    assert states(settings) == [(T0, "active"), (T0 + 110, "idle"), (T0 + 270, "locked"), (T0 + 280, "paused")]  # idle dated from the last input


def test_presence_never_breaks_capture(tmp_path):
    from screen_context.config import Settings
    tracker = sessions.Presence(Settings(tmp_path / "missing", plaintext=True), object())
    assert tracker.tick() is None                                      # no database, no idle API, no lock API


def test_capture_loop_records_a_pause(settings, monkeypatch):
    (settings.root / "paused").touch()
    monkeypatch.setattr(capture, "backend", lambda: Adapter())
    assert capture.run(settings, once=True) == {"status": "paused"}
    assert [s for _, s in states(settings)] == ["paused"]


# --- the Resume card ----------------------------------------------------------------------------

@pytest.fixture
def worked(settings):
    now = time.time()
    add(settings, "old morning work", app="com.apple.Notes", ts=now - 5 * 3600, title="Morning notes")
    sessions.record(settings, "locked", now - 4 * 3600)
    sessions.record(settings, "active", now - 3000)
    add(settings, "Spec draft https://docs.example.com/x", app="com.google.Chrome", ts=now - 2400, title="Spec — Docs")
    add(settings, "Spec draft continued https://docs.example.com/x", app="com.google.Chrome", ts=now - 2300, title="Spec — Docs")
    add(settings, "def resume(): pass", app="com.microsoft.VSCode", ts=now - 2000, title="sessions.py")
    add(settings, "vault secret", app="com.1password.1password", ts=now - 1900, title="Vault")          # excluded
    add(settings, "history of my screen", app="com.google.Chrome", ts=now - 1850, title=f"{SELF_TITLE} - Google Chrome")
    add(settings, "last thing I read: rate limits per client", app="com.google.Chrome", ts=now - 1800, title="API limits")
    return settings, now


def test_resume_card_shows_the_latest_session(worked):
    settings, now = worked
    card = sessions.resume(settings, now=now)
    assert card["frames"] == 4 and card["last_app"] == "com.google.Chrome"
    assert [d["title"] for d in card["documents"]] == ["API limits", "sessions.py", "Spec — Docs"]
    assert "rate limits per client" in card["excerpt"]
    text = json.dumps(card)
    assert "Morning notes" not in text and "Vault" not in text and SELF_TITLE not in text
    row = next(r for r in audit.rows(settings) if r["action"] == "resume")
    assert row["path"] == "user" and len(row["frame_ids"]) == 4


def test_threshold_is_configurable(worked):
    settings, now = worked
    settings.set_session_idle_minutes(3)
    assert sessions.resume(settings, now=now)["frames"] == 1           # 5 min gaps now split: only the last screen
    with pytest.raises(ValueError): settings.set_session_idle_minutes(0)


def test_own_ui_title_is_never_kept():
    policy = {"denied_apps": [], "denied_title_patterns": [], "denied_domains": []}
    assert denied(policy, {"app_bundle": "com.apple.Safari", "window_title": SELF_TITLE})
    assert not denied(policy, {"app_bundle": "com.apple.Safari", "window_title": "ScreenContext on GitHub"})


# --- the card in the UI, and feedback -----------------------------------------------------------

def test_card_is_on_todays_page_only_and_feedback_is_stored_locally(worked, ui_sessions):
    settings, now = worked
    async def steps(client):
        await opened(client, ui_sessions)
        page = (await client.get("/")).text
        other = (await client.get("/", params={"date": "2020-01-01"})).text
        match = __import__("re").search(r'data-start="([^"]+)" data-end="([^"]+)"', page)
        body = {"verdict": "helpful", "session_start": float(match.group(1)), "session_end": float(match.group(2))}
        refused = [(await client.post("/api/feedback", json=body)).status_code,                              # no Origin
                   (await client.post("/api/feedback", json={**body, "verdict": "great"}, headers=ORIGIN)).status_code,
                   (await client.get("/api/feedback")).status_code]
        done = await client.post("/api/feedback", json=body, headers=ORIGIN)                                  # no confirmation step
        return page, other, refused, done
    page, other, refused, done = call(settings, ui_sessions, steps)
    assert 'id="resume-card"' in page and "API limits" in page and "resume-card" not in other
    assert refused == [403, 400, 405] and done.status_code == 200
    assert sessions.feedback_summary(settings) == [{"idle_minutes": 15, "helpful": 1, "off": 0}]
    assert next(r for r in audit.rows(settings) if r["action"] == "ui.feedback")["params"]["verdict"] == "helpful"


def test_feedback_and_presence_are_never_served_over_mcp(settings):
    from screen_context.mcp_server import create_server
    names = {tool.name for tool in asyncio.run(create_server(settings, "full").list_tools())}
    assert not {n for n in names if any(w in n for w in ("feedback", "presence", "session", "resume"))}
    import screen_context.mcp_server as mcp, screen_context.service as service
    for module in (mcp, service):
        source = open(module.__file__, encoding="utf-8").read()
        assert "feedback" not in source and "presence" not in source


def test_feedback_validation(settings):
    with pytest.raises(ValueError): sessions.give_feedback(settings, "great", 1.0, 2.0)
    with pytest.raises(ValueError): sessions.give_feedback(settings, "off", "yesterday", 2.0)
    with pytest.raises(ValueError): sessions.give_feedback(settings, "off", True, 2.0)


# --- retention and CLI --------------------------------------------------------------------------

def test_text_retention_removes_old_presence(settings):
    from screen_context.indexer import maintain
    sessions.record(settings, "idle", time.time() - 40 * 86400)
    sessions.record(settings, "active", time.time() - 3600)
    settings.set_retention("text_retention_days", 30)
    maintain(settings)
    assert [s for _, s in states(settings)] == ["active"]


def test_cli_sessions(settings):
    env = {"SCREEN_CONTEXT_HOME": str(settings.root), "SCREEN_CONTEXT_PLAINTEXT": "1", "PATH": "/usr/bin:/bin"}
    run = lambda *a: subprocess.run([sys.executable, "-m", "screen_context.cli", "sessions", *a], env=env, capture_output=True, text=True)
    out = run("--idle", "20")
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == {"idle_minutes": 20, "feedback": [], "latest": None}
    assert run("--idle", "0").returncode != 0
