import pytest


@pytest.fixture(autouse=True)
def english(monkeypatch):
    """Pin the OS-language fallback so tests do not depend on the host locale."""
    monkeypatch.setenv("SCREEN_CONTEXT_LANG", "en")
