"""Windows artifact smoke test. No screen capture and no existing data access."""
import asyncio
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile


async def verify_mcp(command, env, cwd):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=command[0],
        args=[*command[1:], "serve", "--profile", "standard"], env=env, cwd=cwd)
    async with asyncio.timeout(30):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listing = await session.list_tools()
                names = {tool.name for tool in listing.tools}
                assert {"search_screen_history", "get_recent_activity", "get_context_around"} <= names
                assert not {"get_snapshot_image", "get_current_screen"} & names
                result = await session.call_tool("search_screen_history", {"query": "配布接続確認"})
                assert not result.is_error
                assert json.loads(result.content[0].text)["count"] == 0
                denied = await session.call_tool("get_snapshot_image", {"frame_id": "verification-only"})
                assert denied.is_error


def verify_command(command):
    # Exercise Unicode/space-containing data paths without using the user's home/key.
    with tempfile.TemporaryDirectory(prefix="ScreenContext 検証 verification ") as temp:
        env = dict(os.environ, SCREEN_CONTEXT_HOME=temp, SCREEN_CONTEXT_KEY=secrets.token_hex(32), PYTHONIOENCODING="utf-8")
        env.pop("SCREEN_CONTEXT_PLAINTEXT", None)
        for args in (["init"], ["status"]):
            result = subprocess.run([*command, *args], cwd=temp, env=env, capture_output=True, text=True, encoding="utf-8", timeout=30, check=True)
            assert json.loads(result.stdout)["encrypted"] is True
        assert not (Path(temp) / "history.db").read_bytes().startswith(b"SQLite format")
        asyncio.run(verify_mcp(command, env, temp))


def main():
    if sys.platform != "win32": raise SystemExit("Run verification on Windows")
    base = Path(__file__).resolve().parent.parent / "dist" / "windows"
    cli = base / "screen-context" / "screen-context.exe"
    assert (base / "ScreenContext" / "ScreenContext.exe").is_file()
    verify_command([str(cli)])
    print("Encrypted initialization and stdio MCP passed; GUI/WGC/OCR/credentials still require Windows acceptance tests.")


if __name__ == "__main__": main()
