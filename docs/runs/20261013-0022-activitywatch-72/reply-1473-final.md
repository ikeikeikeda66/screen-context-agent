Hi! Following up on what we agreed here, the companion example and its docs are now in ScreenContext:

- Example and docs: https://github.com/ikeikeikeda66/screen-context-agent/blob/3becdb5cdcb35e03922e7287a1d6ce3610df9926/examples/activitywatch/README.md
- Japanese version: https://github.com/ikeikeikeda66/screen-context-agent/blob/3becdb5cdcb35e03922e7287a1d6ce3610df9926/examples/activitywatch/README.ja.md
- PR: https://github.com/ikeikeikeda66/screen-context-agent/pull/91

How the points we agreed on are handled:

1. **Companion first, user-started.** `aw_context.py --from … --to …` (or `--last 30m`) reads ActivityWatch's window/AFK events for the range you choose and looks up each active interval in ScreenContext. `aw_range.py --start … --end …` takes a range you already have (for example from the ActivityWatch UI) and makes one lookup. Nothing runs in the background, and ScreenContext's own exclusions apply.
2. **Only timestamps go to ScreenContext.** The range is explicit and required; a missing range is an error, never a whole-history search. It is half-open `[start, end)`, at most 7 days, in Unix seconds or ISO 8601 (no offset = local time). ScreenContext reads no frame outside it.
3. **Nothing is written back to ActivityWatch.** `aw_context.py` sends only GET requests (bucket list, then the range's events); `aw_range.py` does not contact ActivityWatch at all. The result is time-stamped references with short snippets, each marked `"untrusted": true`. Separately, ScreenContext writes one row to its own audit log per lookup so the user can see what was read; that log is not exposed to the assistant.
4. **Small reference implementation plus docs.** The README covers units and time zones, the 7-day limit, `--limit` (1–50) and `"more"`, and a walkthrough you can run in a temporary folder with synthetic data.

Acceptance checks and the tests that cover them (`tests/test_activitywatch.py`, ActivityWatch simulated):
- No OCR outside `[t0, t1)`: `test_service_range_is_half_open_at_both_edges`, `test_aw_range_takes_unix_seconds_and_keeps_the_half_open_range`, `test_aw_range_takes_iso_8601_with_offset`, `test_aw_context_range_keeps_the_half_open_range` (frames just before start, at start, just before end, at end).
- The ActivityWatch datastore is not modified: `test_read_only_fake_activitywatch_only_gets_the_range` (every request is a body-less GET within the range), `test_aw_range_never_connects_to_activitywatch`.
- No range, no lookup: `test_aw_range_refuses_bad_ranges_before_any_lookup`, `test_aw_context_rejects_last_together_with_from_and_to`.
- End to end over MCP: `test_aw_range_through_the_real_mcp_server`.

Real-machine check (aw_context.py, before this PR): macOS 15 on Apple Silicon with ActivityWatch v0.13.2 (aw-watcher-window and aw-watcher-afk). `--last 30m` returned 8 intervals; only GET requests were sent to ActivityWatch (6, confirmed through a proxy); excluding Safari in ScreenContext took the matching references from 3 to 0; and in a separate check, none of 23 records returned for a range lay outside it.

It is a reference example, not an official plugin; feedback on bucket selection or anything that would fit ActivityWatch better is welcome.
