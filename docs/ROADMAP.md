# Roadmap

This roadmap records the decisions for the next expansion of ScreenContext and the order of work. Each work item is tracked as a GitHub issue.

## Why

ScreenContext is valued today mainly by people who already see the value of the parts (capture, OCR, encrypted history, MCP). The next releases aim to:

1. Make the recorded data **visible and controllable by the user** (purge, export, audit), which is the precondition for trusting a screen recorder.
2. Give a **first experience that works without an MCP client** (the Today view), so the value is clear in one look.
3. Make **installation short** enough that developers do not drop out before reaching that experience.

The tool itself stays simple: local, encrypted, no LLM inside, no telemetry.

## Decisions

| # | Topic | Decision |
|---|---|---|
| 1 | Primary audience | Developers who use MCP clients. The Today view is the entry experience for people who do not know MCP. Enterprise is not a target for now. |
| 2 | First experience | A local, read-only-by-default **Today view** (digest + search) with no LLM. Control features (purge, export, access log) live on the same screen. |
| 3 | "Where was I" | A **Resume** card in the Today view, pull only (no notifications). A work session is a span between screen lock or 15 minutes idle (configurable), across apps. |
| 4 | UI form and write authority | Localhost web UI (`screen-context ui`), separate from `serve`. **Agent path is read-only; the user path (CLI and UI) may write.** 127.0.0.1, random port, one-time token moved to a cookie, Host/Origin check, POST-only writes with confirmation. The UI shows IDE apps; `policy.json` always applies. |
| 5 | Deletion | Three mechanisms: **A. retention** (preview days, OCR text days; text default stays unlimited) with a usage report; **B. selective purge** (time range, app, keyword, block, last N minutes), physical and cascading to FTS, previews, rollups, outbox evidence and audit entries, with `secure_delete`, no undo, and a warning for already-exported or already-returned data; **C. full wipe** by key destruction plus data-folder removal. Adding an exclusion still hides by default, with an opt-in "also delete past matches". |
| 6 | Output | Two separate commands. `backup`/`restore`: encrypted archive, key wrapped with a user passphrase (scrypt + AES-GCM), restorable on another machine even after a full wipe. `export --from --to --format jsonl\|md\|csv\|viking`: plaintext, policy applied, recorded in the audit log. `export DATE`/`push DATE` are folded in. |
| 7 | Enterprise | Now: one **settings resolver** with precedence managed > user > default. Future: configuration profiles, ADMX, OS log forwarding. No management server. |
| 8 | Audit | Move to an encrypted `audit` table with query text and returned frame IDs; user path only (not exposed over MCP); records user-path writes; purgeable with selective purge (the purge record itself stays). `audit.jsonl` is migrated and removed. |
| 9 | Code signing | **No Apple Developer ID.** Use a fixed self-signed identity so Screen Recording permission survives updates (to be verified). |
| 10 | Security | Per-client tokens (identity, revocation, audit), first-connection approval through the broker, Touch ID / Windows Hello for the UI session (5 minutes idle, expires on screen lock) and for sensitive operations. Keeping the key inside the signed app is deferred (needs Developer ID). |
| 11 | Sensitive input | Drop the frame: Secure Input (macOS) / password field focus (Windows), card numbers (Luhn), My Number (check digit). Default denylist for contacts apps and checkout pages. **Combination rule on by default**: NAME + any of ADDRESS, PHONE, DOB, EMAIL within 5 OCR lines → redact those lines and store no preview. Rules live in `policy.json`; `pii-check` tests a text; skip counts (no content) are shown in the Today view. |
| 12 | Distribution | Main path: prebuilt DMG from GitHub Releases, self-signed, with **GitHub Artifact Attestations**, plus a Homebrew tap. Secondary path: `install.sh` from source. |
| 13 | Order | Phase 0 → 1 → 2 → 3. Public release after phase 3. |
| 14–15 | Windows | Each phase is done on macOS first, then followed on Windows with real-device validation before the next phase. Public release is macOS first. |
| 16 | Existing features | `diary-material` stays and shares code with the digest. OpenViking moves into `export --format viking`. The proposal runner stays as experimental and moves out of the README's main flow. |
| 17 | Success | No telemetry. Phase 2 done: the maintainer opens the Today view on 10+ working days in 2 weeks. Phase 3 done: DMG download to connected MCP client in 10 minutes or less on a fresh machine. |

A note on personal data: the combination rule is risk based. Legally, a name alone can already be personal information; the rule targets combinations whose leak causes real harm.

## Threat model changes

- Without key isolation (decision 10), **any process running as the same user can read the history** by starting `screen-context serve`, even without Screen Recording permission. Per-client tokens and approval identify and gate clients; they do not stop same-user malware. The README must say so.
- Managed settings (future) prevent accidents and policy violations, not a malicious local administrator.

## Phases

### Phase 0: spikes and baseline

- macOS: Screen Recording permission with a fixed self-signed identity across rebuilds.
- macOS: Touch ID from the app bundle; Secure Input detection.
- Windows: Windows Hello and UI Automation password-field detection.
- Windows: real-device validation of the current beta (acceptance checklist items 1–7 in [WINDOWS.md](WINDOWS.md)). Required before phase 1 on Windows; runs in parallel with the macOS spikes.

### Phase 1: trust foundation (CLI)

Settings resolver, schema v3, per-client tokens and approval, sensitive-input filters, retention, selective purge, full wipe, backup/restore, export, docs. Then the Windows follow-up.

### Phase 2: Today view

UI server and session security, digest and search, work sessions and the Resume card, control tabs, menu bar entries, two weeks of dogfooding. Then the Windows follow-up.

### Phase 3: distribution (public release, macOS first)

Indexer inside the app, first-run setup, bundled CLI, release pipeline, uninstall, README restructure, fresh-machine test. Then the Windows follow-up.

## Future

- Key isolation inside the signed app (revisit if Developer ID becomes justified, for example enterprise demand or store distribution).
- Managed settings: configuration profile schema, ADMX template, OS log forwarding of audit events.
- Optional push notification for Resume.
- Windows code signing after the beta.
