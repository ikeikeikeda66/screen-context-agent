import asyncio
import json
import subprocess
import sys
import pytest
from test_core import settings, add
from screen_context import access, audit, store
from mcp.server.mcpserver.exceptions import ToolError
from screen_context.mcp_server import create_server


def test_only_the_hash_is_stored_and_reissue_replaces_the_token(settings):
    first = access.issue(settings, "cursor")
    with store.connect(settings, readonly=True) as con:
        stored = [tuple(r) for r in con.execute("SELECT * FROM clients")]
    assert first not in json.dumps(stored) and stored[0][1] == access.digest(first)
    second = access.issue(settings, "cursor")
    assert access.authenticate(settings, second, "standard") == "cursor"
    with pytest.raises(PermissionError, match="mcp-config"): access.authenticate(settings, first, "standard")


@pytest.mark.parametrize("token", [None, "", "sc_unknown"])
def test_missing_or_unknown_token_is_refused(settings, token):
    with pytest.raises(PermissionError, match="mcp-config"): access.authenticate(settings, token, "standard")


def test_profile_ceiling(settings):
    standard, full = access.issue(settings, "coder"), access.issue(settings, "agent", "full")
    with pytest.raises(PermissionError, match="standard"): access.authenticate(settings, standard, "full")
    assert access.authenticate(settings, full, "standard") == "agent"
    assert access.authenticate(settings, full, "openclaw") == "agent"  # legacy alias for full


def test_revoke_list_and_audit(settings):
    add(settings, "配信API仕様")
    token = access.issue(settings, "cursor")
    access.decide(settings, "cursor", True, "cli")
    authorize = lambda: access.authorize(settings, token, "standard")
    server = create_server(settings, "standard", authorize=authorize)
    asyncio.run(server.call_tool("search_screen_history", {"query": "配信API"}))
    listed = access.clients(settings)
    assert [(c["name"], c["profile"], c["state"]) for c in listed] == [("cursor", "standard", "active")] and listed[0]["last_used"]
    assert audit.rows(settings, client="cursor")[0]["query"] == "配信API"
    access.revoke(settings, "cursor")
    assert access.clients(settings)[0]["state"] == "revoked"
    with pytest.raises(ToolError, match="mcp-config"): asyncio.run(server.call_tool("search_screen_history", {"query": "配信API"}))
    with pytest.raises(ValueError): access.revoke(settings, "cursor")
    assert [r["action"] for r in audit.rows(settings, client="cli")] == ["clients.revoke", "clients.approve", "clients.issue"]


@pytest.mark.parametrize("name", ["", "a b", "x" * 65, "../etc"])
def test_client_names_are_validated(settings, name):
    with pytest.raises(ValueError): access.issue(settings, name)


def test_cli_serve_without_token_explains_the_fix_and_clients_commands(settings):
    env = {"SCREEN_CONTEXT_HOME": str(settings.root), "SCREEN_CONTEXT_PLAINTEXT": "1", "PATH": "/usr/bin:/bin"}
    cli = [sys.executable, "-m", "screen_context.cli"]
    served = subprocess.run([*cli, "serve"], env=env, capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
    assert served.returncode != 0 and "mcp-config" in served.stderr
    subprocess.run([*cli, "mcp-config", "--client", "cursor", "--name", "cursor-work"], env=env, capture_output=True, check=True)
    run = lambda *a: json.loads(subprocess.run([*cli, "clients", *a], env=env, capture_output=True, text=True, check=True).stdout)
    assert [c["name"] for c in run("list")] == ["cursor-work"]
    assert run("revoke", "cursor-work") == {"revoked": "cursor-work"}
    assert run("list")[0]["state"] == "revoked"
