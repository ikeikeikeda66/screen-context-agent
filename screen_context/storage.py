"""How much space each kind of data takes, for choosing retention periods."""
from . import store


def size(paths):
    return sum(p.stat().st_size for p in paths if p.is_file())


def usage(settings):
    root = settings.root
    result = {
        "previews_bytes": size((root / "images").glob("*")),
        "database_bytes": size(root.glob("history.db*")),  # includes the WAL; OCR text lives here
        "spool_bytes": size((root / "spool").glob("*.frame")),
        "exports_bytes": size((root / "exports").glob("*")),
    }
    with store.connect(settings, readonly=True) as con:
        frames, oldest, previews = con.execute("SELECT count(*), min(ts), count(image_path) FROM frames").fetchone()
        audit_rows = con.execute("SELECT count(*) FROM audit").fetchone()[0]
    skipped = skip_counts(settings)
    retention = {name: settings.retention(name) for name in ("preview_retention_days", "text_retention_days", "audit_retention_days")}
    return {**result, "frames": frames, "frames_with_preview": previews, "oldest_frame_ts": oldest, "audit_rows": audit_rows, "retention": retention,
            "skipped": skipped}


def skip_counts(settings, days=30):
    """Frames not recorded (dropped or redacted) by sensitive-input rule, over the last `days` days."""
    from datetime import datetime, timedelta
    since = (datetime.now() - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    with store.connect(settings, readonly=True) as con:
        rows = con.execute("SELECT category, sum(count) AS n FROM skip_counts WHERE day >= ? GROUP BY category ORDER BY n DESC", (since,))
        return {r["category"]: r["n"] for r in rows}
