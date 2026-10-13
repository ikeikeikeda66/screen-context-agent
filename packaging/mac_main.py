"""Frozen bundle entry: never load executable Python from outside the app.

The app launcher (Contents/MacOS/ScreenContext) starts the menu bar app with no arguments and the CLI
with arguments. Contents/MacOS/screen-context is a link to it that always starts the CLI, and shows
the help when given no arguments, so it never opens the menu bar app. The launcher name arrives in
ARGVZERO (py2app's main.c).
"""
import os
import sys
import traceback

CLI_NAME = "screen-context"


def plan(argv, name):
    """Return ("gui" or "cli", argv for that entry point)."""
    if name == CLI_NAME:
        return "cli", [CLI_NAME, *argv[1:]] if len(argv) > 1 else [CLI_NAME, "--help"]
    return ("gui", argv) if len(argv) == 1 else ("cli", argv)


if __name__ == "__main__":
    try:
        mode, sys.argv[:] = plan(sys.argv, os.path.basename(os.environ.get("ARGVZERO", "")))
        if mode == "gui":
            from screen_context.mac_app import main
        else:
            from screen_context.cli import main
        main()
    except Exception:
        # Do not invoke py2app's GUI error handler for a recoverable startup error.
        traceback.print_exc()
        raise SystemExit(1)
