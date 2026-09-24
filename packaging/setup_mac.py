from setuptools import setup
from pathlib import Path
import sys
# Build-time path only; the installed bundle contains its own modules.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# py2app's Tk recipe probes excluded nodes too. Make Tk unavailable in this
# build process so its optional recipe cannot open a GUI and abort in a sandbox.
sys.modules["_tkinter"] = None
sys.modules["tkinter"] = None
setup(
    name="ScreenContext",
    app=["mac_main.py"],
    options={"py2app": {
        "argv_emulation": False,
        "excludes": ["tkinter", "_tkinter", "pytest", "tests"],
        "includes": ["_cffi_backend", "sqlcipher3.dbapi2", "keyring.backends.macOS"],
        "packages": ["screen_context", "PIL", "cryptography", "keyring", "objc", "Foundation", "AppKit", "Quartz", "ScreenCaptureKit"],
        "plist": {"CFBundleName": "ScreenContext", "CFBundleDisplayName": "Screen Context", "CFBundleIdentifier": "local.screencontext.capture", "CFBundleVersion": "0.1.0", "CFBundleShortVersionString": "0.1.0", "LSUIElement": True, "CFBundleDevelopmentRegion": "en", "CFBundleLocalizations": ["en", "ja"], "LSMinimumSystemVersion": "14.0"},
    }},
)
