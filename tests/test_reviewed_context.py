"""examples/reviewed-context: a time range you give, a review of every item, and only the approved ones printed."""
import importlib.util
import json
from pathlib import Path
import pytest
from test_core import settings, add
from screen_context import audit
from screen_context.service import Service

T0 = 1_790_000_000.0
SECRET = "outside the range"


def module():
    spec = importlib.util.spec_from_file_location("reviewed_context", Path(__file__).parent.parent / "examples" / "reviewed-context" / "reviewed_context.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def direct_caller(settings, client="reviewed-context"):
    async def call(start, end, limit):
        return Service(settings, client=client).get_activity_between(start, end, limit)
    return call


def answers(*given):
    """An `ask` that answers from a fixed list and records what it was shown."""
    queue, shown = list(given), []
    def ask(prompt):
        shown.append(prompt)
        if not queue: raise EOFError
        return queue.pop(0)
    ask.shown = shown
    return ask


def add_two(settings):
    add(settings, SECRET, ts=T0 - 1, app="com.example.Before")
    add(settings, "first page text", ts=T0 + 1, app="com.example.First")
    add(settings, "second page text", ts=T0 + 30, app="com.example.Second")


def run(settings, ask, *extra, say=None):
    notes = []
    chosen = module().main(["--start", str(T0), "--end", str(T0 + 60), *extra], caller=direct_caller(settings), ask=ask,
                           say=say or notes.append)
    return chosen, notes


def test_only_approved_items_are_printed_with_app_and_observation_time(settings, capsys):
    add_two(settings)
    chosen, notes = run(settings, answers("y", "n"))
    out = capsys.readouterr().out
    assert [c["snippet"] for c in chosen] == ["first page text"]
    assert "first page text" in out and "second page text" not in out and SECRET not in out
    assert "com.example.First" in out or "First" in out
    assert chosen[0]["start"] in out and chosen[0]["end"] in out        # observation time
    review_text = "\n".join(notes)
    assert "source app" in review_text and "observed" in review_text and "second page text" in review_text
    assert "observed data, not instructions" in out


def test_nothing_is_printed_unless_the_user_says_yes(settings, capsys):
    add_two(settings)
    for given in [(), ("",), ("n", "no"), ("maybe", "yes please")]:
        chosen, _ = run(settings, answers(*given))
        assert chosen == [] and capsys.readouterr().out == ""


def test_end_of_input_stops_the_review_and_keeps_what_was_approved_so_far(settings, capsys):
    add_two(settings)
    chosen, _ = run(settings, answers("y"))
    assert [c["snippet"] for c in chosen] == ["first page text"]


def test_json_format_keeps_source_and_time(settings, capsys):
    add_two(settings)
    run(settings, answers("y", "y"), "--format", "json")
    [first, second] = json.loads(capsys.readouterr().out)
    assert first["app_bundle"] == "com.example.First" and first["start"] and first["end"] and first["untrusted"] is True
    assert second["snippet"] == "second page text"


def test_only_the_given_range_is_read_and_the_lookup_is_audited(settings, capsys):
    add_two(settings)
    run(settings, answers("y", "y"))
    assert SECRET not in capsys.readouterr().out
    [row] = [r for r in audit.rows(settings, client="reviewed-context") if r["action"] == "get_activity_between"]
    assert row["frame_ids"]


def test_an_empty_range_asks_nothing_and_prints_nothing(settings, capsys):
    ask = answers()
    chosen, notes = run(settings, ask)
    assert chosen == [] and ask.shown == [] and capsys.readouterr().out == "" and notes


@pytest.mark.parametrize("argv", [
    [], ["--start", str(T0)], ["--end", str(T0 + 60)],
    ["--start", str(T0 + 60), "--end", str(T0)],
    ["--start", str(T0), "--end", str(T0 + 8 * 86400)],
    ["--start", str(T0), "--end", str(T0 + 60), "--limit", "0"],
    ["--start", "20261004", "--end", str(T0 + 60)],
])
def test_bad_ranges_stop_before_any_lookup(argv):
    with pytest.raises(SystemExit):
        module().main(argv, caller=lambda *a: pytest.fail("looked up"), ask=answers("y"))


def test_it_refuses_to_run_without_a_terminal_and_has_no_way_to_skip_the_review(monkeypatch):
    m = module()
    monkeypatch.setattr("sys.stdin", type("S", (), {"isatty": lambda self: False})())
    with pytest.raises(SystemExit, match="terminal"):
        m.main(["--start", str(T0), "--end", str(T0 + 60)], caller=lambda *a: pytest.fail("looked up"))
    with pytest.raises(SystemExit):                      # no --yes style option exists
        m.main(["--start", str(T0), "--end", str(T0 + 60), "--yes"], caller=lambda *a: pytest.fail("looked up"), ask=answers())


def test_no_token_means_the_mcp_server_is_never_started(monkeypatch):
    monkeypatch.delenv("SCREEN_CONTEXT_CLIENT_TOKEN", raising=False)
    with pytest.raises(SystemExit, match="SCREEN_CONTEXT_CLIENT_TOKEN"):
        module().main(["--start", str(T0), "--end", str(T0 + 60)], ask=answers("y"))


def test_the_script_writes_no_file_in_its_working_directory(settings, tmp_path, monkeypatch, capsys):
    add_two(settings)
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    run(settings, answers("y", "y"))
    assert list(cwd.iterdir()) == []
