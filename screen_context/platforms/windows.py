"""WGC by exact HWND and Windows.Media.Ocr. Requires Windows hardware validation."""
import asyncio
import ctypes
from ctypes import wintypes
import inspect
import threading
import uuid
from PIL import Image

CLSCTX_INPROC_SERVER = 0x1
COINIT_MULTITHREADED = 0x0
S_OK, S_FALSE, RPC_E_CHANGED_MODE = 0x0, 0x1, 0x80010106
# Slot numbers in the vtable, counted from IUnknown (QueryInterface 0, AddRef 1, Release 2).
VTABLE_RELEASE = 2
VTABLE_GET_FOCUSED_ELEMENT = 8     # IUIAutomation::GetFocusedElement
VTABLE_GET_CURRENT_IS_PASSWORD = 35  # IUIAutomationElement::get_CurrentIsPassword
CLSID_CUIAUTOMATION = "ff48dba4-60ef-4201-aa87-54103eef594e"
IID_IUIAUTOMATION = "30cbe57d-d9d0-452a-ab13-7ac5ac4825ee"


class UiaError(OSError):
    """UI Automation could not answer. Capture treats an exception from the check as Secure Input on."""


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16), ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def parse(cls, text):
        value = uuid.UUID(text)
        return cls(value.time_low, value.time_mid, value.time_hi_version, (ctypes.c_ubyte * 8)(*value.bytes[8:]))


def load_ole32():
    ole32 = ctypes.WinDLL("ole32")
    ole32.CoInitializeEx.argtypes, ole32.CoInitializeEx.restype = [ctypes.c_void_p, ctypes.c_ulong], ctypes.c_long
    ole32.CoCreateInstance.argtypes = [ctypes.POINTER(_GUID), ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)]
    ole32.CoCreateInstance.restype = ctypes.c_long
    return ole32


def _method(interface, index, arguments):
    """The COM method in slot `index` of `interface`, taking `this` plus `arguments` pointer-sized arguments."""
    table = ctypes.cast(interface, ctypes.POINTER(ctypes.c_void_p))[0]
    address = ctypes.cast(table, ctypes.POINTER(ctypes.c_void_p))[index]
    return ctypes.CFUNCTYPE(ctypes.c_long, *([ctypes.c_void_p] * (1 + arguments)))(address)


def _check(result, what):
    code = result & 0xFFFFFFFF
    if code & 0x80000000: raise UiaError(f"{what} failed: HRESULT 0x{code:08X}")


class FocusPasswordProbe:
    """True while the keyboard focus is in a password field (UIA IsPassword). Use it from one thread at a time
    per thread: COM is initialised and IUIAutomation created lazily on each thread that calls it.
    Call it from long-lived threads only (the capture thread): the automation object is kept per thread and never released."""

    def __init__(self, ole32=None):
        self._ole32 = ole32
        self._local = threading.local()

    def _automation(self):
        automation = getattr(self._local, "automation", None)
        if automation: return automation
        if ctypes.sizeof(ctypes.c_void_p) != 8: raise UiaError("raw COM calls need a 64-bit process")
        if self._ole32 is None: self._ole32 = load_ole32()
        if not getattr(self._local, "com", False):
            # MTA, as UI Automation clients are advised to use. S_FALSE: already initialised here.
            # RPC_E_CHANGED_MODE: this thread is already an STA, which UI Automation also works in.
            code = self._ole32.CoInitializeEx(None, COINIT_MULTITHREADED) & 0xFFFFFFFF
            if code not in (S_OK, S_FALSE, RPC_E_CHANGED_MODE): _check(code, "CoInitializeEx")
            self._local.com = True  # never uninitialised: the thread lives as long as the capture process
        pointer = ctypes.c_void_p()
        _check(self._ole32.CoCreateInstance(ctypes.byref(_GUID.parse(CLSID_CUIAUTOMATION)), None, CLSCTX_INPROC_SERVER,
                                            ctypes.byref(_GUID.parse(IID_IUIAUTOMATION)), ctypes.pointer(pointer)), "CoCreateInstance")
        if not pointer.value: raise UiaError("CoCreateInstance returned no object")
        self._local.automation = pointer.value
        return pointer.value

    def focused_is_password(self):
        automation = self._automation()
        element = ctypes.c_void_p()
        focused = _method(automation, VTABLE_GET_FOCUSED_ELEMENT, 1)(automation, ctypes.addressof(element))
        if focused & 0x80000000 and element.value:  # a failed call can still have written an element
            _method(element.value, VTABLE_RELEASE, 0)(element.value)
        _check(focused, "GetFocusedElement")
        if not element.value: return False  # nothing has the focus
        flag = ctypes.c_int32()
        try:
            _check(_method(element.value, VTABLE_GET_CURRENT_IS_PASSWORD, 1)(element.value, ctypes.addressof(flag)), "get_CurrentIsPassword")
        finally:
            _method(element.value, VTABLE_RELEASE, 0)(element.value)
        return bool(flag.value)


class Backend:
    def __init__(self):
        self.user = ctypes.windll.user32
        self.kernel = ctypes.windll.kernel32
        self.user.GetForegroundWindow.restype = wintypes.HWND
        self.user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self.user.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
        self.user.AttachThreadInput.restype = wintypes.BOOL
        self.kernel.GetCurrentThreadId.restype = wintypes.DWORD
        self.user.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        self.user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.user.IsWindow.argtypes = [wintypes.HWND]
        self.user.IsWindow.restype = wintypes.BOOL
        self.user.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.user.OpenInputDesktop.restype = wintypes.HANDLE
        self.user.SwitchDesktop.argtypes = [wintypes.HANDLE]
        self.user.CloseDesktop.argtypes = [wintypes.HANDLE]

    def session_locked(self):
        """True while the lock screen (or another secure desktop) has the input. Windows Graphics
        Capture must not be started then: on real hardware the capture library crashes the whole
        process with an access violation that no Python handler can catch (#47)."""
        desktop = self.user.OpenInputDesktop(0, False, 0x0100)  # DESKTOP_SWITCHDESKTOP
        if not desktop: return True  # the input desktop is not ours: locked or secure
        try: switched = self.user.SwitchDesktop(desktop)
        finally: self.user.CloseDesktop(desktop)
        if not switched: return True
        # The Windows 10/11 lock screen is LockApp.exe on the user's own desktop, where the check
        # above passes (#60), so look at what has the foreground too.
        from screen_context.health import foreground_is_lock_screen
        try: return foreground_is_lock_screen(self.user)
        except OSError: return False

    def secure_input(self):
        """True while the keyboard focus is in a password field (#16), asked of UI Automation. Raises when the
        answer cannot be had; capture then skips the frame. The probe is created on first use, on the calling thread."""
        probe = getattr(self, "_password_probe", None)
        if probe is None: probe = self._password_probe = FocusPasswordProbe()
        return probe.focused_is_password()

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

    # MB_YESNO | MB_DEFBUTTON2 (denial is the default) | MB_SETFOREGROUND | MB_TOPMOST. The dialogs come
    # from a capture worker process that owns no window, so without the last two they can open behind
    # other windows and only flash in the taskbar while the caller waits.
    DIALOG = 0x4 | 0x100 | 0x10000 | 0x40000

    def _dialog(self, text):
        """MB_SETFOREGROUND alone does not work here (#50): the calling process is a windowless
        capture worker, and Windows' foreground-lock blocks an unprivileged background process
        from taking the foreground. Attaching our thread's input queue to the foreground window's
        makes the calling thread indistinguishable from it for that check, which lets
        MB_SETFOREGROUND succeed. https://learn.microsoft.com/windows/win32/api/winuser/nf-winuser-attachthreadinput"""
        foreground = self.user.GetForegroundWindow()
        this_thread = self.kernel.GetCurrentThreadId()
        foreground_thread = self.user.GetWindowThreadProcessId(foreground, None) if foreground else 0
        attached = bool(foreground_thread) and foreground_thread != this_thread and \
            self.user.AttachThreadInput(this_thread, foreground_thread, True)
        try:
            return self.user.MessageBoxW(None, text, "Screen Context", self.DIALOG)
        finally:
            if attached: self.user.AttachThreadInput(this_thread, foreground_thread, False)

    def approve_current(self):
        from ..config import Settings
        from ..i18n import resolve, t
        lang = resolve(Settings.environment())
        return self._dialog(t("approve.title", lang) + "\n\n" + t("approve.body", lang)) == 6

    def approve_client(self, name, profile):
        from ..config import Settings
        from ..i18n import resolve, t
        lang = resolve(Settings.environment())
        text = t("client.title", lang, name=name) + "\n\n" + t("client.body", lang, name=name, profile=profile)
        return self._dialog(text) == 6

    def authenticate(self, reason_text):
        """Windows Hello, or the sign-in password when Hello is not set up (#33). Asked from this
        windowless worker like the approvals above."""
        from ..reauth import windows
        return windows(reason_text)

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
