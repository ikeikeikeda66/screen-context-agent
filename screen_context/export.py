"""Plaintext export by time range (roadmap decision 6). The policy always applies.

Everything written here leaves the encrypted store, so each export is audited with the
IDs of the frames it contained. A later purge of those frames can then warn that a copy
already exists outside the store.
"""
import csv
import io
import json
from datetime import datetime
from pathlib import Path
from . import audit, store
from .crypto import atomic_write
from .privacy import MARKERS, NOTICE, denied

FORMATS = ("jsonl", "md", "csv", "viking")


def frames(settings, since, until, exclude_ide=False):
    policy = settings.policy()
    profile = "standard" if exclude_ide else "full"  # the standard profile is the one that hides IDEs
    with store.connect(settings, readonly=True) as con:
        rows = [dict(r) for r in con.execute(
            "SELECT id, ts, app_bundle, app_name, window_title, display_id, ocr_text, domains FROM frames "
            "WHERE ts >= ? AND ts < ? ORDER BY ts, id", (since, until))]
    return [r for r in rows if not denied(policy, r, profile)]


def record(row):
    return {"frame_id": row["id"], "ts": row["ts"], "time": datetime.fromtimestamp(row["ts"]).isoformat(timespec="seconds"),
            "app": row["app_name"], "app_bundle": row["app_bundle"], "title": row["window_title"],
            "domains": json.loads(row["domains"]), "text": row["ocr_text"], **MARKERS}


def render(rows, fmt):
    records = [record(r) for r in rows]
    if fmt == "jsonl":
        return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)
    if fmt == "csv":
        out = io.StringIO()
        writer = csv.DictWriter(out, ["frame_id", "time", "app", "app_bundle", "title", "domains", "text"], extrasaction="ignore")
        writer.writeheader()
        for r in records: writer.writerow({**r, "domains": " ".join(r["domains"])})
        return out.getvalue()
    lines, day = [f"<!-- {NOTICE} -->", ""], None
    for r in records:
        if r["time"][:10] != day:
            day = r["time"][:10]
            lines += [f"# {day}", ""]
        lines += [f"## {r['time'][11:16]} {r['app']} — {r['title']}", "", r["text"], ""]
    return "\n".join(lines)


def write(settings, since, until, fmt, out_dir=None, exclude_ide=False, actor="cli"):
    if fmt not in FORMATS: raise ValueError("Format must be one of " + ", ".join(FORMATS))
    if settings.option("export_allowed", True) is False: raise PermissionError("Exports are disabled by your administrator")
    if until <= since: raise ValueError("--to must be after --from")
    rows = frames(settings, since, until, exclude_ide)
    folder = Path(out_dir) if out_dir else settings.root / "exports"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = lambda ts: datetime.fromtimestamp(ts).strftime("%Y%m%d-%H%M")
    if fmt == "viking":
        from .viking import export as daily
        days = sorted({datetime.fromtimestamp(r["ts"]).strftime("%Y-%m-%d") for r in rows})
        paths = [str(daily(settings, day, folder, audited=False)) for day in days]
    else:
        path = folder / f"screen-context-{stamp(since)}-{stamp(until)}.{fmt}"
        if path.exists(): raise FileExistsError(f"{path} already exists")
        atomic_write(path, render(rows, fmt).encode("utf-8"))
        path.chmod(0o600)
        paths = [str(path)]
    audit.record(settings, "user", actor, "export", params={"format": fmt, "since": since, "until": until, "paths": paths,
                 "exclude_ide": exclude_ide}, frame_ids=[r["id"] for r in rows], count=len(rows))
    return {"paths": paths, "frames": len(rows), "format": fmt,
            "note": "Plaintext outside the encrypted store: later exclusions and purges do not reach it."}
