import asyncio
import json
import sqlite3
import subprocess
import sys
import pytest
from test_core import settings, add
from screen_context import audit, store
from screen_context.config import Settings
from screen_context.mcp_server import create_server
from screen_context.service import Service


def test_v2_to_v3_imports_and_removes_legacy_log(tmp_path):
    s = Settings(tmp_path, plaintext=True); s.prepare()
    con = sqlite3.connect(s.db); con.executescript(store.SCHEMA + store.SCHEMA_V2 + "PRAGMA user_version=2;"); con.close()
    lines = [json.dumps({"ts": 1.5, "client": "cursor", "profile": "standard", "tool": "search_screen_history", "query_sha256": "ab" * 32, "count": 2}),
             json.dumps({"ts": 2.5, "client": "claude-code", "profile": "full", "tool": "get_recent_activity", "query_sha256": "cd" * 32, "count": 0}),
             '{"ts": 3.5, "client": "cut short']
    (tmp_path / "audit.jsonl").write_text("\n".join(lines), encoding="utf-8")
    assert store.initialize(s) == (2, 3)
    assert not (tmp_path / "audit.jsonl").exists()
    entries = audit.rows(s)
    assert [(e["client"], e["action"], e["result_count"], e["path"], e["query"]) for e in entries] == [
        ("claude-code", "get_recent_activity", 0, "agent", None), ("cursor", "search_screen_history", 2, "agent", None)]
    assert entries[1]["legacy_sha256"] == "ab" * 32
    with store.connect(s, readonly=True) as c:
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"audit", "clients", "skip_counts"} <= tables


def test_tool_calls_record_query_and_returned_frames(settings):
    hit, other = add(settings, "配信API仕様 example.com"), add(settings, "unrelated text")
    Service(settings, client="cursor").search_screen_history("配信API", limit=5)
    Service(settings, "full", client="agent-x").get_recent_activity()
    recent, search = audit.rows(settings)
    assert (search["client"], search["query"], search["frame_ids"], search["params"]) == ("cursor", "配信API", [hit["id"]], {"limit": 5, "since_minutes": None})
    assert recent["client"] == "agent-x" and recent["query"] is None and set(recent["frame_ids"]) == {hit["id"], other["id"]}
    assert audit.rows(settings, client="cursor") == [search]
    assert not (settings.root / "audit.jsonl").exists()


def test_audit_is_never_exposed_over_mcp(settings):
    for profile in ("standard", "full"):
        names = {tool.name for tool in asyncio.run(create_server(settings, profile).list_tools())}
        assert names and not any("audit" in name for name in names)


def test_cli_audit_list_and_export_is_itself_audited(settings):
    add(settings, "配信API仕様")
    Service(settings, client="cursor").search_screen_history("配信API")
    env = {"SCREEN_CONTEXT_HOME": str(settings.root), "SCREEN_CONTEXT_PLAINTEXT": "1", "PATH": "/usr/bin:/bin"}
    run = lambda *a: subprocess.run([sys.executable, "-m", "screen_context.cli", "audit", *a], env=env, capture_output=True, text=True, check=True).stdout
    listed = json.loads(run("list", "--client", "cursor"))
    assert [e["query"] for e in listed] == ["配信API"]
    exported = [json.loads(line) for line in run("export").splitlines()]
    assert [e["query"] for e in exported] == ["配信API"]
    assert audit.rows(settings, client="cli")[0]["action"] == "audit.export"


def test_record_rejects_unknown_path(settings):
    with pytest.raises(ValueError): audit.record(settings, "mcp", "x", "y")
