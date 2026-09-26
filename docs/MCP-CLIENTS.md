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
- The token carries a profile ceiling: a `standard` token cannot start or call a `full` server.
- The server checks the token on every tool call and names the client in the audit log from the token, not from anything the client sends.
- `screen-context clients list` shows each client, its profile, whether it is active, and when it last read your history. `screen-context clients revoke NAME` stops it at its next call, without restarting anything.
- Entries created before this version have no token and the server refuses to start with them. Run `mcp-config` again and replace the entry.
- Limit: the token sits in the client's configuration file. Tokens identify and gate clients; they do not stop malware running as your user.

When you run from a source checkout, the command is `<checkout>/.venv/bin/python -m screen_context.cli`. When you run the command from the built macOS app (`ScreenContext.app/Contents/MacOS/ScreenContext mcp-config ...`), the entry points at the app.

Restart the client after you change its configuration.

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
