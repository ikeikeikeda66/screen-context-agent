"""ActivityWatch companion (#66): the bounded `get_activity_between` tool and the example in
examples/activitywatch. ActivityWatch is simulated; one test runs the real MCP server over stdio."""
import asyncio
import importlib.util
import io
import json
import os
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
import pytest
from test_core import settings, add, change
from screen_context import access, audit
from screen_context.mcp_server import create_server
from screen_context.service import Service

spec = importlib.util.spec_from_file_location("aw_context", Path(__file__).parent.parent / "examples" / "activitywatch" / "aw_context.py")
aw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(aw)

T0 = 1_790_000_000.0          # an arbitrary past instant
SECRET = "outside the range"


def iso(ts): return datetime.fromtimestamp(ts, timezone.utc).isoformat().replace("+00:00", "Z")


# --- get_activity_between -----------------------------------------------------------------------

def test_only_frames_in_the_half_open_range_are_read(settings):
    add(settings, SECRET + " before", ts=T0 - 1)
    add(settings, "at the start", ts=T0)
    add(settings, "inside", ts=T0 + 30)
    add(settings, SECRET + " at the end", ts=T0 + 60)
    result = Service(settings, client="cursor").get_activity_between(T0, T0 + 60)
    text = json.dumps(result, ensure_ascii=False)
    assert "at the start" in text and "inside" in text and SECRET not in text
    assert all(T0 <= r["start_ts"] <= r["end_ts"] < T0 + 60 for r in result["records"]) and result["more"] is False


def test_exclusions_still_apply(settings):
    add(settings, "excluded password manager text", app="com.example.Vault", ts=T0 + 10)
    add(settings, "allowed text", ts=T0 + 20, app="com.apple.Safari")
    change(settings, denied_apps=["com.example.Vault"])
    text = json.dumps(Service(settings).get_activity_between(T0, T0 + 60), ensure_ascii=False)
    assert "allowed text" in text and "password manager" not in text


def test_the_call_is_audited_with_its_range(settings):
    add(settings, "inside", ts=T0 + 5)
    Service(settings, client="activitywatch").get_activity_between(T0, T0 + 60)
    [row] = [r for r in audit.rows(settings, client="activitywatch") if r["action"] == "get_activity_between"]
    assert row["path"] == "agent" and row["params"] == {"start": T0, "end": T0 + 60, "limit": 20} and row["result_count"] == 1


def test_limit_and_more(settings):
    for i in range(3): add(settings, f"block {i}", app=f"com.example.App{i}", ts=T0 + i * 10)
    result = Service(settings).get_activity_between(T0, T0 + 60, limit=2)
    assert [r["app_bundle"] for r in result["records"]] == ["com.example.App0", "com.example.App1"] and result["more"]


@pytest.mark.parametrize("start, end, limit", [(T0, T0, 10), (T0 + 1, T0, 10), (T0, T0 + 8 * 86400, 10),
                                               (T0, T0 + 60, 0), (T0, T0 + 60, 51), (-1, T0, 10), (float("nan"), T0, 10)])
def test_bad_ranges_are_refused(settings, start, end, limit):
    with pytest.raises(ValueError): Service(settings).get_activity_between(start, end, limit)


def test_the_tool_is_in_both_profiles(settings):
    for profile in ("standard", "full"):
        names = {t.name for t in asyncio.run(create_server(settings, profile).list_tools())}
        assert "get_activity_between" in names


# --- interval handling ----------------------------------------------------------------------------

def win(s, e, app, title="t"): return (T0 + s, T0 + e, {"app": app, "title": title})
def afk(s, e, status): return (T0 + s, T0 + e, {"status": status})


def test_intervals_are_clipped_to_the_range():
    segs = aw.intervals([win(-100, 50, "Code"), win(50, 400, "Chrome")], None, T0, T0 + 300)
    assert [(s["start"] - T0, s["end"] - T0, s["app"]) for s in segs] == [(0, 50, "Code"), (50, 300, "Chrome")]


def test_afk_time_is_left_out_and_same_app_neighbours_merge():
    window = [win(0, 100, "Code"), win(100, 103, "Code"), win(103, 300, "Chrome")]
    status = [afk(0, 150, "not-afk"), afk(150, 250, "afk"), afk(250, 300, "not-afk")]
    segs = aw.intervals(window, status, T0, T0 + 300)
    assert [(s["start"] - T0, s["end"] - T0, s["app"]) for s in segs] == [(0, 103, "Code"), (103, 150, "Chrome"), (250, 300, "Chrome")]


def test_app_filter_short_segments_and_the_cap():
    window = [win(0, 5, "Code"), win(5, 100, "Chrome"), win(100, 200, "code"), win(200, 260, "Code")]
    assert [s["app"] for s in aw.intervals(window, None, T0, T0 + 300, apps={"code"})] == ["code", "Code"]
    segs = aw.intervals(window, None, T0, T0 + 300, limit=2)
    assert [s["start"] - T0 for s in segs] == [5, 100]                    # the two longest, in time order


def test_references_drop_anything_outside_the_segment():
    seg = {"start": T0, "end": T0 + 60, "app": "Code", "title": "t"}
    inside = {"block_id": "a", "start_ts": T0 + 1, "end_ts": T0 + 2, "app": "Code", "text": "x " * 500}
    outside = {**inside, "block_id": "b", "start_ts": T0 + 1, "end_ts": T0 + 60}
    [ref] = aw.references(seg, {"records": [inside, outside]})
    assert ref["block_id"] == "a" and len(ref["snippet"]) <= aw.SNIPPET and ref["untrusted"] is True


# --- the whole companion, with a simulated ActivityWatch -------------------------------------------

class FakeAW:
    """ActivityWatch's REST API as far as the companion uses it; records every request."""
    def __init__(self, window, status):
        self.requests, self.window, self.status = [], window, status

    def __call__(self, request, timeout=None):
        self.requests.append((request.get_method(), request.full_url))
        url = urllib.parse.urlparse(request.full_url)
        if url.path == "/api/0/buckets/":
            body = {"aw-watcher-window_pc": {"type": "currentwindow", "hostname": "pc"},
                    "aw-watcher-afk_pc": {"type": "afkstatus", "hostname": "pc"},
                    "aw-watcher-window_other": {"type": "currentwindow", "hostname": "other"}}
        else:
            spans = self.window if "window" in url.path else self.status
            body = [{"timestamp": iso(s), "duration": e - s, "data": d} for s, e, d in spans]
        return io.BytesIO(json.dumps(body).encode())


def run_companion(settings, fake, argv, client="activitywatch"):
    asked = []
    async def call(start, end, limit):
        asked.append((start, end))
        return Service(settings, client=client).get_activity_between(start, end, limit)
    found = aw.main(["--from", iso(T0), "--to", iso(T0 + 300), "--host", "pc", "--format", "json", *argv],
                    opener=fake, caller=call)
    return found, asked


def test_companion_end_to_end(settings, capsys):
    add(settings, SECRET, ts=T0 - 30, app="com.microsoft.VSCode")
    add(settings, "editing main.py", ts=T0 + 20, app="com.microsoft.VSCode")
    add(settings, "reading the docs", ts=T0 + 120, app="com.google.Chrome")
    add(settings, "while away", ts=T0 + 200, app="com.google.Chrome")
    add(settings, "vault text", ts=T0 + 260, app="com.example.Vault")
    change(settings, denied_apps=["com.example.Vault"], ide_apps=[])
    fake = FakeAW([win(-60, 100, "Code"), win(100, 300, "Chrome")], [afk(-60, 180, "not-afk"), afk(180, 240, "afk"), afk(240, 300, "not-afk")])
    found, asked = run_companion(settings, fake, [])
    # Never asks outside [t0, t1), nor for the AFK minutes.
    assert all(T0 <= s < e <= T0 + 300 for s, e in asked)
    assert not any(s < T0 + 240 and e > T0 + 180 for s, e in asked)
    text = json.dumps(found, ensure_ascii=False)
    assert "editing main.py" in text and "reading the docs" in text
    assert SECRET not in text and "while away" not in text and "vault text" not in text
    ref = found[0]["references"][0]
    assert ref["start"].startswith("20") and ref["app"] and ref["app_bundle"] and found[0]["interval"]["app"] == "Code"
    # ActivityWatch is only read, and only this host's buckets.
    assert {m for m, _ in fake.requests} == {"GET"} and not any("_other" in u for _, u in fake.requests)
    assert json.loads(capsys.readouterr().out) == found


def test_include_afk_and_app_filter(settings):
    fake = FakeAW([win(0, 100, "Code"), win(100, 300, "Chrome")], [afk(0, 300, "afk")])
    _, asked = run_companion(settings, fake, [])
    assert asked == []                                                     # everything was AFK
    _, asked = run_companion(settings, fake, ["--include-afk", "--app", "chrome"])
    assert asked == [(T0 + 100, T0 + 300)]


def test_no_lookup_without_a_token(settings, monkeypatch):
    monkeypatch.delenv("SCREEN_CONTEXT_CLIENT_TOKEN", raising=False)
    fake = FakeAW([win(0, 100, "Code")], [])
    with pytest.raises(SystemExit, match="SCREEN_CONTEXT_CLIENT_TOKEN"):
        aw.main(["--from", iso(T0), "--to", iso(T0 + 300), "--host", "pc"], opener=fake)


@pytest.mark.parametrize("argv", [[], ["--from", "10:00"], ["--from", "11:00", "--to", "10:00"],
                                  ["--from", "2026-10-01T00:00", "--to", "2026-10-09T00:00"]])
def test_bad_ranges_stop_before_contacting_anything(argv):
    fake = FakeAW([], [])
    with pytest.raises(SystemExit): aw.main(argv, opener=fake, caller=lambda *a: pytest.fail("looked up"))
    assert fake.requests == []


def test_through_the_real_mcp_server(settings, monkeypatch):
    """The companion's own MCP path: a real `serve` process with an approved token."""
    add(settings, "editing main.py", ts=T0 + 20, app="com.google.Chrome")
    add(settings, SECRET, ts=T0 + 400, app="com.google.Chrome")
    token = access.issue(settings, "activitywatch")
    access.decide(settings, "activitywatch", True, "cli")
    env = {**os.environ, "SCREEN_CONTEXT_HOME": str(settings.root), "SCREEN_CONTEXT_PLAINTEXT": "1", "SCREEN_CONTEXT_CLIENT_TOKEN": token}
    for key, value in env.items(): monkeypatch.setenv(key, value)
    fake = FakeAW([win(0, 300, "Chrome")], [])
    found = aw.main(["--from", iso(T0), "--to", iso(T0 + 300), "--host", "pc", "--format", "json",
                     "--server", f"{sys.executable} -m screen_context.cli serve"], opener=fake)
    text = json.dumps(found, ensure_ascii=False)
    assert "editing main.py" in text and SECRET not in text
    assert any(r["action"] == "get_activity_between" for r in audit.rows(settings, client="activitywatch"))


def test_missing_afk_data_filters_nothing(settings):
    _, asked = run_companion(settings, FakeAW([win(0, 100, "Code")], []), [])
    assert asked == [(T0, T0 + 100)]
