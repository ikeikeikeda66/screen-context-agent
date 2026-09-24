import json
import subprocess
import sys
import time
from datetime import datetime, timedelta
from test_core import settings, add
from screen_context.material import diary_markdown, excerpt


def test_diary_markdown_merges_and_bounds(settings):
    day = datetime(2026, 9, 13)
    for i in range(3): add(settings, "仕様書の確認\n短い\n" + "同じ行が繰り返される\n" * 5, ts=(day + timedelta(hours=10, minutes=i)).timestamp(), title="Docs")
    add(settings, "別作業 example.com", ts=(day + timedelta(hours=13)).timestamp(), title="Other", app="com.apple.finder")
    text = diary_markdown(settings, "2026-09-13", budget=900, lang="ja")
    assert text.count("\n- ") == 2 and "省略" not in text and "10:00–10:02" in text and "記録がない時間帯: 10:02–13:00" in text
    assert "仕様書の確認 / 同じ行が繰り返される" in text and "frame=" in text and "短い" not in text
    assert diary_markdown(settings, "2026-01-01", lang="ja").endswith("記録なし。")
    assert diary_markdown(settings, "2026-01-01", lang="en").endswith("No records.")
    assert excerpt("a\n" + "x" * 300, 100) == ""


def test_cli_proposal_gate_and_health(settings, monkeypatch):
    env = {"SCREEN_CONTEXT_HOME": str(settings.root), "SCREEN_CONTEXT_PLAINTEXT": "1", "PATH": "/usr/bin:/bin"}
    out = subprocess.run([sys.executable, "-m", "screen_context.cli", "proposal", "prepare"], env=env, capture_output=True, text=True, check=True).stdout
    assert json.loads(out.strip().splitlines()[-1]) == {"wakeAgent": False, "outcome": "no_new"}
    out = subprocess.run([sys.executable, "-m", "screen_context.cli", "health"], env=env, capture_output=True, text=True, check=True).stdout
    assert json.loads(out)["state"] == "capture_stopped"


def test_diary_markdown_respects_budget_with_many_intervals(settings):
    day = datetime(2026, 9, 21)
    for i in range(300):
        app = ("com.google.Chrome", "com.apple.finder", "com.anthropic.claudefordesktop")[i % 3]
        add(settings, f"区間{i}の本文テキストです example{i}.com", app=app, ts=(day + timedelta(minutes=2 * i)).timestamp(), title=f"Title {i}")
    text = diary_markdown(settings, "2026-09-21", budget=3000, lang="ja")
    assert len(text) <= 3000
    assert "文字数上限のため省略。アプリ別:" in text


def test_same_app_titles_merge(settings):
    day = datetime(2026, 9, 21, 10)
    texts = ["配信APIの仕様書を読む", "東京の天気予報を確認", "モニター台の価格を比較中", "過去問の一覧を確認"]
    for i, (title, text) in enumerate(zip(["A", "B", "C", "D"], texts)):
        add(settings, text, ts=(day + timedelta(minutes=i)).timestamp(), title=title)
    text = diary_markdown(settings, "2026-09-21", lang="ja")
    assert text.count("\n- ") == 1 and "A / B / C ほか1件" in text
