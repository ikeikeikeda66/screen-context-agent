"""Spike #9: detect a focused password field with UI Automation.

Captures nothing and prints no element names or text, only the process name,
control type and the IsPassword flag of the focused element.
Needs: uv pip install --python .venv\\Scripts\\python.exe comtypes
"""
import argparse
import collections
import platform
import sys
import time
import timeit

SCENARIOS = [
    "Chrome: focus a password field, type, then leave it",
    "Edge: focus a password field, type, then leave it",
    "A Win32 password box (for example a Remote Desktop or Wi-Fi password dialog)",
    "A normal text field in each browser (expect false)",
]


def automation():
    import comtypes.client
    comtypes.client.GetModule("UIAutomationCore.dll")
    from comtypes.gen.UIAutomationClient import CUIAutomation, IUIAutomation
    return comtypes.client.CreateObject(CUIAutomation, interface=IUIAutomation)


def focused(uia):
    import _ctypes
    import psutil
    try:
        element = uia.GetFocusedElement()
        pid = element.CurrentProcessId
        return psutil.Process(pid).name(), int(element.CurrentControlType), bool(element.CurrentIsPassword)
    except (_ctypes.COMError, OSError, psutil.Error):
        return "(none)", 0, False


def watch(seconds, interval):
    uia = automation()
    samples, transitions = collections.Counter(), []
    state, started = None, time.monotonic()
    while time.monotonic() - started < seconds:
        process, control, password = focused(uia)
        samples[(process, password)] += 1
        if password != state:
            transitions.append((round(time.monotonic() - started, 1), password, process, control))
            print(f"{transitions[-1][0]:7.1f}s  is_password={password!s:5}  process={process}  control_type={control}", flush=True)
            state = password
        time.sleep(interval)
    cost = timeit.timeit(lambda: focused(uia), number=500) / 500 * 1e3
    return samples, transitions, cost


def report(samples, transitions, cost):
    processes = sorted({process for process, _ in samples})
    lines = ["### UI Automation password-field probe (#9)", "",
             f"- Windows {platform.version()} ({platform.release()}), Python {platform.python_version()}",
             f"- Frozen build: {getattr(sys, 'frozen', False)}",
             f"- Cost of one focused-element check: {cost:.2f} ms",
             f"- Transitions: {len(transitions)}", "",
             "| Focused process | Samples password | Samples other |", "|---|---|---|"]
    lines += [f"| {p} | {samples[(p, True)]} | {samples[(p, False)]} |" for p in processes]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seconds", type=float, default=180)
    parser.add_argument("--interval", type=float, default=0.2)
    args = parser.parse_args(argv)
    if sys.platform != "win32":
        sys.exit("This probe runs on Windows only.")
    print(f"Watching for {args.seconds:.0f}s. Try these while it runs:")
    for item in SCENARIOS: print(f"  - {item}")
    print(report(*watch(args.seconds, args.interval)))


if __name__ == "__main__":
    main()
