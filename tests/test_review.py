"""Dogfooding report (#32): counts only, never screen text, titles or audit queries."""
import json
import subprocess
import sys
import time
from datetime import datetime
import pytest
from test_core import settings, add
from screen_context import review, sessions, store
from screen_context.i18n import MESSAGES

NOW = time.mktime(datetime(2026, 9, 25, 18, 0).timetuple())   # a Friday, local time
DAY = 86400
SECRET = "Quarterly salary table"


def at(days_ago, hour=12): return time.mktime(datetime.fromtimestamp(NOW - days_ago * DAY).replace(hour=hour, minute=0).timetuple())


def row(settings, ts, action="ui.open", client="ui", path="user", query=None):
    with store.connect(settings) as con:
        con.execute("INSERT INTO audit (ts, path, client, action, query) VALUES (?,?,?,?,?)", (ts, path, client, action, query))


def test_days_opened_count_distinct_working_days_in_the_window(settings):
    for d in range(12): row(settings, at(d))            # Fri 25th back to Mon 14th: Sat 19th and Sun 20th are the weekend
    row(settings, at(0, hour=9))                         # twice on one day still counts once
    row(settings, at(20))                                # outside the 14-day window
    row(settings, at(13), client="cli")                  # Sat 12th, in the window: not the Today view
    row(settings, at(13), path="agent")
    view = review.report(settings, days=14, now=NOW)["today_view"]
    assert view["days_opened"] == 12 and view["working_days_opened"] == 10
    assert view["opens_per_day"]["2026-09-25"] == 2 and view["target_met"]


def test_the_target_is_ten_working_days(settings):
    weekdays = [d for d in range(14) if datetime.fromtimestamp(at(d)).weekday() < 5]
    for d in weekdays[:9]: row(settings, at(d))
    assert not review.report(settings, now=NOW)["today_view"]["target_met"]
    row(settings, at(weekdays[9]))
    view = review.report(settings, now=NOW)["today_view"]
    assert view["working_days_opened"] == 10 and view["target_met"]


def test_ui_actions_include_the_copy_button_but_never_queries(settings):
    row(settings, at(0), action="search_screen_history", query=SECRET)
    row(settings, at(0), action="diary_material", client="ui.copy")
    row(settings, at(0), action="search_screen_history", client="cursor", path="agent", query=SECRET)
    result = review.report(settings, now=NOW)
    assert result["today_view"]["actions"] == {"diary_material": 1, "search_screen_history": 1}
    assert SECRET not in json.dumps(result, ensure_ascii=False)


def test_feedback_per_threshold_in_the_window(settings):
    with store.connect(settings) as con:
        for ts, verdict, minutes in [(at(1), "helpful", 15), (at(1), "off", 15), (at(2), "off", 15), (at(3), "helpful", 20), (at(30), "off", 15)]:
            con.execute("INSERT INTO feedback (ts, verdict, session_start, session_end, idle_minutes) VALUES (?,?,0,0,?)", (ts, verdict, minutes))
    assert review.report(settings, now=NOW)["resume_card"]["feedback"] == [
        {"idle_minutes": 15, "helpful": 1, "off": 2}, {"idle_minutes": 20, "helpful": 1, "off": 0}]


def test_thresholds_are_compared_on_the_same_frames(settings):
    start = at(0, hour=9)
    for minutes in (0, 5, 10, 22, 27, 45, 50):          # gaps of 12 and 18 minutes
        add(settings, SECRET, title=SECRET, ts=start + minutes * 60)
    sessions.record(settings, "locked", start + 51 * 60)
    add(settings, SECRET, ts=start + 52 * 60)          # a lock always splits
    card = review.report(settings, now=NOW)["resume_card"]
    counts = {c["idle_minutes"]: c["sessions"] for c in card["thresholds"]}
    assert counts == {5: 8, 10: 4, 15: 3, 20: 2, 30: 2}
    assert {c["idle_minutes"]: c["median_minutes"] for c in card["thresholds"]}[20] == 25.0
    assert card["idle_minutes"] == 15


def test_sensitive_input_counts_for_the_window(settings):
    today = time.strftime("%Y-%m-%d")
    with store.connect(settings) as con:
        store.count_skip(con, today, "card_number"); store.count_skip(con, today, "card_number")
        store.count_skip(con, today, "name_address")
    assert review.report(settings, days=14)["sensitive_input"]["skipped"] == {"card_number": 2, "name_address": 1}


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_markdown_holds_counts_only(settings, lang):
    add(settings, SECRET, title=SECRET, ts=at(0))
    row(settings, at(0)); row(settings, at(0), action="search_screen_history", query=SECRET)
    text = review.markdown(review.report(settings, now=NOW), lang)
    assert SECRET not in text and "2026-09-25" in text and "| 15 ← |" in text and "pii-check" in text
    assert "search_screen_history" in text


def test_every_review_message_is_in_both_catalogs():
    keys = {k for k in MESSAGES["en"] if k.startswith("review.")}
    assert keys and keys == {k for k in MESSAGES["ja"] if k.startswith("review.")}


def test_cli(settings):
    env = {"SCREEN_CONTEXT_HOME": str(settings.root), "SCREEN_CONTEXT_PLAINTEXT": "1", "SCREEN_CONTEXT_LANG": "en", "PATH": "/usr/bin:/bin"}
    run = lambda *a: subprocess.run([sys.executable, "-m", "screen_context.cli", "review", *a], env=env, capture_output=True, text=True, encoding="utf-8")
    result = json.loads(run("--days", "7").stdout)
    assert result["days"] == 7 and result["today_view"]["days_opened"] == 0
    assert run("--format", "md").stdout.startswith("## Dogfooding report")
    assert run("--days", "0").returncode != 0
