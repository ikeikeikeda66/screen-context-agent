"""ActivityWatch companion (#72): screen-text references for a time range you give explicitly.

Pick the range yourself (for example from ActivityWatch's window history) and pass it as `--start` and
`--end`. The range is [start, end), and it is at most 7 days. This script does not connect to ActivityWatch.

1. Check the arguments. Nothing is looked up when the range is missing or invalid.
2. Make one `get_activity_between(start, end)` call over MCP. The server reads only frames inside the
   range and applies your exclusions; the call is audited like any other client's.
3. Print the timestamped references (app, title, a short snippet). Nothing is written anywhere else.

Uses only the standard library plus the `mcp` package that ScreenContext already installs, so run it
with ScreenContext's Python: `.venv/bin/python examples/activitywatch/aw_range.py --start 2026-10-04T14:00 --end 2026-10-04T15:30`.
"""
import argparse
import importlib.util
import json
import os
import re
import shlex
import sys
from datetime import datetime
from pathlib import Path

# The companion's shared helpers (MCP caller, references, Markdown) live in aw_context.py beside this file.
_spec = importlib.util.spec_from_file_location("aw_context", Path(__file__).resolve().parent / "aw_context.py")
aw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(aw)

MAX_TS = 32503680000           # the server's upper bound for a timestamp (Unix seconds)
UNIX_SECONDS = re.compile(r"\d+(\.\d+)?")


def parse_instant(name, value):
    """Unix seconds, or ISO 8601 (local time when there is no offset). HH:MM is not accepted."""
    try:
        if UNIX_SECONDS.fullmatch(value):
            # A short all-digit value such as 20261004 looks like a date in basic ISO form; refuse it.
            if value.isdigit() and len(value) < 10:
                raise SystemExit(f"--{name}: use ISO 8601 (YYYY-MM-DDTHH:MM[:SS][+HH:MM]) or Unix seconds with 10 digits, not {value!r}")
            ts = float(value)
        else:
            t = datetime.fromisoformat(value)
            ts = (t if t.tzinfo else t.astimezone()).timestamp()
    except (ValueError, OverflowError):
        raise SystemExit(f"--{name} must be Unix seconds or ISO 8601 with a date, not {value!r}")
    if not 0 <= ts <= MAX_TS: raise SystemExit(f"--{name} is outside the supported time range")
    return ts


def main(argv=None, caller=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--start", required=True, help="start of the range, inclusive: Unix seconds or ISO 8601")
    parser.add_argument("--end", required=True, help="end of the range, exclusive: Unix seconds or ISO 8601")
    parser.add_argument("--limit", type=int, default=20, help="activity blocks to return (1–50, default 20)")
    parser.add_argument("--format", choices=["json", "md"], default="md")
    parser.add_argument("--json", dest="format", action="store_const", const="json", help="same as --format json")
    parser.add_argument("--server", default=shlex.join([sys.executable, "-m", "screen_context.cli", "serve", "--profile", "standard"]),
                        help="command that starts the ScreenContext MCP server (default: this Python's screen-context serve)")
    args = parser.parse_args(argv)
    start, end = parse_instant("start", args.start), parse_instant("end", args.end)
    if not start < end: raise SystemExit("--start must be before --end")
    if end - start > aw.MAX_RANGE: raise SystemExit("the range must be 7 days or shorter")
    if not 1 <= args.limit <= 50: raise SystemExit("--limit must be between 1 and 50")
    if caller is None and not os.environ.get("SCREEN_CONTEXT_CLIENT_TOKEN"):
        raise SystemExit("set SCREEN_CONTEXT_CLIENT_TOKEN (screen-context mcp-config --client generic --name activitywatch)")

    segment = {"start": start, "end": end, "app": "", "title": ""}

    async def run():
        if caller is not None: return await aw.lookup([segment], caller, args.limit)
        async with aw.mcp_caller(shlex.split(args.server), dict(os.environ))() as call:
            return await aw.lookup([segment], call, args.limit)

    found = aw.run_lookup(run())
    print(json.dumps(found, ensure_ascii=False, indent=2) if args.format == "json" else aw.markdown(found))
    return found


if __name__ == "__main__":
    main()
