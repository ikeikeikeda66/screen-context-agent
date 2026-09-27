"""Add an app or a domain to the exclusion policy, optionally deleting what it already matches
(roadmap decision 5). Shared by `screen-context exclude` and the UI's Data tab.

A new exclusion hides past records from every read at once, because the policy is applied on
read. Deleting them as well is a separate, explicit choice: off by default, no undo.
"""
import json
import re
from . import purge, store
from .crypto import atomic_write
from .privacy import denied

KINDS = {"app": "denied_apps", "domain": "denied_domains"}
DOMAIN = re.compile(r"(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/\S*)?")
APP = re.compile(r"[\w.+ -]{1,200}")
RULE = {"denied_apps": [], "denied_domains": [], "denied_title_patterns": []}


def normalize(kind, value):
    if kind not in KINDS: raise ValueError("Choose app or domain")
    value = (value or "").strip()
    if kind == "domain":
        value = value.lower().removeprefix("https://").removeprefix("http://").rstrip("/")
        if not DOMAIN.fullmatch(value): raise ValueError("Enter a domain such as example.com")
    elif not APP.fullmatch(value): raise ValueError("Enter an app's bundle ID (macOS) or process name (Windows)")
    return value


def matching(settings, kind, value):
    """IDs of stored frames that this one rule excludes."""
    rule = {**RULE, KINDS[kind]: [value]}
    host = value.split("/", 1)[0]
    sql, args = ("SELECT * FROM frames WHERE app_bundle = ?", [value]) if kind == "app" else \
                ("SELECT * FROM frames WHERE instr(lower(domains), ?) > 0 OR instr(lower(ocr_text), ?) > 0", [host, host])
    with store.connect(settings, readonly=True) as con:
        return [r["id"] for r in con.execute(sql + " ORDER BY ts, id", args) if denied(rule, dict(r))]


def exclude(settings, kind, value, delete_past=False, apply=True, actor="cli"):
    """Add the rule (unless already present) and, with `delete_past`, purge its past matches.
    Without `apply` nothing changes: the result says what would happen."""
    value = normalize(kind, value)
    key = KINDS[kind]
    path = settings.root / "policy.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    present = value.casefold() in {x.casefold() for x in settings.policy()[key]}
    ids = matching(settings, kind, value) if delete_past else []
    result = {"kind": kind, "value": value, "added": not present, "delete_past": delete_past}
    if not apply:
        return {**result, **({"would_delete": purge.plan(settings, ids)} if delete_past else {})}
    if not present:
        data[key] = [*data.get(key, []), value]
        atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2).encode())
        settings.policy()  # fail loudly here, not in the capture loop, if the file became invalid
    if delete_past:
        result["deleted"] = purge.execute(settings, ids, {"exclude": kind, "value": value}, actor=actor, action="purge")["frames"] if ids else 0
    return result
