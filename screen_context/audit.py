"""Audit log in the encrypted database. Readable only on the user path (CLI, UI), never over MCP.

Agent rows record what each client asked for (query text included) and which frames it
received, so the user can see what already left the machine before purging it.
User rows record the user's own operations (export, purge, backup, ...).
"""
import json
import time
from . import store

PATHS = ("agent", "user")


def record(settings, path, client, action, *, profile=None, query=None, params=None, frame_ids=(), count=0):
    if path not in PATHS: raise ValueError("Unknown audit path")
    with store.connect(settings) as con:
        con.execute("INSERT INTO audit (ts, path, client, profile, action, query, params, frame_ids, result_count) VALUES (?,?,?,?,?,?,?,?,?)",
                    (time.time(), path, client, profile, action, query, json.dumps(params or {}, ensure_ascii=False, sort_keys=True),
                     json.dumps(list(dict.fromkeys(frame_ids))), count))


def rows(settings, client=None, since=None, limit=100):
    sql, args = "SELECT * FROM audit WHERE ts >= ?", [since or 0]
    if client is not None:
        sql += " AND client = ?"
        args.append(client)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(limit)
    with store.connect(settings, readonly=True) as con:
        return [{**dict(r), "params": json.loads(r["params"]), "frame_ids": json.loads(r["frame_ids"])} for r in con.execute(sql, args)]


def import_jsonl(con, path):
    """Copy a pre-v3 audit.jsonl into the audit table. Those rows only kept a digest of the arguments."""
    imported = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
            values = (float(entry["ts"]), str(entry["client"]), entry.get("profile"), str(entry["tool"]), entry.get("query_sha256"), int(entry.get("count", 0)))
        except (ValueError, KeyError, TypeError):
            continue  # a line cut short by a crash; the rest of the log is still worth keeping
        con.execute("INSERT INTO audit (ts, path, client, profile, action, legacy_sha256, result_count) VALUES (?, 'agent', ?, ?, ?, ?, ?)",
                    values)
        imported += 1
    return imported
