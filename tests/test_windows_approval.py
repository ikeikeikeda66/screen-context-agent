"""#50: a MessageBoxW from a windowless worker process cannot take the foreground on its own
(Windows' foreground-lock blocks SetForegroundWindow from background processes); attaching our
thread's input queue to the foreground window's lets MB_SETFOREGROUND actually work."""
from types import SimpleNamespace
from screen_context.platforms.windows import Backend


def make_adapter(foreground_hwnd, foreground_thread, this_thread, attach_result=True):
    calls = []
    user = SimpleNamespace(
        GetForegroundWindow=lambda: foreground_hwnd,
        GetWindowThreadProcessId=lambda hwnd, pid: foreground_thread,
        AttachThreadInput=lambda a, b, attach: (calls.append(("attach", a, b, attach)), attach_result)[1],
        MessageBoxW=lambda owner, text, title, flags: (calls.append(("messagebox", text)), 6)[1],
    )
    kernel = SimpleNamespace(GetCurrentThreadId=lambda: this_thread)
    adapter = Backend.__new__(Backend)
    adapter.user, adapter.kernel, adapter.calls = user, kernel, calls
    return adapter


def test_dialog_attaches_to_the_foreground_thread_before_showing_and_detaches_after():
    adapter = make_adapter(foreground_hwnd=42, foreground_thread=100, this_thread=200)
    assert adapter._dialog("hello") == 6
    assert adapter.calls == [("attach", 200, 100, True), ("messagebox", "hello"), ("attach", 200, 100, False)]


def test_dialog_skips_attach_when_there_is_no_foreground_window():
    adapter = make_adapter(foreground_hwnd=0, foreground_thread=0, this_thread=200)
    assert adapter._dialog("hello") == 6
    assert adapter.calls == [("messagebox", "hello")]


def test_dialog_skips_attach_when_already_on_the_foreground_thread():
    adapter = make_adapter(foreground_hwnd=42, foreground_thread=200, this_thread=200)
    assert adapter._dialog("hello") == 6
    assert adapter.calls == [("messagebox", "hello")]


def test_dialog_does_not_detach_when_attach_failed():
    adapter = make_adapter(foreground_hwnd=42, foreground_thread=100, this_thread=200, attach_result=False)
    assert adapter._dialog("hello") == 6
    assert adapter.calls == [("attach", 200, 100, True), ("messagebox", "hello")]
