"""Windows Hello and the sign-in password fallback (#33), with simulated WinRT and Win32; nothing
is shown and no real credential is checked."""
import asyncio
import ctypes
import sys
import time
from types import ModuleType, SimpleNamespace
import pytest
from test_core import settings, add
from screen_context import i18n, quick, reauth, store, windows_app  # imported before sys.platform is faked
from screen_context.platforms.windows import Backend

HELLO = "winrt.windows.security.credentials.ui"


def fake_hello(monkeypatch, availability, result=0, delay=0):
    asked = []

    class UserConsentVerifier:
        @staticmethod
        async def check_availability_async(): return availability
        @staticmethod
        async def request_verification_async(message):
            asked.append(message)
            await asyncio.sleep(delay)
            return result
    module = ModuleType(HELLO)
    module.UserConsentVerifier = UserConsentVerifier
    monkeypatch.setitem(sys.modules, HELLO, module)
    return asked


# --- Windows Hello -----------------------------------------------------------------------------

@pytest.mark.parametrize("result, status", [(0, reauth.VERIFIED), (6, reauth.CANCELLED), (5, reauth.FAILED),
                                            (4, reauth.FAILED), (1, reauth.FAILED), (99, reauth.FAILED)])
def test_hello_result(monkeypatch, result, status):
    asked = fake_hello(monkeypatch, availability=0, result=result)
    assert reauth.windows_hello("export your screen history") == status
    assert asked == ["export your screen history"]


@pytest.mark.parametrize("availability", [1, 2, 3])
def test_hello_not_set_up_or_disabled_by_policy(monkeypatch, availability):
    asked = fake_hello(monkeypatch, availability)
    assert reauth.windows_hello("x") == reauth.NOT_SET_UP and asked == []


def test_hello_busy_is_a_failure(monkeypatch):
    fake_hello(monkeypatch, availability=4)
    assert reauth.windows_hello("x") == reauth.FAILED


def test_hello_without_an_answer_in_time_is_cancelled(monkeypatch):
    fake_hello(monkeypatch, availability=0, result=0, delay=5)
    started = time.monotonic()
    assert reauth.windows_hello("x", timeout=.05) == reauth.CANCELLED
    assert time.monotonic() - started < 2


def test_hello_missing_falls_back(monkeypatch):
    monkeypatch.setitem(sys.modules, HELLO, None)       # import fails
    assert reauth.windows_hello("x") == reauth.NOT_SET_UP


@pytest.mark.parametrize("hello, password_used", [(reauth.VERIFIED, False), (reauth.CANCELLED, False),
                                                   (reauth.FAILED, False), (reauth.NOT_SET_UP, True)])
def test_password_only_when_hello_is_not_set_up(hello, password_used):
    used = []
    status = reauth.windows("x", hello=lambda text: hello, password=lambda text: used.append(text) or "from-password")
    assert (status == "from-password") is password_used and used == (["x"] if password_used else [])


# --- the sign-in password fallback -------------------------------------------------------------

class Fn:
    def __init__(self, body): self.body = body
    def __call__(self, *args): return self.body(*args)


class Win32:
    """credui, advapi32, kernel32 and ole32 as far as windows_password uses them."""
    def __init__(self, prompt=0, unpack=True, logon=True, same=True, user="PC\\alice", password="hunter2hunter2"):
        self.calls, self.freed, self.seen = [], [], {}
        self.packed = ctypes.create_string_buffer(b"secret-packed-credentials", 32)
        self.closed = []

        def prompt_fn(info, auth_error, package, in_buf, in_size, out_buf, out_size, save, flags):
            self.seen["flags"] = flags
            self.seen["message"] = info._obj.pszMessageText
            if prompt: return prompt
            out_buf._obj.value = ctypes.addressof(self.packed)
            out_size._obj.value = 32
            return 0

        def unpack_fn(flags, buf, size, user_buf, user_n, domain_buf, domain_n, pw_buf, pw_n):
            self.seen["pw_buf"] = pw_buf
            if not unpack: return False
            user_buf.value, domain_buf.value, pw_buf.value = user, "", password
            return True

        def logon_fn(name, domain, pw, kind, provider, token):
            self.calls.append(("logon", name, domain, pw if isinstance(pw, str) else pw.value, kind))
            if not logon: return False
            token._obj.value = 1001
            return True

        def open_token(process, access, token):
            token._obj.value = 1002
            return True

        sids = {1001: 0x5100, 1002: 0x5100 if same else 0x5200}

        def token_info(handle, kind, buffer, size, needed):
            handle = handle.value if hasattr(handle, "value") else handle
            if buffer is None:
                needed._obj.value = 16
                return False
            ctypes.memmove(buffer, ctypes.byref(ctypes.c_void_p(sids[handle])), ctypes.sizeof(ctypes.c_void_p))
            return True

        self.dlls = {
            "credui": SimpleNamespace(CredUIPromptForWindowsCredentialsW=Fn(prompt_fn), CredUnPackAuthenticationBufferW=Fn(unpack_fn)),
            "advapi32": SimpleNamespace(LogonUserW=Fn(logon_fn), OpenProcessToken=Fn(open_token),
                                        GetTokenInformation=Fn(token_info), EqualSid=Fn(lambda a, b: a == b)),
            "kernel32": SimpleNamespace(GetCurrentProcess=Fn(lambda: -1),
                                        CloseHandle=Fn(lambda h: self.closed.append(h.value if hasattr(h, "value") else h) or True)),
            "ole32": SimpleNamespace(CoTaskMemFree=Fn(lambda p: self.freed.append(p.value if hasattr(p, "value") else p))),
        }

    def __call__(self, name): return self.dlls[name]


def test_password_verified_for_the_same_user_and_wiped():
    win = Win32()
    assert reauth.windows_password("back up your screen history", dll=win) == reauth.VERIFIED
    assert win.calls == [("logon", "alice", "PC", "hunter2hunter2", 2)]      # interactive logon, domain split
    assert win.seen["flags"] == 0x200 and win.seen["message"] == "back up your screen history"  # current user only
    assert win.seen["pw_buf"].value == "" and win.packed.raw == b"\x00" * 32   # password and packed buffer zeroed
    assert win.freed == [ctypes.addressof(win.packed)] and 1001 in win.closed and 1002 in win.closed


@pytest.mark.parametrize("win, status", [
    (Win32(prompt=1223), reauth.CANCELLED),
    (Win32(prompt=5), reauth.FAILED),
    (Win32(unpack=False), reauth.FAILED),
    (Win32(logon=False), reauth.FAILED),
    (Win32(same=False), reauth.FAILED),                                       # another account's password
])
def test_password_refusals(win, status):
    assert reauth.windows_password("x", dll=win) == status
    if win.freed: assert win.packed.raw == b"\x00" * 32


@pytest.mark.parametrize("name, domain, expected", [
    ("PC\\alice", "", ("alice", "PC")), ("alice", "", ("alice", None)), ("alice@example.com", "", ("alice@example.com", None)),
    ("MicrosoftAccount\\alice@example.com", "", ("alice@example.com", "MicrosoftAccount")), ("alice", "CORP", ("alice", "CORP")),
])
def test_split_user(name, domain, expected):
    assert reauth.split_user(name, domain) == expected


def test_the_windows_adapter_answers_requests(monkeypatch):
    monkeypatch.setattr(reauth, "windows", lambda text: "verified:" + text)
    assert Backend.authenticate(Backend.__new__(Backend), "open your screen history") == "verified:open your screen history"


# --- messages name the platform's check ---------------------------------------------------------

@pytest.mark.parametrize("platform, en, ja", [("darwin", "Touch ID or your password", "Touch ID またはパスワード"),
                                              ("win32", "Windows Hello or your Windows password", "Windows Hello または Windows のパスワード")])
def test_messages_name_the_platform_check(monkeypatch, platform, en, ja):
    monkeypatch.setattr(sys, "platform", platform)
    keys = [k for k in i18n.MESSAGES["en"] if k.startswith("ui.reauth.") or k.startswith("auth.refused.")]
    assert keys
    for key in keys:
        assert en in i18n.auth(key, "en") and ja in i18n.auth(key, "ja") and "{" not in i18n.auth(key, "ja")


# --- control window shortcuts --------------------------------------------------------------------

def test_delete_recent_asks_then_deletes(settings):
    add(settings, "by mistake", ts=time.time() - 30)
    told, asked = [], []
    assert quick.delete_recent(settings, 5, "en", lambda title, body: asked.append(title) or False, told.append) is None
    with store.connect(settings, readonly=True) as con: assert con.execute("SELECT count(*) FROM frames").fetchone()[0] == 1
    result = quick.delete_recent(settings, 5, "en", lambda title, body: True, told.append)
    assert result["frames"] == 1 and told == ["Deleted 1 screens."] and asked == ["Delete what was recorded in the last 5 min?"]
    with store.connect(settings, readonly=True) as con: assert con.execute("SELECT count(*) FROM frames").fetchone()[0] == 0


def test_delete_recent_with_nothing_to_delete_does_not_ask(settings):
    told = []
    assert quick.delete_recent(settings, 60, "en", lambda *a: pytest.fail("asked"), told.append) is None
    assert told == ["Nothing was recorded in the last hour."]


def test_open_today_on_windows_starts_the_cli_without_a_console(settings, monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "ScreenContext" / "ScreenContext.exe"))
    spawned = []
    assert quick.open_today(settings, lambda: "verified", spawn=lambda cmd, **kw: spawned.append((cmd, kw))) == "verified"
    cmd, kw = spawned[0]
    assert cmd == [str(tmp_path / "screen-context" / "screen-context.exe"), "ui"]
    assert kw["creationflags"] == 0x08000000 and kw["env"]["SCREEN_CONTEXT_HOME"] == str(settings.root)
