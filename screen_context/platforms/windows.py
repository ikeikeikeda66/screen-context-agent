"""WGC by exact HWND and Windows.Media.Ocr. Requires Windows hardware validation."""
import asyncio
import ctypes
from ctypes import wintypes
import inspect
import threading
from PIL import Image


class Backend:
    def __init__(self):
        self.user = ctypes.windll.user32
        self.user.GetForegroundWindow.restype = wintypes.HWND
        self.user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self.user.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        self.user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.user.IsWindow.argtypes = [wintypes.HWND]
        self.user.IsWindow.restype = wintypes.BOOL

    def window_identity(self, hwnd):
        import psutil
        if not hwnd or not self.user.IsWindow(hwnd):
            raise RuntimeError("Window is unavailable")
        pid = wintypes.DWORD()
        if not self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)) or not pid.value:
            raise RuntimeError("Window process is unavailable")
        text = ctypes.create_unicode_buffer(self.user.GetWindowTextLengthW(hwnd)+1)
        self.user.GetWindowTextW(hwnd, text, len(text))
        try:
            process = psutil.Process(pid.value)
            name, started = process.name(), process.create_time()
        except psutil.Error as error:
            raise RuntimeError("Window process is unavailable") from error
        return dict(app_bundle=name, app_name=name, window_title=text.value,
                    window_id=hwnd, process_id=pid.value, process_started_at=started)

    def foreground(self):
        try:
            return self.window_identity(self.user.GetForegroundWindow())
        except (RuntimeError, OSError):
            # The shared capture loop probes foreground outside its error handler.
            # An unavailable desktop must fail capture, not kill the worker.
            return dict(app_bundle="", app_name="", window_title="", window_id=0)

    def validate_target(self, front):
        if self.window_identity(front["window_id"]) != front:
            raise RuntimeError("Window changed during capture request")

    def idle_seconds(self):
        class LastInput(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]
        value = LastInput(); value.cbSize = ctypes.sizeof(value)
        if not self.user.GetLastInputInfo(ctypes.byref(value)): raise ctypes.WinError()
        return ((ctypes.windll.kernel32.GetTickCount() - value.dwTime) & 0xffffffff)/1000

    def approve_current(self):
        # MB_YESNO | MB_DEFBUTTON2: denial is the default.
        from ..config import Settings
        from ..i18n import resolve, t
        lang = resolve(Settings.environment())
        return self.user.MessageBoxW(None, t("approve.title", lang) + "\n\n" + t("approve.body", lang), "Screen Context", 0x104) == 6

    def capture(self, front):
        from windows_capture import WindowsCapture
        self.validate_target(front)
        if "window_hwnd" not in inspect.signature(WindowsCapture).parameters:
            raise RuntimeError("Upgrade windows-capture to a version supporting exact window_hwnd capture")
        cap = WindowsCapture(cursor_capture=False, window_hwnd=front["window_id"])
        done, result, errors = threading.Event(), [], []
        @cap.event
        def on_frame_arrived(frame, capture_control):
            if done.is_set(): return
            try:
                result.append(Image.frombytes("RGBA", (frame.width, frame.height), frame.frame_buffer.copy().tobytes(), "raw", "BGRA").convert("RGB"))
            except Exception as error:
                errors.append(error)
            finally:
                done.set()
        @cap.event
        def on_closed(): done.set()
        control = cap.start_free_threaded()
        try:
            if not done.wait(15): raise TimeoutError("WGC capture timed out")
        finally:
            control.stop()
        if errors: raise RuntimeError("WGC frame conversion failed") from errors[0]
        if not result: raise RuntimeError("Window closed before capture")
        self.validate_target(front)
        return result[0], {"display_id": "foreground-window"}


def recognize(image):
    import os
    # One Windows OCR engine reads one language. Default: the user's profile languages.
    requested = os.environ.get("SCREEN_CONTEXT_OCR_LANGUAGES", "").split(",")[0].strip()

    async def perform():
        from winrt.windows.media.ocr import OcrEngine
        from winrt.windows.globalization import Language
        from winrt.windows.graphics.imaging import SoftwareBitmap, BitmapPixelFormat
        from winrt.windows.storage.streams import DataWriter
        engine = OcrEngine.try_create_from_language(Language(requested)) if requested else OcrEngine.try_create_from_user_profile_languages()
        if engine is None: raise RuntimeError("No Windows OCR engine for the requested language; install its OCR capability in Windows Settings")
        # Tile oversized native images instead of shrinking text below readable size.
        size = min(1600, OcrEngine.max_image_dimension)
        output = []
        for y in range(0, image.height, size):
            for x in range(0, image.width, size):
                tile = image.crop((max(0,x-64), max(0,y-64), min(image.width,x+size+64), min(image.height,y+size+64)))
                if max(tile.size) > OcrEngine.max_image_dimension: raise RuntimeError("OCR image size limit too small")
                writer = DataWriter()
                writer.write_bytes(tile.convert("RGBA").tobytes("raw", "BGRA"))
                bitmap = SoftwareBitmap.create_copy_from_buffer(writer.detach_buffer(), BitmapPixelFormat.BGRA8, tile.width, tile.height)
                try:
                    result = await engine.recognize_async(bitmap)
                    for line in result.lines:
                        words = list(line.words)
                        if not words: continue
                        left = min(w.bounding_rect.x for w in words)+max(0,x-64)
                        top = min(w.bounding_rect.y for w in words)+max(0,y-64)
                        right = max(w.bounding_rect.x+w.bounding_rect.width for w in words)+max(0,x-64)
                        bottom = max(w.bounding_rect.y+w.bounding_rect.height for w in words)+max(0,y-64)
                        output.append({"text": line.text, "confidence": None, "bbox": [left/image.width, 1-bottom/image.height, (right-left)/image.width, (bottom-top)/image.height]})
                finally:
                    bitmap.close(); writer.close()
        from ..indexer import merge_lines
        return merge_lines(output)
    return asyncio.run(perform())
