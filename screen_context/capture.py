"""Capture process with bounded, atomic spool."""
import io
import json
import time
import uuid
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
    while not stop.is_set():
        from .broker import process_client_requests, process_requests
        process_client_requests(settings, adapter)
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
        try:
            image, meta = adapter.capture(front)
        except Exception as error:
            atomic_write(settings.root / "capture-status.json", json.dumps({"ts": time.time(), "status": "error", "error_type": type(error).__name__}).encode())
            if once: raise
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
