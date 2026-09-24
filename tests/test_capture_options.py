import pytest
from screen_context.config import Settings


def test_interval_persists_and_reloads(tmp_path):
    settings = Settings(tmp_path)
    assert settings.capture_interval() == 15
    settings.set_capture_interval(60)
    assert Settings(tmp_path).capture_interval() == 60
    settings.set_capture_interval(5)
    assert settings.capture_interval() == 5


@pytest.mark.parametrize("value", [True, 0, 4, 301, 2.5, "15", None])
def test_invalid_interval_does_not_replace_valid_value(tmp_path, value):
    settings = Settings(tmp_path)
    settings.set_capture_interval(30)
    with pytest.raises(ValueError): settings.set_capture_interval(value)
    assert settings.capture_interval() == 30


def test_paused_capture_never_calls_capture_backend(tmp_path, monkeypatch):
    from screen_context import capture
    settings = Settings(tmp_path)
    (tmp_path / "paused").touch()
    class Adapter:
        def capture(self, front): raise AssertionError("must not capture")
        def foreground(self): raise AssertionError("must not inspect foreground")
    monkeypatch.setattr(capture, "backend", Adapter)
    assert capture.run(settings, once=True) == {"status": "paused"}
