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
| Approval broker | `broker.py` | `get_current_screen` writes a request file; the capture process shows an OS dialog and captures only after "Allow Once". A new client token's first call writes a `.client` request; the capture process (also while paused) asks whether the client may read the history and records the answer in the database, so the MCP server itself never approves anything. |
| Local UI | `ui.py` | `screen-context ui`: a user-path web UI, separate from `serve` and free of capture imports. Listens on 127.0.0.1 at a random port. A one-time launch token (2 minutes) becomes an HttpOnly, SameSite=Strict session cookie. Every request must carry this server's Host; a write must be a same-Origin JSON POST that repeats a confirmation nonce issued for that action in that session. No CORS. A session ends after 5 minutes without a user request, and at once when the screen locks (`health.screen_locked`, macOS and Windows). The process exits when no session or launch link is left. It audits opening, closing and every write (`client = ui`). Pages (`ui_views.py`): the Today digest from `material.digest`, the same merged intervals as `diary-material`; search through `Service.search_screen_history` with the hit in context and previews via `get_snapshot_image`; all reads use the full profile (IDE apps shown), always apply the policy, and are audited on the user path. Pages carry the window title `ScreenContext Today` (`privacy.SELF_TITLE`), which `denied()` always excludes, so the UI never records itself. |
| Work sessions | `sessions.py` | The capture loop records presence transitions (`active`, `idle` after 60 s without input, `locked`, `paused`) in `presence`. A session ends where a lock or pause begins, where idle of at least `session_idle_minutes` (default 15) begins, or at a gap between frames of that length. The Resume card shows the latest session within 3 days. Card feedback goes to `feedback` in the encrypted database and is never served over MCP. Text retention also deletes old presence rows. |
| Control tabs | `ui_actions.py`, `exclusions.py` | Every UI write is a (prepare, run) pair: prepare validates the body and returns the parameters and the confirmation text (with a dry-run count), run calls the same function as the CLI (`purge.run`, `Settings.set_retention`, `exclusions.exclude`, `access.revoke`). The confirmation nonce is bound to the action and a digest of its exact parameters. Export, backup and client approval also need re-authentication (below); wipe and restore stay in the CLI because they need the capture app stopped. |
| Re-authentication | `reauth.py` | Touch ID with the login password as fallback (LocalAuthentication, `LAPolicyDeviceOwnerAuthentication`), asked only by the capture app. The menu's Open Today asks before it starts `screen-context ui`, so no launch token exists without it. For export, backup and approval, the UI redeems the confirmation nonce, then writes `requests/<id>.auth` naming a reason from a fixed list (never free text) and waits for the app's `.authreply`. Any answer other than `verified` (cancelled, failed, unavailable, no app, timeout, or anything unexpected) refuses the change and is audited as `ui.reauth`. On Windows (#33) the capture worker asks with Windows Hello (`UserConsentVerifier`); when Hello is not set up or is disabled by policy, it falls back to the sign-in password (`CredUIPromptForWindowsCredentialsW` for the current user, checked with `LogonUserW` and accepted only for the same SID; buffers are zeroed). The control window's Open Today asks in its own process. |

On Windows the capture loop checks whether the session is locked (the input desktop cannot be opened or switched to) and starts no capture then, because the capture library can crash natively when the lock screen takes over (#47). The Windows control window restarts a worker that exits abnormally, at most 3 times in 10 minutes, and records the restart in `capture-status.json`; after that it stops both workers as before.

On macOS the menu bar app runs capture on its main thread and the indexer as a child process (`screen-context index --watch` under `desktop.Workers`, restarted after a crash; `launch.py`, #34). The Windows control window runs both as worker processes. The capture and indexer processes coordinate with lock files (`capture.lock`, `indexer.lock`) and status files (`capture-status.json`, `index-status.json`). `health.py` combines them with the session state to tell `paused`, `capture_stopped`, `permission_error`, `locked`, `indexer_stopped`, `indexing_delayed`, `idle` and `active` apart.

## Data

| Layer | Content | Retention |
|---|---|---|
| Spool | AES-GCM encrypted PNG plus metadata | Until indexed; deleted after 24 hours if never indexed |
| Frames | App, window title, OCR text, domains, OCR bounding boxes, preview path | Bounding boxes and preview image: `preview_retention_days` (default 90). The whole frame: `text_retention_days` (default forever), deleted through the purge cascade |
| Activity blocks | Consecutive frames of one app with similar text (trigram Jaccard ≥ 0.25, gap ≤ 10 minutes) | Computed at query time |
| Daily rollups | Compact per-day summary | Rebuilt or removed when frames of that day are deleted |
| Indexed events | Monotonic sequence of OCR completion, for delta consumers | Kept |
| Audit | Agent path: client, tool, query text, arguments, returned frame IDs. User path: the user's own operations | `audit_retention_days` (default forever) |
| Clients, skip counts | Per-client token hashes; counts of frames not stored, by reason (no content) | Kept |
| Consumers, runs, outbox | Cursor, lease and proposal history for the periodic proposal runner | Kept |

Whole-folder operations (`lifecycle.py`) hold both worker locks, so capture and indexing cannot run meanwhile. `wipe` deletes the key before the files (crypto-erase). `backup` stores the SQLCipher backup-API snapshot, the sealed previews and the settings, plus the data key sealed with a passphrase-derived key (scrypt n=2^15, r=8, p=1; AES-GCM). `restore` checks the passphrase and the archive paths before writing anything, then runs `init` to migrate an older schema.

Retention periods are capture options (`screen-context retention`), resolved like other settings, so an administrator can set them. The hourly `maintain` applies them.

The schema version is stored in `PRAGMA user_version` (currently 3). Writers refuse a database with a different version. `screen-context init` migrates older databases; back up `history.db` first.

## Privacy model

- Two paths reach the data. The **agent path** (the MCP server) reads screen data only; it writes audit rows and proposals, needs a per-client token, and never sees the audit log. The **user path** (the CLI and the local UI, `screen-context ui`) may also write: purge, retention, `pii-scan`, export, backup, restore, wipe, client approval and revocation. Every user-path write is audited.
- Exclusions (`policy.json`) are applied at capture, after OCR, and again on every read. Changing the policy therefore hides old data from every tool without rewriting the database.
- Domain exclusions depend on the URL being visible in the OCR text. They are not a complete block.
- Hiding and deleting are separate. A policy change hides; `purge` (`purge.py`) deletes. It cascades to the FTS entry, preview, OCR-completion event, unindexed spool files, rollups, proposal evidence, and the query text and frame IDs of audit rows. It runs with `secure_delete`, then FTS `optimize` and a WAL checkpoint, so the deleted text does not stay in free pages. The purge itself is audited with a hash of the selector, never the keyword.
- `pii-scan --apply` (`rescan.py`) applies the sensitive-input rules to frames stored before them. Drops go through the purge cascade. Redactions rewrite the text and, because the FTS table has no update trigger, delete the old FTS entry and insert the new one explicitly; the preview is deleted and rollups and proposal evidence follow. A second run finds nothing.
- The `standard` profile also hides IDE and terminal apps.
- Sensitive-input detectors (`sensitive.py`: card numbers with a Luhn check, My Number with its check digit and a nearby label) run in the indexer after OCR. A match drops the frame before any image or row is written and increments `skip_counts` by reason only. Contacts apps and checkout pages are excluded like any other policy rule, at capture, after OCR and on every read.
- The personal-data combination rule (`pii.py`) runs next: when a name label and an address, phone number, date of birth or e-mail address appear within a few OCR lines, those lines are replaced with a placeholder (text and bounding box), the rest of the frame is stored, no preview image is written, and `skip_counts` records the matched rule.
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
