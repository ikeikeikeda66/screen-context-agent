"""Synthetic data only. Frames are stored with the rules off, as before the rules existed."""
import json
import subprocess
import sys
import pytest
from PIL import Image
from test_core import settings, change
from screen_context import audit, rescan, store
from screen_context.capture import spool
from screen_context.config import DEFAULT_POLICY, Settings
from screen_context.indexer import drain, maintain
from screen_context.service import Service

SIGNATURE = ["来週の打ち合わせ資料を添付します。", "--", "山田 花子 様", "〒100-0001 東京都千代田区千代田1-1", "TEL 03-1234-5678"]
CARD = ["お支払い", "4111 1111 1111 1111"]
PLAIN = ["普通のページ"]


def record(settings, lines):
    spool(settings, Image.new("RGB", (100, 100)), dict(app_bundle="com.example.Mail", app_name="Mail", window_title="Mail", display_id="1"))
    drain(settings, lambda _: [{"text": line, "bbox": [0, i / 10, .5, .05]} for i, line in enumerate(lines)])


@pytest.fixture
def old_data(settings):
    change(settings, sensitive_detectors=[], pii_combinations=[])
    for lines in (SIGNATURE, CARD, PLAIN): record(settings, lines)
    change(settings, sensitive_detectors=DEFAULT_POLICY["sensitive_detectors"], pii_combinations=DEFAULT_POLICY["pii_combinations"])
    return settings


def frames(settings):
    with store.connect(settings, readonly=True) as con:
        return {r["ocr_text"].split("\n")[0]: dict(r) for r in con.execute("SELECT * FROM frames")}


def test_dry_run_counts_by_category_and_changes_nothing(old_data):
    before = frames(old_data)
    drops, redactions = rescan.scan(old_data)
    summary = rescan.report(old_data, drops, redactions)
    assert summary["drop"] == {"card_number": 1} and summary["redact"] == {"name+address": 1, "name+phone": 1}
    assert summary["frames"] == {"drop": 1, "redact": 1}
    assert frames(old_data) == before


def test_apply_matches_what_the_indexer_does_today(old_data, tmp_path):
    fresh = Settings(tmp_path / "fresh", plaintext=True); store.initialize(fresh)
    for lines in (SIGNATURE, CARD, PLAIN): record(fresh, lines)

    rescan.apply(old_data, *rescan.scan(old_data))
    old, new = frames(old_data), frames(fresh)
    assert set(old) == set(new) == {SIGNATURE[0], PLAIN[0]}  # the card frame is gone in both
    for key in old:
        assert old[key]["ocr_text"] == new[key]["ocr_text"]
        assert [line["bbox"] is None for line in json.loads(old[key]["ocr_json"])] == [line["bbox"] is None for line in json.loads(new[key]["ocr_json"])]
        assert (old[key]["image_path"] is None) == (new[key]["image_path"] is None)
    assert len(list((old_data.root / "images").iterdir())) == 1  # only the plain frame keeps a preview


def test_redacted_text_leaves_the_search_index(old_data):
    reader = Service(old_data, "full", audit_path=None)
    assert reader.search_screen_history("03-1234-5678")["count"] == 1
    rescan.apply(old_data, *rescan.scan(old_data))
    assert reader.search_screen_history("03-1234-5678")["count"] == 0
    assert reader.search_screen_history("千代田区")["count"] == 0
    assert reader.search_screen_history("打ち合わせ資料")["count"] == 1
    with store.connect(old_data) as con: con.execute("INSERT INTO frames_fts(frames_fts) VALUES('integrity-check')")


def test_cascade_rollups_outbox_audit_and_idempotence(old_data):
    signature_id = frames(old_data)[SIGNATURE[0]]["id"]
    with store.connect(old_data) as con:
        con.execute("INSERT INTO runs VALUES ('r1','c',0,NULL,0,0,0,'p','open',NULL)")
        con.execute("INSERT INTO notification_outbox VALUES ('o1','r1','k',0,'quote: 03-1234-5678',?, 'unknown','sent',NULL)", (json.dumps([signature_id]),))
    maintain(old_data)
    rescan.apply(old_data, *rescan.scan(old_data))
    with store.connect(old_data, readonly=True) as con:
        assert "03-1234-5678" not in con.execute("SELECT payload FROM rollups").fetchone()[0]
        assert con.execute("SELECT body FROM notification_outbox").fetchone()[0] == "[purged]"
    entry = audit.rows(old_data)[0]
    assert entry["action"] == "pii-scan" and entry["params"] == {"drop": {"card_number": 1}, "redact": {"name+address": 1, "name+phone": 1}}
    assert "03-1234-5678" not in json.dumps(audit.rows(old_data))
    assert rescan.scan(old_data) == ({}, {})  # nothing left to do


def test_frames_older_than_ninety_days_without_ocr_json(old_data):
    with store.connect(old_data) as con: con.execute("UPDATE frames SET ocr_json = NULL")
    drops, redactions = rescan.scan(old_data)
    assert len(drops) == 1 and len(redactions) == 1
    rescan.apply(old_data, drops, redactions)
    assert "TEL" not in frames(old_data)[SIGNATURE[0]]["ocr_text"]


def test_cli_dry_run_then_apply(old_data):
    env = {"SCREEN_CONTEXT_HOME": str(old_data.root), "SCREEN_CONTEXT_PLAINTEXT": "1", "PATH": "/usr/bin:/bin"}
    run = lambda *a: json.loads(subprocess.run([sys.executable, "-m", "screen_context.cli", "pii-scan", *a], env=env, capture_output=True, text=True, check=True).stdout)
    dry = run()
    assert dry["applied"] is False and dry["frames"] == {"drop": 1, "redact": 1} and "--apply" in dry["next"]
    assert run("--apply")["applied"] is True
    assert run("--apply") == {"frames": {"drop": 0, "redact": 0}, "applied": False}
