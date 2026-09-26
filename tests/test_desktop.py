import json
from types import SimpleNamespace
import pytest
from screen_context.config import Settings
from screen_context.desktop import Workers, mcp_config, status_text


class Event:
    def __init__(self): self.signaled = False
    def set(self): self.signaled = True


class Process:
    def __init__(self, **kwargs):
        self.alive = False
        self.exitcode = None
    def start(self): self.alive = True
    def is_alive(self): return self.alive
    def join(self, timeout=None): pass


def test_worker_failure_stops_peer_and_prevents_double_start(tmp_path):
    workers = Workers(Settings(tmp_path), SimpleNamespace(Event=Event, Process=Process))
    workers.start()
    with pytest.raises(RuntimeError): workers.start()
    capture = workers.processes["capture"]
    capture.alive, capture.exitcode = False, 1
    assert workers.poll() == {"index": "running", "capture": "failed"}
    assert workers.stop_event.signaled
    with pytest.raises(RuntimeError): workers.start()
    index = workers.processes["index"]
    index.alive, index.exitcode = False, 0
    workers.start()
    assert not workers.stop_event.signaled


def test_partial_spawn_failure_requests_graceful_stop(tmp_path):
    count = 0
    def make_process(**kwargs):
        nonlocal count
        count += 1
        if count == 2: raise OSError("spawn failed")
        return Process(**kwargs)
    workers = Workers(Settings(tmp_path), SimpleNamespace(Event=Event, Process=make_process))
    with pytest.raises(OSError): workers.start()
    assert workers.stop_event.signaled
    assert "index" in workers.processes


def test_mcp_config_preserves_spaces_and_no_shell(tmp_path):
    data = mcp_config([r"C:\Program Files\ScreenContext\screen-context.exe"], Settings(tmp_path), "sc_example")
    server = json.loads(json.dumps(data))["mcpServers"]["screen-context"]
    assert server["command"] == r"C:\Program Files\ScreenContext\screen-context.exe"
    assert server["args"] == ["serve", "--profile", "standard"]
    assert "KEY" not in json.dumps(server) and server["env"]["SCREEN_CONTEXT_CLIENT_TOKEN"] == "sc_example"


def test_status_does_not_expose_error_payload(tmp_path):
    path = tmp_path / "status.json"
    assert status_text(path, "ja") == "処理記録なし"
    assert status_text(path) == "No results recorded"
    path.write_text(json.dumps({"ts": 1789260000, "status": "error", "error": "private content"}))
    assert "撮影エラー" in status_text(path, "ja")
    assert "Capture error" in status_text(path, "en")
    assert "private" not in status_text(path)
    path.write_text('{')
    assert status_text(path, "ja") == "処理記録なし"
