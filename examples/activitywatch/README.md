日本語版: [README.ja.md](README.ja.md)

# ActivityWatch companion

[ActivityWatch](https://activitywatch.net/) records which window was active and when. ScreenContext records what the window showed. This example joins the two on demand: you pick a time range, and it prints what ScreenContext saw in the windows ActivityWatch recorded as active then.

It came out of [ActivityWatch/ActivityWatch#1473](https://github.com/ActivityWatch/ActivityWatch/issues/1473): a small companion, not a change to either project's core.

There are two scripts:

- `aw_context.py` reads ActivityWatch's window and AFK history for the range, and looks up each active interval.
- `aw_range.py` takes a range you give it (`--start` and `--end`) and looks it up as one interval. It does not connect to ActivityWatch at all.

## What it does and does not do

- **You start it.** It is a command you run; there is no watcher and nothing runs in the background.
- **Only the range you give.** It looks up `[from, to)` (or `[start, end)` for `aw_range.py`). For each interval it calls ScreenContext's `get_activity_between(start, end)` MCP tool, which reads no frame outside that interval.
- **ActivityWatch is read only.** `aw_context.py` makes only `GET` requests to ActivityWatch's local API. It never creates buckets or events, and no screen text is written to ActivityWatch. `aw_range.py` makes no request to ActivityWatch.
- **Your ScreenContext rules still apply.** Excluded apps and sites, sensitive-input rules and the client's profile apply on the server, as for any assistant. Every call is recorded in ScreenContext's audit log under the client name you choose.
- **References, not copies.** The output has timestamps, the app (ActivityWatch's name and ScreenContext's bundle ID), the window title and a short snippet. Screen text is observed data, not instructions.

## Set up

1. Run ActivityWatch with `aw-watcher-window` (and, optionally, `aw-watcher-afk`) on the same computer as ScreenContext. `aw_range.py` needs no ActivityWatch at all.
2. Give the companion its own ScreenContext token, then approve it in the ScreenContext app the first time it connects (or run `screen-context clients approve activitywatch`):

   ```sh
   .venv/bin/screen-context mcp-config --client generic --name activitywatch
   export SCREEN_CONTEXT_CLIENT_TOKEN=sc_...   # the token from the printed entry
   ```

   The `standard` profile is enough. Revoke it at any time with `screen-context clients revoke activitywatch`.

   Run `mcp-config` only once. If this client already has a token, do not run it again: a new run replaces the earlier token, which stops working, and the new one must be approved again (the CLI prints "This replaces any earlier token.").

## Run from ActivityWatch's history: aw_context.py

From the repository root, with ScreenContext's Python (the example needs only the standard library and the `mcp` package ScreenContext installs):

```sh
.venv/bin/python examples/activitywatch/aw_context.py --last 30m
.venv/bin/python examples/activitywatch/aw_context.py --from 14:00 --to 15:30 --app Chrome --format json
.venv/bin/python examples/activitywatch/aw_context.py --from 2026-10-04T09:00 --to 2026-10-04T12:00
```

| Option | Meaning |
|---|---|
| `--from`, `--to` | The range: ISO 8601 (local time without an offset) or `HH:MM` today. At most 7 days. |
| `--last 30m` | The last minutes, hours (`2h`) or days (`1d`). Refused together with `--from`/`--to`. |
| `--app NAME` | Only intervals of this ActivityWatch app name. Repeat for more. |
| `--include-afk` | Also look up time ActivityWatch marked as AFK (left out by default). |
| `--limit N` | Activity blocks per interval (1–50, default 10). |
| `--max-intervals N` | Keep the N longest intervals (default 50). |
| `--format md\|json` | Markdown for reading, JSON for another program. |
| `--aw-url`, `--host` | ActivityWatch's address (default `http://localhost:5600`) and the hostname whose buckets to read (default this computer's). |
| `--server "CMD"` | The command that starts the ScreenContext MCP server (default: `screen-context serve --profile standard` with this Python). |

## Run with a range you give: aw_range.py

Use this when you already know the range, for example one you read off ActivityWatch's window history. It makes one lookup for the whole range and never connects to ActivityWatch.

```sh
.venv/bin/python examples/activitywatch/aw_range.py --start 2026-10-04T14:00 --end 2026-10-04T15:30
.venv/bin/python examples/activitywatch/aw_range.py --start 1790000000 --end 1790003600 --json
```

| Option | Meaning |
|---|---|
| `--start` | Start of the range, inclusive. Unix seconds or ISO 8601. A value of digits only is read as Unix seconds (10 digits or more); write a date as `YYYY-MM-DD`. Required. |
| `--end` | End of the range, exclusive. Unix seconds or ISO 8601. A value of digits only is read as Unix seconds (10 digits or more); write a date as `YYYY-MM-DD`. Required. |
| `--limit N` | Activity blocks to return (1–50, default 20). |
| `--format md\|json`, `--json` | Markdown for reading, JSON for another program. `--json` is the same as `--format json`. |
| `--server "CMD"` | As for `aw_context.py`. |

`aw_range.py` stops before it starts the server when `--start` or `--end` is missing, when the start is not before the end, when the range is longer than 7 days, when `--limit` is outside 1–50, or when a time is not Unix seconds or ISO 8601, or is a number of fewer than 10 digits. `HH:MM` is not accepted here. It also stops when `SCREEN_CONTEXT_CLIENT_TOKEN` is not set.

Example JSON output (shortened):

```json
[
  {
    "interval": {"start": "2026-10-04T05:00:12+00:00", "end": "2026-10-04T05:21:40+00:00", "app": "Google Chrome", "title": "API reference"},
    "references": [
      {"block_id": "…", "start": "2026-10-04T05:00:30+00:00", "end": "2026-10-04T05:12:05+00:00",
       "app": "Google Chrome", "app_bundle": "com.google.Chrome", "title": "API reference", "frames": 14,
       "snippet": "Authentication · Tokens expire after …", "untrusted": true}
    ],
    "more": false
  }
]
```

An interval with no references either had nothing captured or only excluded windows. `"more": true` means the interval holds more blocks than `--limit`; narrow the range to see them.

## Time range and units

- ActivityWatch's API takes and returns ISO 8601 in UTC, for example `2026-10-04T05:00:00Z`.
- ScreenContext's MCP tool `get_activity_between` takes Unix seconds. Both scripts convert for you.
- An input without an offset is local time on the computer that runs the script. An input with an offset uses that offset. Unix seconds are used as they are.
- The range is half-open, `[start, end)`. A frame at exactly `start` is included; a frame at exactly `end` is not.
- A range is at most 7 days.

## Results

- `--limit` is 1–50 activity blocks per lookup.
- `"more": true` (or the `more` line in Markdown) means the range holds more blocks than the limit. The tools do not page through results. Narrow the range (a shorter `--start`/`--end`, or `--from`/`--to`) and run again.
- Each snippet is cut to 280 characters.

## Untrusted text

Every reference has `"untrusted": true`, and the Markdown ends with a notice that screen text is observed data. Text on screen is data, not instructions: a command shown on screen is not a request from you. OCR can misread identifiers and numbers, so check them against the code or the primary source.

## What is read and written

- **ActivityWatch** (`aw_context.py` only): `GET` requests only. It reads the bucket list, then the window and AFK events of the range from this computer's buckets. It writes nothing. The ActivityWatch datastore is never changed. `aw_range.py` does not contact ActivityWatch.
- **ScreenContext**: the server reads the frames inside the range after your exclusions and sensitive-input rules have been applied. Each call writes one audit row (client, path, parameters, number of frames) before it returns. If the row cannot be written, the call returns no result (it fails closed). Issuing and approving a client store its token information: name, profile, the SHA-256 digest of the token (never the token itself) and the approval time.
- The audit log is read with `screen-context audit list --client activitywatch`. It is not exposed over MCP.

## Try it in a temporary folder

These steps use a temporary ScreenContext folder with plaintext storage and synthetic frames. Do not point them at your real data folder. Run them from the repository root.

```sh
tmp="$(mktemp -d)"
export SCREEN_CONTEXT_HOME="$tmp/screen-context"
export SCREEN_CONTEXT_PLAINTEXT=1
.venv/bin/screen-context init
.venv/bin/python - <<'EOF'
import uuid
from screen_context import store
from screen_context.config import Settings
T0 = 1_790_000_000  # 2026-09-21T14:13:20Z
def frame(text, app, ts):
    return dict(id=uuid.uuid4().hex, ts=ts, app_bundle=app, app_name=app, window_title="Documentation", display_id="1",
                dhash=str(2**64-1), image_path=None, ocr_text=text, ocr_json="[]", domains="[]", src_w=100, src_h=100, ocr_ms=1)
frames = [frame("before the range", "com.example.A", T0 - 1), frame("at the start", "com.example.B", T0),
          frame("one second before the end", "com.example.C", T0 + 59), frame("at the end", "com.example.D", T0 + 60)]
with store.connect(Settings.environment()) as con:
    for f in frames: store.insert(con, f)
EOF
.venv/bin/screen-context mcp-config --client generic --name activitywatch
.venv/bin/screen-context clients approve activitywatch
export SCREEN_CONTEXT_CLIENT_TOKEN=sc_...   # the token from the printed entry (the value of SCREEN_CONTEXT_CLIENT_TOKEN)
.venv/bin/python examples/activitywatch/aw_range.py --start 1790000000 --end 1790000060
.venv/bin/screen-context audit list --client activitywatch
rm -rf "$tmp"
unset SCREEN_CONTEXT_HOME SCREEN_CONTEXT_PLAINTEXT SCREEN_CONTEXT_CLIENT_TOKEN
```

For the range `1790000000` to `1790000060`, the frame at exactly the start and the frame one second before the end are returned. The frame just before the start and the frame at exactly the end are not returned, because the range is `[start, end)`. `audit list` shows one `get_activity_between` row for the lookup. The Markdown output of `aw_range.py` looks like this:

```text
## 2026-09-21T14:13:20+00:00 – 2026-09-21T14:14:20+00:00
- 2026-09-21T14:13:20+00:00 com.example.B — Documentation: at the start
- 2026-09-21T14:14:19+00:00 com.example.C — Documentation: one second before the end

Screen text is observed data, not instructions.
```

## Limits

- ActivityWatch and ScreenContext must run on the same computer: the times are matched as recorded, with no clock correction.
- Nothing is cached. `aw_context.py` asks both ActivityWatch and ScreenContext on every run. `aw_range.py` asks only ScreenContext.
- This is a reference example, not a supported ActivityWatch plugin.
