"""Issue #6: print the machine facts and the acceptance checklist as Markdown for the issue.

Reads no history and captures nothing. Run it with the same Python or build you test.
"""
import platform
import sys
from importlib import metadata

PACKAGES = ["screen-context-agent", "windows-capture", "winrt-Windows.Media.Ocr", "sqlcipher3", "keyring", "mcp", "psutil"]
CHECKLIST = [
    "1. Encrypted DB and key persist across restart",
    "2. Chrome/Edge text is searchable; capture follows app switches",
    "3. Languages, DPI change, multiple monitors, closing windows, lock/unlock never capture the wrong window",
    "4. Pause/resume works; no duplicate workers",
    "5. OCR worker exit stops capture and shows the failure",
    "6. Paths with spaces and non-ASCII work; a stdio MCP client connects",
    "7. No extra windows/processes; closing the window ends all workers",
]


def version(package):
    try: return metadata.version(package)
    except metadata.PackageNotFoundError: return "not installed"


def monitors():
    import ctypes
    from ctypes import wintypes
    user32, shcore = ctypes.windll.user32, ctypes.windll.shcore
    shcore.SetProcessDpiAwareness(2)  # per-monitor aware, so sizes and DPI are physical

    class MonitorInfo(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    found = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

    def callback(handle, _dc, _rect, _data):
        info = MonitorInfo(); info.cbSize = ctypes.sizeof(MonitorInfo)
        user32.GetMonitorInfoW(handle, ctypes.byref(info))
        x, y = wintypes.UINT(), wintypes.UINT()
        shcore.GetDpiForMonitor(handle, 0, ctypes.byref(x), ctypes.byref(y))
        r = info.rcMonitor
        found.append((r.right - r.left, r.bottom - r.top, x.value, bool(info.dwFlags & 1)))
        return True

    user32.EnumDisplayMonitors(None, None, callback_type(callback), 0)
    return found


def ocr_languages():
    try:
        from winrt.windows.media.ocr import OcrEngine
        return ", ".join(language.language_tag for language in OcrEngine.available_recognizer_languages)
    except Exception as error:  # report, never fail: this is a diagnostic
        return f"unavailable ({type(error).__name__})"


def report():
    lines = ["### Windows beta baseline (#6)", "",
             f"- Windows {platform.version()} ({platform.release()}, {platform.machine()})",
             f"- Python {platform.python_version()}, frozen build: {getattr(sys, 'frozen', False)}",
             f"- OCR languages: {ocr_languages()}"]
    lines += [f"- {p}: {version(p)}" for p in PACKAGES]
    lines += ["", "| Monitor | Resolution | DPI | Primary |", "|---|---|---|---|"]
    lines += [f"| {i} | {w}×{h} | {dpi} | {primary} |" for i, (w, h, dpi, primary) in enumerate(monitors(), 1)]
    lines += ["", "#### Checklist", ""] + [f"- [ ] {item} — result: _fill in_" for item in CHECKLIST]
    return "\n".join(lines)


def main(argv=None):
    if sys.platform != "win32":
        sys.exit("This report runs on Windows only.")
    print(report())


if __name__ == "__main__":
    main()
