"""A database whose schema version differs from this binary stops each command that opens it,
with one message on stderr and no traceback; commands that only back up or report still run (#70).
Everything runs under tmp_path, with plaintext storage and no capture."""
import json
import os
import sqlite3
import subprocess
import sys
import time
import pytest
from screen_context import store
from screen_context.config import Settings

PASSPHRASE = "correct horse battery staple"
COMMANDS = [("clients", "list"), ("usage",), ("audit", "list"), ("sessions",), ("review",), ("maintain",), ("pii-scan",)]


def run(root, *args, lang="en"):
    env = {"SCREEN_CONTEXT_HOME": str(root), "SCREEN_CONTEXT_PLAINTEXT": "1", "PATH": "/usr/bin:/bin",
           "SCREEN_CONTEXT_LANG": lang, "SystemRoot": os.environ.get("SystemRoot", "")}
    return subprocess.run([sys.executable, "-m", "screen_context.cli", *args], env=env, capture_output=True, text=True,
                          encoding="utf-8", timeout=60, stdin=subprocess.DEVNULL)


def make(root, version):
    s = Settings(root, plaintext=True)
    store.initialize(s)
    con = sqlite3.connect(s.db); con.execute(f"PRAGMA user_version={version}"); con.commit(); con.close()
    return s


def user_version(root):
    con = sqlite3.connect(root / "history.db")
    try: return con.execute("PRAGMA user_version").fetchone()[0]
    finally: con.close()


@pytest.mark.parametrize("version", [3, 9])
@pytest.mark.parametrize("args", COMMANDS, ids=lambda a: " ".join(a))
def test_commands_that_open_the_database_refuse_a_mismatch(tmp_path, args, version):
    make(tmp_path, version)
    result = run(tmp_path, *args)
    assert result.returncode == 1 and result.stdout == ""
    assert "Traceback" not in result.stderr
    lines = result.stderr.strip().splitlines()
    assert len(lines) == 1
    assert f"v{version}" in lines[0] and f"v{store.SCHEMA_VERSION}" in lines[0]
    if version == 3:
        assert "screen-context init" in lines[0] and "Update ScreenContext" not in lines[0]
    else:
        assert "Update ScreenContext" in lines[0] and "screen-context backup" not in lines[0]


@pytest.mark.parametrize("version,needle", [(3, "古い"), (9, "更新")])
def test_japanese_message_on_a_mismatch(tmp_path, version, needle):
    make(tmp_path, version)
    result = run(tmp_path, "usage", lang="ja")
    assert result.returncode == 1 and result.stdout == "" and "Traceback" not in result.stderr
    assert needle in result.stderr


def test_init_refuses_a_newer_database_without_writing(tmp_path):
    make(tmp_path, 9)
    result = run(tmp_path, "init")
    assert result.returncode == 1 and "Traceback" not in result.stderr
    assert "Update ScreenContext" in result.stderr
    assert user_version(tmp_path) == 9


@pytest.mark.parametrize("version", [3, 9])
def test_backup_still_works_on_a_mismatched_database(tmp_path, version):
    data = tmp_path / "data"
    make(data, version)
    secret = tmp_path / "pass.txt"; secret.write_text(PASSPHRASE + "\n", encoding="utf-8")
    result = run(data, "backup", str(tmp_path / "b.zip"), "--passphrase-file", str(secret))
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("args", [("health",), ("status",), ("language",), ("retention",), ("--help",)])
def test_commands_that_do_not_need_the_schema_still_run_on_a_newer_database(tmp_path, args):
    make(tmp_path, 9)
    result = run(tmp_path, *args)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("version", [3, 9])
@pytest.mark.parametrize("command", ["index", "maintain"])
def test_mismatch_keeps_old_spool_frames(tmp_path, command, version):
    # Frames older than 24h are deleted by maintenance; a mismatched database must stop that first (#70).
    make(tmp_path, version)
    spool = tmp_path / "spool"; spool.mkdir(exist_ok=True)
    frame_id = "f" * 32
    header = {"id": frame_id, "ts": time.time(), "app_bundle": "x", "app_name": "x", "window_title": "",
              "display_id": "1", "dhash": "0", "domains": "[]"}
    frame = spool / f"{frame_id}.frame"
    frame.write_bytes(json.dumps(header).encode() + b"\n" + b"not a png")
    two_days_ago = time.time() - 2 * 86400
    os.utime(frame, (two_days_ago, two_days_ago))
    result = run(tmp_path, command)
    assert result.returncode == 1 and "Traceback" not in result.stderr
    assert list(spool.glob("*.frame")) == [frame]
