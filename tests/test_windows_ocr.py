"""Contract test for Windows OCR against a simulated winrt; no real OCR engine is used."""
import sys
from types import SimpleNamespace

from PIL import Image


def install_fake_winrt(monkeypatch, create_copy_from_buffer):
    class BitmapPixelFormat:
        BGRA8 = "bgra8"

    class BitmapAlphaMode:
        IGNORE = "ignore"

    class SoftwareBitmap:
        @staticmethod
        def create_copy_from_buffer(*args):
            return create_copy_from_buffer(*args)

    class DataWriter:
        def __init__(self):
            self._bytes = None

        def write_bytes(self, data):
            self._bytes = data

        def detach_buffer(self):
            return SimpleNamespace(bytes=self._bytes)

        def close(self):
            pass

    class Word:
        def __init__(self, x, y, w, h):
            self.bounding_rect = SimpleNamespace(x=x, y=y, width=w, height=h)

    class Line:
        def __init__(self, text, words):
            self.text = text
            self.words = words

    class OcrResult:
        def __init__(self, lines):
            self.lines = lines

    class OcrEngine:
        max_image_dimension = 4096

        @staticmethod
        def try_create_from_user_profile_languages():
            return OcrEngine()

        @staticmethod
        def try_create_from_language(language):
            return OcrEngine()

        async def recognize_async(self, bitmap):
            return OcrResult([Line("hi", [Word(1, 1, 2, 2)])])

    class Language:
        def __init__(self, tag):
            self.tag = tag

    monkeypatch.setitem(sys.modules, "winrt", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "winrt.windows", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "winrt.windows.media", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "winrt.windows.media.ocr", SimpleNamespace(OcrEngine=OcrEngine))
    monkeypatch.setitem(sys.modules, "winrt.windows.globalization", SimpleNamespace(Language=Language))
    monkeypatch.setitem(sys.modules, "winrt.windows.graphics", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "winrt.windows.graphics.imaging", SimpleNamespace(
        SoftwareBitmap=SoftwareBitmap, BitmapPixelFormat=BitmapPixelFormat, BitmapAlphaMode=BitmapAlphaMode))
    monkeypatch.setitem(sys.modules, "winrt.windows.storage", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "winrt.windows.storage.streams", SimpleNamespace(DataWriter=DataWriter))


def test_recognize_only_uses_the_four_argument_overload(monkeypatch):
    """The winrt-Windows.Graphics.Imaging binding only exposes the 4-argument
    SoftwareBitmap.create_copy_from_buffer overload (no BitmapAlphaMode); calling it
    with 5 arguments raises TypeError: Invalid parameter count on real hardware."""
    calls = []

    def create_copy_from_buffer(*args):
        calls.append(args)
        if len(args) != 4:
            raise TypeError("Invalid parameter count")
        return SimpleNamespace(close=lambda: None)

    install_fake_winrt(monkeypatch, create_copy_from_buffer)

    from screen_context.platforms.windows import recognize
    lines = recognize(Image.new("RGB", (10, 10), "white"))

    assert calls and all(len(call) == 4 for call in calls)
    assert [line["text"] for line in lines] == ["hi"]
