"""Writes the local UI offers (#26, #30). Each one calls the same function as its CLI command.

An action is (prepare, run):
- prepare(settings, body, lang) -> (params, message) validates the request body and returns the
  normalized parameters and the confirmation text (with a dry-run count where there is one). It
  changes nothing. The confirmation nonce is bound to these exact parameters.
- run(settings, params, lang) -> dict carries the action out and returns what goes into the audit row,
  plus an optional "notice" shown to the user (not audited).
  Keywords are never returned (a purged keyword must not stay in the log).
"""
import time
from datetime import datetime
from pathlib import Path
from . import access, exclusions, export, lifecycle, purge
from .i18n import auth, t


def set_paused(settings, paused):
    flag = settings.root / "paused"
    if paused: flag.touch(mode=0o600)
    else: flag.unlink(missing_ok=True)
    return {"paused": paused}


def text(body, name, limit=500):
    value = body.get(name)
    if value is None or value == "": return None
    if not isinstance(value, str) or len(value) > limit: raise ValueError(f"{name}: invalid value")
    return value.strip() or None


def days(body, name, required=False):
    value = body.get(name)
    if value in (None, ""):
        if required: raise ValueError(f"{name}: enter a number of days")
        return None
    try: value = int(value)
    except (TypeError, ValueError): raise ValueError(f"{name}: enter a number of days") from None
    if not 1 <= value <= 36500: raise ValueError(f"{name}: 1–36500 days")
    return value


def moment(body, name):
    value = text(body, name, 40)
    if value is None: return None
    try: return datetime.fromisoformat(value).timestamp()
    except ValueError: raise ValueError(f"{name}: invalid date and time") from None


# --- pause / resume ----------------------------------------------------------------------------

def prepare_pause(settings, body, lang): return {}, t("ui.confirm.pause", lang)
def prepare_resume(settings, body, lang): return {}, t("ui.confirm.resume", lang)


# --- retention (`screen-context retention`) ----------------------------------------------------

RETENTION = (("preview", "preview_retention_days"), ("text", "text_retention_days"), ("audit", "audit_retention_days"))


def prepare_retention(settings, body, lang):
    params = {field: days(body, field, required=field == "preview") for field, _ in RETENTION}
    shown = {field: t("ui.days", lang, n=v) if v else t("ui.forever", lang) for field, v in params.items()}
    return params, t("ui.retention.confirm", lang, **shown)


def run_retention(settings, params, lang):
    for field, name in RETENTION: settings.set_retention(name, params[field])
    return params


# --- purge (`screen-context purge`) ------------------------------------------------------------

def selector(body):
    chosen = {"since": moment(body, "from"), "until": moment(body, "to"), "app": text(body, "app", 200),
              "keyword": text(body, "keyword"), "block": text(body, "block", 64)}
    if chosen["since"] is not None and chosen["until"] is not None and chosen["until"] <= chosen["since"]:
        raise ValueError("to: must be after from")
    return chosen


def prepare_purge(settings, body, lang):
    params = selector(body)
    plan = purge.run(settings, **params)  # dry run: the same path as `purge` without --yes
    if not plan["frames"] and not plan["spool_files"]: raise ValueError(t("ui.purge.nothing", lang))
    message = t("ui.purge.confirm", lang, frames=plan["frames"], images=plan["images"], spool=plan["spool_files"])
    if plan["already_received_by"]:
        who = t("list.sep", lang).join(sorted({r["client"] for r in plan["already_received_by"]}))
        message += "\n\n" + t("ui.purge.received", lang, who=who)
    return params, message


def run_purge(settings, params, lang):
    done = purge.run(settings, **params, apply=True, actor="ui")
    return {"frames": done["frames"], "days": done.get("days", []), "deleted": done["deleted"]}


# --- exclusion (`screen-context exclude`) ------------------------------------------------------

def prepare_exclude(settings, body, lang):
    kind, past = body.get("kind"), body.get("delete_past") is True
    if not isinstance(kind, str): raise ValueError("kind: choose app or domain")
    value = exclusions.normalize(kind, text(body, "value", 300))
    params = {"kind": kind, "value": value, "delete_past": past}
    if not past: return params, t("ui.exclude.confirm", lang, value=value)
    frames = exclusions.exclude(settings, kind, value, True, apply=False)["would_delete"]["frames"]
    return params, t("ui.exclude.confirm_past", lang, value=value, frames=frames)


def run_exclude(settings, params, lang):
    return exclusions.exclude(settings, params["kind"], params["value"], params["delete_past"], actor="ui")


# --- clients (`screen-context clients revoke`) -------------------------------------------------

def prepare_revoke(settings, body, lang):
    name = text(body, "name", 64)
    if not any(c["name"] == name and c["state"] != "revoked" for c in access.clients(settings)):
        raise ValueError("No client with that name can be revoked")
    return {"name": name}, t("ui.clients.revoke_confirm", lang, name=name)


def run_revoke(settings, params, lang):
    access.revoke(settings, params["name"], actor="ui")
    return params


# --- export (`screen-context export`), with re-authentication -----------------------------------

def prepare_export(settings, body, lang):
    if settings.option("export_allowed", True) is False: raise PermissionError("Exports are disabled by your administrator")
    since, until = moment(body, "from"), moment(body, "to") or time.time()
    if since is None: raise ValueError("from: choose a start date")
    if until <= since: raise ValueError("to: must be after from")
    fmt = body.get("format")
    if fmt not in ("jsonl", "md", "csv"): raise ValueError("format: jsonl, md or csv")
    params = {"since": since, "until": until, "format": fmt, "exclude_ide": body.get("exclude_ide") is True}
    frames = len(export.frames(settings, since, until, params["exclude_ide"]))
    return params, t("ui.export.confirm", lang, frames=frames, format=fmt) + "\n\n" + auth("ui.reauth.note", lang)


def run_export(settings, params, lang):
    done = export.write(settings, params["since"], params["until"], params["format"], exclude_ide=params["exclude_ide"], actor="ui")
    return {"frames": done["frames"], "format": done["format"], "notice": t("ui.export.done", lang, path=done["paths"][0])}


# --- backup (`screen-context backup`), with re-authentication -----------------------------------

def prepare_backup(settings, body, lang):
    if settings.option("backup_allowed", True) is False: raise PermissionError("Backups are disabled by your administrator")
    target = text(body, "path", 1000)
    if target is None: raise ValueError("path: enter where to save the backup")
    target = Path(target).expanduser()
    if not target.is_absolute(): raise ValueError("path: enter a full path")
    if target.exists(): raise ValueError(f"{target} already exists")
    if not target.parent.is_dir(): raise ValueError(f"{target.parent} does not exist")
    passphrase, again = body.get("passphrase"), body.get("again")
    if not isinstance(passphrase, str) or len(passphrase) < lifecycle.MIN_PASSPHRASE:
        raise ValueError(f"passphrase: at least {lifecycle.MIN_PASSPHRASE} characters")
    if passphrase != again: raise ValueError(t("ui.backup.mismatch", lang))
    return {"path": str(target), "passphrase": passphrase}, t("ui.backup.confirm", lang, path=target) + "\n\n" + auth("ui.reauth.note", lang)


def run_backup(settings, params, lang):
    done = lifecycle.backup(settings, params["path"], params["passphrase"], actor="ui")
    return {"images": done["images"], "notice": t("ui.backup.done", lang, path=done["backup"])}  # never the passphrase


# --- client approval (`screen-context clients approve`), with re-authentication ---------------

def prepare_approve(settings, body, lang):
    name = text(body, "name", 64)
    client = next((c for c in access.clients(settings) if c["name"] == name and c["state"] == "pending"), None)
    if client is None: raise ValueError("No client with that name is waiting for approval")
    return {"name": name}, t("ui.clients.approve_confirm", lang, name=name, profile=client["profile"]) + "\n\n" + auth("ui.reauth.note", lang)


def run_approve(settings, params, lang):
    access.decide(settings, params["name"], True, "ui")
    return params


# Actions that need Touch ID or the password, performed by the capture app (#27): action -> reason.
REAUTH = {"export": "export", "backup": "backup", "approve": "approve"}

ACTIONS = {
    "pause": (prepare_pause, lambda settings, params, lang: set_paused(settings, True)),
    "resume": (prepare_resume, lambda settings, params, lang: set_paused(settings, False)),
    "retention": (prepare_retention, run_retention),
    "purge": (prepare_purge, run_purge),
    "exclude": (prepare_exclude, run_exclude),
    "revoke": (prepare_revoke, run_revoke),
    "export": (prepare_export, run_export),
    "backup": (prepare_backup, run_backup),
    "approve": (prepare_approve, run_approve),
}
