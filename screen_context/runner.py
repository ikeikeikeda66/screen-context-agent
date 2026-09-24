"""Periodic proposal consumer: delta fetch with cursor and lease, no-notify gating,
evidence-checked proposal registration and an outbox whose delivery result is unknown by design
(the external scheduler delivers the agent's output; nothing here re-sends)."""
import hashlib
import json
import re
import time
import uuid
from . import store
from .activity import blocks
from .health import NOT_CURRENT, health
from .i18n import resolve, t
from .privacy import denied

CONSUMER = "proposal"
TEXT_BUDGET = 8000
BLOCK_CHARS = 600
SUPPRESS_SECONDS = 24 * 3600
SILENT = "[SILENT]"
EVIDENCE_MIN_CHARS = 6  # after normalize(): letters and digits only


def policy_revision(policy):
    return hashlib.sha256(json.dumps(policy, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def is_ai_output(record, policy):
    """Frames showing an assistant's output (policy ai_output_*) are not new facts about the user."""
    if (record.get("app_bundle") or "").casefold() in {x.casefold() for x in policy["ai_output_apps"]}: return True
    title = record.get("window_title") or record.get("title") or ""
    return any(re.search(p, title) for p in policy["ai_output_title_patterns"])


def normalize(text):
    return re.sub(r"[\s\d\W_]+", "", (text or "").casefold())


def _run(con, run_id):
    row = con.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
    if row is None: raise ValueError("Unknown run")
    return dict(row)


def prepare(settings, consumer=CONSUMER, window_minutes=60, fresh_minutes=15, lease_seconds=180, now=None, run_id=None):
    """Returns (outcome, material). material is None unless outcome == "ready"."""
    now = now or time.time()
    run_id = run_id or uuid.uuid4().hex
    h = health(settings, now)
    policy = settings.policy()
    revision = policy_revision(policy)
    with store.connect(settings) as con:
        row = con.execute("SELECT * FROM consumers WHERE consumer_id=?", (consumer,)).fetchone()
        if row is None:
            con.execute("INSERT INTO consumers (consumer_id, cursor_seq, lease_until, lease_run, updated_at) VALUES (?,0,0,NULL,?)", (consumer, now))
            cursor = 0
        elif row["lease_until"] > now and row["lease_run"]:
            return "busy", None
        else: cursor = row["cursor_seq"]
        # A run handed to the agent but never finished is retried from its starting cursor.
        for r in con.execute("SELECT run_id, cursor_before FROM runs WHERE consumer_id=? AND state='handed_off'", (consumer,)).fetchall():
            con.execute("UPDATE runs SET state='abandoned', finished_at=? WHERE run_id=?", (now, r["run_id"]))
            cursor = min(cursor, r["cursor_before"])
        snapshot = con.execute("SELECT coalesce(max(seq),0) FROM indexed_events").fetchone()[0]
        sql = "SELECT f.*, e.seq FROM indexed_events e JOIN frames f ON f.id=e.frame_id WHERE e.seq>? AND e.seq<=?"
        args = [cursor, snapshot]
        if cursor == 0:
            sql += " AND e.indexed_at>=?"; args.append(now - window_minutes * 60)
        rows = [dict(r) for r in con.execute(sql + " ORDER BY f.ts, f.id", args) if not denied(policy, dict(r), "full")]

        def record(state, advance, detail=None):
            con.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?)", (run_id, consumer, now, None if state == "handed_off" else now, cursor, snapshot if advance else cursor, snapshot, revision, state, json.dumps(detail or {}, ensure_ascii=False)))
            con.execute("UPDATE consumers SET cursor_seq=?, lease_until=?, lease_run=?, updated_at=? WHERE consumer_id=?",
                        (snapshot if advance else cursor, now + lease_seconds if state == "handed_off" else 0, run_id if state == "handed_off" else None, now, consumer))

        if snapshot <= cursor or not rows:
            record("no_new", True); return "no_new", None
        if h["state"] in NOT_CURRENT:
            # Keep the cursor: the observations may still be current once the session resumes.
            record(h["state"], False); return h["state"], None
        latest = max(r["ts"] for r in rows)
        if now - latest > fresh_minutes * 60:
            record("stale", True, {"latest_ts": latest}); return "stale", None
        # Late OCR can surface days-old screens; they are consumed but never shown as current work.
        activity = [b for b in blocks(rows) if now - b["end_ts"] <= window_minutes * 60]
        for b in activity: b["ai_output"] = is_ai_output(b, policy)
        if not activity:
            record("stale", True, {"latest_ts": latest}); return "stale", None
        if all(b["ai_output"] for b in activity):
            record("ai_only", True); return "ai_only", None
        budget, out = TEXT_BUDGET, []
        for b in activity:
            text = b["text"][:min(BLOCK_CHARS, max(budget, 0))]
            budget -= len(text)
            out.append({"frame_id": b["block_id"], "frame_ids": b["frame_ids"], "start_ts": b["start_ts"], "end_ts": b["end_ts"], "app": b["app"], "app_bundle": b["app_bundle"],
                        "title": b["title"][:120], "domains": b["domains"][:10], "text": text, "truncated": len(text) < len(b["text"]), "ai_output": b["ai_output"]})
        recent = [{"created_at": r["created_at"], "body": r["body"]} for r in con.execute("SELECT o.created_at, o.body FROM notification_outbox o JOIN runs r ON r.run_id=o.run_id WHERE r.consumer_id=? AND o.created_at>? ORDER BY o.created_at DESC LIMIT 20", (consumer, now - SUPPRESS_SECONDS))]
        material = {"run_id": run_id, "consumer": consumer, "generated_at": now, "health_state": h["state"], "cursor_before": cursor, "cursor_after": snapshot, "policy_revision": revision,
                    "latest_observation_ts": latest, "blocks": out, "recent_proposals": recent}
        record("handed_off", True, {"frames": len(rows), "blocks": len(out), "frame_ids": [r["id"] for r in rows]})
    return "ready", material


def submit(settings, run_id, proposal, next_step, evidence, frame_ids, delivery="external", now=None):
    """Register one proposal. Rejects evidence that is not in the run's frames or is excluded now."""
    now = now or time.time()
    for name, value in (("proposal", proposal), ("next_step", next_step), ("evidence", evidence)):
        if not isinstance(value, str) or not value.strip() or len(value) > 1000: raise ValueError(f"{name} must contain 1–1000 characters")
    if not isinstance(frame_ids, list) or not frame_ids or len(frame_ids) > 50 or any(not isinstance(x, str) for x in frame_ids): raise ValueError("frame_ids must list 1–50 ids")
    policy = settings.policy()
    with store.connect(settings) as con:
        run = _run(con, run_id)
        if run["state"] != "handed_off": raise ValueError("Run is not open for proposals")
        allowed = set(json.loads(run["detail"]).get("frame_ids", []))
        if not set(frame_ids) <= allowed: raise ValueError("frame_ids must come from this run")
        rows = [dict(r) for r in con.execute(f"SELECT * FROM frames WHERE id IN ({','.join('?'*len(frame_ids))})", frame_ids)]
        if len(rows) != len(set(frame_ids)) or any(denied(policy, r, "full") for r in rows): raise ValueError("Evidence unavailable")
        # The quote must come from a frame that is not another AI's output (assistant apps, the agent's own channel),
        # so a proposal cannot rest only on what an assistant said.
        quote = normalize(evidence)
        if len(quote) < EVIDENCE_MIN_CHARS: raise ValueError(f"evidence must quote at least {EVIDENCE_MIN_CHARS} characters of screen text")
        sources = [r for r in rows if not is_ai_output(r, policy) and quote in normalize(r["ocr_text"] + "\n" + r["window_title"])]
        if not sources:
            if any(quote in normalize(r["ocr_text"] + "\n" + r["window_title"]) for r in rows): raise ValueError("Evidence must come from a non-AI screen")
            raise ValueError("Evidence quote not found in referenced frames")
        key = hashlib.sha256((run["consumer_id"] + "|" + normalize(proposal) + "|" + normalize(next_step)).encode()).hexdigest()
        dup = con.execute("SELECT o.created_at FROM notification_outbox o JOIN runs r ON r.run_id=o.run_id WHERE o.dedup_key=? AND r.consumer_id=?", (key, run["consumer_id"])).fetchone()
        if dup and dup["created_at"] > now - SUPPRESS_SECONDS:
            con.execute("UPDATE runs SET detail=json_set(detail,'$.suppressed',1) WHERE run_id=?", (run_id,))
            return {"decision": "suppressed_duplicate", "message": None}
        source = min(sources, key=lambda r: r["ts"])
        when = time.strftime("%H:%M", time.localtime(source["ts"]))
        message = t("proposal.message", resolve(settings), proposal=proposal.strip(), when=when, app=source["app_name"], evidence=evidence.strip(), next_step=next_step.strip())
        state = "mock_sent" if delivery == "mock" else "handed_off"
        con.execute("INSERT OR REPLACE INTO notification_outbox VALUES (?,?,?,?,?,?,?,?,NULL)", (uuid.uuid4().hex, run_id, key, now, message, json.dumps(frame_ids), delivery, state))
    return {"decision": "deliver", "message": message}


def finish(settings, run_id, response, now=None):
    """Close a run with the agent's final text. Delivery belongs to the scheduler; the result stays unknown here."""
    now = now or time.time()
    text = (response or "").strip()
    with store.connect(settings) as con:
        run = _run(con, run_id)
        if run["state"] != "handed_off": return {"run_id": run_id, "state": run["state"], "changed": False}
        sent = con.execute("SELECT count(*) FROM notification_outbox WHERE run_id=?", (run_id,)).fetchone()[0]
        if not text or text.startswith(SILENT): state = "no_proposal"
        elif sent: state = "delivered_unknown"
        else: state = "unregistered_output"
        con.execute("UPDATE runs SET state=?, finished_at=?, detail=json_set(detail,'$.response_chars',?) WHERE run_id=?", (state, now, len(text), run_id))
        con.execute("UPDATE consumers SET lease_until=0, lease_run=NULL, updated_at=? WHERE consumer_id=? AND lease_run=?", (now, run["consumer_id"], run_id))
    return {"run_id": run_id, "state": state, "changed": True}


def material_markdown(m, lang="en"):
    f = lambda ts: time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
    lines = [t("proposal.title", lang, run_id=m["run_id"]),
             t("proposal.meta", lang, generated=f(m["generated_at"]), state=m["health_state"], latest=f(m["latest_observation_ts"])),
             t("proposal.rules", lang), ""]
    for b in m["blocks"]:
        if not b["text"].strip() and not b["title"].strip(): continue  # e.g. empty 2×2 captures
        tag = t("proposal.ai_tag", lang) if b["ai_output"] else ""
        lines.append(f"## {f(b['start_ts'])[11:]}–{f(b['end_ts'])[11:]} {b['app']} {tag}| {b['title']} | frame_id={b['frame_id']} frames={len(b['frame_ids'])}")
        if b["domains"]: lines.append("domains: " + ", ".join(b["domains"]))
        lines.append(b["text"] + (t("proposal.truncated", lang) if b["truncated"] else ""))
        lines.append("")
    if m["recent_proposals"]:
        lines.append(t("proposal.recent", lang))
        lines += [f"- {f(p['created_at'])} {p['body'].splitlines()[0]}" for p in m["recent_proposals"]]
    return "\n".join(lines)
