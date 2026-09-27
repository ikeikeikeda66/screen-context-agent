"""Work sessions and the Resume card (#29, roadmap decisions 3 and 17).

A work session is a run of screens across apps. It ends at a screen lock, a pause, or idle time
of at least the configured threshold (15 minutes by default). The capture process records
presence transitions (`record`); frames give the rest: an active user produces a frame at least
every 5 minutes, so a gap between frames at least as long as the threshold also ends a session.

Feedback on the card ("helpful" / "off") stays in the local encrypted database to tune the
threshold. It is never served over MCP.
"""
import time
from . import audit, store
from .activity import blocks
from .material import excerpt
from .privacy import domains
from .service import Service

IDLE_MARK = 60      # seconds without input before the capture process records "idle"
BREAKS = ("locked", "paused")
LOOKBACK = 3 * 86400
VERDICTS = ("helpful", "off")


def record(settings, state, ts):
    with store.connect(settings) as con:
        con.execute("INSERT INTO presence (ts, state) VALUES (?, ?)", (ts, state))


def presence(settings, since, until):
    """Presence events in [since, until], preceded by the last one before `since` (the state at `since`)."""
    with store.connect(settings, readonly=True) as con:
        before = con.execute("SELECT ts, state FROM presence WHERE ts < ? ORDER BY ts DESC, id DESC LIMIT 1", (since,)).fetchall()
        rows = con.execute("SELECT ts, state FROM presence WHERE ts >= ? AND ts <= ? ORDER BY ts, id", (since, until)).fetchall()
    return [(r["ts"], r["state"]) for r in [*before, *rows]]


def breaks(events, threshold, until):
    """Spans that end a session: every lock or pause, and idle spans of at least `threshold` seconds."""
    spans = []
    for i, (ts, state) in enumerate(events):
        end = events[i + 1][0] if i + 1 < len(events) else until
        if state in BREAKS or (state == "idle" and end - ts >= threshold): spans.append((ts, end))
    return spans


def split(frames, events, threshold, until):
    """Group time-ordered frames into sessions. A session ends where a break begins: frames that
    keep arriving during a long idle stretch (a video, notifications) join the next session
    instead of each becoming one."""
    starts = [start for start, _ in breaks(events, threshold, until)]
    sessions, current = [], []
    for frame in frames:
        if current:
            a, b = current[-1]["ts"], frame["ts"]
            if b - a >= threshold or any(a < start <= b for start in starts):
                sessions.append(current)
                current = []
        current.append(frame)
    if current: sessions.append(current)
    return sessions


def resume(settings, client="ui", now=None):
    """The latest work session in the last 3 days, for the Resume card; None when there is none.
    Read on the user path with the full profile (the policy applies) and audited."""
    now = now or time.time()
    minutes = settings.session_idle_minutes()
    frames = Service(settings, "full", client, audit_path=None).rows(now - LOOKBACK, now)
    groups = split(frames, presence(settings, now - LOOKBACK, now), minutes * 60, now)
    if not groups: return None
    last = groups[-1]
    acts = blocks(last)
    main = sorted(acts, key=lambda b: (b["end_ts"] - b["start_ts"], b["frames"]), reverse=True)[:3]
    documents, seen = [], set()
    for b in reversed(acts):
        if b["title"] and b["title"] not in seen:
            seen.add(b["title"])
            documents.append({"title": b["title"], "app": b["app"], "domains": b["domains"][:3]})
    audit.record(settings, "user", client, "resume", params={"idle_minutes": minutes},
                 frame_ids=[f["id"] for f in last], count=len(last))
    return {"start_ts": last[0]["ts"], "end_ts": last[-1]["ts"], "frames": len(last), "idle_minutes": minutes,
            "blocks": [{"app": b["app"], "title": b["title"], "start_ts": b["start_ts"], "end_ts": b["end_ts"]}
                       for b in sorted(main, key=lambda b: b["start_ts"])],
            "documents": documents[:6], "last_app": last[-1]["app_name"],
            "excerpt": excerpt(last[-1]["ocr_text"], 300), "domains": domains(last[-1]["ocr_text"])[:3]}


def give_feedback(settings, verdict, session_start, session_end):
    if verdict not in VERDICTS: raise ValueError("verdict must be helpful or off")
    for value in (session_start, session_end):
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 32503680000:
            raise ValueError("invalid session time")
    minutes = settings.session_idle_minutes()
    with store.connect(settings) as con:
        con.execute("INSERT INTO feedback (ts, verdict, session_start, session_end, idle_minutes) VALUES (?,?,?,?,?)",
                    (time.time(), verdict, session_start, session_end, minutes))
    return {"verdict": verdict, "idle_minutes": minutes}


def feedback_summary(settings):
    """Verdict counts per threshold, so the user can see whether a change helped."""
    with store.connect(settings, readonly=True) as con:
        rows = con.execute("SELECT idle_minutes, verdict, count(*) AS n FROM feedback GROUP BY idle_minutes, verdict ORDER BY idle_minutes").fetchall()
    summary = {}
    for r in rows: summary.setdefault(r["idle_minutes"], {v: 0 for v in VERDICTS})[r["verdict"]] = r["n"]
    return [{"idle_minutes": m, **counts} for m, counts in summary.items()]


class Presence:
    """Used by the capture loop: record active / idle / locked / paused, on transitions only."""
    def __init__(self, settings, adapter, clock=time.time):
        self.settings, self.adapter, self.clock, self.last = settings, adapter, clock, None

    def observe(self, paused):
        now = self.clock()
        if paused: return "paused", now
        check = getattr(self.adapter, "session_locked", None)
        try:
            if check is not None: locked = check()
            else:
                from .health import screen_locked
                locked = screen_locked()
        except Exception: locked = False
        if locked: return "locked", now
        try: idle = float(self.adapter.idle_seconds())
        except Exception: idle = 0.0
        return ("idle", now - idle) if idle >= IDLE_MARK else ("active", now)

    def tick(self, paused=False):
        state, ts = self.observe(paused)
        if state == self.last: return None
        try: record(self.settings, state, ts)
        except Exception: return None  # presence is best effort; it never stops capture (e.g. before `init`)
        self.last = state
        return state
