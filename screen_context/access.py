"""Per-client tokens for the MCP server (roadmap decision 10, steps I and II).

`mcp-config` issues a random token for one client and stores only its SHA-256.
`serve` accepts a call only with a known, unrevoked token whose profile ceiling
covers the server's profile, and the audit log names the client from the token,
not from anything the client says about itself.

A new token starts as "pending". Its first tool call asks the user in the capture
app (menu bar or control window) whether this client may read the history; the app
records the decision. "denied" and "revoked" tokens are refused.

This identifies and gates clients. It does not stop malware running as the same
user, which can read the token from the client's configuration file.
"""
import hashlib
import hmac
import re
import secrets
import time
from . import audit, store
from .service import PROFILES, profile_name

TOKEN_ENV = "SCREEN_CONTEXT_CLIENT_TOKEN"
NAME = re.compile(r"[A-Za-z0-9._-]{1,64}")
MISSING = ("This MCP entry has no valid client token. Run `screen-context mcp-config --client <name>` "
           "again and replace the screen-context entry in your client's configuration.")
NO_APP = ("{name} needs your approval, but the ScreenContext app is not running. Start it and retry, "
          "or run `screen-context clients approve {name}`.")
WAITING = ("{name} is waiting for your approval in the ScreenContext app. Approve it there, "
           "or run `screen-context clients approve {name}`, then retry.")
DENIED = ("{name} was not allowed to read screen history. To connect it, run `screen-context mcp-config` "
          "again and replace the entry; the new token asks for approval again.")


def digest(token): return hashlib.sha256(token.encode()).hexdigest()


def issue(settings, name, profile="standard"):
    """Create or replace the token for `name`. The previous token stops working at once and the
    new one waits for the user's approval."""
    if not NAME.fullmatch(name or ""): raise ValueError("Client name must be 1–64 letters, digits, '.', '_' or '-'")
    profile = profile_name(profile)
    token = "sc_" + secrets.token_urlsafe(32)
    with store.connect(settings) as con:
        con.execute("""INSERT INTO clients (name, token_sha256, profile, state, created_at) VALUES (?, ?, ?, 'pending', ?)
                       ON CONFLICT(name) DO UPDATE SET token_sha256=excluded.token_sha256, profile=excluded.profile,
                       state='pending', created_at=excluded.created_at, approved_at=NULL, revoked_at=NULL""",
                    (name, digest(token), profile, time.time()))
    audit.record(settings, "user", "cli", "clients.issue", params={"name": name, "profile": profile})
    return token


def authenticate(settings, token, profile):
    """Client name for a live (active or pending) token that may use `profile`; PermissionError otherwise.
    Cheap and non-blocking: the HTTP gate calls it for every request."""
    if not token: raise PermissionError(MISSING)
    wanted = digest(token)
    with store.connect(settings, readonly=True) as con:
        rows = con.execute("SELECT name, profile, state, token_sha256 FROM clients").fetchall()
    # A SQL equality lookup on the digest column is not constant-time; compare every row so a
    # request's timing cannot be used to narrow down a valid token's digest byte by byte.
    row = next((r for r in rows if hmac.compare_digest(r["token_sha256"], wanted)), None)
    if row is None or row["state"] not in ("active", "pending"): raise PermissionError(MISSING)
    if PROFILES.index(profile_name(profile)) > PROFILES.index(row["profile"]):
        raise PermissionError(f"Client {row['name']} is limited to the {row['profile']} profile")
    return row["name"]


def state(settings, name):
    with store.connect(settings, readonly=True) as con:
        row = con.execute("SELECT state FROM clients WHERE name = ?", (name,)).fetchone()
    return row["state"] if row else None


def admit(settings, name, timeout=60):
    """Return `name` once the client is approved. A pending client triggers one approval dialog in
    the capture app and waits for the user's answer; tool calls run in worker threads, so waiting
    here does not stall other requests."""
    current = state(settings, name)
    if current == "active": return name
    if current != "pending": raise PermissionError(MISSING if current != "denied" else DENIED.format(name=name))
    from .broker import request_client
    from .health import lock_held
    if not lock_held(settings.root / "capture.lock"): raise PermissionError(NO_APP.format(name=name))
    current = request_client(settings, name, timeout)
    if current == "active": return name
    raise PermissionError((DENIED if current == "denied" else WAITING).format(name=name))


def authorize(settings, token, profile, timeout=60):
    return admit(settings, authenticate(settings, token, profile), timeout)


def pending_profile(settings, name):
    with store.connect(settings, readonly=True) as con:
        row = con.execute("SELECT profile FROM clients WHERE name = ? AND state = 'pending'", (name,)).fetchone()
    return row["profile"] if row else None


def decide(settings, name, allow, actor):
    """Record the user's answer for a pending client. `actor` is "app" (dialog) or "cli"."""
    with store.connect(settings) as con:
        changed = con.execute("UPDATE clients SET state=?, approved_at=? WHERE name=? AND state='pending'",
                              ("active" if allow else "denied", time.time() if allow else None, name)).rowcount
    if not changed: raise ValueError(f"No client named {name} is waiting for approval")
    audit.record(settings, "user", actor, "clients.approve" if allow else "clients.deny", params={"name": name})


def clients(settings):
    with store.connect(settings, readonly=True) as con:
        return [dict(r) for r in con.execute(
            """SELECT c.name, c.profile, c.state, c.created_at, c.revoked_at,
                      (SELECT max(ts) FROM audit a WHERE a.client = c.name AND a.path = 'agent') AS last_used
               FROM clients c ORDER BY c.name""")]


def revoke(settings, name):
    with store.connect(settings) as con:
        changed = con.execute("UPDATE clients SET state='revoked', revoked_at=? WHERE name=? AND state!='revoked'",
                              (time.time(), name)).rowcount
    if not changed: raise ValueError(f"No active client named {name}")
    audit.record(settings, "user", "cli", "clients.revoke", params={"name": name})
