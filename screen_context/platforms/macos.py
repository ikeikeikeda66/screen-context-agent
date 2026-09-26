import io
from PIL import Image
import Quartz
from AppKit import NSApplication, NSWorkspace
from Foundation import NSMutableData, NSDate, NSRunLoop
from . import sck


class Backend:
    def __init__(self):
        NSApplication.sharedApplication()
        if not Quartz.CGPreflightScreenCaptureAccess():
            raise PermissionError("Grant Screen Recording to ScreenContext.app, then relaunch with open")

    def foreground(self):
        # NSWorkspace caches activation state until Cocoa processes its events.
        # The daemon waits on threading.Event, so refresh before every read,
        # including the post-capture attribution check.
        NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.01))
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if app is None: return {"app_bundle": "", "app_name": "", "window_title": "", "window_id": None}
        pid = app.processIdentifier()
        front = {"app_bundle": str(app.bundleIdentifier() or ""), "app_name": str(app.localizedName() or ""), "window_title": "", "window_id": None}
        for w in Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements, Quartz.kCGNullWindowID) or []:
            bounds = w.get("kCGWindowBounds", {})
            # Chrome exposes tiny utility windows ahead of its document window.
            # Keep z-order among usable windows; never select another app.
            if bounds.get("Width", 0) <= 2 or bounds.get("Height", 0) <= 2:
                continue
            if w.get("kCGWindowOwnerPID") == pid and w.get("kCGWindowLayer") == 0:
                front.update(window_title=str(w.get("kCGWindowName") or ""), window_id=int(w["kCGWindowNumber"]))
                break
        return front

    def idle_seconds(self):
        return Quartz.CGEventSourceSecondsSinceLastEventType(Quartz.kCGEventSourceStateCombinedSessionState, Quartz.kCGAnyInputEventType)

    def list_displays(self): return sck.list_displays()

    def approve_current(self):
        from AppKit import NSAlert, NSAlertFirstButtonReturn
        from ..config import Settings
        from ..i18n import resolve, t
        lang = resolve(Settings.environment())
        alert = NSAlert.alloc().init()
        alert.setMessageText_(t("approve.title", lang))
        alert.setInformativeText_(t("approve.body", lang))
        alert.addButtonWithTitle_(t("approve.deny", lang))
        alert.addButtonWithTitle_(t("approve.allow", lang))
        return alert.runModal() == NSAlertFirstButtonReturn + 1

    def approve_client(self, name, profile):
        from AppKit import NSAlert, NSAlertFirstButtonReturn
        from ..config import Settings
        from ..i18n import resolve, t
        lang = resolve(Settings.environment())
        alert = NSAlert.alloc().init()
        alert.setMessageText_(t("client.title", lang, name=name))
        alert.setInformativeText_(t("client.body", lang, name=name, profile=profile))
        alert.addButtonWithTitle_(t("client.deny", lang))
        alert.addButtonWithTitle_(t("client.allow", lang))
        return alert.runModal() == NSAlertFirstButtonReturn + 1

    def capture(self, front):
        if front["window_id"] is None: raise RuntimeError("No foreground window")
        content = sck.shareable_content()
        target = next((w for w in content.windows() if int(w.windowID()) == front["window_id"]), None)
        if target is None: raise RuntimeError("Foreground window disappeared")
        if str(target.title() or "") != front["window_title"] or str(target.owningApplication().bundleIdentifier() or "") != front["app_bundle"]:
            raise RuntimeError("Window changed during capture request")
        filt = sck.SCContentFilter.alloc().initWithDesktopIndependentWindow_(target)
        scale = float(filt.pointPixelScale() or 1)
        cfg = sck.SCStreamConfiguration.alloc().init()
        cfg.setWidth_(int(filt.contentRect().size.width*scale))
        cfg.setHeight_(int(filt.contentRect().size.height*scale))
        cfg.setShowsCursor_(False)
        cg = sck._sync(lambda cb: sck.SCScreenshotManager.captureImageWithFilter_configuration_completionHandler_(filt, cfg, cb))
        data = NSMutableData.data()
        dest = Quartz.CGImageDestinationCreateWithData(data, "public.png", 1, None)
        Quartz.CGImageDestinationAddImage(dest, cg, None)
        if not Quartz.CGImageDestinationFinalize(dest): raise RuntimeError("PNG encoding failed")
        image = Image.open(io.BytesIO(bytes(data))).convert("RGB")
        return image, {"display_id": "foreground-window"}
