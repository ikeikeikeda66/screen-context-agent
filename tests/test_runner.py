import json
import time
import pytest
from test_core import settings, add, change
from screen_context import runner, health
from screen_context.service import Service


@pytest.fixture
def active(monkeypatch):
    state = {"state": "active"}
    monkeypatch.setattr(runner, "health", lambda s, now=None: state)
    return state


def test_first_run_window_then_delta_and_late_ocr(settings, active):
    now = time.time()
    add(settings, "古い資料", ts=now - 7200)          # indexed now, but only ts is old
    fresh = add(settings, "新しい資料 example.com", ts=now - 60)
    outcome, m = runner.prepare(settings, now=now, run_id="r1")
    assert outcome == "ready"
    assert [b["frame_id"] for b in m["blocks"]] == [fresh["id"]]  # consumed by OCR order, shown only if the screen itself is recent
    assert runner.finish(settings, "r1", "[SILENT]")["state"] == "no_proposal"
    late = add(settings, "遅れてOCRされた", ts=now - 30)     # OCR completed after the cursor moved
    outcome, m = runner.prepare(settings, now=now + 1, run_id="r2")
    assert outcome == "ready" and [b["frame_id"] for b in m["blocks"]] == [late["id"]]
    assert runner.prepare(settings, now=now + 2, run_id="r3")[0] == "busy"
    runner.finish(settings, "r2", "")
    assert runner.prepare(settings, now=now + 3, run_id="r4")[0] == "no_new"


def test_old_screens_indexed_late_are_not_shown_as_current(settings, active):
    now = time.time()
    add(settings, "三日前の画面", ts=now - 3 * 86400)   # OCR finished just now
    fresh = add(settings, "今の画面", ts=now - 30)
    outcome, m = runner.prepare(settings, now=now, run_id="r1")
    assert outcome == "ready" and [b["frame_id"] for b in m["blocks"]] == [fresh["id"]]
    runner.finish(settings, "r1", "[SILENT]")
    add(settings, "AIの回答", app="com.anthropic.claudefordesktop", ts=now)
    add(settings, "古い画面", ts=now - 7200)
    assert runner.prepare(settings, now=now + 1, run_id="r2")[0] == "ai_only"


def test_first_run_includes_everything_in_window(settings, active):
    now = time.time()
    a = add(settings, "A", ts=now - 600); b = add(settings, "B", ts=now - 300)
    outcome, m = runner.prepare(settings, now=now, run_id="r1")
    assert outcome == "ready" and {x for blk in m["blocks"] for x in blk["frame_ids"]} == {a["id"], b["id"]}


def test_gating_states(settings, active):
    now = time.time()
    add(settings, "作業中", ts=now - 20)
    active["state"] = "locked"
    assert runner.prepare(settings, now=now, run_id="r1")[0] == "locked"
    active["state"] = "active"
    assert runner.prepare(settings, now=now, run_id="r2")[0] == "ready"     # cursor was kept while locked
    runner.finish(settings, "r2", "[SILENT]")
    add(settings, "古い観測", ts=now - 3600)
    assert runner.prepare(settings, now=now + 1, run_id="r3")[0] == "stale"  # advanced, not re-offered
    assert runner.prepare(settings, now=now + 2, run_id="r4")[0] == "no_new"
    change(settings, ai_output_title_patterns=["Assistant Bot"])
    add(settings, "AIの回答", app="com.anthropic.claudefordesktop", ts=now)
    add(settings, "エージェントの投稿", app="com.example.chat", title="#general | Assistant Bot", ts=now)
    assert runner.prepare(settings, now=now + 3, run_id="r5")[0] == "ai_only"


def test_exclusions_advance_cursor_and_hide_content(settings, active):
    now = time.time()
    add(settings, "秘密 https://private.example.com/x", ts=now - 10)
    change(settings, denied_domains=["example.com"])
    assert runner.prepare(settings, now=now, run_id="r1")[0] == "no_new"
    add(settings, "公開情報", ts=now - 5)
    outcome, m = runner.prepare(settings, now=now + 1, run_id="r2")
    assert outcome == "ready" and "秘密" not in json.dumps(m, ensure_ascii=False)


def test_abandoned_run_is_retried(settings, active):
    now = time.time()
    f = add(settings, "途中で落ちた", ts=now - 10)
    assert runner.prepare(settings, now=now, run_id="r1", lease_seconds=60)[0] == "ready"
    assert runner.prepare(settings, now=now + 30, run_id="r2")[0] == "busy"
    outcome, m = runner.prepare(settings, now=now + 61, run_id="r3")
    assert outcome == "ready" and m["blocks"][0]["frame_id"] == f["id"]
    from screen_context import store
    with store.connect(settings, readonly=True) as con:
        assert con.execute("SELECT state FROM runs WHERE run_id='r1'").fetchone()[0] == "abandoned"


def test_submit_checks_evidence_and_suppresses_duplicates(settings, active, monkeypatch):
    monkeypatch.setenv("SCREEN_CONTEXT_LANG", "ja")
    now = time.time()
    f = add(settings, "配信API仕様を確認中 締切は金曜", ts=now - 10)
    other = add(settings, "別の画面", ts=now - 5)
    runner.prepare(settings, now=now, run_id="r1")
    with pytest.raises(ValueError): runner.submit(settings, "r1", "提案", "次", "存在しない引用", [f["id"]])
    with pytest.raises(ValueError): runner.submit(settings, "r1", "提案", "次", "配信API仕様", ["nope"])
    r = runner.submit(settings, "r1", "締切前に配信API仕様の未確認箇所を洗い出す", "仕様書の差分を1件確認", "確認中 締切は金曜", [f["id"]], delivery="mock", now=now)
    assert r["decision"] == "deliver" and r["message"].startswith("💡") and "確認中 締切は金曜" in r["message"] and "次の一手:" in r["message"]
    assert runner.finish(settings, "r1", r["message"])["state"] == "delivered_unknown"
    add(settings, "配信API仕様 続き", ts=now + 100)
    runner.prepare(settings, now=now + 101, run_id="r2")
    from screen_context import store
    with store.connect(settings, readonly=True) as con:
        ids = json.loads(con.execute("SELECT detail FROM runs WHERE run_id='r2'").fetchone()[0])["frame_ids"]
    dup = runner.submit(settings, "r2", "締切前に配信API仕様の未確認箇所を洗い出す。", "仕様書の差分を 2 件確認", "配信API仕様", ids, now=now + 101)
    assert dup["decision"] == "suppressed_duplicate"
    assert runner.finish(settings, "r2", "何か書いた")["state"] == "unregistered_output"
    with pytest.raises(ValueError): runner.submit(settings, "r2", "x", "y", "配信API仕様", ids)
    change(settings, denied_apps=["com.google.Chrome"])
    add(settings, "z", app="com.apple.finder", ts=now + 200)
    runner.prepare(settings, now=now + 201, run_id="r3")
    with pytest.raises(ValueError): runner.submit(settings, "r3", "x", "y", "配信API仕様", [f["id"]])


def test_activity_delta_pagination_policy_and_profile(settings):
    now = time.time()
    ids = [add(settings, f"資料{i} 検索", ts=now - 100 + i)["id"] for i in range(5)]
    s = Service(settings, "full")
    with pytest.raises(PermissionError): Service(settings).get_activity_delta()
    first = s.get_activity_delta(limit=2)
    assert [r["frame_id"] for r in first["records"]] == ids[:2] and first["has_more"] and first["next_cursor"]
    add(settings, "取得中に増えた", ts=now)
    second = s.get_activity_delta(cursor=first["next_cursor"], limit=2)
    third = s.get_activity_delta(cursor=second["next_cursor"], limit=2)
    assert [r["frame_id"] for r in second["records"] + third["records"]] == ids[2:]
    assert third["next_cursor"] is None and third["freshness"]["behind"] == 1
    with pytest.raises(ValueError): s.get_activity_delta(cursor=first["next_cursor"][:-4] + "AAAA")
    change(settings, denied_title_patterns=["Documentation"])
    with pytest.raises(ValueError): s.get_activity_delta(cursor=first["next_cursor"])
    assert s.get_activity_delta()["count"] == 0
    assert s.get_capture_health()["state"] == "capture_stopped"


def test_health_state_order():
    base = {"paused": False, "capture": {"running": True, "error_type": None}, "permission": "unknown", "session": {"locked": False, "idle_seconds": 0}, "indexer": {"running": True}, "queue": {"oldest_age_seconds": 0}}
    assert health.derive_state(base) == "active"
    assert health.derive_state({**base, "queue": {"oldest_age_seconds": 900}}) == "indexing_delayed"
    assert health.derive_state({**base, "session": {"locked": True, "idle_seconds": 0}}) == "locked"
    assert health.derive_state({**base, "paused": True, "session": {"locked": True, "idle_seconds": 0}}) == "paused"
    assert health.derive_state({**base, "permission": "denied"}) == "permission_error"


def test_submit_rejects_ai_only_and_short_evidence(settings, active):
    now = time.time()
    ai = add(settings, "変更Xの影響報告（承認待ち）です", app="com.anthropic.claudefordesktop", ts=now - 20)
    web = add(settings, "fork リポジトリに PR を送る手順", ts=now - 10)
    runner.prepare(settings, now=now, run_id="r1")
    with pytest.raises(ValueError, match="non-AI"): runner.submit(settings, "r1", "承認する", "判定する", "変更Xの影響報告", [ai["id"]], now=now)
    with pytest.raises(ValueError, match="non-AI"): runner.submit(settings, "r1", "承認する", "判定する", "変更Xの影響報告", [ai["id"], web["id"]], now=now)
    with pytest.raises(ValueError, match="at least"): runner.submit(settings, "r1", "PRを確認", "gh で見る", "PR を", [web["id"]], now=now)
    r = runner.submit(settings, "r1", "PRの状態を確認", "gh pr list を実行", "fork リポジトリに PR", [ai["id"], web["id"]], delivery="mock", now=now)
    assert r["decision"] == "deliver" and "com.google.Chrome" in r["message"]
