import json
import subprocess
import sys
import time
import pytest
from PIL import Image
from test_core import settings, add, change
from screen_context import audit, purge, store
from screen_context.capture import spool
from screen_context.indexer import drain, maintain
from screen_context.service import Service

MARKER = "zqxjmarker"


def indexed(settings, text, app="com.google.Chrome"):
    record = spool(settings, Image.new("RGB", (100, 100)), dict(app_bundle=app, app_name=app, window_title="Docs", display_id="1"))
    drain(settings, lambda _: [{"text": text, "bbox": [0, 0, 1, 1]}])
    return record["id"]


def query(settings, sql, *args):
    with store.connect(settings, readonly=True) as con: return [tuple(r) for r in con.execute(sql, args)]


def test_selectors_combine_and_one_is_required(settings):
    now = time.time()
    a = add(settings, "alpha " + MARKER, app="com.google.Chrome", ts=now - 7200)["id"]
    b = add(settings, "beta " + MARKER, app="com.apple.Safari", ts=now - 60)["id"]
    c = add(settings, "gamma", app="com.apple.Safari", ts=now - 30)["id"]
    assert set(purge.select(settings, keyword=MARKER)) == {a, b}
    assert purge.select(settings, keyword=MARKER, app="com.apple.Safari") == [b]
    assert set(purge.select(settings, since=now - purge.duration("15m"))) == {b, c}
    assert purge.select(settings, until=now - 3600) == [a]
    assert purge.select(settings, block=b) == [b]  # different text: a separate block from c
    d = add(settings, "gamma continued", app="com.apple.Safari", ts=now - 20)["id"]
    assert set(purge.select(settings, block=c)) == {c, d}  # one block of similar consecutive frames
    with pytest.raises(ValueError): purge.select(settings)
    with pytest.raises(ValueError): purge.duration("15 minutes")


def test_excluded_selector_finds_what_the_policy_hides(settings):
    kept = add(settings, "public page")["id"]
    hidden = add(settings, "private https://private.example.com/x")["id"]
    change(settings, denied_domains=["private.example.com"])
    assert purge.select(settings, excluded=True) == [hidden] and kept not in purge.select(settings, excluded=True)


@pytest.fixture
def production_delete_mode(monkeypatch):
    """SQLCipher defaults to secure_delete=OFF, but many system SQLite builds (used by plaintext
    tests) default to ON, which would hide a missing PRAGMA. Start every connection OFF."""
    from contextlib import contextmanager
    original = store.connect
    @contextmanager
    def connect(*args, **kwargs):
        with original(*args, **kwargs) as con:
            con.execute("PRAGMA secure_delete=OFF")
            yield con
    monkeypatch.setattr(store, "connect", connect)


def test_purge_cascades_and_leaves_no_text_behind(settings, production_delete_mode):
    target = indexed(settings, "secret plan " + MARKER)
    other = indexed(settings, "ordinary page")
    Service(settings, client="cursor").search_screen_history(MARKER)
    Service(settings, client="cursor").search_screen_history("ordinary")
    with store.connect(settings) as con:
        con.execute("INSERT INTO runs VALUES ('r1','c',0,NULL,0,0,0,'p','open',NULL)")
        con.execute("INSERT INTO notification_outbox VALUES ('o1','r1','k',0,?,?, 'unknown','sent',NULL)", ("quote: " + MARKER, json.dumps([target])))
    maintain(settings)
    assert MARKER in query(settings, "SELECT payload FROM rollups")[0][0]

    ids = purge.select(settings, keyword=MARKER)
    preview = purge.plan(settings, ids)
    assert preview["frames"] == 1 and preview["images"] == 1
    assert preview["already_received_by"] == [{"path": "agent", "client": "cursor", "frames": 1, "last_ts": pytest.approx(time.time(), abs=60)}]
    assert query(settings, "SELECT count(*) FROM frames")[0][0] == 2  # plan changes nothing

    on_disk = lambda: b"".join(p.read_bytes() for p in settings.root.glob("history.db*"))
    assert MARKER.encode() in on_disk()  # otherwise the final check would prove nothing
    purge.execute(settings, ids, {"keyword": MARKER})
    assert query(settings, "SELECT id FROM frames") == [(other,)]
    assert query(settings, "SELECT count(*) FROM indexed_events WHERE frame_id = ?", target)[0][0] == 0
    assert Service(settings, "full", audit_path=None).search_screen_history(MARKER)["count"] == 0
    assert len(list((settings.root / "images").iterdir())) == 1
    assert query(settings, "SELECT body, frame_ids FROM notification_outbox") == [(purge.PURGED, "[]")]
    assert MARKER not in query(settings, "SELECT payload FROM rollups")[0][0]
    rows = audit.rows(settings)
    assert rows[0]["action"] == "purge" and rows[0]["result_count"] == 1 and MARKER not in json.dumps(rows[0])
    assert all(r["query"] != MARKER and target not in r["frame_ids"] for r in rows)
    assert [r["query"] for r in rows if r["client"] == "cursor"] == ["ordinary", None]
    # secure_delete, FTS optimize and the WAL checkpoint leave no copy of the text in the files.
    assert MARKER.encode() not in on_disk()


def test_last_minutes_also_removes_unindexed_spool_files(settings):
    spool(settings, Image.new("RGB", (10, 10)), dict(app_bundle="x", app_name="x", window_title="t", display_id="1"))
    files = purge.spooled(settings, since=time.time() - 60)
    assert len(files) == 1 and purge.spooled(settings, until=time.time() - 3600) == []
    purge.execute(settings, [], {"since": time.time() - 60}, files)
    assert not list((settings.root / "spool").iterdir())


def test_empty_day_drops_its_rollup(settings):
    only = add(settings, "lonely " + MARKER)["id"]
    maintain(settings)
    purge.execute(settings, [only], {"block": only})
    assert query(settings, "SELECT count(*) FROM rollups")[0][0] == 0


def test_cli_dry_run_then_yes(settings):
    add(settings, "cli " + MARKER)
    env = {"SCREEN_CONTEXT_HOME": str(settings.root), "SCREEN_CONTEXT_PLAINTEXT": "1", "PATH": "/usr/bin:/bin"}
    run = lambda *a: subprocess.run([sys.executable, "-m", "screen_context.cli", "purge", *a], env=env, capture_output=True, text=True)
    dry = json.loads(run("--keyword", MARKER).stdout)
    assert dry["frames"] == 1 and dry["deleted"] is False and "--yes" in dry["next"]
    assert query(settings, "SELECT count(*) FROM frames")[0][0] == 1
    assert json.loads(run("--keyword", MARKER, "--yes").stdout)["deleted"] is True
    assert query(settings, "SELECT count(*) FROM frames")[0][0] == 0
    assert run().returncode != 0 and "Choose what to purge" in run().stderr
