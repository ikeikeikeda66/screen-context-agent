# Changelog

## Unreleased — Today view / Today ビュー

- macOS app: `Contents/MacOS/screen-context` runs the command line (never the menu bar app; no arguments shows the help), and `mcp-config` from the app points clients at it (#35).
- macOS: memory no longer grows while the app runs. The menu bar app's own event loop, the foreground-window check, the capture and each OCR call in `index --watch` now empty their Objective-C autorelease pool; before, both processes grew by several hundred MB an hour until swap filled. As a backstop, the menu bar app restarts the indexer when its physical footprint passes `SCREEN_CONTEXT_INDEXER_MAX_MB` (default 2048), within the usual restart limit, without blocking the menu (#98).
- examples/activitywatch: `aw_range.py` takes an explicit `--start`/`--end` (ISO 8601 or Unix seconds) and looks up only that range, without connecting to ActivityWatch; `aw_context.py` refuses `--last` together with `--from`/`--to`. The README (now also in Japanese) documents units, the half-open range, the 7-day and result limits, untrusted text, and what is read and written (#72).
- Windows: capture is also skipped while the keyboard focus is in a password field (UI Automation `IsPassword`, through raw COM calls with no new dependency). A check that fails, including UI Automation being unavailable, counts as on. Not yet run on real hardware; the Phase 0 probe (a separate script) only showed that Edge exposes `IsPassword` (#16, #25).
- macOS: capture is skipped while Secure Input is on (a password field has the keyboard). The check runs before each capture and again right after it, so an image taken while a field gets focus is dropped and never spooled. In the capture loop each skipped cycle is counted as `secure_input`, shown on the Data page as a count of cycles; `get_current_screen` returns denied and is not counted. Nothing about the skipped window is kept. A check that fails counts as on, and the capture status then carries its `error_type` (#16).
- Personal-data redaction: lines elsewhere in a frame that hold a fragment of a redacted e-mail address or phone number (8+ letters and digits, or 7+ digits) are redacted too, both when indexing and with `pii-scan --apply`. The fragments are the whole address, its local part (except role names such as info, support or admin) and its domain; a domain counts only where it stands alone, not inside another address or a URL. Public mail domains are not fragments. Frames redacted by an earlier version may still hold such a fragment; `purge --keyword` removes them (#55).
- A database written by another version no longer ends in a traceback. CLI commands print one line (English or Japanese) and exit with status 1; the MCP server answers each tool call with that line over stdio, and HTTP requests with 503 and that line. `maintain` and `index` stop before deleting old spool frames. An older database says to back up and run `screen-context init`; a newer one says not to run `init` and to update. `health` reports the newer case as `needs_newer_binary`, `backup` works on either (not recorded in the access log, `"audited": false`), `init` leaves a newer database unchanged, and `restore` refuses an archive from a newer version before replacing anything (#70).
- MCP: invalid tool input returns its reason (for example `start must be before end`) instead of a generic error, and the server no longer logs a traceback for it. Other internal errors stay generic. Dates must be zero-padded `YYYY-MM-DD`; `push`, `export DATE` and `diary-material` reject other forms with a usage error (#69).
- MCP: `get_snapshot_image` spells out its four annotation hints in its decorator, as `get_current_screen` does, so static scanners see them. The values sent in `tools/list` are unchanged; a test now checks the raw `tools/list` of a real `serve --profile full` process (#77).
- Sensitive input: a table of accounts or people (a header with two of name, ID, password, phone, postal code and address columns, one of them name, ID or password, then at least two rows with values of those kinds) drops the whole frame, as card numbers do. On by default through the new `sensitive_tables` policy key, so existing `policy.json` files get it too; set it to `[]` to turn it off (#65).
- MCP: every tool declares all four annotation hints. `get_current_screen` is now marked as not read-only and not idempotent, because each approved call stores a new frame (#73).
- `push`: `VIKING_API_KEY` is sent only to the loopback OpenViking endpoint. Environment proxies are not used, redirects are not followed, and no empty key header is sent (#73).
- MCP: `get_activity_between(start, end)` returns activity blocks built only from frames inside the range (at most 7 days), in both profiles. [examples/activitywatch](examples/activitywatch) uses it to look up what ScreenContext saw during a time range from ActivityWatch; it only reads from ActivityWatch (#66).
- macOS: the menu bar app runs the indexer itself (`screen-context index --watch` as a child process, restarted after a crash) and shows its state in the menu. **Start at Login** uses the app's own login item. On first start the app offers to remove the old `local.screencontext.indexer` LaunchAgent (#34).
- `screen-context ui`: a local web UI with a one-time link, Host/Origin checks, confirmed writes, and a session that ends after 5 idle minutes or on screen lock (#26).
- Today view: digest by app and by site, pages viewed, intervals, full-text search with context and previews, date navigation, and copy for your assistant (#28).
- "Where you left off" card with work sessions and local-only feedback; `screen-context sessions` (#29).
- **Database schema v4** (presence and feedback tables): run `screen-context init` after updating. Until then, `health` reports `needs_init`.
- Control tabs in the UI: Data (storage, not-recorded counts, retention, delete, exclude), Access log, Clients (revoke). Each runs the same code as its CLI command (#30).
- `screen-context exclude --app | --domain [--delete-past]`; `usage` reports the not-recorded counts.
- macOS menu bar: "Open Today…" and "Delete Recent" (last 5 min, 15 min or hour), through the same purge path as `purge --last` (#31).
- Touch ID (or the login password) before "Open Today…" and before exporting, backing up or approving a client in the UI; the menu bar app asks, and any other answer refuses the change. On Windows, Windows Hello or the sign-in password (#27, #33).
- `screen-context review [--days N] [--format md]`: a dogfooding report with counts only — days the Today view was opened, Resume card feedback, sessions per idle threshold, sensitive-input counts (#32).
- Purge warnings no longer count your own page views in the UI as copies; the UI's copy button still counts.
- Fixed: `retention --preview none` made hourly maintenance fail; previews are now kept forever as documented.
- Windows: `health` reports a locked session.
- Windows control window: "Open Today…" (after Windows Hello or the sign-in password) and "Delete Recent" (last 5 min, 15 min or hour, the same purge path) (#33).

日本語：ローカル Web UI、Today ビュー（ダイジェスト・検索・コピー）、「直前の作業」カード、利用状況レポート（`review`）、Touch ID / Windows Hello による再認証（Today を開く・出力・バックアップ・承認）、メニューバーアプリによる indexer の起動と「ログイン時に起動」、アカウントや個人の一覧表を含む画面の破棄（`sensitive_tables`）、時間帯を限定する MCP ツール `get_activity_between` と ActivityWatch 連携の例、Windows の操作ウィンドウの「Today を開く」「最近の記録を削除」を追加しました。MCP ツールへの不正な入力には、汎用エラーではなく理由を返すようにしました。日付はゼロ埋めの `YYYY-MM-DD` だけを受け付けます。DB スキーマが v4 になったため、更新後に `screen-context init` を実行してください。別のバージョンが書いた DB では、トレースバックではなく1行の案内（古い DB はバックアップ後に init、新しい DB は更新）を表示するようにしました。個人情報の伏せ字で、同じ画面に残ったメールアドレスや電話番号の断片の行も伏せ字にするようにしました。以前の版で伏せ字にした画面に残った断片は `purge --keyword` で削除できます。macOS で Secure Input が有効な間（パスワード入力中など）は撮影しないようにしました。Windows でも、キーボードフォーカスがパスワード欄にある間は撮影を止めます（UI Automation の `IsPassword`、判定に失敗した場合も止まります。この実装は Windows 実機で未実行です。Phase 0 の探索（別スクリプト）では Edge が `IsPassword` を返すことだけを確認しています）。ActivityWatch の例に、指定した範囲（`--start`/`--end`、ISO 8601 または Unix 秒）だけを参照し ActivityWatch には接続しない `aw_range.py` を追加し、`aw_context.py` は `--last` と `--from`/`--to` の同時指定を拒否するようにしました。macOS アプリの `Contents/MacOS/screen-context` はコマンドラインを実行し（メニューバーアプリは開きません。引数なしでヘルプを表示します）、アプリから実行した `mcp-config` はこのパスを指すようにしました（#35）。

## 0.2.0 — Trust foundation / 信頼の土台

You decide which assistants may read your history, what is never recorded, and how long anything is kept. Roadmap Phase 1 ([#3](https://github.com/ikeikeikeda66/screen-context-agent/issues/3)).

### Added

- **Per-client tokens** for the MCP server (`mcp-config` issues one per client; only its SHA-256 is stored), with a profile ceiling per client, `clients list` and `clients revoke`.
- **First-connection approval**: a new client's first call asks in the menu bar app or the Windows control window, also while capture is paused; `clients approve` from the terminal.
- **Audit log** in the encrypted database: client, query text, arguments and returned frame IDs for every tool call. `audit list` and `audit export`; never served over MCP.
- **Sensitive input**: frames with card numbers (Luhn) or My Number (check digit and label) are dropped; name + address, phone, date of birth or e-mail within 5 lines is redacted; the contacts app and checkout pages are excluded by default. `pii-check FILE`, and `pii-scan [--apply]` for earlier history.
- **Data control**: `purge` with a dry run and a cascading delete; `retention` for previews, text and the audit log; `usage`; `wipe` (key first); passphrase-protected `backup` and `restore`; `export --from/--to --format jsonl|md|csv|viking`, audited so `purge` warns about copies.
- Settings resolver (managed > user > default) for administrator-locked settings.
- `packaging/macos/signing_identity.sh`: a self-signed identity that keeps the Screen Recording permission across rebuilds.
- Phase 0 probes for real hardware in `spikes/phase0/`.

### Changed

- Database schema v3. Run `screen-context init` after updating; `health` reports `needs_init` until then.
- MCP entries now carry `SCREEN_CONTEXT_CLIENT_TOKEN`. Entries from 0.1 must be created again with `mcp-config`.
- `export DATE` is deprecated; use `export --format viking`.
- `packaging/build_mac.sh` signs every nested extension module and applies `packaging/entitlements.plist` (library validation off), so a self-signed build starts under the hardened runtime.

### Fixed

- Windows: capture skips a locked session instead of crashing the capture library, and a crashed worker restarts up to 3 times in 10 minutes ([#47](https://github.com/ikeikeikeda66/screen-context-agent/issues/47)).
- Windows: approval dialogs open in front of other windows ([#50](https://github.com/ikeikeikeda66/screen-context-agent/issues/50)).
- Windows: CLI output is UTF-8 in the frozen build ([#44](https://github.com/ikeikeikeda66/screen-context-agent/issues/44)); OCR works with the current `SoftwareBitmap` bindings ([#45](https://github.com/ikeikeikeda66/screen-context-agent/issues/45)).
- `uv.lock` matches `pyproject.toml` again, so `uv sync --locked` works.

### Known limitations

- The macOS app is not notarized: build it on the Mac that runs it.
- Capture does not yet pause while macOS Secure Input is on ([#16](https://github.com/ikeikeikeda66/screen-context-agent/issues/16)).
- A truncated duplicate OCR line can escape personal-data redaction ([#55](https://github.com/ikeikeikeda66/screen-context-agent/issues/55)).
- Windows remains beta ([#25](https://github.com/ikeikeikeda66/screen-context-agent/issues/25)).

### 日本語の要約

- 追加：クライアント別トークンと初回承認、監査ログ、機微入力（カード番号・マイナンバー・氏名との組み合わせ）の除外、`purge`・`retention`・`usage`・`wipe`・`backup`/`restore`・期間指定の `export`、自己署名証明書を作るスクリプト。
- 変更：DB スキーマ v3（更新後に `init` を実行）。MCP の設定は `mcp-config` で作り直す。`export DATE` は非推奨。
- 修正：Windows の画面ロック時のクラッシュ、承認ダイアログの前面表示、文字化け、OCR。`uv.lock` の不整合。
- 既知の制限：macOS アプリは公証なし（各自の Mac でビルド）、Secure Input 中の撮影停止は未対応、OCR の重複行による伏せ字漏れ、Windows はベータ版。

## 0.1.0

First public version: foreground-window capture, OS OCR, encrypted history, read-only MCP server (macOS; Windows beta).
