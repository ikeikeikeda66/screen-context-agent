"""ScreenCaptureKit capture core (macOS 14+ path, SCScreenshotManager)."""
import threading
import objc
import Quartz
from ScreenCaptureKit import (
    SCShareableContent,
    SCContentFilter,
    SCStreamConfiguration,
    SCScreenshotManager,
)


class CaptureError(RuntimeError):
    pass


def _sync(call, timeout=15.0):
    """Run a completionHandler-based API synchronously."""
    box = {}
    done = threading.Event()

    def handler(result, error):
        box["result"] = result
        box["error"] = error
        done.set()

    call(handler)
    if not done.wait(timeout):
        raise CaptureError("timeout waiting for completion handler")
    if box["error"] is not None:
        raise CaptureError(str(box["error"]))
    return box["result"]


def shareable_content(on_screen_only=True):
    return _sync(
        lambda h: SCShareableContent.getShareableContentExcludingDesktopWindows_onScreenWindowsOnly_completionHandler_(
            True, on_screen_only, h
        )
    )


def list_displays():
    content = shareable_content()
    return [
        {
            "display_id": int(d.displayID()),
            "width": int(d.width()),
            "height": int(d.height()),
        }
        for d in content.displays()
    ]


def capture(display_id=None, exclude_bundle_ids=(), max_long_side=1600):
    """Capture one display. Returns (CGImage, meta)."""
    content = shareable_content()
    displays = content.displays()
    if not displays:
        raise CaptureError("no displays reported (TCC permission missing?)")
    display = displays[0]
    if display_id is not None:
        for d in displays:
            if int(d.displayID()) == int(display_id):
                display = d
                break

    excluded = [
        app
        for app in content.applications()
        if app.bundleIdentifier() in set(exclude_bundle_ids)
    ]

    filt = SCContentFilter.alloc().initWithDisplay_excludingApplications_exceptingWindows_(
        display, excluded, []
    )

    w, h = int(filt.contentRect().size.width), int(filt.contentRect().size.height)
    scale = 1.0
    if max_long_side and max(w, h) > max_long_side:
        scale = max_long_side / float(max(w, h))
    ow, oh = max(1, int(w * scale)), max(1, int(h * scale))

    cfg = SCStreamConfiguration.alloc().init()
    cfg.setWidth_(ow)
    cfg.setHeight_(oh)
    cfg.setShowsCursor_(False)

    image = _sync(
        lambda hh: SCScreenshotManager.captureImageWithFilter_configuration_completionHandler_(
            filt, cfg, hh
        )
    )
    if image is None:
        raise CaptureError("captureImage returned nil")

    meta = {
        "display_id": int(display.displayID()),
        "src_size": [w, h],
        "out_size": [int(Quartz.CGImageGetWidth(image)), int(Quartz.CGImageGetHeight(image))],
        "excluded_bundle_ids": [str(a.bundleIdentifier()) for a in excluded],
    }
    return image, meta


def has_permission():
    """True if the process is actually allowed to read screen content."""
    try:
        content = shareable_content()
    except CaptureError:
        return False
    # Without TCC, displays list is empty or window titles are stripped.
    return len(content.displays()) > 0 and bool(
        Quartz.CGPreflightScreenCaptureAccess()
    )


def _ensure_app_connection():
    """Window-level SCContentFilter needs a window-server connection; a bare
    Python process has none and CoreGraphics aborts with CGS_REQUIRE_INIT."""
    from AppKit import NSApplication
    NSApplication.sharedApplication()


def capture_window(bundle_id, title_contains=None, max_long_side=0):
    """Capture a single window.

    Window-level capture is what makes per-app exclusion possible at all, and
    it also lets the indexer read a background window without stealing focus.
    """
    # on_screen_only=False trips CGS_REQUIRE_INIT in a non-NSApplication process
    _ensure_app_connection()
    content = shareable_content(on_screen_only=True)
    target = None
    for w in content.windows():
        app = w.owningApplication()
        if app is None or app.bundleIdentifier() != bundle_id:
            continue
        t = w.title()
        if title_contains and (t is None or title_contains not in str(t)):
            continue
        if int(w.frame().size.width) < 200:
            continue
        target = w
        break
    if target is None:
        raise CaptureError(f"no window for {bundle_id}")

    filt = SCContentFilter.alloc().initWithDesktopIndependentWindow_(target)
    w = int(filt.contentRect().size.width)
    h = int(filt.contentRect().size.height)
    scale = int(filt.pointPixelScale() or 1)
    ow, oh = w * scale, h * scale
    if max_long_side and max(ow, oh) > max_long_side:
        r = max_long_side / float(max(ow, oh))
        ow, oh = int(ow * r), int(oh * r)

    cfg = SCStreamConfiguration.alloc().init()
    cfg.setWidth_(ow)
    cfg.setHeight_(oh)
    cfg.setShowsCursor_(False)
    image = _sync(
        lambda hh: SCScreenshotManager.captureImageWithFilter_configuration_completionHandler_(
            filt, cfg, hh))
    if image is None:
        raise CaptureError("captureImage returned nil")
    meta = {"display_id": -1, "src_size": [w * scale, h * scale],
            "out_size": [int(Quartz.CGImageGetWidth(image)),
                         int(Quartz.CGImageGetHeight(image))],
            "window_title": str(target.title() or ""),
            "excluded_bundle_ids": []}
    return image, meta
