"""First-run guide of the macOS app (#35-C): Screen Recording permission, then `init` (key and
database), then an offer to add ScreenContext to the AI assistants found on this Mac.

Free of AppKit and Quartz: mac_app.py passes the permission functions and the dialogs (`ui`), so the
steps can be tested with fakes. Nothing here captures; the app starts capture only after `run()`
returns READY.

State lives in `setup.json` inside the data folder: {"version": 1, "stage": "init" | "clients" | "done"}.
- no file and no database: first run, start with the permission check;
- no file but a database: installed before this guide existed, nothing is shown (the file is written as "done");
- "init": the permission was checked and `init` has not finished, run it again (it is idempotent);
- "clients": init finished, only the assistant offer is left;
- "done": show nothing.
An unreadable file counts as "clients" when the database exists (init had finished), otherwise as "init".
The permission is not stored: macOS decides it each launch.
"""
import json
import shlex
from . import client_config, clients, store
from .crypto import atomic_write
from .i18n import schema_message, t

READY, QUIT = "ready", "quit"        # run() result: start capture / leave without starting it
FILE = "setup.json"
STAGES = ("init", "clients", "done")
# client_config.TARGETS id -> name shown in the dialog
NAMES = {"claude-desktop": "Claude Desktop", "cursor": "Cursor", "vscode": "VS Code", "gemini": "Gemini CLI", "codex": "Codex CLI"}


def load(settings):
    """The saved stage, or None when there is no setup.json."""
    path = settings.root / FILE
    if not path.exists(): return None
    try:
        stage = json.loads(path.read_text(encoding="utf-8")).get("stage")
    except (OSError, ValueError, AttributeError):
        return _unreadable(settings)
    return stage if stage in STAGES else _unreadable(settings)


def _unreadable(settings):
    """A broken state file: with a database, init has finished, so only the offer is left (no GUI initialize)."""
    return "clients" if settings.db.exists() else "init"


def save(settings, stage):
    atomic_write(settings.root / FILE, json.dumps({"version": 1, "stage": stage}).encode())


def run(settings, ui, lang, *, preflight, request, open_settings, initialize=store.initialize,
        plan=client_config.plan, apply=client_config.apply, home=None):
    """Carry the user through the steps that are left. Returns READY or QUIT.

    ui.permission(lang) -> True to open System Settings; ui.error(text); ui.choose(options, lang) -> list of
    client ids (options are (id, name) pairs); ui.report(text, lang).
    preflight() -> bool, request() and open_settings() wrap the macOS calls.
    """
    stage = load(settings)
    if stage is None and settings.db.exists():
        try: save(settings, "done")
        except OSError: pass
        return READY
    if stage == "done": return READY
    if stage != "clients":
        if not preflight():
            request()                                  # makes macOS list the app under Screen Recording
            if ui.permission(lang): open_settings()
            return QUIT                                # the change only applies after the app is reopened
        try:
            save(settings, "init")
            initialize(settings)
            save(settings, "clients")
        except store.SchemaMismatch as error:
            ui.error(schema_message(error, lang, db=str(settings.db)))
            return QUIT
        except Exception as error:
            ui.error(t("setup.init_failed", lang, error=type(error).__name__))
            return QUIT
    text = connect_clients(settings, ui, lang, plan=plan, apply=apply, home=home)
    try: save(settings, "done")
    except OSError: pass                               # the offer comes again at the next launch; harmless
    ui.report(t("setup.done", lang) + ("\n\n" + text if text else ""), lang)
    return READY


def candidates(settings, plan=client_config.plan, home=None):
    """(id, name) of the supported clients that look installed and still need the entry."""
    found = []
    for client in client_config.TARGETS:
        try: change = plan(settings, client, home=home)
        except Exception: continue
        if change.action == "unchanged": continue
        if change.action == "manual" and change.reason in ("not_installed", "platform"): continue
        found.append((client, NAMES.get(client, client)))
    return found


def connect_clients(settings, ui, lang, plan=client_config.plan, apply=client_config.apply, home=None):
    """Offer the installed clients, add the entry to the chosen ones. Returns the text to show
    (empty when the user skipped). Also used by the menu item "Connect an Assistant…"."""
    options = candidates(settings, plan, home)
    if not options: return t("setup.clients.none", lang, command=_command())
    chosen = [c for c in ui.choose(options, lang) if c in dict(options)]
    lines = []
    for client in chosen:
        name = dict(options)[client]
        try:
            change = plan(settings, client, home=home)      # again: the file may have changed while the dialog was open
            lines.append(name + ": " + _connect(change, client, apply, lang))
        except Exception as error:
            lines.append(name + ": " + t("setup.client_failed", lang, client=name, error=type(error).__name__))
    return "\n\n".join(lines)


def _command(client="CLIENT", force=False):
    """The Terminal command that adds the entry, quoted for the shell: the .app launcher's path has a space.
    CLIENT stands for the client name when none is known (a bare <name> would be read by the shell as a redirect)."""
    words = [*clients.cli_command(), "mcp-config", "--client", client, "--write"]
    if force: words.append("--force")
    return shlex.join(words)


def _connect(change, client, apply, lang):
    if change.action == "conflict":
        text = t("cfg.conflict_http" if change.reason == "http" else "cfg.conflict", lang, path=change.path, home=change.other_home)
        return text + " " + t("setup.conflict_hint", lang, command=_command(client, force=True))
    if change.action == "manual":
        return t("cfg.reason." + change.reason, lang, client=NAMES.get(client, client)) + " " + t("setup.manual_hint", lang, command=_command(client))
    if change.action == "unchanged":
        return t("cfg.unchanged", lang, path=change.path)
    try: result = apply(change)
    except Exception as error:
        return t("cfg.failed", lang, path=change.path, reason=type(error).__name__)
    parts = [t("cfg." + change.action, lang, path=result["path"])]
    if result["backup"]: parts.append(t("cfg.backup", lang, path=result["backup"]))
    parts.append(t("cfg.next", lang, client=NAMES.get(client, client), name=change.name))
    if change.previous_owner: parts.append(t("cfg.previous_owner", lang, owner=change.previous_owner))   # the name only, never the token
    return " ".join(parts)
