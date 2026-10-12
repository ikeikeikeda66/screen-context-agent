"""Capture process with bounded, atomic spool."""
import io
import json
import time
import uuid
from . import store
from .crypto import atomic_write, get_key, seal
from .privacy import denied


def dhash(image):
    from PIL import Image
    px = list(image.convert("L").resize((9, 8), Image.Resampling.BILINEAR).tobytes())
    result = 0
    for y in range(8):
        for x in range(8): result = (result << 1) | int(px[y*9+x] > px[y*9+x+1])
    return result


def spool(settings, image, metadata):
    record = {**metadata, "id": uuid.uuid4().hex, "ts": time.time(), "dhash": str(dhash(image))}
    if denied(settings.policy(), record): return None
    buf = io.BytesIO(); image.save(buf, "PNG")
    data = json.dumps(record, ensure_ascii=False).encode() + b"\n" + buf.getvalue()
    if not settings.plaintext: data = seal(data, get_key(settings))
    atomic_write(settings.root / "spool" / (record["id"] + ".frame"), data)
    return record


def locked(adapter):
    """Platforms that can tell report a locked session; capture is skipped until it unlocks."""
    check = getattr(adapter, "session_locked", None)
    return bool(check and check())


def _secure_input_state(adapter):
    """(on, error_type): error_type names the exception class when the check failed, never its message."""
    check = getattr(adapter, "secure_input", None)
    if check is None: return False, None
    try: return bool(check()), None
    except Exception as error: return True, type(error).__name__


def secure_input(adapter):
    """True while the OS says a secure field has the keyboard (#16). A platform without the check reports False;
    a check that fails reports True, so a failure never turns into a capture."""
    return _secure_input_state(adapter)[0]


def _secure_skip(settings, adapter):
    """Count and record a capture cycle that Secure Input stops (#16). Returns True when the cycle was skipped.
    Called before the capture and again right after it, so a field that gets focus mid-capture drops the image."""
    on, error_type = _secure_input_state(adapter)
    if not on: return False
    # Only the reason is kept: nothing about the window that was not captured (#16).
    status = {"ts": time.time(), "status": "secure_input"}
    if error_type: status["error_type"] = error_type
    atomic_write(settings.root / "capture-status.json", json.dumps(status).encode())
    store.record_skip(settings, "secure_input")
    return True


def backend():
    import sys
    if sys.platform == "darwin":
        from .platforms.macos import Backend
    elif sys.platform == "win32":
        from .platforms.windows import Backend
    else: raise RuntimeError("Capture requires macOS 14+ or Windows")
    return Backend()


def run(settings, once=False, stop=None):
    import threading
    stop = stop or threading.Event()
    adapter = backend()
    previous_hash, previous_identity, last_saved = None, None, 0
    last_probe = None
    from .sessions import Presence
    presence = Presence(settings, adapter)
    while not stop.is_set():
        from .broker import process_client_requests, process_requests
        process_client_requests(settings, adapter)
        from .i18n import resolve
        from .reauth import process_requests as process_reauth
        process_reauth(settings, adapter, resolve(settings))
        presence.tick(paused=(settings.root / "paused").exists())
        if (settings.root / "paused").exists():
            last_probe = None
            if once: return {"status": "paused"}
            stop.wait(1); continue
        process_requests(settings, adapter)
        interval = settings.capture_interval()
        if not once and last_probe is not None and time.monotonic() < last_probe + interval:
            stop.wait(1); continue
        last_probe = time.monotonic()
        queued = list((settings.root / "spool").glob("*.frame"))
        if len(queued) >= 100 or sum(p.stat().st_size for p in queued) > 512*1024*1024:
            if once: return {"status": "queue_full"}
            stop.wait(1); continue
        front = adapter.foreground()
        if stop.is_set() or (settings.root / "paused").exists():
            if once: return {"status": "paused"}
            continue
        if denied(settings.policy(), front):
            previous_identity = None
            if once: return {"status": "excluded"}
            stop.wait(1); continue
        if locked(adapter):
            previous_identity = None
            if once: return {"status": "locked"}
            stop.wait(1); continue
        if _secure_skip(settings, adapter):
            previous_identity = None
            if once: return {"status": "secure_input"}
            stop.wait(1); continue
        try:
            image, meta = adapter.capture(front)
        except Exception as error:
            atomic_write(settings.root / "capture-status.json", json.dumps({"ts": time.time(), "status": "error", "error_type": type(error).__name__}).encode())
            if once: raise
            stop.wait(1); continue
        # The field may have taken focus during the capture: the image is dropped, never spooled.
        if _secure_skip(settings, adapter):
            previous_identity = None
            if once: return {"status": "secure_input"}
            stop.wait(1); continue
        if adapter.foreground() != front:
            if once: return {"status": "foreground_changed"}
            stop.wait(1); continue
        current = dhash(image)
        identity = (front["app_bundle"], front["window_title"], front.get("window_id"))
        changed = previous_hash is None or (current ^ previous_hash).bit_count() > 6
        idle = adapter.idle_seconds() > 120
        due = identity != previous_identity or changed or (not idle and time.monotonic()-last_saved >= 300)
        if once or due:
            result = spool(settings, image, {**front, **meta})
            atomic_write(settings.root / "capture-status.json", json.dumps({"ts": time.time(), "status": "spooled" if result else "excluded", "app_bundle": front["app_bundle"]}).encode())
            previous_hash, previous_identity, last_saved = current, identity, time.monotonic()
            if once: return {"status": "spooled" if result else "excluded", "frame_id": result["id"] if result else None}
        stop.wait(1)
