import os
import sys
import pytest
from screen_context import memory


@pytest.mark.skipif(sys.platform != "darwin", reason="libproc is macOS only")
def test_footprint_of_this_process_is_a_positive_int():
    value = memory.footprint_mb(os.getpid())
    assert isinstance(value, int) and value > 0


def test_footprint_of_a_missing_process_is_none():
    pid = 2**22 + 12345
    try:
        os.kill(pid, 0)
        exists = True
    except ProcessLookupError:
        exists = False
    except PermissionError:
        exists = True
    if exists: pytest.skip("pid exists on this host")
    assert memory.footprint_mb(pid) is None


def test_footprint_without_pid_is_none():
    assert memory.footprint_mb(None) is None


def test_footprint_off_macos_is_none(monkeypatch):
    monkeypatch.setattr(memory.sys, "platform", "linux")
    assert memory.footprint_mb(os.getpid()) is None


def test_limit_defaults_to_2048_mb(monkeypatch):
    assert memory.limit_mb({}) == 2048
    monkeypatch.delenv("SCREEN_CONTEXT_INDEXER_MAX_MB", raising=False)
    assert memory.limit_mb() == 2048


def test_limit_reads_the_environment_override():
    assert memory.limit_mb({"SCREEN_CONTEXT_INDEXER_MAX_MB": "512"}) == 512


@pytest.mark.parametrize("value", ["", "abc", "1.5", "0", "-100"])
def test_invalid_or_non_positive_limit_falls_back_to_default(value):
    assert memory.limit_mb({"SCREEN_CONTEXT_INDEXER_MAX_MB": value}) == 2048
