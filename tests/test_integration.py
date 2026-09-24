import asyncio
import io
import json
import os
import sqlite3
import sys
import threading
import pytest
from PIL import Image
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from screen_context import store
from screen_context.config import Settings
from screen_context.capture import spool
from screen_context.indexer import drain
from screen_context.service import Service


def test_encrypted_pipeline(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_CONTEXT_KEY", "ab"*32)
    cfg = Settings(tmp_path)
    store.initialize(cfg)
    r = spool(cfg, Image.new("RGB", (100,100)), dict(app_bundle="Chrome",app_name="Chrome",window_title="Docs",display_id="1"))
    assert b"Docs" not in next((tmp_path/"spool").glob("*.frame")).read_bytes()
    assert drain(cfg, lambda _: [{"text":"暗号化検索検証", "bbox":[0,0,1,1]}])["indexed"] == 1
    assert Service(cfg).search_screen_history("暗号化")["count"] == 1
    assert Image.open(io.BytesIO(Service(cfg,"full").get_snapshot_image(r["id"]))).size == (100,100)
    assert not cfg.db.read_bytes().startswith(b"SQLite format")
    with sqlite3.connect(cfg.db) as con:
        with pytest.raises(sqlite3.DatabaseError): con.execute("SELECT * FROM frames").fetchall()
    monkeypatch.setenv("SCREEN_CONTEXT_KEY", "cd"*32)
    with pytest.raises(Exception): Service(cfg).search_screen_history("暗号化")


def test_stdio_real_process(tmp_path):
    cfg = Settings(tmp_path, plaintext=True); store.initialize(cfg)
    spool(cfg, Image.new("RGB", (100,100)), dict(app_bundle="Chrome",app_name="Chrome",window_title="Docs",display_id="1"))
    drain(cfg, lambda _: [{"text":"配信APIドキュメント", "bbox":[0,0,1,1]}])
    async def run():
        params = StdioServerParameters(command=sys.executable, args=["-m","screen_context.cli","serve"], env={**os.environ,"SCREEN_CONTEXT_HOME":str(tmp_path),"SCREEN_CONTEXT_PLAINTEXT":"1"})
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listing = await session.list_tools()
                assert len(listing.tools) == 4
                assert "get_day_material" in {tool.name for tool in listing.tools}
                result = await session.call_tool("search_screen_history", {"query":"配信"})
                assert not result.is_error
                data = json.loads(result.content[0].text)
                assert data["records"][0]["text"] == "配信APIドキュメント"
                material = await session.call_tool("get_day_material", {"date": "2026-09-12", "timezone": "Asia/Tokyo", "purpose": "report"})
                assert not material.is_error
                assert json.loads(material.content[0].text)["coverage"]["full_day"] is False
                denied = await session.call_tool("get_snapshot_image", {"frame_id":"x"})
                assert denied.is_error
    asyncio.run(run())


@pytest.mark.parametrize("approve", [False, True])
def test_broker_requires_approval(tmp_path, approve):
    from screen_context.broker import process_requests, request_current
    cfg = Settings(tmp_path, plaintext=True); store.initialize(cfg)
    class Adapter:
        def foreground(self): return dict(app_bundle="Chrome", app_name="Chrome", window_title="Docs")
        def approve_current(self): return approve
        def capture(self, front):
            assert approve
            return Image.new("RGB",(100,100)), {"display_id":"1"}
    stop = threading.Event()
    def worker():
        while not stop.wait(.01):
            process_requests(cfg, Adapter())
            drain(cfg, lambda _: [{"text":"public", "bbox":[0,0,1,1]}])
    thread = threading.Thread(target=worker); thread.start()
    try:
        if approve:
            image = request_current(Service(cfg,"full"), timeout=2)
            assert Image.open(io.BytesIO(image)).size == (100,100)
        else:
            with pytest.raises(PermissionError): request_current(Service(cfg,"full"), timeout=2)
    finally: stop.set(); thread.join()
    assert not list((tmp_path/"requests").iterdir())
