"""Frozen bundle entry: never load executable Python from outside the app."""
import sys
import traceback

if __name__ == "__main__":
    try:
        if len(sys.argv) == 1:
            from screen_context.mac_app import main
        else:
            from screen_context.cli import main
        main()
    except Exception:
        # Do not invoke py2app's GUI error handler for a recoverable startup error.
        traceback.print_exc()
        raise SystemExit(1)
