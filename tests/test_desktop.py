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
        self.terminated = False
    def start(self): self.alive = True
    def is_alive(self): return self.alive
    def join(self, timeout=None): pass
    def terminate(self):
        self.terminated = True
        if not getattr(self, "stubborn", False): self.alive = False
    def kill(self): self.killed, self.alive = True, False


def memory_workers(tmp_path, reading, **kwargs):
    measured = []
    def measure(pid):
        measured.append(pid)
        return reading
    workers = Workers(Settings(tmp_path), SimpleNamespace(Event=Event, Process=Process), measure=measure, limit=2048, **kwargs)
    workers.start()
    return workers, measured


def test_indexer_over_memory_limit_is_restarted(tmp_path):
    workers, measured = memory_workers(tmp_path, 3000)
    first = workers.processes["index"]
    assert workers.poll() == {"index": "running", "capture": "running"}
    assert first.terminated and workers.processes["index"] is first           # told to stop; poll() does not wait for it
    assert workers.poll() == {"index": "running", "capture": "running"}
    assert workers.processes["index"] is not first and workers.processes["index"].is_alive()
    assert workers.last_restart_reason == "memory"
    assert not workers.stop_event.signaled
    assert measured == [None]                                                  # only the indexer is measured


def test_indexer_that_ignores_terminate_is_killed_before_restart(tmp_path, monkeypatch):
    import screen_context.desktop as desktop
    clock = [1000.0]
    monkeypatch.setattr(desktop.time, "monotonic", lambda: clock[0])
    workers, _ = memory_workers(tmp_path, 3000)
    first = workers.processes["index"]
    first.stubborn = True                                                      # still draining the spool after SIGTERM
    workers.poll()
    clock[0] += 5
    assert workers.poll() == {"index": "running", "capture": "running"}
    assert workers.processes["index"] is first and not getattr(first, "killed", False)
    clock[0] += 6
    workers.poll()
    assert first.killed and workers.processes["index"] is first                # killed; the restart waits for the next poll
    workers.poll()
    assert workers.processes["index"] is not first and workers.last_restart_reason == "memory"
    assert len(workers.restarts) == 1 and not workers.stopping


def test_indexer_under_memory_limit_is_left_alone(tmp_path):
    workers, _ = memory_workers(tmp_path, 1000)
    index = workers.processes["index"]
    assert workers.poll() == {"index": "running", "capture": "running"}
    assert not index.terminated and workers.processes["index"] is index and workers.last_restart_reason is None


def test_unknown_memory_reading_is_left_alone(tmp_path):
    workers, _ = memory_workers(tmp_path, None)
    index = workers.processes["index"]
    assert workers.poll() == {"index": "running", "capture": "running"}
    assert not index.terminated and workers.processes["index"] is index and workers.last_restart_reason is None


def test_memory_limit_without_restarts_left_fails_the_indexer_and_stops_peer(tmp_path):
    workers, _ = memory_workers(tmp_path, 3000, max_restarts=0)
    index = workers.processes["index"]
    assert workers.poll() == {"index": "failed", "capture": "running"}
    assert index.terminated and workers.stop_event.signaled and workers.stopping
    assert workers.last_restart_reason is None


def test_worker_failure_stops_peer_and_prevents_double_start(tmp_path):
    # Without restarts left, a dead worker stops its peer.
    workers = Workers(Settings(tmp_path), SimpleNamespace(Event=Event, Process=Process), max_restarts=0)
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


def test_secure_input_status_says_skipped_not_processed(tmp_path):
    path = tmp_path / "status.json"
    path.write_text(json.dumps({"ts": 1789260000, "status": "secure_input"}))
    en = status_text(path, "en")
    assert "Skipped (secure input)" in en and "Processed" not in en
    ja = status_text(path, "ja")
    assert "撮影を控えた（セキュア入力中）" in ja and "処理済み" not in ja
