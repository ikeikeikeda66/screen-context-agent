"""Explicit, bounded daily export and local Viking push."""
import hashlib
import json
import os
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from . import audit
from .crypto import atomic_write
from .service import Service, day_range


def export(settings, day, folder=None, audited=True):
    """Daily rollup as JSON. Audited with the day's frame IDs, like other exports, unless the caller
    (export.write) records one row for the whole range itself."""
    start, end = day_range(day)
    service = Service(settings, "full", "viking-export", audit_path=None)
    payload = service.get_daily_rollup(day)
    content = json.dumps(payload, ensure_ascii=False, indent=2).encode()
    path = (folder or settings.root / "exports") / (day + ".json")
    atomic_write(path, content)
    if audited:
        ids = [r["id"] for r in service.rows(start, end)]
        audit.record(settings, "user", "cli", "export", params={"format": "viking", "day": day, "paths": [str(path)]},
                     frame_ids=ids, count=len(ids))
    return path


LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect would carry X-API-Key to wherever it points, possibly off this machine (#73)."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "Viking endpoint redirected; not followed", headers, fp)


def local_opener():
    """No proxy (HTTP_PROXY would otherwise receive the key) and no redirects."""
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())


def push(settings, day, endpoint="http://127.0.0.1:1933", timeout=30, opener=None):
    """Send one day's rollup to a local OpenViking server, only when the user runs `push DATE`.
    VIKING_API_KEY, if set, goes only to that loopback endpoint: no proxy, no redirects."""
    parts = urlsplit(endpoint)
    if parts.scheme not in ("http", "https") or parts.hostname not in LOCAL_HOSTS: raise ValueError("Viking endpoint must be local")
    path = export(settings, day)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    receipt = path.with_suffix(".receipt")
    if receipt.exists() and receipt.read_text() == digest: return {"status": "unchanged"}
    data = json.dumps({"path": str(path), "to": "viking://resources/screen_context/" + day, "wait": True, "timeout": timeout, "reason": "Untrusted daily screen observations"}).encode()
    headers = {"Content-Type": "application/json"}
    if os.environ.get("VIKING_API_KEY"): headers["X-API-Key"] = os.environ["VIKING_API_KEY"]
    req = urllib.request.Request(endpoint.rstrip("/") + "/api/v1/resources", data=data, headers=headers, method="POST")
    with (opener or local_opener()).open(req, timeout=timeout+5) as res: result = json.load(res)
    if result.get("status") not in ("success", "ok"): raise RuntimeError("Viking did not confirm success")
    atomic_write(receipt, digest.encode())
    return {"status": "uploaded", "date": day}
