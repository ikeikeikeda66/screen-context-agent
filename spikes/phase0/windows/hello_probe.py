"""Spike #9: local user authentication through Windows Hello (UserConsentVerifier).

Shows one Windows Security prompt. Captures nothing and reads no history.
Needs: uv pip install --python .venv\\Scripts\\python.exe winrt-Windows.Security.Credentials.UI
"""
import argparse
import asyncio
import platform
import sys
import time


def name(value):
    return getattr(value, "name", str(value))


async def verify(message, request):
    from winrt.windows.security.credentials.ui import UserConsentVerifier
    result = {"availability": name(await UserConsentVerifier.check_availability_async())}
    if request:
        started = time.monotonic()
        # Console processes have no window to parent the prompt; note whether it appears in front.
        result["verification"] = name(await UserConsentVerifier.request_verification_async(message))
        result["seconds"] = round(time.monotonic() - started, 1)
    return result


def report(result, frozen):
    return "\n".join([
        "### Windows Hello probe (#9)", "",
        f"- Windows {platform.version()} ({platform.release()}), Python {platform.python_version()}",
        f"- Process: `{sys.executable}` (frozen build: {frozen})",
        f"- Availability: {result['availability']}",
        f"- Verification: {result.get('verification', 'not requested')} ({result.get('seconds', '-')} s)",
        "- Prompt appeared in front of other windows: _fill in_",
        "- Fallback when Hello is not set up (PIN / password): _fill in_",
    ])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check-only", action="store_true", help="report availability without prompting")
    args = parser.parse_args(argv)
    if sys.platform != "win32":
        sys.exit("This probe runs on Windows only.")
    result = asyncio.run(verify("ScreenContext spike: confirm it is you", not args.check_only))
    print(report(result, getattr(sys, "frozen", False)))


if __name__ == "__main__":
    main()
