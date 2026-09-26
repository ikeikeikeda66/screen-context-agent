"""The frozen Windows build ignores PYTHONIOENCODING and falls back to the system
ANSI code page for stdout/stderr (see #44), corrupting any non-ASCII CLI output.
The CLI must fix its own streams to UTF-8 instead of relying on the environment."""
import io
import json

import pytest

from screen_context import cli


class RecordingStream(io.StringIO):
    def __init__(self):
        super().__init__()
        self.reconfigured = []

    def reconfigure(self, **kwargs):
        self.reconfigured.append(kwargs)


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_CONTEXT_HOME", str(tmp_path))
    monkeypatch.setenv("SCREEN_CONTEXT_PLAINTEXT", "1")
    return tmp_path


def test_main_forces_utf8_stdout_and_stderr(home, monkeypatch):
    out, err = RecordingStream(), RecordingStream()
    monkeypatch.setattr("sys.argv", ["screen-context", "status"])
    monkeypatch.setattr("sys.stdout", out)
    monkeypatch.setattr("sys.stderr", err)

    cli.main()

    assert {"encoding": "utf-8"} in out.reconfigured
    assert {"encoding": "utf-8"} in err.reconfigured
    assert json.loads(out.getvalue())["initialized"] is False
