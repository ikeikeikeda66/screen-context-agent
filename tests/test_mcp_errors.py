import asyncio
import json
import logging
import os
import subprocess
import sys
import threading
import pytest
from test_core import settings, add
from mcp import Client
from mcp.server.mcpserver.exceptions import ToolError
from screen_context import access, audit
from screen_context.mcp_server import create_server

T0 = 1_790_000_000.0


@pytest.mark.parametrize("start,end,reason", [
    (T0 + 1, T0, "start must be before end"),
    (T0, T0, "start must be before end"),
    (T0, T0 + 7 * 86400 + 1, "7 days or shorter"),
    (-1, T0, "between 0 and"),
])
def test_invalid_range_returns_the_reason_without_internal_wrapping(settings, start, end, reason):
    server = create_server(settings, "standard")
    with pytest.raises(ToolError, match=reason) as info:
        asyncio.run(server.call_tool("get_activity_between", {"start": start, "end": end}))
    assert type(info.value) is ToolError


def test_in_memory_client_gets_the_reason_and_no_traceback_log(settings, caplog):
    caplog.set_level(logging.DEBUG)

    async def run():
        async with Client(create_server(settings, "standard")) as client:
            return await client.call_tool("get_activity_between", {"start": T0 + 1, "end": T0})

    result = asyncio.run(run())
    assert result.is_error
    assert "start must be before end" in result.content[0].text
    assert not [r for r in caplog.records if "unexpected exception" in r.getMessage().lower() or r.exc_info]


def test_stdio_raw_json_rpc_returns_reasons_and_no_traceback(settings):
    add(settings, "配信API仕様", ts=T0 + 20)
    token = access.issue(settings, "cursor")
    access.decide(settings, "cursor", True, "cli")
    env = {**os.environ, "SCREEN_CONTEXT_HOME": str(settings.root), "SCREEN_CONTEXT_PLAINTEXT": "1",
           "SCREEN_CONTEXT_CLIENT_TOKEN": token}
    proc = subprocess.Popen([sys.executable, "-m", "screen_context.cli", "serve"], env=env,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            encoding="utf-8")
    # The watchdog kills the server if a read below would otherwise wait forever.
    watchdog = threading.Timer(30, proc.kill)
    watchdog.start()
    try:
        def send(line):
            proc.stdin.write(line + "\n")
            proc.stdin.flush()
            return json.loads(proc.stdout.readline())

        send(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                         "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}}))
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        proc.stdin.flush()
        # Each call is read before the next is sent. Closing stdin while a call is still running cancels it.
        reversed_range = send(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                          "params": {"name": "get_activity_between", "arguments": {"start": T0 + 1, "end": T0}}}))
        same_point = send(json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                      "params": {"name": "get_activity_between", "arguments": {"start": T0, "end": T0}}}))
        # NaN is not valid JSON, so this request is written by hand to send the NaN literal.
        nan_call = send('{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"get_activity_between","arguments":{"start":NaN,"end":1790000000}}}')
        proc.stdin.close()
        err = proc.stderr.read()
        proc.wait(timeout=30)
    finally:
        watchdog.cancel()
        if proc.poll() is None: proc.kill()
    assert proc.returncode == 0, err
    for response, reason in [(reversed_range, "start must be before end"), (same_point, "start must be before end"), (nan_call, "between 0 and")]:
        assert response["result"]["isError"] is True
        assert reason in response["result"]["content"][0]["text"]
    assert "Traceback" not in err and "unexpected exception" not in err


def test_valid_call_returns_the_block_and_invalid_call_leaves_no_client_context(settings):
    from screen_context.service import CURRENT_CLIENT
    add(settings, "editing main.py", ts=T0 + 20)
    token = access.issue(settings, "cursor")
    access.decide(settings, "cursor", True, "cli")
    authorize = lambda: access.authorize(settings, token, "standard")
    server = create_server(settings, "standard", authorize=authorize)
    result = asyncio.run(server.call_tool("get_activity_between", {"start": T0, "end": T0 + 60}))
    assert not result.is_error
    data = json.loads(result.content[0].text)
    assert len(data["records"]) == 1
    assert "editing main.py" in data["records"][0]["text"]
    assert audit.rows(settings, client="cursor")[0]["action"] == "get_activity_between"
    with pytest.raises(ToolError, match="between 0 and"):
        asyncio.run(server.call_tool("get_activity_between", {"start": -1, "end": T0}))
    assert CURRENT_CLIENT.get() is None


def test_revoked_client_gets_the_reconnect_hint(settings):
    add(settings, "配信API仕様", ts=T0 + 20)
    token = access.issue(settings, "cursor")
    access.decide(settings, "cursor", True, "cli")
    server = create_server(settings, "standard", authorize=lambda: access.authorize(settings, token, "standard"))
    asyncio.run(server.call_tool("get_activity_between", {"start": T0, "end": T0 + 60}))
    access.revoke(settings, "cursor")
    with pytest.raises(ToolError, match="mcp-config") as info:
        asyncio.run(server.call_tool("get_activity_between", {"start": T0, "end": T0 + 60}))
    assert type(info.value) is ToolError


def test_full_tool_schema_does_not_change_with_authorize(settings):
    plain = create_server(settings, "full")
    guarded = create_server(settings, "full", authorize=lambda: "x")
    dump = lambda server: json.dumps([t.model_dump(mode="json", exclude_none=True) for t in asyncio.run(server.list_tools())], sort_keys=True)
    assert dump(plain) == dump(guarded)
    assert len(asyncio.run(plain.list_tools())) == 13


# Schema mismatch (#70): a database at another schema version must reach the client as a hint, never as a traceback.
MISMATCH_HINT = {3: "screen-context init", 9: "Update ScreenContext"}


def set_version(settings, version):
    import sqlite3
    con = sqlite3.connect(settings.db)
    try:
        con.execute(f"PRAGMA user_version={version}")
        con.commit()
    finally:
        con.close()


@pytest.mark.parametrize("version", [3, 9])
def test_schema_mismatch_returns_the_hint_and_leaves_no_client_context(settings, caplog, version):
    from screen_context.service import CURRENT_CLIENT
    caplog.set_level(logging.DEBUG)
    token = access.issue(settings, "cursor")
    access.decide(settings, "cursor", True, "cli")
    server = create_server(settings, "standard", authorize=lambda: access.authorize(settings, token, "standard"))
    set_version(settings, version)
    with pytest.raises(ToolError, match=MISMATCH_HINT[version]) as info:
        asyncio.run(server.call_tool("search_screen_history", {"query": "x"}))
    assert type(info.value) is ToolError
    assert CURRENT_CLIENT.get() is None
    assert not [r for r in caplog.records if r.exc_info or "unexpected exception" in r.getMessage().lower()]


def test_schema_mismatch_in_the_tool_body_returns_the_hint(settings, caplog):
    caplog.set_level(logging.DEBUG)
    set_version(settings, 9)
    server = create_server(settings, "standard", authorize=lambda: "c")
    with pytest.raises(ToolError, match="Update ScreenContext") as info:
        asyncio.run(server.call_tool("search_screen_history", {"query": "x"}))
    assert type(info.value) is ToolError
    assert not [r for r in caplog.records if r.exc_info or "unexpected exception" in r.getMessage().lower()]


def test_in_memory_client_gets_the_schema_hint_and_no_traceback_log(settings, caplog):
    caplog.set_level(logging.DEBUG)
    token = access.issue(settings, "cursor")
    access.decide(settings, "cursor", True, "cli")
    set_version(settings, 9)

    async def run():
        server = create_server(settings, "standard", authorize=lambda: access.authorize(settings, token, "standard"))
        async with Client(server) as client:
            return await client.call_tool("search_screen_history", {"query": "x"})

    result = asyncio.run(run())
    assert result.is_error
    assert "Update ScreenContext" in result.content[0].text
    assert not [r for r in caplog.records if "unexpected exception" in r.getMessage().lower() or r.exc_info]


@pytest.mark.parametrize("version", [3, 9])
def test_stdio_schema_mismatch_answers_each_call_with_the_hint(settings, version):
    token = access.issue(settings, "cursor")
    access.decide(settings, "cursor", True, "cli")
    set_version(settings, version)
    env = {**os.environ, "SCREEN_CONTEXT_HOME": str(settings.root), "SCREEN_CONTEXT_PLAINTEXT": "1",
           "SCREEN_CONTEXT_CLIENT_TOKEN": token, "SCREEN_CONTEXT_LANG": "en"}
    proc = subprocess.Popen([sys.executable, "-m", "screen_context.cli", "serve"], env=env,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            encoding="utf-8")
    # The watchdog kills the server if a read below would otherwise wait forever.
    watchdog = threading.Timer(30, proc.kill)
    watchdog.start()
    lines = []
    try:
        def send(line):
            proc.stdin.write(line + "\n")
            proc.stdin.flush()
            lines.append(proc.stdout.readline())
            return json.loads(lines[-1])

        send(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                         "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}}))
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        proc.stdin.flush()
        tools = send(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}))
        assert len(tools["result"]["tools"]) > 0
        call = send(json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                "params": {"name": "search_screen_history", "arguments": {"query": "x"}}}))
        proc.stdin.close()
        err = proc.stderr.read()
        lines += proc.stdout.read().splitlines()
        proc.wait(timeout=30)
    finally:
        watchdog.cancel()
        if proc.poll() is None: proc.kill()
    assert proc.returncode == 0, err
    assert call["result"]["isError"] is True
    assert MISMATCH_HINT[version] in call["result"]["content"][0]["text"]
    for line in lines:
        json.loads(line)
    assert "Traceback" not in err
    assert MISMATCH_HINT[version] in err
