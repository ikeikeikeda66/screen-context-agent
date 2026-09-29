"""Menu bar and control window shortcuts (#31, #33): delete what was just recorded, and open the
Today view.

Kept free of AppKit and tkinter so it can be tested anywhere; mac_app.py and windows_app.py only
add the menu or buttons and the dialogs.
The quick purge is `screen-context purge --last Nm --yes`: the same selective purge path, which
also removes unindexed spool files in the window. The Today view runs as its own process
(`screen-context ui`), so it never shares a process with capture.
"""
import os
import subprocess
import sys
from . import purge
from .i18n import t

WINDOWS = (5, 15, 60)  # minutes offered in the menu


def plan(settings, minutes):
    """What a quick purge would delete now, and who already received it. Changes nothing."""
    return purge.run(settings, last=f"{minutes}m")


def span(minutes, lang):
    return t("menu.span.hour", lang) if minutes == 60 else t("menu.span.minutes", lang, n=minutes)


def confirmation(settings, minutes, lang):
    """(title, body) for the confirmation dialog, or (message, None) when there is nothing to delete."""
    found = plan(settings, minutes)
    if not found["frames"] and not found["spool_files"]:
        return t("menu.delete.nothing", lang, span=span(minutes, lang)), None
    body = t("menu.delete.body", lang, frames=found["frames"], spool=found["spool_files"])
    if found["already_received_by"]:
        who = t("list.sep", lang).join(sorted({r["client"] for r in found["already_received_by"]}))
        body += "\n\n" + t("menu.delete.received", lang, who=who)
    return t("menu.delete.title", lang, span=span(minutes, lang)), body


def delete(settings, minutes):
    return purge.run(settings, last=f"{minutes}m", apply=True, actor="app")


def delete_recent(settings, minutes, lang, ask, tell):
    """The whole quick purge for a window without a menu bar (Windows): `ask(title, body)` must
    return True to delete; `tell(text)` shows the outcome. Returns the purge result, or None."""
    title, body = confirmation(settings, minutes, lang)
    if body is None:
        tell(title)
        return None
    if not ask(title, body): return None
    result = delete(settings, minutes)
    tell(t("menu.delete.done", lang, frames=result["frames"]))
    return result


def cli_command():
    """How this installation runs the CLI. In the app bundle, py2app's launcher (EXECUTABLEPATH)
    with an argument runs the CLI instead of the menu bar (packaging/mac_main.py). The frozen Windows
    control window runs the CLI executable next to it."""
    launcher = os.environ.get("EXECUTABLEPATH")
    if getattr(sys, "frozen", None) == "macosx_app" and launcher: return [launcher]
    if sys.platform == "win32":
        from .windows_app import cli_command as windows_cli
        return windows_cli()
    return [sys.executable, "-m", "screen_context.cli"]


def ui_command():
    """The command that starts the Today view."""
    return [*cli_command(), "ui"]


def child_env(settings):
    """Environment for a CLI child process: the same data folder and mode as this process."""
    env = {**os.environ, "SCREEN_CONTEXT_HOME": str(settings.root)}
    if settings.plaintext: env["SCREEN_CONTEXT_PLAINTEXT"] = "1"
    return env


def open_today(settings, authenticate, spawn=subprocess.Popen):
    """Start the Today view for this data folder once `authenticate()` returns "verified" (Touch ID
    or the password, #27). Nothing starts, so no launch token exists, otherwise. The UI opens the
    browser with a one-time link and exits when its session ends. Returns the check's result."""
    from .reauth import VERIFIED
    status = authenticate()
    if status != VERIFIED: return status
    env = child_env(settings)
    # Windows: no console window for the CLI; start_new_session is POSIX only and ignored there.
    extra = {"creationflags": 0x08000000} if sys.platform == "win32" else {}  # CREATE_NO_WINDOW
    spawn(ui_command(), env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
          stderr=subprocess.DEVNULL, start_new_session=True, **extra)
    return status
