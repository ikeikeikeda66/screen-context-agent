"""Re-authentication (#27, #33, roadmap decision 10): Touch ID or Windows Hello, or the sign-in
password when neither is set up, before opening the Today view and before sensitive changes made in it.

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


# Windows Hello (UserConsentVerifier). Availability and result values of the WinRT enums.
HELLO_AVAILABLE, HELLO_NOT_SET_UP = 0, {1, 2, 3}  # DeviceNotPresent, NotConfiguredForUser, DisabledByPolicy
HELLO_VERIFIED, HELLO_CANCELED = 0, 6
NOT_SET_UP = "not_set_up"


def windows_hello(reason_text, timeout=120):
    """Ask with Windows Hello (face, fingerprint or PIN). Returns VERIFIED, CANCELLED, FAILED, or
    NOT_SET_UP when this PC or account has no Hello, so the caller can fall back to the password."""
    import asyncio
    try: from winrt.windows.security.credentials.ui import UserConsentVerifier
    except ImportError: return NOT_SET_UP

    async def ask():
        available = int(await UserConsentVerifier.check_availability_async())
        if available in HELLO_NOT_SET_UP: return NOT_SET_UP
        if available != HELLO_AVAILABLE: return FAILED  # DeviceBusy
        try: result = int(await asyncio.wait_for(UserConsentVerifier.request_verification_async(reason_text), timeout))
        except asyncio.TimeoutError: return CANCELLED
        return VERIFIED if result == HELLO_VERIFIED else CANCELLED if result == HELLO_CANCELED else FAILED
    return asyncio.run(ask())


def windows_password(reason_text, dll=None):
    """Ask for the Windows sign-in password of the current user and check it with LogonUserW. Only a
    logon as this same user (same SID) counts. The password buffers are zeroed before returning."""
    import ctypes
    from ctypes import byref, wintypes
    dll = dll or ctypes.WinDLL
    credui, advapi, kernel, ole32 = dll("credui"), dll("advapi32"), dll("kernel32"), dll("ole32")
    declare(credui, advapi, kernel, ole32)

    class Info(ctypes.Structure):  # CREDUI_INFOW
        _fields_ = [("cbSize", wintypes.DWORD), ("hwndParent", wintypes.HWND), ("pszMessageText", wintypes.LPCWSTR),
                    ("pszCaptionText", wintypes.LPCWSTR), ("hbmBanner", wintypes.HANDLE)]
    info = Info(ctypes.sizeof(Info), None, reason_text, "ScreenContext", None)
    package, packed, packed_size, save = wintypes.ULONG(0), ctypes.c_void_p(), wintypes.ULONG(0), wintypes.BOOL(False)
    # CREDUIWIN_ENUMERATE_CURRENT_USER: offer only the signed-in user.
    error = credui.CredUIPromptForWindowsCredentialsW(byref(info), 0, byref(package), None, 0, byref(packed), byref(packed_size), byref(save), 0x200)
    if error == 1223: return CANCELLED  # ERROR_CANCELLED
    if error: return FAILED
    user, domain, password = ctypes.create_unicode_buffer(514), ctypes.create_unicode_buffer(338), ctypes.create_unicode_buffer(257)
    try:
        sizes = [wintypes.DWORD(len(b)) for b in (user, domain, password)]
        # CRED_PACK_PROTECTED_CREDENTIALS: also unpack a protected password.
        if not credui.CredUnPackAuthenticationBufferW(1, packed, packed_size, user, byref(sizes[0]), domain, byref(sizes[1]), password, byref(sizes[2])):
            return FAILED
        name, where = split_user(user.value, domain.value)
        token = wintypes.HANDLE()
        if not advapi.LogonUserW(name, where, password, 2, 0, byref(token)): return FAILED  # interactive, default provider
        try: return VERIFIED if same_user(advapi, kernel, token) else FAILED
        finally: kernel.CloseHandle(token)
    finally:
        ctypes.memset(password, 0, ctypes.sizeof(password))
        if packed.value:
            ctypes.memset(packed.value, 0, packed_size.value)
            ole32.CoTaskMemFree(packed)


def declare(credui, advapi, kernel, ole32):
    """Prototypes, so handles and pointers keep their full width on 64-bit Windows."""
    import ctypes
    from ctypes import POINTER, c_void_p, wintypes
    DW, H = wintypes.DWORD, wintypes.HANDLE
    for fn, args, result in [
        (credui.CredUIPromptForWindowsCredentialsW, [c_void_p, DW, POINTER(wintypes.ULONG), c_void_p, wintypes.ULONG,
                                                     POINTER(c_void_p), POINTER(wintypes.ULONG), POINTER(wintypes.BOOL), DW], DW),
        (credui.CredUnPackAuthenticationBufferW, [DW, c_void_p, DW, wintypes.LPWSTR, POINTER(DW), wintypes.LPWSTR, POINTER(DW),
                                                  wintypes.LPWSTR, POINTER(DW)], wintypes.BOOL),
        (advapi.LogonUserW, [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, DW, DW, POINTER(H)], wintypes.BOOL),
        (advapi.OpenProcessToken, [H, DW, POINTER(H)], wintypes.BOOL),
        (advapi.GetTokenInformation, [H, ctypes.c_int, c_void_p, DW, POINTER(DW)], wintypes.BOOL),
        (advapi.EqualSid, [c_void_p, c_void_p], wintypes.BOOL),
        (kernel.GetCurrentProcess, [], H),
        (kernel.CloseHandle, [H], wintypes.BOOL),
        (ole32.CoTaskMemFree, [c_void_p], None),
    ]:
        fn.argtypes, fn.restype = args, result


def split_user(name, domain):
    """User and domain for LogonUserW: "DOMAIN\\user" is split; "user@example.com" stays whole."""
    if not domain and "\\" in name: domain, name = name.split("\\", 1)
    return name, domain or None


def same_user(advapi, kernel, token):
    import ctypes
    from ctypes import byref, wintypes
    current = wintypes.HANDLE()
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 0x8, byref(current)): return False  # TOKEN_QUERY
    try:
        buffers = []
        for handle in (token, current):
            size = wintypes.DWORD(0)
            advapi.GetTokenInformation(handle, 1, None, 0, byref(size))  # TokenUser; learns the size
            buffer = ctypes.create_string_buffer(size.value or 1)
            if not advapi.GetTokenInformation(handle, 1, buffer, size, byref(size)): return False
            buffers.append(buffer)
        sids = [ctypes.cast(b, ctypes.POINTER(ctypes.c_void_p))[0] for b in buffers]  # TOKEN_USER.User.Sid
        return bool(advapi.EqualSid(sids[0], sids[1]))
    finally: kernel.CloseHandle(current)


def windows(reason_text, hello=windows_hello, password=windows_password):
    """Windows Hello, or the sign-in password when Hello is not set up (or disabled by policy)."""
    status = hello(reason_text)
    return password(reason_text) if status == NOT_SET_UP else status


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
