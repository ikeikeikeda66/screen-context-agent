"""Spike #8: watch the global Secure Input flag and the frontmost app.

Captures nothing and prints no window titles or text, only bundle IDs and the flag.
"""
import argparse
import collections
import platform
import sys
import time
import timeit

CARBON = "/System/Library/Frameworks/Carbon.framework/Carbon"
SCENARIOS = [
    "Safari: focus a password field, type, then leave it",
    "Chrome: focus a password field, type, then leave it",
    "A native app password field (for example a login sheet or System Settings)",
    "A normal text field in each browser (expect false)",
    "Terminal with Secure Keyboard Entry on, then off (a known source of 'stuck' true)",
]


def secure_input_function():
    import ctypes
    function = ctypes.cdll.LoadLibrary(CARBON).IsSecureEventInputEnabled
    function.restype, function.argtypes = ctypes.c_bool, []
    return function


def frontmost():
    from AppKit import NSWorkspace
    from Foundation import NSDate, NSRunLoop
    # NSWorkspace only updates activation state while the run loop turns (see platforms/macos.py).
    NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.01))
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    return str(app.bundleIdentifier() or "") if app else ""


def watch(seconds, interval, stuck_after):
    enabled = secure_input_function()
    samples = collections.Counter()
    transitions, stuck = [], set()
    state, since, started = None, time.monotonic(), time.monotonic()
    while time.monotonic() - started < seconds:
        now, app = enabled(), frontmost()
        samples[(app, now)] += 1
        if now != state:
            transitions.append((round(time.monotonic() - started, 1), now, app))
            print(f"{transitions[-1][0]:7.1f}s  secure_input={now!s:5}  front={app}", flush=True)
            state, since = now, time.monotonic()
        elif now and time.monotonic() - since > stuck_after:
            stuck.add(app)
        time.sleep(interval)
    cost = timeit.timeit(enabled, number=10000) / 10000 * 1e6
    return samples, transitions, stuck, cost


def report(samples, transitions, stuck, cost, stuck_after):
    apps = sorted({app for app, _ in samples})
    lines = ["### Secure Input probe (#8)", "",
             f"- macOS {platform.mac_ver()[0]}, {platform.machine()}",
             f"- `IsSecureEventInputEnabled()` cost: {cost:.2f} µs per call",
             f"- Transitions: {len(transitions)}",
             f"- True for more than {stuck_after:.0f}s in a row while frontmost: {', '.join(sorted(stuck)) or 'none'}", "",
             "| Frontmost app | Samples true | Samples false |", "|---|---|---|"]
    lines += [f"| {app or '(none)'} | {samples[(app, True)]} | {samples[(app, False)]} |" for app in apps]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seconds", type=float, default=180)
    parser.add_argument("--interval", type=float, default=0.2)
    parser.add_argument("--stuck-after", type=float, default=30)
    args = parser.parse_args(argv)
    if sys.platform != "darwin":
        sys.exit("This probe runs on macOS only.")
    print(f"Watching for {args.seconds:.0f}s. Try these while it runs:")
    for item in SCENARIOS: print(f"  - {item}")
    print(report(*watch(args.seconds, args.interval, args.stuck_after), args.stuck_after))


if __name__ == "__main__":
    main()
