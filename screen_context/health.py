"""Operational state for consumers. Distinguishes paused, stopped, locked, delayed and idle;
the last saved capture result alone cannot tell these apart."""
import json
import os
import sys
import time
from . import store


def lock_held(path):
    """True when another process holds the flock (capture/indexer are running)."""
    if not path.exists(): return False
    if os.name == "nt": return True  # msvcrt probing would block; treat presence as unknown-running
    import fcntl
    with open(path, "a+b") as f:
        try: fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError: return True
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        return False


def read_json(path):
    try: return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError): return {}


def session_state():
    """(locked, idle_seconds); None when the platform cannot tell."""
    if sys.platform != "darwin": return None, None
    try:
        import Quartz
        info = Quartz.CGSessionCopyCurrentDictionary() or {}
        locked = bool(dict(info).get("CGSSessionScreenIsLocked", False))
        idle = float(Quartz.CGEventSourceSecondsSinceLastEventType(Quartz.kCGEventSourceStateCombinedSessionState, Quartz.kCGAnyInputEventType))
        return locked, idle
    except Exception: return None, None


def health(settings, now=None):
    now = now or time.time()
    root = settings.root
    capture = read_json(root / "capture-status.json")
    index = read_json(root / "index-status.json")
    queued = list((root / "spool").glob("*.frame"))
    oldest = min((p.stat().st_mtime for p in queued), default=None)
    locked, idle = session_state()
    last_seq, last_indexed_at, last_frame_ts, version = 0, None, None, None
    if settings.db.exists():
        # migrating=True skips the schema guard: health must describe an outdated database
        # (right after an upgrade, before init) instead of failing on it.
        with store.connect(settings, readonly=True, migrating=True) as con:
            version = con.execute("PRAGMA user_version").fetchone()[0]
            if version == store.SCHEMA_VERSION:
                row = con.execute("SELECT seq, indexed_at FROM indexed_events ORDER BY seq DESC LIMIT 1").fetchone()
                if row: last_seq, last_indexed_at = row[0], row[1]
                row = con.execute("SELECT max(ts) FROM frames").fetchone()
                last_frame_ts = row[0] if row else None
    result = {
        "ts": now,
        "paused": (root / "paused").exists(),
        "capture": {"running": lock_held(root / "capture.lock"), "last_status": capture.get("status"), "last_ts": capture.get("ts"),
                    "age_seconds": None if capture.get("ts") is None else round(now - capture["ts"]), "error_type": capture.get("error_type")},
        "indexer": {"running": lock_held(root / "indexer.lock"), "last_ts": index.get("ts"), "age_seconds": None if index.get("ts") is None else round(now - index["ts"]),
                    "failed": index.get("failed", 0), "last_error_type": index.get("last_error_type")},
        "queue": {"count": len(queued), "oldest_age_seconds": None if oldest is None else round(now - oldest)},
        "session": {"locked": locked, "idle_seconds": None if idle is None else round(idle)},
        "index": {"last_seq": last_seq, "last_indexed_at": last_indexed_at, "last_frame_ts": last_frame_ts},
        "schema_version": store.SCHEMA_VERSION,
        "database_schema": version,
    }
    result["permission"] = "denied" if result["capture"]["error_type"] == "PermissionError" else "unknown"
    result["state"] = derive_state(result)
    return result


def derive_state(h):
    # An outdated database (upgrade without `init`) blocks every reader and writer, so it comes first.
    if h.get("database_schema") not in (None, 0, h.get("schema_version")): return "needs_init"
    if h["paused"]: return "paused"
    if not h["capture"]["running"]: return "capture_stopped"
    if h["permission"] == "denied": return "permission_error"
    if h["session"]["locked"]: return "locked"
    if not h["indexer"]["running"]: return "indexer_stopped"
    if (h["queue"]["oldest_age_seconds"] or 0) > 300: return "indexing_delayed"
    if (h["session"]["idle_seconds"] or 0) > 300: return "idle"
    return "active"


# States in which observations must not be treated as the user's current work.
NOT_CURRENT = {"needs_init", "paused", "capture_stopped", "permission_error", "locked", "indexer_stopped"}
