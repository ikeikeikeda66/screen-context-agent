"""Uninstall (roadmap #37): take ScreenContext out of the AI clients, Login Items and launchd, and
optionally erase the data.

plan() only reads. It never writes a file, the database, the credential store or a login item.
apply() carries a plan out in a fixed order and records every step in a Result:

  workers stopped (else nothing changes) -> client files -> revoke every client token (not with wipe)
  -> Login Item -> old LaunchAgent -> log folder -> wipe (only when asked)

A failed step does not stop the later ones; Result.ok is False and the step says what failed.
Not touched: the app itself, backups and exports kept outside the data folder, and, without wipe,
the data folder with its key. The log folder holds only the indexer's stdout/stderr: the indexer
never prints OCR text, window titles or queries (indexer.py keeps only the error type, #34).
"""
import os
import shutil
import subprocess
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path

from . import access, client_config, launch, lifecycle
from .clients import CLIENTS
from .i18n import t

AUTO = object()
MANUAL = {  # clients without a file ScreenContext can edit: what the user does by hand
    "claude-code": "claude mcp remove screen-context --scope user",
    "windsurf": "delete the screen-context entry in ~/.codeium/windsurf/mcp_config.json",
    "generic": "delete the screen-context entry from the client you added it to",
}
LOGIN_ACTIVE = (launch.ENABLED, launch.REQUIRES_APPROVAL)


def _default_run(*args, **kwargs): return subprocess.run(*args, **kwargs)   # tests replace this


@dataclass
class Plan:
    wipe: bool
    root: Path
    changes: list                  # client_config.Change per supported client, in client_config.TARGETS order
    manual: dict                   # client -> what the user does by hand
    login: str                     # enabled | approval | off | manual (no login service: not the app bundle)
    legacy_agent: str | None       # "loaded" | "installed" | None
    clients: list                  # [{"name", "state"}]: tokens that are not revoked yet
    clients_error: str             # "" or the exception class name when the database could not be read
    logs: Path | None
    erase: list                    # wipe only: [{"code", "detail"}]
    remains: list                  # [{"code", "detail"}]
    settings: object = field(default=None, repr=False)
    home: object = field(default=None, repr=False)
    service: object = field(default=None, repr=False)
    run: object = field(default=None, repr=False)


@dataclass
class Result:
    ok: bool
    steps: list = field(default_factory=list)   # [{"step", "status": done|skipped|failed|manual, "detail"}]
    manual: dict = field(default_factory=dict)
    wiped: dict | None = None                   # lifecycle.wipe's answer

    @property
    def aborted(self): return bool(self.steps) and self.steps[0]["step"] == "workers" and self.steps[0]["status"] == "failed"


def _clients(settings):
    if not settings.db.exists(): return [], ""
    try: return [{"name": c["name"], "state": c["state"]} for c in access.clients(settings) if c["state"] != "revoked"], ""
    except Exception as error: return [], type(error).__name__


def _login_state(service):
    if service is None: return "manual"
    try: status = int(service.status())
    except Exception: return "manual"
    return "enabled" if status == launch.ENABLED else "approval" if status == launch.REQUIRES_APPROVAL else "off"


def _legacy(home, run):
    try: return launch.legacy_agent(home, run)
    except OSError: return None          # no launchctl on this system


def plan(settings, home=None, wipe=False, include_related=(), service=AUTO, run=None):
    """What uninstall would do. `include_related` names entries (other than screen-context) that the
    user picked from Change.related; a name found in no client file raises ValueError."""
    run = run or _default_run
    service = launch.login_service() if service is AUTO else service
    include = tuple(dict.fromkeys(include_related))
    found = {c: client_config.remove_plan(c, home, settings) for c in client_config.TARGETS}
    unknown = [n for n in include if not any(n in ch.related for ch in found.values())]
    if unknown: raise ValueError("Not a related entry in any client file: " + ", ".join(unknown))
    changes = []
    for client, change in found.items():
        chosen = [n for n in include if n in change.related]
        changes.append(client_config.remove_plan(client, home, settings, also=chosen) if chosen else change)
    manual = {c: MANUAL[c] for c in CLIENTS if c not in client_config.TARGETS and c in MANUAL}
    for change in changes:
        if change.action == "manual" and change.reason in ("unreadable", "unsupported"):
            manual[change.client] = f"remove the screen-context entry in {change.path} by hand"
    clients, clients_error = _clients(settings)
    legacy = _legacy(home, run)
    logs = launch.log_dir(home)
    logs = logs if logs.exists() or logs.is_symlink() else None
    erase, remains = [], []
    if wipe:
        if not settings.plaintext: erase.append({"code": "key", "detail": ""})
        if settings.root.exists(): erase.append({"code": "data", "detail": str(settings.root)})
        if (settings.root / "exports").exists(): erase.append({"code": "exports", "detail": str(settings.root / "exports")})
        if os.environ.get("SCREEN_CONTEXT_KEY"): remains.append({"code": "env_key", "detail": ""})
    else:
        remains.append({"code": "data", "detail": str(settings.root)})
    remains.append({"code": "backups", "detail": ""})
    for change in changes:
        if change.action == "remove": remains.append({"code": "config_backup", "detail": f"{change.path}.screen-context-*.bak"})
        if change.action == "conflict" and change.reason == "other_home": remains.append({"code": "other_home", "detail": f"{change.client} ({change.other_home})"})
        for name in change.related:
            if name not in change.names: remains.append({"code": "related", "detail": f"{change.client}: {name}"})
    if legacy: remains.append({"code": "legacy_disabled", "detail": str(launch.legacy_plist(home)) + ".disabled"})
    remains.append({"code": "app", "detail": ""})
    return Plan(wipe, settings.root, changes, manual, _login_state(service), legacy, clients, clients_error, logs,
                erase, remains, settings, home, service, run)


def apply(plan, actor="cli"):
    """Carry out `plan`. Never raises for a failed step; read Result.ok and Result.steps.
    Needs capture.lock and indexer.lock: when a worker runs, nothing is changed (Result.aborted)."""
    settings, steps = plan.settings, []
    def step(name, status, detail=""): steps.append({"step": name, "status": status, "detail": detail})
    def failed(error): return f"{type(error).__name__}: {error}"
    locks = ExitStack()
    if settings.root.exists():
        try: locks = lifecycle.workers_stopped(settings)
        except RuntimeError as error:
            hint = (f" The old LaunchAgent {launch.LEGACY_LABEL} may be running the indexer: "
                    f"launchctl bootout gui/{os.getuid()}/{launch.LEGACY_LABEL}") if plan.legacy_agent == "loaded" else ""
            step("workers", "failed", str(error) + hint)
            return Result(False, steps, plan.manual)
    step("workers", "done", "capture and indexer are stopped")
    result = Result(True, steps, plan.manual)
    try:
        for change in plan.changes:
            name = "client:" + change.client
            if change.action == "remove":
                try: step(name, "done", client_config.remove(change)["backup"] or "")
                except Exception as error: step(name, "failed", failed(error))
            elif change.action == "manual" and change.reason in ("unreadable", "unsupported"): step(name, "manual", change.reason)
            else: step(name, "skipped", change.reason or change.action)
        todo, error = _clients(settings)     # also before a wipe: the tokens are revoked whatever happens to the data
        if error: step("revoke", "failed", "database unreadable: " + error)
        for client in todo:
            try: access.revoke(settings, client["name"], actor); step("revoke:" + client["name"], "done")
            except Exception as error: step("revoke:" + client["name"], "failed", failed(error))
        if not todo and not error: step("revoke", "skipped", "no client tokens")
        service = plan.service
        if service is None: step("login", "manual", "System Settings > General > Login Items")
        else:
            try:
                if int(service.status()) in LOGIN_ACTIVE:
                    ok, _ = service.unregisterAndReturnError_(None)
                    step("login", "done" if ok else "failed", "" if ok else "unregister was refused")
                else: step("login", "skipped", "not a login item")
            except Exception as error: step("login", "failed", failed(error))
        try:
            if _legacy(plan.home, plan.run) is None: step("legacy_agent", "skipped", "none")
            else:
                gone = launch.remove_legacy_agent(plan.home, plan.run)
                step("legacy_agent", "done" if gone else "failed", "" if gone else f"launchctl bootout gui/{os.getuid()}/{launch.LEGACY_LABEL}")
        except Exception as error: step("legacy_agent", "failed", failed(error))
        logs = launch.log_dir(plan.home)
        try:
            if logs.is_symlink(): logs.unlink(); step("logs", "done", str(logs))
            elif logs.exists(): shutil.rmtree(logs); step("logs", "done", str(logs))
            else: step("logs", "skipped", "none")
        except OSError as error: step("logs", "failed", failed(error))
        if plan.wipe:
            try:
                if settings.root.exists():
                    result.wiped = lifecycle.wipe(settings, locks=locks)
                    step("wipe", "done", result.wiped["wiped"])
                else:
                    from .crypto import delete_key
                    key = False if settings.plaintext else delete_key(settings)
                    step("wipe", "skipped", "no data folder" + ("; the key was deleted" if key else ""))
            except Exception as error: step("wipe", "failed", failed(error))
    finally:
        locks.close()
    result.ok = all(s["status"] != "failed" for s in steps)
    return result


# --- text shared by the CLI and the menu bar app (37-B) -----------------------------------------

def confirmation_word(plan): return "ERASE" if plan.wipe else "UNINSTALL"


def lines(plan, lang="en"):
    """{"do": [...], "manual": [...], "remains": [...]}: user-facing sentences, no I/O."""
    do = []
    for change in plan.changes:
        if change.action == "remove":
            if change.before: do.append(t("uninstall.do.client", lang, client=change.client, path=change.path))   # the screen-context key itself
            if change.names: do.append(t("uninstall.do.related", lang, names=", ".join(change.names), client=change.client, path=change.path))
    if plan.clients and not plan.wipe: do.append(t("uninstall.do.revoke", lang, count=len(plan.clients)))
    if plan.login in ("enabled", "approval"): do.append(t("uninstall.do.login", lang))
    if plan.legacy_agent: do.append(t("uninstall.do.legacy", lang, label=launch.LEGACY_LABEL))
    if plan.logs: do.append(t("uninstall.do.logs", lang, path=plan.logs))
    if plan.wipe:
        do.append(t("uninstall.do.wipe", lang, path=plan.root))
        for item in plan.erase:
            if item["code"] == "exports": do.append(t("uninstall.do.exports", lang, path=item["detail"]))
    manual = [t("uninstall.manual.client", lang, client=c, hint=h) for c, h in plan.manual.items()]
    if plan.login == "manual": manual.append(t("uninstall.manual.login", lang))
    remains = [t("uninstall.remains." + r["code"], lang, detail=r["detail"]) for r in plan.remains]
    return {"do": do, "manual": manual, "remains": remains}


def confirmation(plan, lang="en"):
    """(title, body) for a confirmation dialog or prompt."""
    text = lines(plan, lang)
    parts = ["\n".join("- " + s for s in text["do"]) or t("uninstall.nothing", lang)]
    if text["manual"]: parts.append(t("uninstall.manual.header", lang) + "\n" + "\n".join("- " + s for s in text["manual"]))
    parts.append(t("uninstall.remains.header", lang) + "\n" + "\n".join("- " + s for s in text["remains"]))
    return t("uninstall.title.wipe" if plan.wipe else "uninstall.title", lang), "\n\n".join(parts)


def result_message(result, lang="en"):
    if result.aborted: return t("uninstall.result.aborted", lang, reason=result.steps[0]["detail"])
    bad = [s["step"] for s in result.steps if s["status"] == "failed"]
    return t("uninstall.result.partial", lang, steps=", ".join(bad)) if bad else t("uninstall.result.done", lang)


def describe(plan):
    """The plan as JSON-able data (for --dry-run)."""
    return {"wipe": plan.wipe, "root": str(plan.root),
            "clients": [{"client": c.client, "action": c.action, "reason": c.reason, "path": str(c.path) if c.path else None,
                         "other_home": c.other_home or None, "related": c.related, "removing": list(c.names)} for c in plan.changes],
            "manual": plan.manual, "login": plan.login, "legacy_agent": plan.legacy_agent,
            "revoke": [] if plan.wipe else plan.clients, "database_error": plan.clients_error,
            "logs": str(plan.logs) if plan.logs else None,
            "erase": plan.erase, "remains": plan.remains, "confirm_with": confirmation_word(plan)}
