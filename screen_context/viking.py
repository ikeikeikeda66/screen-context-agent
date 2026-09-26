"""Explicit, bounded daily export and local Viking push."""
import hashlib
import json
import os
import urllib.request
from urllib.parse import urlsplit
from .crypto import atomic_write
from .service import Service, day_range


def export(settings, day):
    day_range(day)
    payload = Service(settings, "full", "viking-export", audit_path="user").get_daily_rollup(day)
    content = json.dumps(payload, ensure_ascii=False, indent=2).encode()
    path = settings.root / "exports" / (day + ".json")
    atomic_write(path, content)
    return path


def push(settings, day, endpoint="http://127.0.0.1:1933", timeout=30):
    if urlsplit(endpoint).hostname not in ("localhost", "127.0.0.1", "::1"): raise ValueError("Viking endpoint must be local")
    path = export(settings, day)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    receipt = path.with_suffix(".receipt")
    if receipt.exists() and receipt.read_text() == digest: return {"status": "unchanged"}
    data = json.dumps({"path": str(path), "to": "viking://resources/screen_context/" + day, "wait": True, "timeout": timeout, "reason": "Untrusted daily screen observations"}).encode()
    req = urllib.request.Request(endpoint.rstrip("/") + "/api/v1/resources", data=data, headers={"Content-Type": "application/json", "X-API-Key": os.environ.get("VIKING_API_KEY", "")}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout+5) as res: result = json.load(res)
    if result.get("status") not in ("success", "ok"): raise RuntimeError("Viking did not confirm success")
    atomic_write(receipt, digest.encode())
    return {"status": "uploaded", "date": day}
