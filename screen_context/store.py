import json
import sqlite3
from contextlib import contextmanager
from .crypto import get_key

SCHEMA = """
CREATE TABLE IF NOT EXISTS frames (
 id TEXT PRIMARY KEY, ts REAL NOT NULL, app_bundle TEXT NOT NULL, app_name TEXT NOT NULL,
 window_title TEXT NOT NULL, display_id TEXT NOT NULL, dhash TEXT NOT NULL,
 image_path TEXT, ocr_text TEXT NOT NULL, ocr_json TEXT, domains TEXT NOT NULL,
 src_w INTEGER, src_h INTEGER, ocr_ms INTEGER
);
CREATE INDEX IF NOT EXISTS frames_ts ON frames(ts);
CREATE VIRTUAL TABLE IF NOT EXISTS frames_fts USING fts5(ocr_text, content='frames', content_rowid='rowid', tokenize='trigram');
CREATE TRIGGER IF NOT EXISTS frames_ai AFTER INSERT ON frames BEGIN
 INSERT INTO frames_fts(rowid,ocr_text) VALUES(new.rowid,new.ocr_text);
END;
CREATE TRIGGER IF NOT EXISTS frames_ad AFTER DELETE ON frames BEGIN
 INSERT INTO frames_fts(frames_fts,rowid,ocr_text) VALUES('delete',old.rowid,old.ocr_text);
END;
CREATE TABLE IF NOT EXISTS rollups (day TEXT PRIMARY KEY, payload TEXT NOT NULL);
"""

# Version 2: monotonically increasing OCR-completion sequence for delta consumers,
# consumer cursors with leases, run history and the proposal outbox.
# The trigger fills indexed_events inside the same transaction as the frame insert,
# so an older binary that still inserts frames directly cannot leave gaps.
SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS indexed_events (
 seq INTEGER PRIMARY KEY AUTOINCREMENT, frame_id TEXT NOT NULL UNIQUE, indexed_at REAL NOT NULL
);
CREATE TRIGGER IF NOT EXISTS frames_ai_seq AFTER INSERT ON frames BEGIN
 INSERT OR IGNORE INTO indexed_events(frame_id, indexed_at) VALUES(new.id, (julianday('now')-2440587.5)*86400.0);
END;
INSERT OR IGNORE INTO indexed_events(frame_id, indexed_at) SELECT id, ts FROM frames ORDER BY ts, id;
CREATE TABLE IF NOT EXISTS consumers (
 consumer_id TEXT PRIMARY KEY, cursor_seq INTEGER NOT NULL DEFAULT 0,
 lease_until REAL NOT NULL DEFAULT 0, lease_run TEXT, updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
 run_id TEXT PRIMARY KEY, consumer_id TEXT NOT NULL, started_at REAL NOT NULL, finished_at REAL,
 cursor_before INTEGER NOT NULL, cursor_after INTEGER NOT NULL, snapshot_seq INTEGER NOT NULL,
 policy_revision TEXT NOT NULL, state TEXT NOT NULL, detail TEXT
);
CREATE TABLE IF NOT EXISTS notification_outbox (
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL, dedup_key TEXT NOT NULL UNIQUE, created_at REAL NOT NULL,
 body TEXT NOT NULL, frame_ids TEXT NOT NULL, delivery TEXT NOT NULL, state TEXT NOT NULL, receipt TEXT
);
"""

# Version 3: the audit log moves from plaintext audit.jsonl into the encrypted database
# and records query text and returned frames, so the user can see what each client read
# (and purge it later). clients holds per-client tokens (hash only); skip_counts records
# how many frames were not stored and why, never their content.
SCHEMA_V3 = """
CREATE TABLE IF NOT EXISTS audit (
 id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, path TEXT NOT NULL CHECK (path IN ('agent', 'user')),
 client TEXT NOT NULL, profile TEXT, action TEXT NOT NULL, query TEXT, params TEXT NOT NULL DEFAULT '{}',
 frame_ids TEXT NOT NULL DEFAULT '[]', result_count INTEGER NOT NULL DEFAULT 0, legacy_sha256 TEXT
);
CREATE INDEX IF NOT EXISTS audit_ts ON audit(ts);
CREATE INDEX IF NOT EXISTS audit_client ON audit(client, ts);
CREATE TABLE IF NOT EXISTS clients (
 name TEXT PRIMARY KEY, token_sha256 TEXT NOT NULL UNIQUE, profile TEXT NOT NULL, state TEXT NOT NULL,
 created_at REAL NOT NULL, approved_at REAL, revoked_at REAL
);
CREATE TABLE IF NOT EXISTS skip_counts (
 day TEXT NOT NULL, category TEXT NOT NULL, count INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (day, category)
);
"""

MIGRATIONS = {1: SCHEMA, 2: SCHEMA_V2, 3: SCHEMA_V3}
SCHEMA_VERSION = max(MIGRATIONS)


@contextmanager
def connect(settings, readonly=False, migrating=False):
    driver = sqlite3
    if not settings.plaintext:
        try: from sqlcipher3 import dbapi2 as driver
        except ImportError as e: raise RuntimeError("SQLCipher unavailable. Install encrypted extra; plaintext requires explicit SCREEN_CONTEXT_PLAINTEXT=1 (development only).") from e
    con = driver.connect(settings.db.as_uri() + ("?mode=ro" if readonly else "?mode=rwc"), uri=True, timeout=10)
    try:
        if not settings.plaintext:
            key = get_key(settings)
            con.execute('PRAGMA key = "x\'' + key.hex() + '\'"')
            if not con.execute("PRAGMA cipher_version").fetchone(): raise RuntimeError("SQLCipher required")
        con.row_factory = driver.Row
        con.execute("PRAGMA busy_timeout=10000")
        if readonly: con.execute("PRAGMA query_only=ON")
        else:
            con.execute("PRAGMA journal_mode=WAL")
            version = con.execute("PRAGMA user_version").fetchone()[0]
            # Writers refuse both directions of mismatch: an outdated DB needs an explicit
            # migration (with a backup), and a newer DB must not be written by an old binary.
            if not migrating and version not in (0, SCHEMA_VERSION):
                raise RuntimeError(f"Database schema version {version} does not match {SCHEMA_VERSION}; run screen-context init after backing up history.db")
        yield con
        if not readonly: con.commit()
    except BaseException:
        con.rollback()
        raise
    finally: con.close()


def migrate(con):
    """Apply pending migrations in order. Returns (before, after) versions."""
    before = con.execute("PRAGMA user_version").fetchone()[0]
    if before > SCHEMA_VERSION: raise RuntimeError(f"Database schema version {before} is newer than this binary ({SCHEMA_VERSION})")
    for version in sorted(MIGRATIONS):
        if version > before:
            con.executescript(MIGRATIONS[version])
            con.execute(f"PRAGMA user_version={version}")
    return before, SCHEMA_VERSION


def initialize(settings):
    settings.prepare()
    if not settings.plaintext: get_key(settings, create=True)
    legacy = settings.root / "audit.jsonl"
    with connect(settings, migrating=True) as con:
        versions = migrate(con)
        if legacy.exists():
            from .audit import import_jsonl
            import_jsonl(con, legacy)
    # Only after the import has committed: the plaintext log must not outlive its copy, nor vanish without one.
    legacy.unlink(missing_ok=True)
    settings.db.chmod(0o600)
    return versions


def snapshot(settings, path):
    """Consistent copy of the database while writers may be running, encrypted with the same key."""
    with connect(settings, readonly=True) as source:
        driver = sqlite3 if settings.plaintext else __import__("sqlcipher3.dbapi2", fromlist=["dbapi2"])
        target = driver.connect(str(path))
        try:
            if not settings.plaintext: target.execute('PRAGMA key = "x\'' + get_key(settings).hex() + '\'"')
            source.backup(target)
        finally: target.close()


def count_skip(con, day, category):
    """Count a frame that was not stored, by reason only."""
    con.execute("INSERT INTO skip_counts (day, category, count) VALUES (?, ?, 1) "
                "ON CONFLICT(day, category) DO UPDATE SET count = count + 1", (day, category))


def insert(con, record):
    columns = ("id", "ts", "app_bundle", "app_name", "window_title", "display_id", "dhash", "image_path", "ocr_text", "ocr_json", "domains", "src_w", "src_h", "ocr_ms")
    con.execute("INSERT OR IGNORE INTO frames (" + ",".join(columns) + ") VALUES (" + ",".join("?" for _ in columns) + ")", [record.get(k) for k in columns])
