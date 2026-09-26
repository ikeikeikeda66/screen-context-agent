"""Every response is filtered with the current policy, before pagination."""
from datetime import datetime, timedelta
import base64
import contextvars
import hmac
import json
import math
import time
from . import audit, store
from .activity import blocks
from .privacy import denied, envelope
from .crypto import get_key, unseal


def bounded(value, low, high, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}")
    if name != "ts" and not isinstance(value, int): raise ValueError(f"{name} must be an integer")
    return value


# "standard" serves coding assistants: 4 read-only tools, IDE and terminal frames excluded.
# "full" serves personal agents: timelines, diary material, health, deltas, proposals and images.
PROFILES = ("standard", "full")
# Names used by earlier releases; accepted so existing client configurations keep working.
PROFILE_ALIASES = {"claude_code": "standard", "openclaw": "full"}


# Client identity for the current tool call, set from a verified token (see access.py and mcp_server.py).
CURRENT_CLIENT = contextvars.ContextVar("screen_context_client", default=None)


def profile_name(value):
    value = PROFILE_ALIASES.get(value, value)
    if value not in PROFILES: raise ValueError("Unknown profile")
    return value


def day_range(day):
    start = datetime.strptime(day, "%Y-%m-%d")
    return start.timestamp(), (start + timedelta(days=1)).timestamp()


class Service:
    def __init__(self, settings, profile="standard", client=None):
        profile = profile_name(profile)
        self.settings, self.profile, self.client = settings, profile, client or profile

    def rows(self, since=0, until=None, query=None):
        policy = self.settings.policy()
        sql, args = "SELECT id,ts,app_bundle,app_name,window_title,display_id,ocr_text,domains FROM frames WHERE ts >= ?", [since]
        if until is not None:
            sql += " AND ts < ?"
            args.append(until)
        if query is not None:
            # Quoted literal MATCH cannot inject FTS operators. Short Japanese terms use instr.
            if len(query) >= 3:
                sql += " AND rowid IN (SELECT rowid FROM frames_fts WHERE frames_fts MATCH ?)"
                args.append('"' + query.replace('"', '""') + '"')
            else:
                sql += " AND instr(lower(ocr_text),lower(?)) > 0"
                args.append(query)
        sql += " ORDER BY ts,id"
        with store.connect(self.settings, readonly=True) as con:
            return [dict(r) for r in con.execute(sql, args) if not denied(policy, dict(r), self.profile)]

    def finish(self, records, tool, arguments):
        # The query is stored in the encrypted database so the user can see what each client asked
        # for and received. Auditing fails closed: no audit row, no result.
        arguments = dict(arguments)
        query = arguments.pop("query", None)
        returned = [i for r in records for i in ([r["frame_id"]] if "frame_id" in r else r.get("frame_ids", []))]
        audit.record(self.settings, "agent", CURRENT_CLIENT.get() or self.client, tool, profile=self.profile, query=query,
                     params=arguments, frame_ids=returned, count=len(records))
        budget, out = 10000, []
        for rec in records:
            rec = dict(rec)
            rec.pop("frame_ids", None)
            if "domains" in rec: rec["domains"] = rec["domains"][:20]
            if "title" in rec: rec["title"] = rec["title"][:300]
            if "text" in rec:
                text = rec["text"]
                rec["text"] = text[:min(1500, budget)]
                rec["truncated"] = len(text) > len(rec["text"])
                budget -= len(rec["text"])
            out.append(rec)
        return envelope(out, tool=tool, profile=self.profile)

    def search_screen_history(self, query: str, limit: int = 10, since_minutes: int | None = None):
        if not isinstance(query, str) or not query.strip() or len(query) > 500: raise ValueError("query must contain 1–500 characters")
        bounded(limit, 1, 50, "limit")
        since = 0 if since_minutes is None else time.time() - bounded(since_minutes, 1, 5256000, "since_minutes") * 60
        rows = self.rows(since, query=query.strip())
        recs = [{"frame_id": r["id"], "ts": r["ts"], "app": r["app_name"], "app_bundle": r["app_bundle"], "title": r["window_title"], "text": r["ocr_text"], "domains": json.loads(r["domains"])} for r in reversed(rows[-limit:])]
        return self.finish(recs, "search_screen_history", locals_args(query=query, limit=limit, since_minutes=since_minutes))

    def get_recent_activity(self, minutes: int = 60, limit: int = 20):
        bounded(minutes, 1, 129600, "minutes"); bounded(limit, 1, 50, "limit")
        recs = blocks(self.rows(time.time() - minutes * 60))
        return self.finish(list(reversed(recs[-limit:])), "get_recent_activity", {"minutes": minutes, "limit": limit})

    def get_context_around(self, ts: float, n: int = 3):
        bounded(ts, 0, 32503680000, "ts"); bounded(n, 1, 20, "n")
        recs = blocks(self.rows(max(0, ts - 90*86400), ts + 90*86400))
        before = [r for r in recs if r["start_ts"] <= ts][-n:]
        after = [r for r in recs if r["start_ts"] > ts][:n]
        return self.finish(before + after, "get_context_around", {"ts": ts, "n": n})

    def require_full(self):
        if self.profile != "full": raise PermissionError("Tool unavailable for this profile")

    def get_activity_timeline(self, hours: int = 8):
        self.require_full(); bounded(hours, 1, 2160, "hours")
        recs = [{k: v for k, v in b.items() if k not in ("text", "title", "domains", "frame_ids")} for b in blocks(self.rows(time.time()-hours*3600))]
        return self.finish(recs[:500], "get_activity_timeline", {"hours": hours})

    def get_daily_rollup(self, date: str | None = None):
        self.require_full()
        day = date or datetime.now().strftime("%Y-%m-%d")
        start, end = day_range(day)
        # Source text is retained, allowing new exclusions to be applied even to old rollups.
        recs = []
        for b in blocks(self.rows(start, end)):
            recs.append({"app": b["app"], "start_ts": b["start_ts"], "end_ts": b["end_ts"], "observed_minutes": round((b["end_ts"]-b["start_ts"])/60, 1), "domains": b["domains"], "text": b["text"][:250]})
        return self.finish(recs[:30], "get_daily_rollup", {"date": day})

    def get_diary_material(self, date: str | None = None, offset: int = 0, limit: int = 10):
        """Paginated evidence for a diary draft, not inferred accomplishments."""
        self.require_full()
        bounded(offset, 0, 1000000, "offset")
        bounded(limit, 1, 10, "limit")
        day = date or datetime.now().strftime("%Y-%m-%d")
        start, end = day_range(day)
        activities = blocks(self.rows(start, end))
        selected = activities[offset:offset+limit]
        records = [{"frame_id": b["block_id"], "start_ts": b["start_ts"],
                    "end_ts": b["end_ts"], "app": b["app"],
                    "app_bundle": b["app_bundle"], "title": b["title"],
                    "frames": b["frames"], "text": b["text"][:1000],
                    "excerpt_truncated": len(b["text"]) > 1000,
                    "domains": b["domains"]} for b in selected]
        result = self.finish(records, "get_diary_material", {"date": day, "offset": offset, "limit": limit})
        result.update(date=day, timezone=str(datetime.fromtimestamp(start).astimezone().tzinfo),
                      total_blocks=len(activities), offset=offset,
                      next_offset=offset+len(selected) if offset+len(selected) < len(activities) else None,
                      interpretation="Displayed content is evidence of viewing only, not completion, intent, emotion, or time worked. Missing records do not mean no activity.")
        return result

    def get_day_material(self, date: str, timezone: str, cursor: str | None = None,
                         purpose: str = "report", limit: int = 10):
        """Bounded, fixed-snapshot evidence for a user-requested day report/diary draft."""
        from datetime import date as calendar_date, datetime, time as day_time
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        from . import store
        from .runner import policy_revision

        if not isinstance(date, str) or len(date) != 10:
            raise ValueError("date must use YYYY-MM-DD")
        try:
            day = calendar_date.fromisoformat(date)
            if day.isoformat() != date: raise ValueError
            zone = ZoneInfo(timezone)
        except (ValueError, ZoneInfoNotFoundError, TypeError):
            raise ValueError("date or timezone is invalid") from None
        if purpose not in ("report", "diary"):
            raise ValueError("purpose must be report or diary")
        bounded(limit, 1, 10, "limit")

        start = datetime.combine(day, day_time.min, zone).timestamp()
        end = datetime.combine(calendar_date.fromordinal(day.toordinal()+1), day_time.min, zone).timestamp()
        policy = self.settings.policy()
        revision = policy_revision(policy)
        if cursor is None:
            with store.connect(self.settings, readonly=True) as con:
                snapshot = con.execute("SELECT coalesce(max(seq),0) FROM indexed_events").fetchone()[0]
            seq = 0
        else:
            state = self.decode_cursor(cursor)
            if (state.get("kind") != "day_material" or state.get("date") != date or
                    state.get("timezone") != timezone or state.get("purpose") != purpose or
                    state.get("policy") != revision or type(state.get("snapshot")) is not int or
                    type(state.get("seq")) is not int or state["seq"] > state["snapshot"]):
                raise ValueError("CURSOR_EXPIRED: cursor does not match this request or current policy")
            snapshot, seq = state["snapshot"], state["seq"]

        records, last = [], seq
        has_more = False
        with store.connect(self.settings, readonly=True) as con:
            rows = con.execute(
                "SELECT f.*, e.seq, e.indexed_at FROM indexed_events e "
                "JOIN frames f ON f.id=e.frame_id "
                "WHERE e.seq>? AND e.seq<=? AND f.ts>=? AND f.ts<? ORDER BY e.seq",
                (seq, snapshot, start, end),
            )
            for row in rows:
                item = dict(row)
                last = item["seq"]
                if denied(policy, item, self.profile):
                    continue
                if len(records) == limit:
                    has_more = True
                    last = records[-1]["seq"]
                    break
                text = item["ocr_text"] or ""
                records.append({"seq": item["seq"], "frame_id": item["id"], "observed_at": item["ts"],
                                "indexed_at": item["indexed_at"], "app": item["app_name"],
                                "app_bundle": item["app_bundle"], "title": item["window_title"],
                                "text": text[:1000], "truncated": len(text) > 1000,
                                "domains": json.loads(item["domains"])[:10]})

        next_cursor = self.encode_cursor({"kind": "day_material", "profile": self.profile,
            "date": date, "timezone": timezone, "purpose": purpose, "seq": last,
            "snapshot": snapshot, "policy": revision}) if has_more else None
        newest_indexed_at = None
        with store.connect(self.settings, readonly=True) as con:
            row = con.execute("SELECT max(indexed_at) FROM indexed_events WHERE seq<=?", (snapshot,)).fetchone()
            if row: newest_indexed_at = row[0]
        result = self.finish(records, "get_day_material", {"date": date, "timezone": timezone,
            "purpose": purpose, "cursor": bool(cursor), "limit": limit})
        result.update(schema_version=1, status="ok", date=date, timezone=timezone, purpose=purpose,
            snapshot_seq=snapshot, next_cursor=next_cursor, has_more=has_more,
            freshness={"last_indexed_at": newest_indexed_at},
            coverage={"scope": "indexed_day", "full_document": False, "full_day": False,
                      "has_gaps": True, "records_in_page": len(result["records"])})
        return result

    def get_capture_health(self):
        """Operational state so a consumer can tell paused, stopped, locked, delayed and idle apart."""
        self.require_full()
        from .health import health
        data = health(self.settings)
        self.finish([], "get_capture_health", {})
        return {"schema_version": 1, "status": "ok", **data}

    def cursor_key(self):
        from .crypto import get_key
        return b"cursor" + (b"\0" * 32 if self.settings.plaintext else get_key(self.settings))

    def encode_cursor(self, payload):
        raw = json.dumps(payload, sort_keys=True).encode()
        return base64.urlsafe_b64encode(raw + hmac.new(self.cursor_key(), raw, "sha256").digest()).decode()

    def decode_cursor(self, cursor):
        try:
            data = base64.urlsafe_b64decode(cursor.encode())
            raw, tag = data[:-32], data[-32:]
            if not hmac.compare_digest(tag, hmac.new(self.cursor_key(), raw, "sha256").digest()): raise ValueError
            payload = json.loads(raw)
            if payload.get("profile") != self.profile: raise ValueError
            return payload
        except Exception: raise ValueError("CURSOR_EXPIRED: cursor is invalid for this profile")

    def get_activity_delta(self, cursor: str | None = None, limit: int = 20, since_minutes: int = 60):
        """Frames in OCR-completion order after the cursor; late OCR is never skipped."""
        self.require_full()
        from .runner import policy_revision
        bounded(limit, 1, 50, "limit"); bounded(since_minutes, 1, 1440, "since_minutes")
        policy = self.settings.policy(); revision = policy_revision(policy)
        with store.connect(self.settings, readonly=True) as con:
            if cursor is None:
                snapshot = con.execute("SELECT coalesce(max(seq),0) FROM indexed_events").fetchone()[0]
                seq = con.execute("SELECT coalesce(min(seq),?)-1 FROM indexed_events WHERE indexed_at>=?", (snapshot + 1, time.time() - since_minutes * 60)).fetchone()[0]
            else:
                state = self.decode_cursor(cursor)
                if state.get("policy") != revision: raise ValueError("POLICY_CHANGED: restart without a cursor")
                seq, snapshot = state["seq"], state["snapshot"]
            rows, last, has_more = [], seq, False
            for r in con.execute("SELECT f.*, e.seq, e.indexed_at FROM indexed_events e JOIN frames f ON f.id=e.frame_id WHERE e.seq>? AND e.seq<=? ORDER BY e.seq", (seq, snapshot)):
                r = dict(r)
                if denied(policy, r, self.profile): last = r["seq"]; continue
                if len(rows) == limit: has_more = True; break
                rows.append(r); last = r["seq"]
            newest = con.execute("SELECT coalesce(max(seq),0), max(indexed_at) FROM indexed_events").fetchone()
        recs = [{"seq": r["seq"], "frame_id": r["id"], "ts": r["ts"], "indexed_at": r["indexed_at"], "app": r["app_name"], "app_bundle": r["app_bundle"], "title": r["window_title"], "text": r["ocr_text"], "domains": json.loads(r["domains"])} for r in rows]
        result = self.finish(recs, "get_activity_delta", {"cursor": bool(cursor), "limit": limit, "since_minutes": since_minutes})
        result.update(schema_version=1, status="ok", has_more=has_more, snapshot_seq=snapshot, policy_revision=revision,
                      next_cursor=self.encode_cursor({"profile": self.profile, "seq": last, "snapshot": snapshot, "policy": revision}) if has_more else None,
                      freshness={"last_seq": newest[0], "last_indexed_at": newest[1], "behind": newest[0] - snapshot})
        return result

    def submit_proposal(self, run_id: str, proposal: str, next_step: str, evidence: str, frame_ids: list[str]):
        """Register a proposal for the open run. Duplicate conclusions within 24h are suppressed; evidence must be a quote from the referenced frames."""
        self.require_full()
        from .runner import submit
        if not isinstance(run_id, str) or len(run_id) > 64: raise ValueError("Invalid run_id")
        result = submit(self.settings, run_id, proposal, next_step, evidence, frame_ids)
        self.finish([{"frame_id": f} for f in frame_ids], "submit_proposal", {"run_id": run_id, "decision": result["decision"]})
        return {"schema_version": 1, "status": "ok", **result}

    def get_snapshot_image(self, frame_id: str):
        self.require_full()
        if not isinstance(frame_id, str) or len(frame_id) > 64: raise ValueError("Invalid frame ID")
        policy = self.settings.policy()
        with store.connect(self.settings, readonly=True) as con:
            row = con.execute("SELECT * FROM frames WHERE id=?", (frame_id,)).fetchone()
        if row is None or denied(policy, dict(row), self.profile) or not row["image_path"] or row["ts"] < time.time() - self.settings.retention_days*86400:
            self.finish([], "get_snapshot_image", {"frame_id": frame_id})
            raise ValueError("Snapshot unavailable")
        path = (self.settings.root / "images" / row["image_path"]).resolve()
        if path.parent != (self.settings.root / "images").resolve(): raise ValueError("Invalid image path")
        data = path.read_bytes()
        if not self.settings.plaintext: data = unseal(data, get_key(self.settings))
        self.finish([{"frame_id": frame_id}], "get_snapshot_image", {"frame_id": frame_id})
        return data


def locals_args(**kwargs): return kwargs
