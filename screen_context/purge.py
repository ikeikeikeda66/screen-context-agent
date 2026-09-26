"""Selective purge (roadmap decision 5, mechanism B): physical, cascading, no undo.

Selectors combine with AND: a time range (or the last N minutes), an app, a keyword, one
activity block, or everything the current policy excludes. Deleting a frame also removes
its full-text entry, preview image, OCR-completion event and unindexed spool file, rebuilds
the rollups of the affected days, redacts proposal evidence that quoted it, and strips it
(and the query text) from audit rows that returned it. `secure_delete` overwrites freed
pages, and the FTS index and write-ahead log are rewritten so the text does not linger.

Frames that already left the machine cannot be recalled; `plan` reports which clients
received them and which user exports included them, before anything is deleted.
"""
import hashlib
import json
import re
import time
from datetime import datetime
from . import audit, store
from .activity import blocks
from .crypto import get_key, unseal
from .privacy import denied

DURATION = re.compile(r"(\d+)\s*([mhd])")
PURGED = "[purged]"


def duration(text):
    """Seconds in "15m", "2h" or "1d"."""
    match = DURATION.fullmatch(text.strip())
    if not match: raise ValueError("Duration must look like 15m, 2h or 1d")
    return int(match.group(1)) * {"m": 60, "h": 3600, "d": 86400}[match.group(2)]


def select(settings, since=None, until=None, app=None, keyword=None, block=None, excluded=False):
    """IDs of stored frames matching every given selector. At least one selector is required."""
    if since is None and until is None and not (app or keyword or block or excluded):
        raise ValueError("Choose what to purge: a time range, --last, --app, --keyword, --block or --excluded")
    sql, args = "SELECT id, ts, app_bundle, app_name, window_title, display_id, ocr_text, domains FROM frames WHERE 1", []
    if since is not None: sql += " AND ts >= ?"; args.append(since)
    if until is not None: sql += " AND ts < ?"; args.append(until)
    if app: sql += " AND app_bundle = ?"; args.append(app)
    if keyword:
        if len(keyword) >= 3:
            sql += " AND rowid IN (SELECT rowid FROM frames_fts WHERE frames_fts MATCH ?)"
            args.append('"' + keyword.replace('"', '""') + '"')
        else:
            sql += " AND instr(lower(ocr_text), lower(?)) > 0"; args.append(keyword)
    with store.connect(settings, readonly=True) as con:
        rows = [dict(r) for r in con.execute(sql + " ORDER BY ts, id", args)]
        if block:
            anchor = con.execute("SELECT ts FROM frames WHERE id = ?", (block,)).fetchone()
            if anchor is None: raise ValueError("No frame with that block ID")
            day = datetime.fromtimestamp(anchor["ts"]).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
            same_day = [dict(r) for r in con.execute("SELECT id, ts, app_bundle, app_name, window_title, display_id, ocr_text, domains "
                                                     "FROM frames WHERE ts >= ? AND ts < ? ORDER BY ts, id", (day, day + 86400))]
            members = next((set(b["frame_ids"]) for b in blocks(same_day) if block in b["frame_ids"]), set())
            rows = [r for r in rows if r["id"] in members]
    if excluded:
        policy = settings.policy()
        rows = [r for r in rows if denied(policy, r)]
    return [r["id"] for r in rows]


def spooled(settings, since=None, until=None, app=None):
    """Unindexed spool files in a time range (and app): a purge of the last minutes must not miss
    frames that OCR has not reached yet."""
    key = None if settings.plaintext else get_key(settings)
    found = []
    for path in (settings.root / "spool").glob("*.frame"):
        try:
            raw = path.read_bytes()
            record = json.loads((unseal(raw, key) if key else raw).split(b"\n", 1)[0])
        except (OSError, ValueError):
            continue
        if (since is None or record["ts"] >= since) and (until is None or record["ts"] < until) and (not app or record.get("app_bundle") == app):
            found.append(path)
    return found


def recipients(con, ids):
    """Who already received these frames: [{path, client, frames, last_ts}] from the audit log."""
    wanted, seen = set(ids), {}
    for row in con.execute("SELECT path, client, ts, frame_ids FROM audit WHERE frame_ids != '[]'"):
        hits = wanted & set(json.loads(row["frame_ids"]))
        if hits:
            entry = seen.setdefault((row["path"], row["client"]), {"path": row["path"], "client": row["client"], "frames": set(), "last_ts": 0})
            entry["frames"] |= hits
            entry["last_ts"] = max(entry["last_ts"], row["ts"])
    return [{**e, "frames": len(e["frames"])} for e in seen.values()]


def plan(settings, ids, spool_files=()):
    """What a purge would delete and who already has copies. Changes nothing."""
    with store.connect(settings, readonly=True) as con:
        rows = [dict(r) for r in con.execute(f"SELECT id, ts, image_path FROM frames WHERE id IN ({','.join('?' * len(ids))})", ids)] if ids else []
        already = recipients(con, ids) if ids else []
    return {"frames": len(rows), "images": sum(1 for r in rows if r["image_path"]), "spool_files": len(spool_files),
            "days": sorted({datetime.fromtimestamp(r["ts"]).strftime("%Y-%m-%d") for r in rows}), "already_received_by": already}


def redact_outbox(con, ids):
    """Proposal evidence quotes frame text, so evidence citing these frames goes too."""
    wanted = set(ids)
    for row in con.execute("SELECT id, frame_ids FROM notification_outbox").fetchall():
        if wanted & set(json.loads(row["frame_ids"])):
            con.execute("UPDATE notification_outbox SET body = ?, frame_ids = '[]' WHERE id = ?", (PURGED, row["id"]))


def rebuild_rollups(settings, days):
    from .service import Service
    service = Service(settings, "full", "purge", audit_path=None)
    rollups = {day: service.get_daily_rollup(day) for day in days}
    with store.connect(settings) as con:
        con.execute("PRAGMA secure_delete=ON")
        for day, payload in rollups.items():
            if payload["count"]: con.execute("INSERT OR REPLACE INTO rollups VALUES (?, ?)", (day, json.dumps(payload, ensure_ascii=False)))
            else: con.execute("DELETE FROM rollups WHERE day = ?", (day,))


def finish(settings, images=(), spool_files=()):
    """Checkpoint the WAL so removed text is not left in it, then delete files."""
    with store.connect(settings) as con: con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    folder = (settings.root / "images").resolve()
    for name in images:
        path = (folder / name).resolve()
        if path.parent == folder: path.unlink(missing_ok=True)
    for path in spool_files: path.unlink(missing_ok=True)


def selector_digest(selector):
    # Hashed: a keyword purge must not leave the keyword behind in the log.
    return hashlib.sha256(json.dumps(selector, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def execute(settings, ids, selector, spool_files=(), actor="cli", action="purge"):
    """Delete the frames and everything derived from them. Returns the plan that was carried out."""
    summary = plan(settings, ids, spool_files)
    wanted = set(ids)
    with store.connect(settings) as con:
        con.execute("PRAGMA secure_delete=ON")
        images = [r["image_path"] for r in con.execute(f"SELECT image_path FROM frames WHERE id IN ({','.join('?' * len(ids))}) AND image_path IS NOT NULL", ids)] if ids else []
        for start in range(0, len(ids), 500):
            chunk = ids[start:start + 500]
            marks = ",".join("?" * len(chunk))
            con.execute(f"DELETE FROM frames WHERE id IN ({marks})", chunk)  # trigger removes the FTS entry
            con.execute(f"DELETE FROM indexed_events WHERE frame_id IN ({marks})", chunk)
        redact_outbox(con, ids)
        for row in con.execute("SELECT id, frame_ids FROM audit WHERE frame_ids != '[]'").fetchall():
            returned = json.loads(row["frame_ids"])
            if wanted & set(returned):
                # The query may be what was sensitive, so it goes with the frames; who and when stay.
                con.execute("UPDATE audit SET query = NULL, frame_ids = ? WHERE id = ?", (json.dumps([i for i in returned if i not in wanted]), row["id"]))
        if selector.get("keyword"):
            con.execute("UPDATE audit SET query = NULL WHERE instr(lower(query), lower(?)) > 0", (selector["keyword"],))
        con.execute("INSERT INTO frames_fts(frames_fts) VALUES('optimize')")
    rebuild_rollups(settings, summary["days"])
    finish(settings, images, spool_files)
    audit.record(settings, "user", actor, action, params={"selector_sha256": selector_digest(selector), "images": summary["images"],
                 "spool_files": summary["spool_files"], "days": summary["days"]}, count=summary["frames"])
    return summary
