import csv
import io
import json
import subprocess
import sys
import time
import pytest
from test_core import settings, add, change
from screen_context import audit, export, purge, store

NOW = time.time()


@pytest.fixture
def data(settings):
    rows = {
        "chrome": add(settings, "仕様書の本文 example.com", app="com.google.Chrome", ts=NOW - 3600, title="Spec"),
        "code": add(settings, "def main(): pass", app="com.microsoft.VSCode", ts=NOW - 1800, title="main.py"),
        "old": add(settings, "last week", app="com.google.Chrome", ts=NOW - 8 * 86400, title="Old"),
        "hidden": add(settings, "private https://secret.example.org/x", app="com.google.Chrome", ts=NOW - 600, title="Private"),
    }
    change(settings, denied_domains=["secret.example.org"])
    return settings, rows


def exported(result):
    return open(result["paths"][0], encoding="utf-8").read()


@pytest.mark.parametrize("fmt", ["jsonl", "md", "csv"])
def test_formats_apply_policy_and_range(data, fmt, tmp_path):
    settings, rows = data
    result = export.write(settings, NOW - 86400, NOW, fmt, tmp_path / fmt)
    text = exported(result)
    assert result["frames"] == 2
    assert "仕様書の本文" in text and "def main()" in text          # IDEs are included by default
    assert "last week" not in text and "private" not in text     # outside the range / excluded by policy
    if fmt == "jsonl":
        records = [json.loads(line) for line in text.splitlines()]
        assert [r["frame_id"] for r in records] == [rows["chrome"]["id"], rows["code"]["id"]]
        assert all(r["trust"] == "untrusted" for r in records)
    if fmt == "csv":
        assert [r["title"] for r in csv.DictReader(io.StringIO(text))] == ["Spec", "main.py"]
    if fmt == "md":
        assert "untrusted" in text.splitlines()[0] and "## " in text


def test_exclude_ide(data, tmp_path):
    settings, _ = data
    text = exported(export.write(settings, NOW - 86400, NOW, "jsonl", tmp_path, exclude_ide=True))
    assert "def main()" not in text and "仕様書の本文" in text


def test_export_is_audited_with_frame_ids_so_purge_can_warn(data, tmp_path):
    settings, rows = data
    export.write(settings, NOW - 86400, NOW, "jsonl", tmp_path)
    entry = audit.rows(settings)[0]
    assert (entry["path"], entry["action"], entry["result_count"]) == ("user", "export", 2)
    assert set(entry["frame_ids"]) == {rows["chrome"]["id"], rows["code"]["id"]}
    warning = purge.plan(settings, [rows["chrome"]["id"]])["already_received_by"]
    assert warning == [{"path": "user", "client": "cli", "frames": 1, "last_ts": pytest.approx(time.time(), abs=60)}]


def test_viking_format_writes_daily_rollups_and_one_audit_row(data, tmp_path):
    settings, rows = data
    result = export.write(settings, NOW - 86400 * 10, NOW, "viking", tmp_path)
    assert len(result["paths"]) >= 1 and all(p.endswith(".json") for p in result["paths"])
    assert [e["action"] for e in audit.rows(settings)] == ["export"]  # no second row per day
    assert rows["old"]["id"] in audit.rows(settings)[0]["frame_ids"]


def test_refusals(data, tmp_path):
    settings, _ = data
    export.write(settings, NOW - 86400, NOW, "csv", tmp_path)
    with pytest.raises(FileExistsError): export.write(settings, NOW - 86400, NOW, "csv", tmp_path)
    with pytest.raises(ValueError): export.write(settings, NOW, NOW - 1, "csv", tmp_path)
    with pytest.raises(ValueError): export.write(settings, NOW - 1, NOW, "xml", tmp_path)
    from screen_context.config import Settings
    class Managed:
        def values(self): return {"options": {"export_allowed": False}}
    locked = Settings(settings.root, plaintext=True, managed=Managed())
    with pytest.raises(PermissionError): export.write(locked, NOW - 86400, NOW, "md", tmp_path / "x")


def test_cli_range_export_and_deprecated_date(data, tmp_path):
    settings, _ = data
    env = {"SCREEN_CONTEXT_HOME": str(settings.root), "SCREEN_CONTEXT_PLAINTEXT": "1", "PATH": "/usr/bin:/bin"}
    run = lambda *a: subprocess.run([sys.executable, "-m", "screen_context.cli", "export", *a], env=env, capture_output=True, text=True)
    today = time.strftime("%Y-%m-%d", time.localtime(NOW - 3600))
    out = run("--from", today, "--format", "md", "--out", str(tmp_path))
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout)["frames"] >= 1
    legacy = run(today)
    assert legacy.returncode == 0 and "deprecated" in legacy.stderr and json.loads(legacy.stdout)["path"].endswith(today + ".json")
    assert run().returncode != 0
