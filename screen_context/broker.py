"""Per-call local approval. No capture API is imported in the MCP process."""
import json
import time
import uuid
from .crypto import atomic_write
from .privacy import denied


def request_current(service, timeout=90):
    service.require_full()
    settings = service.settings
    request_id = uuid.uuid4().hex
    path = settings.root / "requests" / (request_id + ".request")
    reply = path.with_suffix(".reply")
    expires = time.time() + timeout
    atomic_write(path, json.dumps({"expires": expires}).encode())
    try:
        while time.time() < expires:
            if reply.exists():
                result = json.loads(reply.read_text())
                if result.get("status") != "approved":
                    service.finish([], "get_current_screen", {"status": "denied"})
                    raise PermissionError("Local approval denied or capture excluded")
                from . import store
                with store.connect(settings, readonly=True) as con:
                    ready = con.execute("SELECT 1 FROM frames WHERE id=?", (result["frame_id"],)).fetchone()
                if ready:
                    data = service.get_snapshot_image(result["frame_id"])
                    service.finish([{"frame_id": result["frame_id"]}], "get_current_screen", {"status": "approved"})
                    return data
            time.sleep(.25)
        service.finish([], "get_current_screen", {"status": "timeout"})
        raise TimeoutError("No approved indexed capture within the deadline")
    finally:
        path.unlink(missing_ok=True)
        reply.unlink(missing_ok=True)


def process_requests(settings, adapter):
    from .capture import spool
    for path in sorted((settings.root / "requests").glob("*.request")):
        reply = path.with_suffix(".reply")
        if reply.exists(): continue
        try:
            req = json.loads(path.read_text())
            if req["expires"] <= time.time():
                path.unlink(missing_ok=True); continue
            target = adapter.foreground()
            allowed = not denied(settings.policy(), target) and adapter.approve_current()
            result = {"status": "denied"}
            # Capture the exact window selected before the dialog, never the dialog itself.
            if allowed and path.exists() and time.time() < req["expires"] and not (settings.root / "paused").exists():
                image, metadata = adapter.capture(target)
                frame = spool(settings, image, {**target, **metadata})
                if frame: result = {"status": "approved", "frame_id": frame["id"]}
            if path.exists(): atomic_write(reply, json.dumps(result).encode())
        except Exception:
            if path.exists(): atomic_write(reply, b'{"status":"denied"}')
