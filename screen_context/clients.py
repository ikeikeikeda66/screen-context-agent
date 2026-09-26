"""MCP client configuration snippets. ScreenContext speaks plain MCP (stdio or Streamable HTTP),
so any MCP client works; these helpers only print the entry in each client's file format."""
import json
import shlex
import sys
from pathlib import Path

# client -> where the snippet goes (shown to the user alongside the snippet)
CLIENTS = {
    "claude-code": "Run this command in a terminal",
    "claude-desktop": "claude_desktop_config.json (Settings > Developer > Edit Config)",
    "cursor": "~/.cursor/mcp.json or .cursor/mcp.json",
    "vscode": ".vscode/mcp.json or the user-level mcp.json (MCP: Open User Configuration)",
    "windsurf": "~/.codeium/windsurf/mcp_config.json",
    "codex": "~/.codex/config.toml",
    "gemini": "~/.gemini/settings.json",
    "generic": "Your client's MCP server configuration (mcpServers format)",
}


def cli_command():
    """Command that starts this installation's CLI."""
    if getattr(sys, "frozen", False):
        if sys.platform == "darwin":
            # py2app: sys.executable is Contents/MacOS/python; the app launcher runs the CLI when given arguments.
            return [str(Path(sys.executable).parent / "ScreenContext")]
        return [sys.executable]
    return [sys.executable, "-m", "screen_context.cli"]


def server_entry(command, settings, token, profile="standard"):
    """The client proves who it is with its own token (see access.py); the server names it from the token."""
    return {"command": str(command[0]), "args": [*map(str, command[1:]), "serve", "--profile", profile],
            "env": {"SCREEN_CONTEXT_HOME": str(settings.root), "SCREEN_CONTEXT_CLIENT_TOKEN": token}}


def render(client, command, settings, token, profile="standard"):
    if client not in CLIENTS: raise ValueError("Unknown client; choose one of " + ", ".join(CLIENTS))
    entry = server_entry(command, settings, token, profile)
    if client == "claude-code":
        env = [part for key, value in entry["env"].items() for part in ("--env", f"{key}={value}")]
        return shlex.join(["claude", "mcp", "add", "--scope", "user", *env, "screen-context", "--", entry["command"], *entry["args"]])
    if client == "codex":
        toml = lambda value: json.dumps(value, ensure_ascii=False)
        env = ", ".join(f"{key} = {toml(value)}" for key, value in entry["env"].items())
        return "\n".join(["[mcp_servers.screen-context]", f"command = {toml(entry['command'])}",
                          f"args = [{', '.join(toml(a) for a in entry['args'])}]", f"env = {{ {env} }}"])
    if client == "vscode":
        return json.dumps({"servers": {"screen-context": {"type": "stdio", **entry}}}, ensure_ascii=False, indent=2)
    return json.dumps({"mcpServers": {"screen-context": entry}}, ensure_ascii=False, indent=2)
