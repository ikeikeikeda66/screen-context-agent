"""Spike #8: local user authentication through LocalAuthentication.

Shows one Touch ID / password prompt per policy. Captures nothing and reads no history.
Needs: uv pip install --python .venv/bin/python pyobjc-framework-LocalAuthentication
"""
import argparse
import platform
import sys
import threading
import time

# LAPolicy values from LocalAuthentication/LAPublicDefines.h.
POLICIES = {"owner": 2, "biometrics": 1}
BIOMETRY = {0: "none", 1: "touch_id", 2: "face_id", 4: "optic_id"}
ERRORS = {-1: "authenticationFailed", -2: "userCancel", -3: "userFallback", -4: "systemCancel",
          -5: "passcodeNotSet", -6: "biometryNotAvailable", -7: "biometryNotEnrolled",
          -8: "biometryLockout", -9: "appCancel", -10: "invalidContext", -11: "companionNotAvailable",
          -12: "biometryNotPaired", -13: "biometryDisconnected", -14: "invalidDimensions"}


def describe(error):
    if error is None: return None
    code = int(error.code())
    return f"{ERRORS.get(code, 'other')} ({error.domain()} {code})"


def evaluate(name, reason, timeout):
    import LocalAuthentication
    from Foundation import NSDate, NSRunLoop
    context = LocalAuthentication.LAContext.alloc().init()
    available, error = context.canEvaluatePolicy_error_(POLICIES[name], None)
    result = {"policy": name, "available": bool(available), "availability_error": describe(error),
              "biometry": BIOMETRY.get(int(context.biometryType()), str(context.biometryType()))}
    if not available: return result
    done, reply = threading.Event(), {}

    def finished(success, error):
        reply.update(success=bool(success), error=describe(error))
        done.set()

    started = time.monotonic()
    context.evaluatePolicy_localizedReason_reply_(POLICIES[name], reason, finished)
    # The reply arrives on a private queue; keep the main run loop alive so the prompt can show.
    while not done.is_set() and time.monotonic() - started < timeout:
        NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.1))
    result.update(reply or {"success": False, "error": "timeout"})
    result["seconds"] = round(time.monotonic() - started, 1)
    return result


def report(results):
    lines = ["### Touch ID probe (#8)", "",
             f"- macOS {platform.mac_ver()[0]}, {platform.machine()}, Python {platform.python_version()}",
             f"- Process: `{sys.executable}` (inside an .app bundle: {'.app/Contents/' in sys.executable})", "",
             "| Policy | Available | Biometry | Success | Error | Seconds |", "|---|---|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r['policy']} | {r['available']} | {r['biometry']} | {r.get('success', '-')} | "
                     f"{r.get('error') or r.get('availability_error') or '-'} | {r.get('seconds', '-')} |")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--policy", choices=["owner", "biometrics", "both"], default="both",
                        help="owner = Touch ID with password fallback; biometrics = Touch ID only")
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args(argv)
    if sys.platform != "darwin":
        sys.exit("This probe runs on macOS only.")
    names = ["owner", "biometrics"] if args.policy == "both" else [args.policy]
    print(report([evaluate(n, "ScreenContext spike: confirm it is you", args.timeout) for n in names]))


if __name__ == "__main__":
    main()
