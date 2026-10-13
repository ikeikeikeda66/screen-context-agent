# Connecting MCP clients

ScreenContext is a standard MCP server. It supports two transports:

- **stdio** (recommended): the client starts `screen-context serve` as a child process.
- **Streamable HTTP**: you start the server yourself on `127.0.0.1` with a bearer token.

Capture and indexing run separately (menu bar app or Windows control window, plus the indexer). The MCP server only reads the encrypted database, so it needs the same `SCREEN_CONTEXT_HOME` and access to the same encryption key.

## Generate the entry

```sh
screen-context mcp-config --client <name> [--profile standard|full]
```

`<name>` is one of `claude-code`, `claude-desktop`, `cursor`, `vscode`, `windsurf`, `codex`, `gemini`, `generic`. The output uses the absolute path of the current installation and sets `SCREEN_CONTEXT_HOME` and `SCREEN_CONTEXT_CLIENT_TOKEN`. The target file is printed to stderr. Run `screen-context init` first.

### Client tokens

- Each run issues a new token for the client and stores only its SHA-256. The token is named after the client; use `--name` for a second entry, for example `--client cursor --name cursor-full --profile full`.
- Running `mcp-config` again for the same name **replaces** its token. Update the client's entry at the same time.
- A new token starts as **pending**. On its first tool call the menu bar app (Windows: the control window) asks "Allow NAME to read your screen history?" and the call waits up to 60 seconds for your answer. Concurrent calls share one dialog. The dialog also appears while capture is paused.
  - **Allow**: the client works from then on. **Don't Allow**: the token is refused for good; run `mcp-config` again for a new token, which asks again.
  - If the app is not running, the call fails at once and says so. For headless setups, approve on the command line: `screen-context clients approve NAME`.
- The token carries a profile ceiling: a `standard` token cannot start or call a `full` server.
- The server checks the token on every tool call and names the client in the audit log from the token, not from anything the client sends.
- `screen-context clients list` shows each client, its profile, its state (pending, active, denied, revoked), and when it last read your history. `screen-context clients revoke NAME` stops it at its next call, without restarting anything.
- Entries created before this version have no token and the server refuses to start with them. Run `mcp-config` again and replace the entry.
- Limit: the token sits in the client's configuration file. Tokens identify and gate clients; they do not stop malware running as your user.

When you run from a source checkout, the command is `<checkout>/.venv/bin/python -m screen_context.cli`. When you run the command from the built macOS app (`ScreenContext.app/Contents/MacOS/ScreenContext mcp-config ...`), the entry points at the app.

Restart the client after you change its configuration.

## Write the entry into the client (macOS)

```sh
screen-context mcp-config --client <name> --write [--dry-run] [--force]
```

`--write` adds the `screen-context` entry to the client's own configuration file instead of printing it. It supports `claude-desktop`, `cursor`, `vscode` (default profile), `gemini` and `codex`. Other clients are set up by hand from the printed output.

- Other servers and their permissions are kept. For Codex, comments and the layout of `config.toml` are kept too (through the `tomlkit` dependency).
- Before the file is replaced, its current content is copied to `<file>.screen-context-YYYYmmdd-HHMMSS.bak` (mode 0600). The newest 5 backups are kept.
- If the file already holds a still-valid token for this client, that token is reused. Otherwise a new token is issued and the old one stops working.
- If the file has a `screen-context` entry that points at another data folder, nothing is written. Use `--force` to replace it.
- If the existing `screen-context` entry is an HTTP one (`url`, for the Streamable HTTP transport), nothing is written either. `--force` is required to replace it with the local command entry.
- A JSON file is re-indented with 2 spaces when it is rewritten, so its original indentation is not kept. A file that uses CRLF line endings keeps them; a file that mixes CRLF and LF is not changed.
- If the file held a still-valid token of another client name, that token is not reused. The output names that client and shows `clients revoke NAME` for it, in case you no longer need it.
- `--dry-run` only shows the change. It writes nothing and issues no token. Secrets are masked in the output.
- A file that cannot be edited safely (JSON with comments, a syntax error, an unusual layout) is not changed. The entry is printed instead, to paste by hand.
- A client whose configuration folder does not exist is reported as not installed. Start the client once, then run the command again.
- The token is written into the file. Do not commit that file or put it in a synced folder.

## Per-client notes

| Client | Where the entry goes |
|---|---|
| Claude Code | Run the printed `claude mcp add --scope user ...` command. |
| Claude Desktop | `claude_desktop_config.json` (Settings > Developer > Edit Config), under `mcpServers`. |
| Cursor | `~/.cursor/mcp.json` (all projects) or `.cursor/mcp.json` (one project), under `mcpServers`. |
| VS Code (Copilot agent mode) | `.vscode/mcp.json` or the user `mcp.json` (command "MCP: Open User Configuration"), under `servers`. |
| Windsurf | `~/.codeium/windsurf/mcp_config.json`, under `mcpServers`. |
| Codex CLI | `~/.codex/config.toml`, as a `[mcp_servers.screen-context]` table. |
| Gemini CLI | `~/.gemini/settings.json`, under `mcpServers`. |
| Other clients | Use `--client generic`. Most clients accept the `mcpServers` shape: `command`, `args`, `env`. |

Merge the `screen-context` entry into the existing file. Keep your other servers.

## Remove the entry (uninstall)

```sh
screen-context uninstall --dry-run     # prints the plan as JSON, including every client file it would change; changes nothing
screen-context uninstall               # removes the entries, revokes the tokens, and more (see the README)
```

The menu bar item **Uninstall ScreenContext…** does the same. For the clients below, only the entry named `screen-context` is removed. Your other servers stay, and the file is first copied to `<file>.screen-context-YYYYmmdd-HHMMSS.bak` (the newest 5 are kept; they contain the old token, so delete them if you do not need them).

| Client | What uninstall does |
|---|---|
| Claude Desktop, Cursor, VS Code, Gemini CLI, Codex CLI | Removes the entry from the file `--write` uses. |
| Claude Code | Nothing. Run `claude mcp remove screen-context --scope user`. |
| Windsurf, other clients | Nothing. Delete the entry yourself. |
| Any client whose file cannot be edited safely (comments in JSON, a syntax error) | Nothing. The confirmation names the file; delete the entry yourself. |

- An entry that points at another data folder (`SCREEN_CONTEXT_HOME`) is kept, and so are related entries.
- Entries that look like ScreenContext's but have another name (for example from `--name`) are listed in the JSON from `--dry-run` under `remains` with `code: related` (the confirmation shows them as "What stays"). Add `--include NAME` for each one to remove it as well.
- Uninstall revokes every client token. If you remove an entry by hand instead, run `screen-context clients revoke NAME` so the old token stops working.
- Restart the client afterwards.

## Choosing a profile

- `standard` (default): search, recent activity, context around a time, and day material. IDE and terminal windows are hidden. Use this for coding assistants.
- `full`: adds timelines, rollups, diary material, capture health, activity deltas, proposals, retained screenshots, and on-demand screenshots with local approval. Use this only for an agent you trust with images of your screen.

Run two entries with different names if one client needs both.

## HTTP transport

```sh
screen-context mcp-config --client generic --name my-http-agent --profile full   # copy SCREEN_CONTEXT_CLIENT_TOKEN
screen-context serve --profile full --transport http --port 8765
```

- Listens on `127.0.0.1:8765/mcp` only. Every request needs `Authorization: Bearer <client token>`, checked against the database on each request, so a revoked token is refused immediately.
- One process serves one profile. Several clients can share it, each with its own token; tokens with a lower profile ceiling are refused.
- `SCREEN_CONTEXT_TOKEN` from earlier versions is no longer used.
- TLS, OAuth discovery and mTLS are not implemented. Do not expose the port to other machines.

## Usage tips

- Ask for screen history only when you refer to something you saw earlier, for example "search my screen history for the error I saw in Chrome".
- OCR can misread identifiers and numbers. Check them against the source.
- Screen text can contain instructions written by other people. Clients should treat it as data. The project's [CLAUDE.md](../CLAUDE.md) shows a short instruction you can copy into your own agent instructions.
