"""Windows Secure Input check (#16): focused password field through UI Automation.
No real UI Automation, COM or desktop is touched. The COM objects are fake vtables built with ctypes."""
import ctypes
from types import SimpleNamespace

import pytest

from screen_context import capture
from screen_context.platforms import windows
from screen_context.platforms.windows import Backend, FocusPasswordProbe, UiaError

E_ACCESSDENIED = 0x80070005 - (1 << 32)       # as the signed 32-bit value ctypes returns
REGDB_E_CLASSNOTREG = 0x80040154 - (1 << 32)
RPC_E_CHANGED_MODE = 0x80010106 - (1 << 32)
KEEP = []  # ctypes callbacks and tables must outlive the test


def fake_object(slots):
    """Address of a COM object whose vtable holds a callback at each given slot number."""
    table = (ctypes.c_void_p * 64)()
    for index, (argument_types, function) in slots.items():
        callback = ctypes.CFUNCTYPE(ctypes.c_long, *argument_types)(function)
        KEEP.append(callback)
        table[index] = ctypes.cast(callback, ctypes.c_void_p).value
    holder = (ctypes.c_void_p * 1)(ctypes.addressof(table))
    KEEP.extend([table, holder])
    return ctypes.addressof(holder)


def fake_element(password, released, result=0):
    def get_flag(this, out):
        ctypes.cast(out, ctypes.POINTER(ctypes.c_int32))[0] = int(password); return result
    def release(this):
        released.append(this); return 0
    return fake_object({windows.VTABLE_GET_CURRENT_IS_PASSWORD: ([ctypes.c_void_p] * 2, get_flag),
                        windows.VTABLE_RELEASE: ([ctypes.c_void_p], release)})


def fake_automation(element, result=0):
    def focused(this, out):
        ctypes.cast(out, ctypes.POINTER(ctypes.c_void_p))[0] = element; return result
    return fake_object({windows.VTABLE_GET_FOCUSED_ELEMENT: ([ctypes.c_void_p] * 2, focused)})


class FakeOle:
    def __init__(self, automation, init=0, create=0):
        self.automation, self.init, self.create, self.calls = automation, init, create, []

    def CoInitializeEx(self, reserved, mode):
        self.calls.append(("init", mode)); return self.init

    def CoCreateInstance(self, clsid, outer, context, iid, out):
        self.calls.append(("create", bytes(clsid._obj), bytes(iid._obj), context))
        out.contents.value = self.automation
        return self.create


def names(ole): return [call[0] for call in ole.calls]


def test_the_interface_constants_are_the_documented_ones():
    # IUnknown takes slots 0-2. IUIAutomation: CompareElements 3, CompareRuntimeIds 4, GetRootElement 5,
    # ElementFromHandle 6, ElementFromPoint 7, GetFocusedElement 8. IUIAutomationElement: CurrentIsPassword is the 33rd method.
    assert (windows.VTABLE_RELEASE, windows.VTABLE_GET_FOCUSED_ELEMENT, windows.VTABLE_GET_CURRENT_IS_PASSWORD) == (2, 8, 35)
    clsid, iid = windows._GUID.parse(windows.CLSID_CUIAUTOMATION), windows._GUID.parse(windows.IID_IUIAUTOMATION)
    assert (clsid.Data1, clsid.Data2, clsid.Data3, bytes(clsid.Data4)) == (0xff48dba4, 0x60ef, 0x4201, bytes.fromhex("aa8754103eef594e"))
    assert (iid.Data1, iid.Data2, iid.Data3, bytes(iid.Data4)) == (0x30cbe57d, 0xd9d0, 0x452a, bytes.fromhex("ab137ac5ac4825ee"))
    assert ctypes.sizeof(clsid) == 16


@pytest.mark.parametrize("password", [True, False])
def test_reports_the_is_password_flag_and_releases_the_element(password):
    released = []
    element = fake_element(password, released)
    ole = FakeOle(fake_automation(element))
    assert FocusPasswordProbe(ole).focused_is_password() is password
    assert released == [element]
    assert ole.calls[0] == ("init", 0)  # multithreaded apartment
    assert ole.calls[1][1:] == (bytes(windows._GUID.parse(windows.CLSID_CUIAUTOMATION)), bytes(windows._GUID.parse(windows.IID_IUIAUTOMATION)), 1)


def test_a_failed_focus_query_releases_the_element_it_wrote():
    released = []
    element = fake_element(True, released)
    with pytest.raises(UiaError, match="GetFocusedElement"):
        FocusPasswordProbe(FakeOle(fake_automation(element, result=E_ACCESSDENIED))).focused_is_password()
    assert released == [element]


def test_a_32bit_process_is_refused_before_any_com_call(monkeypatch):
    real_sizeof = ctypes.sizeof
    monkeypatch.setattr(windows.ctypes, "sizeof", lambda obj: 4 if obj is ctypes.c_void_p else real_sizeof(obj))
    ole = FakeOle(fake_automation(0))
    with pytest.raises(UiaError, match="64-bit"):
        FocusPasswordProbe(ole).focused_is_password()
    assert ole.calls == []


def test_no_focused_element_is_not_a_password_field():
    assert FocusPasswordProbe(FakeOle(fake_automation(0))).focused_is_password() is False


def test_a_failing_property_read_raises_and_still_releases_the_element():
    released = []
    element = fake_element(True, released, result=E_ACCESSDENIED)
    with pytest.raises(UiaError, match="0x80070005"):
        FocusPasswordProbe(FakeOle(fake_automation(element))).focused_is_password()
    assert released == [element]


def test_a_failing_focus_query_raises():
    with pytest.raises(UiaError, match="GetFocusedElement"):
        FocusPasswordProbe(FakeOle(fake_automation(0, result=E_ACCESSDENIED))).focused_is_password()


@pytest.mark.parametrize("init", [0, 1, RPC_E_CHANGED_MODE])  # S_OK, S_FALSE, thread already a single-threaded apartment
def test_com_initialisation_results_that_are_not_errors(init):
    assert FocusPasswordProbe(FakeOle(fake_automation(0), init=init)).focused_is_password() is False


def test_a_failed_com_initialisation_raises():
    with pytest.raises(UiaError, match="CoInitializeEx"):
        FocusPasswordProbe(FakeOle(fake_automation(0), init=-2147024882)).focused_is_password()  # E_OUTOFMEMORY


def test_com_and_the_automation_object_are_created_once_per_thread():
    ole = FakeOle(fake_automation(0))
    probe = FocusPasswordProbe(ole)
    probe.focused_is_password(); probe.focused_is_password()
    assert names(ole) == ["init", "create"]


def test_unavailable_ui_automation_raises_every_time_and_recovers():
    ole = FakeOle(fake_automation(0), create=REGDB_E_CLASSNOTREG)
    probe = FocusPasswordProbe(ole)
    for _ in range(2):
        with pytest.raises(UiaError, match="0x80040154"): probe.focused_is_password()
    ole.create = 0
    assert probe.focused_is_password() is False
    assert names(ole) == ["init", "create", "create", "create"]


def test_backend_builds_the_probe_once_on_first_use(monkeypatch):
    made = []
    class Probe:
        def __init__(self): made.append(self)
        def focused_is_password(self): return True
    monkeypatch.setattr(windows, "FocusPasswordProbe", Probe)
    adapter = Backend.__new__(Backend)  # no Win32 handles needed
    assert made == []
    assert adapter.secure_input() is True and adapter.secure_input() is True
    assert len(made) == 1


@pytest.mark.parametrize("answer", [True, False])
def test_capture_follows_the_probe(answer):
    adapter = Backend.__new__(Backend)
    adapter._password_probe = SimpleNamespace(focused_is_password=lambda: answer)
    assert capture.secure_input(adapter) is answer


def test_capture_treats_a_failing_check_as_on_and_records_only_the_class_name():
    def fail(): raise UiaError("secret window title")
    adapter = Backend.__new__(Backend)
    adapter._password_probe = SimpleNamespace(focused_is_password=fail)
    assert capture._secure_input_state(adapter) == (True, "UiaError")
