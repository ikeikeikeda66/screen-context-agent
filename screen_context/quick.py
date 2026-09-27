"""Menu bar shortcuts (#31): delete what was just recorded, and open the Today view.

Kept free of AppKit so it can be tested anywhere; mac_app.py only adds the menu and dialogs.
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


def ui_command():
    """The command that starts the Today view. In the app bundle, py2app's launcher (EXECUTABLEPATH)
    with an argument runs the CLI instead of the menu bar (packaging/mac_main.py)."""
    launcher = os.environ.get("EXECUTABLEPATH")
    if getattr(sys, "frozen", None) == "macosx_app" and launcher: return [launcher, "ui"]
    return [sys.executable, "-m", "screen_context.cli", "ui"]


def open_today(settings, spawn=subprocess.Popen):
    """Start the Today view for this data folder; it opens the browser with a one-time link and
    exits when its session ends. Touch ID before this call is #27."""
    env = {**os.environ, "SCREEN_CONTEXT_HOME": str(settings.root)}
    if settings.plaintext: env["SCREEN_CONTEXT_PLAINTEXT"] = "1"
    return spawn(ui_command(), env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                 stderr=subprocess.DEVNULL, start_new_session=True)
