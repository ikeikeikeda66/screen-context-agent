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
    assert store.initialize(s) == (1, 2)
    with store.connect(s, readonly=True) as c:
        assert [tuple(r) for r in c.execute("SELECT seq, frame_id FROM indexed_events ORDER BY seq")] == [(1,'a'),(2,'b')]
    with store.connect(s) as c:
        store.insert(c, dict(id='c', ts=3, app_bundle='x', app_name='x', window_title='', display_id='1', dhash='0', ocr_text='t', domains='[]'))
        store.insert(c, dict(id='c', ts=3, app_bundle='x', app_name='x', window_title='', display_id='1', dhash='0', ocr_text='t', domains='[]'))
    with store.connect(s, readonly=True) as c:
        assert c.execute("SELECT count(*) FROM indexed_events").fetchone()[0] == 3
        assert c.execute("PRAGMA user_version").fetchone()[0] == 2
    con = sqlite3.connect(s.db); con.execute("PRAGMA user_version=9"); con.commit(); con.close()
    with pytest.raises(RuntimeError): store.initialize(s)
