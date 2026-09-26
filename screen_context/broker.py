"""Local approval by the user in the capture app: current-screen requests (every call) and new
MCP clients (once per token). No capture API is imported in the MCP process."""
import hashlib
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


def request_client(settings, name, timeout=60, poll=.25):
    """Ask the capture app to show the new-client dialog and wait for the recorded answer.
    Concurrent calls from one client share one request file, so the user sees one dialog.
    Returns the client's state: "active", "denied", or "pending" when nobody answered in time."""
    from .access import state
    path = settings.root / "requests" / (hashlib.sha256(name.encode()).hexdigest()[:32] + ".client")
    deadline = time.time() + timeout

    def shared_expiry():
        try: return float(json.loads(path.read_text())["expires"])
        except (OSError, ValueError, KeyError): return 0.0

    # A later caller with a longer timeout must extend the shared deadline, or its own wait
    # would be cut short by an earlier caller's cleanup once that caller's deadline passes.
    if deadline > shared_expiry(): atomic_write(path, json.dumps({"name": name, "expires": deadline}).encode())
    try:
        while time.time() < deadline:
            current = state(settings, name)
            if current != "pending": return current
            time.sleep(poll)
        return state(settings, name)
    finally:
        # Only withdraw the request once the shared (possibly extended) deadline has passed,
        # so a shorter-timeout caller giving up does not withdraw it for a longer-timeout one.
        if state(settings, name) == "pending" and time.time() >= shared_expiry(): path.unlink(missing_ok=True)


def process_client_requests(settings, adapter):
    """Runs in the capture app, also while capture is paused: approving a client captures nothing.
    The profile shown comes from the database, never from the request file."""
    from .access import decide, pending_profile
    ask = getattr(adapter, "approve_client", None)
    for path in sorted((settings.root / "requests").glob("*.client")):
        try:
            request = json.loads(path.read_text())
            name, expires = request["name"], float(request["expires"])
            if not isinstance(name, str): raise TypeError
        except (OSError, ValueError, KeyError, TypeError):
            path.unlink(missing_ok=True); continue
        if expires <= time.time():
            path.unlink(missing_ok=True); continue
        if ask is None: continue  # this platform cannot ask; the waiting call times out
        try:
            profile = pending_profile(settings, name)
            if profile is not None: decide(settings, name, bool(ask(name, profile)), "app")
        except Exception:
            pass  # a failure approves nothing: the client stays pending or its call times out
        finally:
            path.unlink(missing_ok=True)


def process_requests(settings, adapter):
    from .capture import spool
    for path in sorted((settings.root / "requests").glob("*.request")):
        reply = path.with_suffix(".reply")
        if reply.exists(): continue
        try:
            req = json.loads(path.read_text())
            if req["expires"] <= time.time():
                path.unlink(missing_ok=True); continue
            from .capture import locked
            target = adapter.foreground()
            # Nobody can approve on a locked screen, and capturing then can crash the capture library (#47).
            allowed = not locked(adapter) and not denied(settings.policy(), target) and adapter.approve_current()
            result = {"status": "denied"}
            # Capture the exact window selected before the dialog, never the dialog itself.
            if allowed and path.exists() and time.time() < req["expires"] and not (settings.root / "paused").exists():
                image, metadata = adapter.capture(target)
                frame = spool(settings, image, {**target, **metadata})
                if frame: result = {"status": "approved", "frame_id": frame["id"]}
            if path.exists(): atomic_write(reply, json.dumps(result).encode())
        except Exception:
            if path.exists(): atomic_write(reply, b'{"status":"denied"}')
