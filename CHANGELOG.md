# Changelog

## Unreleased — Today view / Today ビュー

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

日本語：ローカル Web UI、Today ビュー（ダイジェスト・検索・コピー）、「直前の作業」カード、利用状況レポート（`review`）、Touch ID / Windows Hello による再認証（Today を開く・出力・バックアップ・承認）、メニューバーアプリによる indexer の起動と「ログイン時に起動」、Windows の操作ウィンドウの「Today を開く」「最近の記録を削除」を追加しました。DB スキーマが v4 になったため、更新後に `screen-context init` を実行してください。

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
