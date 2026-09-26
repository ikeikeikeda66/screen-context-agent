"""Per-client tokens for the MCP server (roadmap decision 10, step I).

`mcp-config` issues a random token for one client and stores only its SHA-256.
`serve` accepts a call only with a known, unrevoked token whose profile ceiling
covers the server's profile, and the audit log names the client from the token,
not from anything the client says about itself.

This identifies and gates clients. It does not stop malware running as the same
user, which can read the token from the client's configuration file.
"""
import hashlib
import re
import secrets
import time
from . import audit, store
from .service import PROFILES, profile_name

TOKEN_ENV = "SCREEN_CONTEXT_CLIENT_TOKEN"
NAME = re.compile(r"[A-Za-z0-9._-]{1,64}")
MISSING = ("This MCP entry has no valid client token. Run `screen-context mcp-config --client <name>` "
           "again and replace the screen-context entry in your client's configuration.")


def digest(token): return hashlib.sha256(token.encode()).hexdigest()


def issue(settings, name, profile="standard"):
    """Create or replace the token for `name`. The previous token stops working at once."""
    if not NAME.fullmatch(name or ""): raise ValueError("Client name must be 1–64 letters, digits, '.', '_' or '-'")
    profile = profile_name(profile)
    token = "sc_" + secrets.token_urlsafe(32)
    with store.connect(settings) as con:
        con.execute("""INSERT INTO clients (name, token_sha256, profile, state, created_at) VALUES (?, ?, ?, 'active', ?)
                       ON CONFLICT(name) DO UPDATE SET token_sha256=excluded.token_sha256, profile=excluded.profile,
                       state='active', created_at=excluded.created_at, approved_at=NULL, revoked_at=NULL""",
                    (name, digest(token), profile, time.time()))
    audit.record(settings, "user", "cli", "clients.issue", params={"name": name, "profile": profile})
    return token


def authenticate(settings, token, profile):
    """Client name for a token that may use `profile`; PermissionError otherwise."""
    if not token: raise PermissionError(MISSING)
    with store.connect(settings, readonly=True) as con:
        row = con.execute("SELECT name, profile, state FROM clients WHERE token_sha256 = ?", (digest(token),)).fetchone()
    if row is None or row["state"] != "active": raise PermissionError(MISSING)
    if PROFILES.index(profile_name(profile)) > PROFILES.index(row["profile"]):
        raise PermissionError(f"Client {row['name']} is limited to the {row['profile']} profile")
    return row["name"]


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
