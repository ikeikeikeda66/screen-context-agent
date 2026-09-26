import json
import subprocess
import sys
import time
import pytest
from test_core import settings, add
from screen_context import audit, store
from screen_context.indexer import maintain
from screen_context.service import Service

DAY = 86400


def count(settings, sql):
    with store.connect(settings, readonly=True) as con: return con.execute(sql).fetchone()[0]


def test_defaults_keep_text_and_audit_forever(settings):
    assert (settings.retention("preview_retention_days"), settings.retention("text_retention_days"), settings.retention("audit_retention_days")) == (90, None, None)
    add(settings, "ancient page", ts=time.time() - 3000 * DAY)
    Service(settings, client="cursor").search_screen_history("ancient")
    result = maintain(settings)
    assert result["expired_frames"] == 0 and result["expired_audit_rows"] == 0
    assert count(settings, "SELECT count(*) FROM frames") == 1 and count(settings, "SELECT count(*) FROM audit") == 1


def test_text_retention_deletes_whole_frames_through_the_purge_cascade(settings):
    old = add(settings, "expired zqxj text", ts=time.time() - 40 * DAY)
    recent = add(settings, "recent text", ts=time.time() - 5 * DAY)
    maintain(settings)
    assert count(settings, "SELECT count(*) FROM rollups") == 2
    settings.set_retention("text_retention_days", 30)
    result = maintain(settings)
    assert result["expired_frames"] == 1
    with store.connect(settings, readonly=True) as con:
        assert [r[0] for r in con.execute("SELECT id FROM frames")] == [recent["id"]]
        assert con.execute("SELECT count(*) FROM rollups").fetchone()[0] == 1
        assert "zqxj" not in json.dumps([r[0] for r in con.execute("SELECT payload FROM rollups")])
        assert con.execute("SELECT count(*) FROM indexed_events WHERE frame_id = ?", (old["id"],)).fetchone()[0] == 0
    assert Service(settings, "full", audit_path=None).search_screen_history("zqxj")["count"] == 0
    entry = audit.rows(settings)[0]
    assert (entry["client"], entry["action"], entry["result_count"]) == ("maintain", "retention", 1)


def test_preview_retention_is_configurable(settings):
    frame = add(settings, "page", ts=time.time() - 40 * DAY)
    image = settings.root / "images" / "p.webp"; image.write_bytes(b"x")
    with store.connect(settings) as con: con.execute("UPDATE frames SET image_path = ? WHERE id = ?", (image.name, frame["id"]))
    assert maintain(settings)["expired_images"] == 0  # 40 days < default 90
    settings.set_retention("preview_retention_days", 30)
    assert maintain(settings)["expired_images"] == 1 and not image.exists()
    assert count(settings, "SELECT count(*) FROM frames") == 1  # text stays


def test_audit_retention(settings):
    Service(settings, client="cursor").search_screen_history("anything")
    with store.connect(settings) as con: con.execute("UPDATE audit SET ts = ?", (time.time() - 400 * DAY,))
    Service(settings, client="cursor").search_screen_history("today")
    settings.set_retention("audit_retention_days", 365)
    assert maintain(settings)["expired_audit_rows"] == 1
    assert [r["query"] for r in audit.rows(settings)] == ["today"]


@pytest.mark.parametrize("value", [0, 36501, "30", 1.5])
def test_invalid_retention_is_refused(settings, value):
    with pytest.raises(ValueError): settings.set_retention("text_retention_days", value)
    with pytest.raises(ValueError): settings.set_retention("unknown_days", 30)


def test_managed_retention_is_locked(tmp_path):
    from screen_context.config import Settings
    class Managed:
        def values(self): return {"options": {"text_retention_days": 180}}
    managed = Settings(tmp_path, plaintext=True, managed=Managed())
    assert managed.retention("text_retention_days") == 180
    with pytest.raises(PermissionError): managed.set_retention("text_retention_days", None)


def test_cli_retention_and_usage(settings):
    add(settings, "page")
    (settings.root / "images" / "p.webp").write_bytes(b"x" * 1000)
    env = {"SCREEN_CONTEXT_HOME": str(settings.root), "SCREEN_CONTEXT_PLAINTEXT": "1", "PATH": "/usr/bin:/bin"}
    run = lambda *a: subprocess.run([sys.executable, "-m", "screen_context.cli", *a], env=env, capture_output=True, text=True)
    assert json.loads(run("retention", "--text", "365", "--preview", "30").stdout) == {
        "preview_retention_days": 30, "text_retention_days": 365, "audit_retention_days": None}
    assert json.loads(run("retention", "--text", "none").stdout)["text_retention_days"] is None
    assert run("retention", "--audit", "soon").returncode != 0
    report = json.loads(run("usage").stdout)
    assert report["previews_bytes"] == 1000 and report["database_bytes"] > 0 and report["frames"] == 1
    assert report["retention"]["preview_retention_days"] == 30
