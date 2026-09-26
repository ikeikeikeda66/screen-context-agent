"""Apply the sensitive-input rules to frames stored before the rules existed (roadmap decision 11).

`scan` finds what the indexer would do today: drop the frame (card number, My Number) or
redact lines (personal-data combinations). `apply` does exactly that to stored frames:
drops go through the purge cascade; redactions rewrite the text and its full-text entry,
delete the preview, and cascade to rollups and proposal evidence. Running it again finds
nothing, because redacted lines no longer carry the signals.
"""
import json
from datetime import datetime
from . import audit, purge, store
from .i18n import resolve, t
from .pii import redact
from .privacy import domains
from .sensitive import detect


def ocr_lines(row):
    # After 90 days ocr_json (with bounding boxes) is gone; the text lines are enough to redact.
    if row["ocr_json"]: return json.loads(row["ocr_json"])
    return [{"text": line, "bbox": None} for line in row["ocr_text"].split("\n")]


def scan(settings):
    """({frame_id: category} to drop, {frame_id: (new ocr lines, [rules])} to redact). Changes nothing."""
    policy, placeholder = settings.policy(), t("pii.redacted", resolve(settings))
    drops, redactions = {}, {}
    with store.connect(settings, readonly=True) as con:
        for row in con.execute("SELECT id, window_title, ocr_text, ocr_json FROM frames"):
            category = detect(row["ocr_text"] + "\n" + row["window_title"], policy["sensitive_detectors"])
            if category:
                drops[row["id"]] = category
                continue
            lines, rules = redact(ocr_lines(row), policy["pii_combinations"], placeholder)
            if rules: redactions[row["id"]] = (lines, rules)
    return drops, redactions


def counts(drops, redactions):
    result = {"drop": {}, "redact": {}}
    for category in drops.values(): result["drop"][category] = result["drop"].get(category, 0) + 1
    for _, rules in redactions.values():
        for rule in rules: result["redact"][rule] = result["redact"].get(rule, 0) + 1
    return result


def report(settings, drops, redactions):
    ids = [*drops, *redactions]
    with store.connect(settings, readonly=True) as con:
        received = purge.recipients(con, ids) if ids else []
    return {**counts(drops, redactions), "frames": {"drop": len(drops), "redact": len(redactions)}, "already_received_by": received}


def apply(settings, drops, redactions, actor="cli"):
    """Carry out a scan. Returns the same summary as `report`, computed before any change."""
    summary = report(settings, drops, redactions)
    if drops: purge.execute(settings, list(drops), {"pii_scan": "drop"}, actor=actor, action="pii-scan.drop")
    images, days = [], set()
    with store.connect(settings) as con:
        con.execute("PRAGMA secure_delete=ON")
        for frame_id, (lines, _) in redactions.items():
            row = con.execute("SELECT rowid, ts, ocr_text, image_path FROM frames WHERE id = ?", (frame_id,)).fetchone()
            if row is None: continue
            text = "\n".join(line["text"] for line in lines)
            # The FTS table has no update trigger: remove the old entry and add the new one by hand,
            # or the redacted text would stay searchable.
            con.execute("INSERT INTO frames_fts(frames_fts, rowid, ocr_text) VALUES('delete', ?, ?)", (row["rowid"], row["ocr_text"]))
            con.execute("UPDATE frames SET ocr_text = ?, ocr_json = ?, domains = ?, image_path = NULL WHERE id = ?",
                        (text, json.dumps(lines, ensure_ascii=False), json.dumps(domains(text)), frame_id))
            con.execute("INSERT INTO frames_fts(rowid, ocr_text) VALUES(?, ?)", (row["rowid"], text))
            if row["image_path"]: images.append(row["image_path"])
            days.add(datetime.fromtimestamp(row["ts"]).strftime("%Y-%m-%d"))
        purge.redact_outbox(con, list(redactions))
        con.execute("INSERT INTO frames_fts(frames_fts) VALUES('optimize')")
    purge.rebuild_rollups(settings, sorted(days))
    purge.finish(settings, images)
    audit.record(settings, "user", actor, "pii-scan", params={k: summary[k] for k in ("drop", "redact")},
                 count=len(drops) + len(redactions))
    return summary
