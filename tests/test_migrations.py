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
    assert store.initialize(s) == (1, 3)
    with store.connect(s, readonly=True) as c:
        assert [tuple(r) for r in c.execute("SELECT seq, frame_id FROM indexed_events ORDER BY seq")] == [(1,'a'),(2,'b')]
    with store.connect(s) as c:
        store.insert(c, dict(id='c', ts=3, app_bundle='x', app_name='x', window_title='', display_id='1', dhash='0', ocr_text='t', domains='[]'))
        store.insert(c, dict(id='c', ts=3, app_bundle='x', app_name='x', window_title='', display_id='1', dhash='0', ocr_text='t', domains='[]'))
    with store.connect(s, readonly=True) as c:
        assert c.execute("SELECT count(*) FROM indexed_events").fetchone()[0] == 3
        assert c.execute("PRAGMA user_version").fetchone()[0] == 3
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
