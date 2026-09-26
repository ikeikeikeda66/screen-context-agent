"""Settings.environment() must not evaluate Path.home() when SCREEN_CONTEXT_HOME is set.
On Windows, Path.home() needs USERPROFILE/HOMEDRIVE+HOMEPATH; a minimal subprocess
environment (as CLI integration tests use) lacks those and Path.home() raises."""
from pathlib import Path

import pytest

from screen_context.config import Settings


def test_environment_does_not_call_home_when_screen_context_home_is_set(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_CONTEXT_HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: (_ for _ in ()).throw(RuntimeError("Could not determine home directory.")))

    settings = Settings.environment()

    assert settings.root == tmp_path.resolve()


def test_environment_still_falls_back_to_home_when_unset(tmp_path, monkeypatch):
    monkeypatch.delenv("SCREEN_CONTEXT_HOME", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    settings = Settings.environment()

    assert settings.root == (tmp_path / ".screen-context").resolve()
