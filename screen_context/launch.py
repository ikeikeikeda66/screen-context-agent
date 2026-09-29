"""macOS app services (#34): the indexer as a child of the menu bar app, start at login, and the
move away from the old indexer LaunchAgent. Free of AppKit so it can be tested anywhere; mac_app.py
adds the menu items and dialogs.

Capture stays on the app's main thread (approvals and Touch ID need the app). The indexer runs as
`screen-context index --watch` under desktop.Workers, restarted after a crash like on Windows.
"""
import os
import subprocess
import sys
from pathlib import Path

LEGACY_LABEL = "local.screencontext.indexer"
# SMAppServiceStatus
NOT_REGISTERED, ENABLED, REQUIRES_APPROVAL, NOT_FOUND = 0, 1, 2, 3


def log_dir(home=None): return (home or Path.home()) / "Library" / "Logs" / "ScreenContext"


def indexer_workers(settings, home=None, popen=None):
    """Workers that run the indexer CLI for this data folder. Its output goes to the same log file
    the old LaunchAgent used."""
    from .desktop import CommandProcess, Workers
    from .quick import child_env, cli_command
    log = log_dir(home) / "indexer.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    return Workers(settings, kinds=("index",),
                   command=lambda kind: CommandProcess([*cli_command(), "index", "--watch"], env=child_env(settings), log=log, popen=popen))


# --- the old LaunchAgent (packaging/macos/screencontext.indexer.plist) -------------------------

def legacy_plist(home=None): return (home or Path.home()) / "Library" / "LaunchAgents" / (LEGACY_LABEL + ".plist")


def legacy_agent(home=None, run=subprocess.run):
    """"loaded" when launchd runs the old agent, "installed" when only its plist remains (it would
    load at the next login), None when there is none."""
    domain = f"gui/{os.getuid()}/{LEGACY_LABEL}"
    if run(["launchctl", "print", domain], capture_output=True).returncode == 0: return "loaded"
    return "installed" if legacy_plist(home).exists() else None


def remove_legacy_agent(home=None, run=subprocess.run):
    """Unload the old agent and rename its plist to .disabled, so it does not come back at login.
    The file is kept for reference. True when nothing of it is left running or installed."""
    run(["launchctl", "bootout", f"gui/{os.getuid()}/{LEGACY_LABEL}"], capture_output=True)
    plist = legacy_plist(home)
    if plist.exists(): plist.rename(plist.with_name(plist.name + ".disabled"))
    return legacy_agent(home, run) is None


def start_indexer(settings, ask_remove, tell, lang="en", legacy=legacy_agent, remove=remove_legacy_agent, workers=indexer_workers):
    """The menu bar app's startup path for the indexer. An old LaunchAgent would hold indexer.lock,
    so `ask_remove()` is asked first (True: remove it); if the user keeps it, the agent stays the
    indexer and nothing starts. Returns (Workers or None, note for the menu when None)."""
    from .i18n import t
    if legacy():
        if not ask_remove(): return None, "legacy"
        if not remove():
            tell(t("legacy.failed", lang, label=LEGACY_LABEL))
            return None, "legacy"
    try:
        running = workers(settings)
        running.start()
        return running, None
    except Exception as error:
        tell(t("error.indexer", lang, error=type(error).__name__))
        return None, "failed"


def stop_indexer(running, timeout=20):
    """Ask the indexer to finish its current batch and exit; do not wait past `timeout`."""
    if not running: return
    running.stop()
    for p in running.processes.values(): p.join(timeout)


# --- start at login -----------------------------------------------------------------------------

def login_service():
    """The app's own login item (SMAppService.mainAppService, macOS 13+). None when running from
    source or when ServiceManagement is missing: only the app bundle can register itself."""
    if getattr(sys, "frozen", None) != "macosx_app": return None
    try: from ServiceManagement import SMAppService
    except ImportError: return None
    return SMAppService.mainAppService()


def login_enabled(service): return service is not None and int(service.status()) == ENABLED


def toggle_login(service, open_settings):
    """Turn start at login on or off. Returns "enabled", "disabled", "approval" (macOS wants the
    user to allow it in System Settings, which `open_settings()` opens) or "failed"."""
    if int(service.status()) == ENABLED:
        ok, _ = service.unregisterAndReturnError_(None)
        return "disabled" if ok else "failed"
    service.registerAndReturnError_(None)
    status = int(service.status())
    if status == ENABLED: return "enabled"
    if status == REQUIRES_APPROVAL:
        open_settings()
        return "approval"
    return "failed"
