import sqlite3, pytest
from screen_context.config import Settings
from screen_context import store
def test_v1_to_v2(tmp_path):
    s = Settings(tmp_path, plaintext=True); s.prepare()
    con = sqlite3.connect(s.db); con.executescript(store.SCHEMA + "PRAGMA user_version=1;")
    con.execute("INSERT INTO frames VALUES ('b',2,'x','x','','1','0',NULL,'t',NULL,'[]',1,1,1)")
    con.execute("INSERT INTO frames VALUES ('a',1,'x','x','','1','0',NULL,'t',NULL,'[]',1,1,1)")
    con.commit(); con.close()
    with pytest.raises(RuntimeError): 
        with store.connect(s) as c: pass
    assert store.initialize(s) == (1, store.SCHEMA_VERSION)
    with store.connect(s, readonly=True) as c:
        assert [tuple(r) for r in c.execute("SELECT seq, frame_id FROM indexed_events ORDER BY seq")] == [(1,'a'),(2,'b')]
    with store.connect(s) as c:
        store.insert(c, dict(id='c', ts=3, app_bundle='x', app_name='x', window_title='', display_id='1', dhash='0', ocr_text='t', domains='[]'))
        store.insert(c, dict(id='c', ts=3, app_bundle='x', app_name='x', window_title='', display_id='1', dhash='0', ocr_text='t', domains='[]'))
    with store.connect(s, readonly=True) as c:
        assert c.execute("SELECT count(*) FROM indexed_events").fetchone()[0] == 3
        assert c.execute("PRAGMA user_version").fetchone()[0] == store.SCHEMA_VERSION
    con = sqlite3.connect(s.db); con.execute("PRAGMA user_version=9"); con.commit(); con.close()
    with pytest.raises(RuntimeError): store.initialize(s)


def test_readonly_connect_also_refuses_a_schema_mismatch(tmp_path):
    s = Settings(tmp_path, plaintext=True); s.prepare()
    con = sqlite3.connect(s.db); con.executescript(store.SCHEMA + "PRAGMA user_version=1;"); con.close()
    with pytest.raises(RuntimeError, match="schema version"):
        with store.connect(s, readonly=True) as c: pass


def test_health_reports_an_outdated_database_instead_of_failing(tmp_path):
    import json, subprocess, sys
    s = Settings(tmp_path, plaintext=True); s.prepare()
    con = sqlite3.connect(s.db); con.executescript(store.SCHEMA + store.SCHEMA_V2 + "PRAGMA user_version=2;"); con.close()
    env = {"SCREEN_CONTEXT_HOME": str(tmp_path), "SCREEN_CONTEXT_PLAINTEXT": "1", "PATH": "/usr/bin:/bin"}
    out = subprocess.run([sys.executable, "-m", "screen_context.cli", "health"], env=env, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    report = json.loads(out.stdout)
    assert report["state"] == "needs_init" and report["database_schema"] == 2 and report["schema_version"] == store.SCHEMA_VERSION
    store.initialize(s)
    from screen_context.health import health
    assert health(s)["state"] != "needs_init" and health(s)["database_schema"] == store.SCHEMA_VERSION


# Schema version mismatch (#70): a newer or outdated database is refused, never written.
import hashlib
import json
import time
import zipfile
from screen_context import lifecycle
from screen_context.health import derive_state, health as read_health

PASSPHRASE = "correct horse battery staple"


def make_db(tmp_path, version):
    s = Settings(tmp_path, plaintext=True); s.prepare()
    con = sqlite3.connect(s.db)
    con.execute("PRAGMA journal_mode=WAL")
    for v in sorted(store.MIGRATIONS):
        if v <= min(version, store.SCHEMA_VERSION): con.executescript(store.MIGRATIONS[v])
    con.execute(f"PRAGMA user_version={version}")
    con.commit(); con.close()
    return s


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def user_version(path):
    con = sqlite3.connect(path)
    try: return con.execute("PRAGMA user_version").fetchone()[0]
    finally: con.close()


def write_archive(path, db_file, schema):
    manifest = {"format": lifecycle.FORMAT, "created": time.time(), "schema": schema, "encrypted": False}
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.write(db_file, "history.db")
    return path


def test_initialize_leaves_a_newer_database_untouched(tmp_path):
    s = make_db(tmp_path, 9)
    before = sha256(s.db)
    legacy = s.root / "audit.jsonl"; legacy.write_text('{"ts": 1}\n', encoding="utf-8")
    with pytest.raises(store.SchemaMismatch) as excinfo: store.initialize(s)
    assert excinfo.value.newer is True and excinfo.value.found == 9
    assert sha256(s.db) == before and user_version(s.db) == 9
    assert legacy.exists()


def test_connect_refuses_an_outdated_database_without_migrating(tmp_path):
    s = make_db(tmp_path, 3)
    with pytest.raises(store.SchemaMismatch) as excinfo:
        with store.connect(s): pass
    assert excinfo.value.newer is False and excinfo.value.found == 3 and excinfo.value.expected == store.SCHEMA_VERSION


@pytest.mark.parametrize("version", [3, 9])
def test_backup_records_the_real_schema_and_leaves_the_database_alone(tmp_path, version):
    s = make_db(tmp_path, version)
    before = sha256(s.db)
    archive = tmp_path / "b.zip"
    result = lifecycle.backup(s, archive, PASSPHRASE)
    assert result["schema"] == version
    assert result["audited"] is False
    with zipfile.ZipFile(archive) as z: assert json.loads(z.read("manifest.json"))["schema"] == version
    assert sha256(s.db) == before


def test_restore_refuses_a_newer_archive_before_replacing(tmp_path):
    archive = write_archive(tmp_path / "new.zip", make_db(tmp_path / "src", 9).db, 9)
    target = make_db(tmp_path / "data", store.SCHEMA_VERSION)
    before = sha256(target.db)
    with pytest.raises(store.SchemaMismatch) as excinfo: lifecycle.restore(target, archive, PASSPHRASE, replace=True)
    assert excinfo.value.newer is True
    assert sha256(target.db) == before


def test_restore_migrates_an_outdated_archive(tmp_path):
    archive = write_archive(tmp_path / "old.zip", make_db(tmp_path / "src", 3).db, 3)
    target = Settings(tmp_path / "new", plaintext=True)
    result = lifecycle.restore(target, archive, PASSPHRASE)
    assert result["schema"] == [3, store.SCHEMA_VERSION]
    assert user_version(target.db) == store.SCHEMA_VERSION


def test_health_reports_a_newer_database_as_needs_newer_binary(tmp_path):
    s = make_db(tmp_path, 9)
    assert read_health(s)["state"] == "needs_newer_binary"


def test_derive_state_follows_the_database_schema():
    base = {"paused": False, "capture": {"running": True, "error_type": None}, "permission": "unknown",
            "session": {"locked": False, "idle_seconds": None}, "indexer": {"running": True},
            "queue": {"oldest_age_seconds": None}, "schema_version": store.SCHEMA_VERSION}
    assert derive_state({**base, "database_schema": store.SCHEMA_VERSION}) == "active"
    assert derive_state({**base, "database_schema": 3}) == "needs_init"
    assert derive_state({**base, "database_schema": 9}) == "needs_newer_binary"
