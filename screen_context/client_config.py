"""Write the `screen-context` MCP entry into a client's own configuration file (and take it out again).

`plan()` only reads: it decides what would change and never issues a token or touches a file.
`apply()` issues the token (or reuses a valid one), backs the file up, and replaces it atomically.
Anything this module cannot edit without risk (comments in JSON, an unreadable or unusual TOML file,
a client without a known file) becomes a "manual" change; the caller then prints the snippet instead.
Only macOS paths are known; other systems always get "manual".
"""
import copy
import glob
import json
import os
import re
import sys
import tempfile
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import access
from .clients import CLIENTS, cli_command, render, server_entry

KEY = "screen-context"
KEEP_BACKUPS = 5
PLATFORM = sys.platform  # tests replace this
# client -> (path under the home folder, file format, key that holds the servers)
TARGETS = {
    "claude-desktop": (("Library", "Application Support", "Claude", "claude_desktop_config.json"), "json", "mcpServers"),
    "cursor": ((".cursor", "mcp.json"), "json", "mcpServers"),
    "vscode": (("Library", "Application Support", "Code", "User", "mcp.json"), "json", "servers"),
    "gemini": ((".gemini", "settings.json"), "json", "mcpServers"),
    "codex": ((".codex", "config.toml"), "toml", "mcp_servers"),
}
SECRET = re.compile(r"sc_[A-Za-z0-9_-]{8,}")


class _Manual(Exception):
    """The file cannot be edited safely. The argument is a reason code."""


@dataclass
class Change:
    client: str
    name: str                      # token name (the key inside the file is always KEY)
    action: str                    # add | update | unchanged | conflict | manual | remove | absent
    reason: str = ""               # manual: manual_only | platform | not_installed | unreadable | unsupported; conflict: other_home | http
    path: Path | None = None       # the file that would be written (a symlink is already resolved)
    before: str = ""               # the screen-context entry now (secrets masked), for a diff
    after: str = ""                # the entry after the change (secrets masked)
    manual: str = ""               # manual: the snippet with a placeholder token
    related: list = field(default_factory=list)   # remove_plan: other server names that look like ScreenContext
    names: tuple = ()              # remove_plan: related names that will be removed together with KEY
    other_home: str = ""           # conflict: the SCREEN_CONTEXT_HOME the existing entry points at
    reuse_token: str = ""          # the existing token that is still valid (never printed)
    previous_owner: str = ""       # the file held a live token of another client name; that name (the token is never printed)
    original: bytes | None = field(default=None, repr=False)
    settings: object = field(default=None, repr=False)
    profile: str = field(default="standard", repr=False)
    command: list = field(default_factory=list, repr=False)
    format: str = field(default="", repr=False)       # json | toml
    container: str = field(default="", repr=False)    # the key that holds the servers


def _mask(entry):
    if not isinstance(entry, dict): return entry
    entry = copy.deepcopy(entry)
    if isinstance(entry.get("env"), dict):
        entry["env"] = {k: (v if k == "SCREEN_CONTEXT_HOME" else "***") for k, v in entry["env"].items()}
    if isinstance(entry.get("headers"), dict):
        entry["headers"] = {k: "***" for k in entry["headers"]}
    return entry


def _show(fmt, entry):
    if entry is None: return ""
    entry = _mask(entry)
    if fmt == "json": text = json.dumps({KEY: entry}, ensure_ascii=False, indent=2)
    else:
        import tomlkit
        doc = tomlkit.document(); doc["mcp_servers"] = {KEY: entry}
        text = tomlkit.dumps(doc)
    return SECRET.sub("sc_***", text)   # a token left anywhere else in the entry (args, a URL) is masked too


def _desired(client, settings, command, token, profile):
    entry = server_entry(command, settings, token, profile)
    return {"type": "stdio", **entry} if client == "vscode" else entry


def _merge(old, desired):
    """Keep what the user added to the entry; ScreenContext's own keys win."""
    if not isinstance(old, dict) or "url" in old: return copy.deepcopy(desired)
    merged = copy.deepcopy(old)
    for key, value in desired.items():
        merged[key] = {**(old.get("env") if isinstance(old.get("env"), dict) else {}), **value} if key == "env" else value
    return merged


def _eol(text):
    """CRLF when every line ends in CRLF, LF when none does. A mix is not edited (manual)."""
    crlf = text.count("\r\n")
    if crlf and crlf != text.count("\n"): raise _Manual("unsupported")
    return "\r\n" if crlf else "\n"


def _reject_constant(name): raise ValueError("not a finite JSON number: " + name)


def _json_load(text):
    def pairs(items):
        keys = [k for k, _ in items]
        if len(keys) != len(set(keys)): raise ValueError("duplicate key")
        return dict(items)
    if not text.strip(): return {}
    try: data = json.loads(text, object_pairs_hook=pairs, parse_constant=_reject_constant)
    except ValueError: raise _Manual("unreadable")
    if not isinstance(data, dict): raise _Manual("unreadable")
    return data


def _json_edit(text, container, entry, remove, names=()):
    """-> (new text, existing entry or None). Same text back when nothing changes."""
    eol = _eol(text)
    data = _json_load(text)
    servers = data.get(container)
    if servers is None: servers = {}
    if not isinstance(servers, dict): raise _Manual("unsupported")
    old = servers.get(KEY)
    if remove:
        gone = [n for n in (KEY, *names) if n in servers]
        if not gone: return text, None
        for n in gone: del servers[n]
        data[container] = servers
    else:
        merged = _merge(old, entry)
        if merged == old: return text, old
        servers[KEY] = merged; data[container] = servers
    try: out = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    except ValueError: raise _Manual("unsupported")   # e.g. 1e400 reads as inf, which JSON cannot write back
    return out.replace("\n", eol), old


def _toml_edit(text, entry, remove, names=()):
    import tomlkit
    from tomlkit.exceptions import TOMLKitError
    from tomlkit.items import Table, InlineTable
    original, eol = text, _eol(text)
    text = text.replace("\r\n", "\n")
    try:
        before = tomllib.loads(text)
        doc = tomlkit.parse(text)
        if tomlkit.dumps(doc) != text: raise _Manual("unsupported")
    except (tomllib.TOMLDecodeError, TOMLKitError): raise _Manual("unreadable")
    old = (before.get("mcp_servers") or {}).get(KEY) if isinstance(before.get("mcp_servers", {}), dict) else None
    present = [n for n in (KEY, *names) if isinstance(before.get("mcp_servers"), dict) and n in before["mcp_servers"]]
    if remove and not present: return original, None
    if not remove:
        want = _merge(old, entry)
        if want == old: return original, old
    try:
        servers = doc.get("mcp_servers")
        if remove:
            if not isinstance(servers, Table): raise _Manual("unsupported")
            for n in present: del servers[n]
        else:
            if servers is None:
                servers = tomlkit.table(True); doc["mcp_servers"] = servers
            if not isinstance(servers, Table): raise _Manual("unsupported")
            table = servers.get(KEY)
            if table is None or isinstance(table, InlineTable): servers[KEY] = want
            elif isinstance(table, Table):
                for key, value in want.items():
                    if key == "env" and isinstance(table.get("env"), (Table, InlineTable)):
                        for k, v in value.items(): table["env"][k] = v
                    else: table[key] = value
            else: raise _Manual("unsupported")
        out = tomlkit.dumps(doc)
        after = tomllib.loads(out)
    except (TOMLKitError, tomllib.TOMLDecodeError, ValueError, TypeError, KeyError): raise _Manual("unsupported")
    # Everything except our own entry must be exactly what it was before.
    def rest(data):
        data = copy.deepcopy(data); servers = data.get("mcp_servers")
        if isinstance(servers, dict):
            for n in (KEY, *names): servers.pop(n, None)
            if not servers: del data["mcp_servers"]
        return data
    got = (after.get("mcp_servers") or {}).get(KEY)
    if rest(before) != rest(after) or got != (None if remove else want): raise _Manual("unsupported")
    return out.replace("\n", eol), old


def _edit(fmt, container, text, entry, remove=False, names=()):
    return _json_edit(text, container, entry, remove, names) if fmt == "json" else _toml_edit(text, entry, remove, names)


def _locate(client, home):
    """-> (resolved path, format, container) or raises _Manual."""
    if PLATFORM != "darwin": raise _Manual("platform")
    if client not in CLIENTS: raise ValueError("Unknown client; choose one of " + ", ".join(CLIENTS))
    if client not in TARGETS: raise _Manual("manual_only")
    parts, fmt, container = TARGETS[client]
    path = Path(os.path.realpath(Path(home or Path.home()).joinpath(*parts)))
    if not path.parent.is_dir(): raise _Manual("not_installed")
    return path, fmt, container


def _read(path):
    try: return path.read_bytes() if path.exists() else None
    except OSError: raise _Manual("unreadable")


def _text(raw):
    try: return "" if raw is None else raw.decode("utf-8")
    except UnicodeDecodeError: raise _Manual("unreadable")


def _same_home(a, b): return os.path.realpath(os.path.expanduser(str(a))) == os.path.realpath(os.path.expanduser(str(b)))


def plan(settings, client, home=None, name=None, profile="standard", command=None, force=False):
    """Decide what writing the entry would do. Reads the client's file; changes nothing."""
    name = name or client
    command = list(command or cli_command())
    change = Change(client, name, "manual", settings=settings, profile=profile, command=command)
    change.manual = render(client, command, settings, "<token>", profile) if client in CLIENTS else ""
    try:
        path, fmt, container = _locate(client, home)
        change.path, change.format, change.container = path, fmt, container
        raw = _read(path); text = _text(raw)
        change.original = raw
        placeholder = _desired(client, settings, command, "sc_" + "x" * 43, profile)
        _, old = _edit(fmt, container, text, placeholder)       # reads the existing entry and proves the file parses
        token = ""
        if isinstance(old, dict) and "url" in old and not force:   # an HTTP entry is replaced only when forced
            change.action, change.reason = "conflict", "http"
            change.before = _show(fmt, old); change.manual = ""
            return change
        if isinstance(old, dict) and isinstance(old.get("env"), dict):
            token = old["env"].get(access.TOKEN_ENV) or ""
            home_now = old["env"].get("SCREEN_CONTEXT_HOME")
            if home_now and not _same_home(home_now, settings.root) and not force:
                change.action, change.reason, change.other_home = "conflict", "other_home", str(home_now)
                change.before = _show(fmt, old); change.manual = ""
                return change
        if token and access.matches(settings, name, token, profile): change.reuse_token = token
        elif token:
            owner = access.owner(settings, token)
            if owner and owner != name: change.previous_owner = owner
        entry = _desired(client, settings, command, change.reuse_token or placeholder["env"][access.TOKEN_ENV], profile)
        new_text, _ = _edit(fmt, container, text, entry)
        change.before = _show(fmt, old)
        change.after = _show(fmt, _merge(old, entry))
        if new_text == text and raw is not None: change.action = "unchanged"
        else: change.action = "update" if old is not None else "add"
        change.reason = ""; change.manual = ""
    except _Manual as why:
        change.action, change.reason = "manual", str(why)
    return change


def remove_plan(client, home=None, settings=None, also=()):
    """Decide what taking the screen-context entry out would do. Other servers are left alone, except the
    names in `also` (related entries the user chose; a name that is not in the file is ignored)."""
    change = Change(client, KEY, "manual", settings=settings, names=tuple(also))
    try:
        path, fmt, container = _locate(client, home)
        change.path, change.format, change.container = path, fmt, container
        raw = _read(path); text = _text(raw); change.original = raw
        if raw is None: change.action = "absent"; return change
        new_text, old = _edit(fmt, container, text, None, remove=True, names=change.names)
        change.before = _show(fmt, old)
        other = _other_home(old, settings)
        if other:   # the entry belongs to another data folder: left alone, related entries too
            change.action, change.reason, change.other_home = "conflict", "other_home", other
            return change
        change.related = _related(fmt, container, text, settings)
        removes_key = old is not None or bool(change.names)   # a null entry is absent
        change.action = "remove" if new_text != text and removes_key else "absent"; change.reason = ""
    except _Manual as why:
        change.action, change.reason = "manual", str(why)
    return change


def _other_home(entry, settings):
    """The SCREEN_CONTEXT_HOME of `entry` when it is not the data folder of `settings`, else ""."""
    env = entry.get("env") if isinstance(entry, dict) and isinstance(entry.get("env"), dict) else {}
    home = env.get("SCREEN_CONTEXT_HOME")
    return str(home) if home and settings is not None and not _same_home(home, settings.root) else ""


def _related(fmt, container, text, settings=None):
    """Other server names whose entry looks like a ScreenContext one of the same data folder (for the user to choose)."""
    try: servers = (_json_load(text) if fmt == "json" else tomllib.loads(text)).get(container) or {}
    except (_Manual, tomllib.TOMLDecodeError): return []
    def ours(entry):
        if not isinstance(entry, dict): return False
        env = entry.get("env") if isinstance(entry.get("env"), dict) else {}
        return access.TOKEN_ENV in env or "SCREEN_CONTEXT_HOME" in env or "screen_context.cli" in " ".join(map(str, entry.get("args") or []))
    return [k for k, v in servers.items() if k != KEY and ours(v) and not _other_home(v, settings)] if isinstance(servers, dict) else []


# ---- writing -------------------------------------------------------------------------------------------

_STAMP = re.compile(r"\.screen-context-\d{8}-\d{6}\.bak$")


def backup(path, data):
    """Copy `data` (the file's current bytes) next to it with mode 0600; keep the newest KEEP_BACKUPS."""
    stamp = time.time()
    while True:
        target = path.with_name(f"{path.name}.screen-context-{time.strftime('%Y%m%d-%H%M%S', time.localtime(stamp))}.bak")
        try: fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600); break
        except FileExistsError: stamp += 1
    with os.fdopen(fd, "wb") as f: f.write(data); f.flush(); os.fsync(f.fileno())
    old = sorted(p for p in path.parent.glob(glob.escape(path.name) + ".screen-context-*.bak") if _STAMP.search(p.name) and p.name.startswith(path.name + "."))
    for stale in old[:-KEEP_BACKUPS]: stale.unlink(missing_ok=True)
    return target


def write_atomic(path, data):
    """Replace `path` (already resolved) with `data`: same-folder temp file, fsync, os.replace. Keeps the
    file's permission bits; a new file gets 0600 because it holds a token."""
    mode = (path.stat().st_mode & 0o7777) if path.exists() else 0o600
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data); f.flush(); os.fchmod(f.fileno(), mode); os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    try:
        fd = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(fd)
        finally: os.close(fd)
    except OSError: pass


def apply(change):
    """Carry out an add/update plan. -> {"path", "action", "backup", "token_issued"}.
    Raises RuntimeError when the file changed after planning or the plan is not an add/update."""
    if change.action == "unchanged": return {"path": str(change.path), "action": "unchanged", "backup": None, "token_issued": False}
    if change.action not in ("add", "update"): raise RuntimeError("Nothing to write: " + change.action)
    return _commit(change)


def remove(change):
    """Carry out a remove_plan. Only the screen-context entry goes; the file is backed up first."""
    if change.action != "remove": return {"path": str(change.path) if change.path else None, "action": change.action, "backup": None, "token_issued": False}
    return _commit(change, remove=True)


def _commit(change, remove=False):
    path = change.path
    raw = _read_checked(path)
    if raw != change.original: raise RuntimeError("The file changed after the plan was made; run it again")
    text = _text(raw)
    issued = False
    try:
        if remove: new_text, _ = _edit(change.format, change.container, text, None, remove=True, names=change.names)
        else:
            token = change.reuse_token
            if not token: token = access.issue(change.settings, change.name, change.profile); issued = True
            entry = _desired(change.client, change.settings, change.command, token, change.profile)
            new_text, _ = _edit(change.format, change.container, text, entry)
        data = new_text.encode("utf-8")
        saved = backup(path, raw) if raw is not None and data != raw else None
        write_atomic(path, data)
    except BaseException:
        if issued:
            try: access.revoke(change.settings, change.name)
            except ValueError: pass
        raise
    return {"path": str(path), "action": "removed" if remove else change.action, "backup": str(saved) if saved else None, "token_issued": issued}


def _read_checked(path):
    try: return _read(path)
    except _Manual: raise RuntimeError("Cannot read " + str(path))
