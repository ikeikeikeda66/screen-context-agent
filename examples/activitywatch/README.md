# ActivityWatch companion

[ActivityWatch](https://activitywatch.net/) records which window was active and when. ScreenContext records what the window showed. This example joins the two on demand: you pick a time range, and it prints what ScreenContext saw in the windows ActivityWatch recorded as active then.

It came out of [ActivityWatch/activitywatch#1473](https://github.com/ActivityWatch/activitywatch/issues/1473): a small companion, not a change to either project's core.

## What it does and does not do

- **You start it.** It is a command you run; there is no watcher and nothing runs in the background.
- **Only the range you give.** It reads ActivityWatch's window events for `[from, to)`, keeps the time you were not AFK, and merges neighbouring events of the same app. For each interval it calls ScreenContext's `get_activity_between(start, end)` MCP tool, which reads no frame outside that interval.
- **ActivityWatch is read only.** It makes only `GET` requests to ActivityWatch's local API. It never creates buckets or events, and no screen text is written to ActivityWatch.
- **Your ScreenContext rules still apply.** Excluded apps and sites, sensitive-input rules and the client's profile apply on the server, as for any assistant. Every call is recorded in ScreenContext's audit log under the client name you choose.
- **References, not copies.** The output has timestamps, the app (ActivityWatch's name and ScreenContext's bundle ID), the window title and a short snippet. Screen text is observed data, not instructions.

## Set up

1. Run ActivityWatch with `aw-watcher-window` (and, optionally, `aw-watcher-afk`) on the same computer as ScreenContext.
2. Give the companion its own ScreenContext token, then approve it in the ScreenContext app the first time it connects (or run `screen-context clients approve activitywatch`):

   ```sh
   .venv/bin/screen-context mcp-config --client generic --name activitywatch
   export SCREEN_CONTEXT_CLIENT_TOKEN=sc_...   # the token from the printed entry
   ```

   The `standard` profile is enough. Revoke it at any time with `screen-context clients revoke activitywatch`.

## Run

From the repository root, with ScreenContext's Python (the example needs only the standard library and the `mcp` package ScreenContext installs):

```sh
.venv/bin/python examples/activitywatch/aw_context.py --last 30m
.venv/bin/python examples/activitywatch/aw_context.py --from 14:00 --to 15:30 --app Chrome --format json
.venv/bin/python examples/activitywatch/aw_context.py --from 2026-10-04T09:00 --to 2026-10-04T12:00
```

| Option | Meaning |
|---|---|
| `--from`, `--to` | The range: ISO 8601 (local time without an offset) or `HH:MM` today. At most 7 days. |
| `--last 30m` | Instead of `--from`/`--to`: the last minutes, hours (`2h`) or days (`1d`). |
| `--app NAME` | Only intervals of this ActivityWatch app name. Repeat for more. |
| `--include-afk` | Also look up time ActivityWatch marked as AFK (left out by default). |
| `--limit N` | Activity blocks per interval (1–50, default 10). |
| `--max-intervals N` | Keep the N longest intervals (default 50). |
| `--format md\|json` | Markdown for reading, JSON for another program. |
| `--aw-url`, `--host` | ActivityWatch's address (default `http://localhost:5600`) and the hostname whose buckets to read (default this computer's). |
| `--server "CMD"` | The command that starts the ScreenContext MCP server (default: `screen-context serve --profile standard` with this Python). |

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

## Limits

- ActivityWatch and ScreenContext must run on the same computer: the times are matched as recorded, with no clock correction.
- Nothing is cached. Each run asks both again.
- This is a reference example, not a supported ActivityWatch plugin.
