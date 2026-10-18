"""native_ocr must run Vision and CGImage work inside one autorelease pool per call (#98)."""
import sys
from contextlib import contextmanager
from types import ModuleType, SimpleNamespace
import pytest
from PIL import Image

import screen_context.platforms as platforms
from screen_context import indexer


@pytest.fixture
def fake_mac(monkeypatch):
    state = {"pool_depth": 0, "pool_events": [], "cg_is_none": False, "calls": []}

    @contextmanager
    def autorelease_pool():
        state["pool_depth"] += 1
        state["pool_events"].append("enter")
        try:
            yield
        finally:
            state["pool_depth"] -= 1
            state["pool_events"].append("exit")

    objc = ModuleType("objc")
    objc.autorelease_pool = autorelease_pool

    quartz = ModuleType("Quartz")
    quartz.CGImageSourceCreateWithData = lambda data, options: "source"
    def create_image(source, index, options):
        state["calls"].append(("CGImageSourceCreateImageAtIndex", index))
        return None if state["cg_is_none"] else "cgimage"
    quartz.CGImageSourceCreateImageAtIndex = create_image

    foundation = ModuleType("Foundation")
    foundation.NSData = SimpleNamespace(dataWithBytes_length_=lambda data, length: data)

    vision = ModuleType("vision")
    def recognize(cg):
        state["calls"].append(("recognize", state["pool_depth"]))
        return []
    def recognize_tiled(cg, **kw):
        state["calls"].append(("recognize_tiled", state["pool_depth"]))
        return []
    vision.recognize = recognize
    vision.recognize_tiled = recognize_tiled

    monkeypatch.setitem(sys.modules, "objc", objc)
    monkeypatch.setitem(sys.modules, "Quartz", quartz)
    monkeypatch.setitem(sys.modules, "Foundation", foundation)
    monkeypatch.setitem(sys.modules, "screen_context.platforms.vision", vision)
    monkeypatch.setattr(platforms, "vision", vision, raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    return state


def test_native_ocr_wraps_whole_call_in_one_pool(fake_mac):
    assert indexer.native_ocr(Image.new("RGB", (10, 10))) == []
    assert fake_mac["pool_events"] == ["enter", "exit"]


def test_vision_calls_run_inside_pool(fake_mac):
    indexer.native_ocr(Image.new("RGB", (10, 10)))
    assert ("recognize", 1) in fake_mac["calls"]
    assert ("recognize_tiled", 1) in fake_mac["calls"]


def test_missing_cgimage_raises_and_exits_pool(fake_mac):
    fake_mac["cg_is_none"] = True
    with pytest.raises(RuntimeError, match="Image: failed to import"):
        indexer.native_ocr(Image.new("RGB", (10, 10)))
    assert fake_mac["pool_events"] == ["enter", "exit"]
    assert fake_mac["pool_depth"] == 0
