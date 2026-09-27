"""Writes the local UI offers (#26, #30). Each one calls the same function as its CLI command.

An action is (prepare, run):
- prepare(settings, body, lang) -> (params, message) validates the request body and returns the
  normalized parameters and the confirmation text (with a dry-run count where there is one). It
  changes nothing. The confirmation nonce is bound to these exact parameters.
- run(settings, params) -> dict carries the action out and returns what goes into the audit row.
  Keywords are never returned (a purged keyword must not stay in the log).
"""
from datetime import datetime
from . import access, exclusions, purge
from .i18n import t


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


def run_retention(settings, params):
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


def run_purge(settings, params):
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


def run_exclude(settings, params):
    return exclusions.exclude(settings, params["kind"], params["value"], params["delete_past"], actor="ui")


# --- clients (`screen-context clients revoke`) -------------------------------------------------

def prepare_revoke(settings, body, lang):
    name = text(body, "name", 64)
    if not any(c["name"] == name and c["state"] != "revoked" for c in access.clients(settings)):
        raise ValueError("No client with that name can be revoked")
    return {"name": name}, t("ui.clients.revoke_confirm", lang, name=name)


def run_revoke(settings, params):
    access.revoke(settings, params["name"], actor="ui")
    return params


ACTIONS = {
    "pause": (prepare_pause, lambda settings, params: set_paused(settings, True)),
    "resume": (prepare_resume, lambda settings, params: set_paused(settings, False)),
    "retention": (prepare_retention, run_retention),
    "purge": (prepare_purge, run_purge),
    "exclude": (prepare_exclude, run_exclude),
    "revoke": (prepare_revoke, run_revoke),
}
