import asyncio
import httpx
from screen_context import access, audit, store
from screen_context.config import Settings
from screen_context.mcp_server import create_server, BearerGate


def test_streamable_http_real_asgi(tmp_path):
    settings = Settings(tmp_path, plaintext=True)
    store.initialize(settings)
    from screen_context.mcp_server import gated_client
    token = access.issue(settings, "http-agent", "full")
    access.decide(settings, "http-agent", True, "cli")
    server = create_server(settings, "full", authorize=lambda: gated_client(settings))
    app = server.streamable_http_app(stateless_http=True, json_response=True)
    gate = BearerGate(app, settings, "full")

    async def check():
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gate), base_url="http://127.0.0.1:8765") as client:
                request = {"jsonrpc":"2.0", "id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"test","version":"1"}}}
                assert (await client.post("/mcp", json=request)).status_code == 401
                client.headers.update({"Authorization":"Bearer "+token, "Accept":"application/json, text/event-stream"})
                response = await client.post("/mcp", json=request)
                assert response.status_code == 200, response.text
                response = await client.post("/mcp", json={"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}})
                assert response.status_code == 200, response.text
                names = {tool["name"] for tool in response.json()["result"]["tools"]}
                assert len(names) == 13
                assert "get_diary_material" in names
                call = {"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"search_screen_history","arguments":{"query":"anything"}}}
                response = await client.post("/mcp", json=call)
                assert response.status_code == 200 and not response.json()["result"].get("isError"), response.text
    asyncio.run(check())
    # The identity verified by the gate reaches the tool call and names the client in the audit log.
    assert audit.rows(settings, client="http-agent")[0]["query"] == "anything"


def test_http_input_errors_return_the_reason(tmp_path, caplog):
    import logging
    settings = Settings(tmp_path, plaintext=True)
    store.initialize(settings)
    from screen_context.mcp_server import gated_client
    token = access.issue(settings, "http-agent", "full")
    access.decide(settings, "http-agent", True, "cli")
    server = create_server(settings, "full", authorize=lambda: gated_client(settings))
    app = server.streamable_http_app(stateless_http=True, json_response=True)
    gate = BearerGate(app, settings, "full")
    caplog.set_level(logging.INFO)
    calls = [
        ('{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"get_activity_between","arguments":{"start":1790000001.0,"end":1790000000.0}}}', "start must be before end"),
        ('{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"get_activity_between","arguments":{"start":1790000000.0,"end":1790604801.0}}}', "7 days or shorter"),
        ('{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"get_activity_between","arguments":{"start":NaN,"end":1790000000.0}}}', "between 0 and"),
    ]

    async def check():
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gate), base_url="http://127.0.0.1:8765") as client:
                request = {"jsonrpc":"2.0", "id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"test","version":"1"}}}
                client.headers.update({"Authorization":"Bearer "+token, "Accept":"application/json, text/event-stream"})
                response = await client.post("/mcp", json=request)
                assert response.status_code == 200, response.text
                for body, reason in calls:
                    response = await client.post("/mcp", content=body, headers={"Content-Type": "application/json"})
                    assert response.status_code == 200, response.text
                    result = response.json()["result"]
                    assert result["isError"] is True, response.text
                    assert reason in result["content"][0]["text"], response.text
    asyncio.run(check())
    assert not [r for r in caplog.records if "unexpected exception" in r.getMessage().lower()]
