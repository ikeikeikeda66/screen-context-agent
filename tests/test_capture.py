import json
from PIL import Image
from screen_context import capture, store
from screen_context.config import Settings


def test_visual_changes_still_capture_during_human_idle(tmp_path, monkeypatch):
    settings = Settings(tmp_path, plaintext=True); store.initialize(settings)
    clock = [1000.0]
    monkeypatch.setattr(capture.time, "monotonic", lambda: clock[0])
    class Stop:
        cycles = 0
        def is_set(self): return self.cycles >= 16
        def wait(self, seconds): self.cycles += 1; clock[0] += seconds
    class Adapter:
        n = 0
        def foreground(self): return dict(app_bundle="Chrome",app_name="Chrome",window_title="Docs",window_id=1)
        def idle_seconds(self): return 999
        def capture(self, front):
            image = Image.new("L", (90,80))
            image.putdata([int((x % 90)/89*255) if self.n == 0 else int((89-x%90)/89*255) for x in range(90*80)])
            self.n += 1
            return image.convert("RGB"), {"display_id":"1"}
    monkeypatch.setattr(capture, "backend", Adapter)
    capture.run(settings, stop=Stop())
    assert len(list((tmp_path/"spool").glob("*.frame"))) == 2


def test_bad_policy_fails_closed(tmp_path):
    settings = Settings(tmp_path, plaintext=True); store.initialize(settings)
    (tmp_path/"policy.json").write_text('{"denied_title_patterns":["["]}')
    import pytest
    with pytest.raises(Exception):
        capture.spool(settings, Image.new("RGB",(10,10)), dict(app_bundle="Chrome",app_name="Chrome",window_title="Docs"))
    assert not list((tmp_path/"spool").iterdir())
