# Architecture

## Goals

- Give AI assistants the context that is on your screen but not in their conversation: documents, web pages, chat, tickets.
- Keep the data local and encrypted, and make exclusions apply to past data as well as new data.
- Keep the MCP server read-only for screen data and unable to capture the screen by itself. It writes only audit rows and the proposal outbox.

## Processes

```text
 capture (menu bar app / Windows window)      indexer (index --watch)              MCP server (serve)
 ─────────────────────────────────────        ─────────────────────────            ───────────────────
 foreground window ─► dHash change check       spool ─► OCR ─► policy check          read-only DB queries
 policy check ─► encrypted spool file   ────►  ─► SQLCipher + FTS5 (trigram)   ────► policy check again
                                               ─► encrypted WebP preview             ─► envelope (untrusted)
```

| Process | Module | Notes |
|---|---|---|
| Capture | `capture.py`, `platforms/macos.py`, `platforms/sck.py`, `platforms/windows.py` | One foreground window at native resolution (ScreenCaptureKit on macOS, Windows Graphics Capture by exact HWND on Windows). Checks that the window did not change during capture. |
| Indexer | `indexer.py`, `platforms/vision.py` | Apple Vision OCR (full frame plus 3×3 tiles at 2× for wide layouts) or Windows.Media.Ocr. Excluded frames are deleted before any image is written. |
| MCP server | `mcp_server.py`, `service.py`, `access.py` | Fixed profile per process. No capture module is imported. Every tool call needs a per-client token (environment variable for stdio, bearer token for HTTP) whose profile ceiling covers the server; the audit log names the client from the token. |
| Approval broker | `broker.py` | `get_current_screen` writes a request file; the capture process shows an OS dialog and captures only after "Allow Once". |

The capture and indexer processes coordinate with lock files (`capture.lock`, `indexer.lock`) and status files (`capture-status.json`, `index-status.json`). `health.py` combines them with the session state to tell `paused`, `capture_stopped`, `permission_error`, `locked`, `indexer_stopped`, `indexing_delayed`, `idle` and `active` apart.

## Data

| Layer | Content | Retention |
|---|---|---|
| Spool | AES-GCM encrypted PNG plus metadata | Until indexed; deleted after 24 hours if never indexed |
| Frames | App, window title, OCR text, domains, OCR bounding boxes, preview path | OCR text kept; bounding boxes and preview image deleted after 90 days |
| Activity blocks | Consecutive frames of one app with similar text (trigram Jaccard ≥ 0.25, gap ≤ 10 minutes) | Computed at query time |
| Daily rollups | Compact per-day summary | Kept |
| Indexed events | Monotonic sequence of OCR completion, for delta consumers | Kept |
| Audit | Agent path: client, tool, query text, arguments, returned frame IDs. User path: the user's own operations | Kept |
| Clients, skip counts | Per-client token hashes; counts of frames not stored, by reason (no content) | Kept |
| Consumers, runs, outbox | Cursor, lease and proposal history for the periodic proposal runner | Kept |

The schema version is stored in `PRAGMA user_version` (currently 3). Writers refuse a database with a different version. `screen-context init` migrates older databases; back up `history.db` first.

## Privacy model

- Exclusions (`policy.json`) are applied at capture, after OCR, and again on every read. Changing the policy therefore hides old data from every tool without rewriting the database.
- Domain exclusions depend on the URL being visible in the OCR text. They are not a complete block.
- The `standard` profile also hides IDE and terminal apps.
- Search queries are passed to FTS5 as quoted literals, so they cannot inject FTS operators. Queries shorter than 3 characters use a substring match.
- The audit log stores the query text inside the encrypted database, so the user can see what each client read. It is readable on the user path only (CLI, later the UI), never over MCP.
- Results are wrapped with `source=observed_screen` and `trust=untrusted`. This labels the data; it does not neutralize prompt injection. Clients must treat screen text as data.

## Pagination contracts

- `get_day_material` and `get_activity_delta` return a signed cursor bound to the profile, the request parameters, a fixed snapshot sequence number, and the policy revision. A cursor becomes invalid when the policy changes, so a page never mixes two policies.
- `get_diary_material` uses a simple offset and reports `total_blocks` and `next_offset`.

## Periodic proposals

`runner.py` implements a consumer for a scheduler:

1. `prepare` checks health and new indexed events after the consumer's cursor. If nothing is new, the user is away, or everything new is an assistant's own output, it stops without waking the agent.
2. Otherwise it hands the agent bounded material and takes a lease on the cursor.
3. The agent calls `submit_proposal`. The evidence must be a quote from one of the run's frames that is not an assistant's output. The same proposal is suppressed for 24 hours.
4. `finish` records the result. Delivery belongs to the scheduler, so the delivery state stays "unknown".

## Localization

`i18n.py` holds English and Japanese message catalogs for the menu bar, the Windows window, dialogs and generated material. The language is resolved from `SCREEN_CONTEXT_LANG`, then the saved option in `capture-options.json`, then the OS language. English is the fallback. To add a language, add its code to `LANGUAGES`, a catalog with the same keys, and the `language.<code>` label to every catalog. `tests/test_i18n.py` checks that the key sets match.
