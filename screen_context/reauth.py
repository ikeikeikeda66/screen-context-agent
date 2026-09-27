"""Re-authentication (#27, roadmap decision 10): Touch ID, or the login password when Touch ID is
unavailable, before opening the Today view and before sensitive changes made in it.

Only the capture app asks. The UI process requests a check through a file in requests/ and waits
for the app's answer (`request`, `process_requests`), like new-client approval. The request names a
reason from a fixed list, never free text, so the UI cannot choose what the prompt says. Platforms
without an authenticator answer "unavailable" and the change is refused.

Programs running as the same user can write these files too; they are outside the threat model
(they can already read the key).
"""
import json
import threading
import time
import uuid
from .crypto import atomic_write

VERIFIED, CANCELLED, FAILED, UNAVAILABLE, NO_APP, TIMEOUT = "verified", "cancelled", "failed", "unavailable", "no_app", "timeout"
REASONS = ("open", "export", "backup", "approve")
OWNER_POLICY = 2  # LAPolicyDeviceOwnerAuthentication: Touch ID with the password as fallback
CANCEL_CODES = {-2, -4, -9}  # userCancel, systemCancel, appCancel


def touch_id(reason_text, timeout=120):
    """Ask on macOS with LocalAuthentication. Returns one of VERIFIED, CANCELLED, FAILED, UNAVAILABLE."""
    try:
        import LocalAuthentication
        from Foundation import NSDate, NSRunLoop
    except ImportError:
        return UNAVAILABLE
    context = LocalAuthentication.LAContext.alloc().init()
    available, _ = context.canEvaluatePolicy_error_(OWNER_POLICY, None)
    if not available: return UNAVAILABLE
    done, reply = threading.Event(), {}

    def finished(success, error):
        reply["status"] = VERIFIED if success else CANCELLED if error is not None and int(error.code()) in CANCEL_CODES else FAILED
        done.set()

    context.evaluatePolicy_localizedReason_reply_(OWNER_POLICY, reason_text, finished)
    deadline = time.monotonic() + timeout
    while not done.is_set() and time.monotonic() < deadline:
        # The reply arrives on a private queue; keep this thread's run loop turning so the prompt shows.
        NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.1))
    if not done.is_set():
        context.invalidate()
        return CANCELLED
    return reply["status"]


def request(settings, reason, timeout=120, poll=.25):
    """From the UI process: have the capture app ask the user. Returns the app's answer, NO_APP when
    the app is not running, or TIMEOUT."""
    if reason not in REASONS: raise ValueError("Unknown re-authentication reason")
    from .health import lock_held
    if not lock_held(settings.root / "capture.lock"): return NO_APP
    path = settings.root / "requests" / (uuid.uuid4().hex + ".auth")
    reply = path.with_suffix(".authreply")
    deadline = time.time() + timeout
    atomic_write(path, json.dumps({"reason": reason, "expires": deadline}).encode())
    try:
        while time.time() < deadline:
            if reply.exists():
                try: return json.loads(reply.read_text())["status"]
                except (OSError, ValueError, KeyError): return FAILED
            time.sleep(poll)
        return TIMEOUT
    finally:
        path.unlink(missing_ok=True)
        reply.unlink(missing_ok=True)


def process_requests(settings, adapter, lang):
    """In the capture app (also while paused): answer each pending request by asking the user."""
    from .i18n import t
    ask = getattr(adapter, "authenticate", None)
    for path in sorted((settings.root / "requests").glob("*.auth")):
        reply = path.with_suffix(".authreply")
        if reply.exists(): continue
        try:
            wanted = json.loads(path.read_text())
            reason, expires = wanted["reason"], float(wanted["expires"])
            if reason not in REASONS: raise ValueError
        except (OSError, ValueError, KeyError, TypeError):
            path.unlink(missing_ok=True); continue
        if expires <= time.time():
            path.unlink(missing_ok=True); continue
        try: status = ask(t("auth.reason." + reason, lang)) if ask else UNAVAILABLE
        except Exception: status = FAILED
        if path.exists(): atomic_write(reply, json.dumps({"status": status}).encode())
