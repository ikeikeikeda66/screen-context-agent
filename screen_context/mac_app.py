"""Menu bar controls; capture stays on the Cocoa main thread."""
import time
import threading
import objc
from AppKit import NSApplication, NSStatusBar, NSVariableStatusItemLength, NSMenu, NSMenuItem, NSAlert, NSAlertSecondButtonReturn, NSEventMaskAny, NSButton, NSStackView, NSWorkspace, NSLayoutAttributeLeading
from Foundation import NSObject, NSDate, NSDefaultRunLoopMode, NSURL
from . import launch, onboarding, quick, reauth
from .config import Settings
from .i18n import CHOICES, auth, interval_label, resolve, t

INTERVALS = (5, 15, 30, 60, 120, 300)


class MenuController(NSObject):
    def toggle_(self, sender):
        try:
            path = self.settings.root / "paused"
            if path.exists(): path.unlink()
            else: path.touch(mode=0o600)
            self.refresh()
        except Exception:
            self.showError(t("error.toggle", self.lang()))

    def interval_(self, sender):
        try:
            self.settings.set_capture_interval(sender.tag())
            self.refresh()
        except Exception:
            self.showError(t("error.interval", self.lang()))

    def language_(self, sender):
        try:
            self.settings.set_language(CHOICES[sender.tag()])
            self.refresh()
        except Exception:
            self.showError(t("error.language", self.lang()))

    def openToday_(self, sender):
        lang = self.lang()
        try:
            status = quick.open_today(self.settings, lambda: reauth.touch_id(t("auth.reason.open", lang)))
            if status in (reauth.FAILED, reauth.UNAVAILABLE): self.showError(auth("auth.refused." + status, lang))
        except Exception as error: self.showError(t("error.open", lang, error=type(error).__name__))

    def deleteRecent_(self, sender):
        """Quick purge for "I recorded something by mistake": confirm, then `purge --last` (#31)."""
        lang, minutes = self.lang(), sender.tag()
        try:
            title, body = quick.confirmation(self.settings, minutes, lang)
            if body is None:
                self.showError(title)
                return
            alert = NSAlert.alloc().init()
            alert.setMessageText_(title)
            alert.setInformativeText_(body)
            alert.addButtonWithTitle_(t("menu.delete.cancel", lang))   # first button: the default (Return)
            alert.addButtonWithTitle_(t("menu.delete.confirm", lang))
            if hasattr(alert.buttons()[1], "setHasDestructiveAction_"): alert.buttons()[1].setHasDestructiveAction_(True)
            NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
            if alert.runModal() != NSAlertSecondButtonReturn: return
            result = quick.delete(self.settings, minutes)
            self.showError(t("menu.delete.done", lang, frames=result["frames"]))
        except Exception as error:
            self.showError(t("error.purge", lang, error=type(error).__name__))

    def connectClient_(self, sender):
        """Offer the installed AI assistants again (the first-run step "clients"), e.g. after installing one later."""
        lang = self.lang()
        try:
            text = onboarding.connect_clients(self.settings, SetupDialogs(), lang)
            if text: self.showError(text)
        except Exception as error:
            self.showError(t("error.connect", lang, error=type(error).__name__))

    def loginToggle_(self, sender):
        """Start at login through the app's own login item (#34)."""
        lang = self.lang()
        try:
            from ServiceManagement import SMAppService
            result = launch.toggle_login(self.login, SMAppService.openSystemSettingsLoginItems)
            if result in ("approval", "failed"): self.showError(t("login." + result, lang))
        except Exception as error:
            self.showError(t("login.failed", lang) + f" ({type(error).__name__})")
        self.refresh()

    def quit_(self, sender):
        self.stop.set()

    @objc.python_method
    def lang(self):
        return resolve(self.settings)

    @objc.python_method
    def showError(self, text):
        alert = NSAlert.alloc().init()
        alert.setMessageText_(text)
        alert.runModal()

    @objc.python_method
    def refresh(self):
        lang = self.lang()
        paused = (self.settings.root / "paused").exists()
        self.item.button().setTitle_(t("menu.title.paused" if paused else "menu.title.recording", lang))
        self.today_item.setTitle_(t("menu.open_today", lang))
        self.delete_parent.setTitle_(t("menu.delete", lang))
        for item in self.delete_items: item.setTitle_(t("menu.delete.item", lang, span=quick.span(item.tag(), lang)))
        self.toggle_item.setTitle_(t("menu.resume" if paused else "menu.pause", lang))
        self.interval_parent.setTitle_(t("menu.interval", lang))
        self.language_parent.setTitle_(t("menu.language", lang))
        self.quit_item.setTitle_(t("menu.quit", lang))
        self.connect_item.setTitle_(t("menu.connect", lang))
        self.login_item.setTitle_(t("menu.login", lang))
        self.login_item.setEnabled_(self.login is not None)
        self.login_item.setState_(int(launch.login_enabled(self.login)))
        # The indexer is polled here, so a crashed one is restarted (up to 3 times in 10 minutes).
        state = self.workers.poll().get("index", "stopped") if self.workers else self.indexer_note
        self.indexer_item.setTitle_(t("menu.indexer." + state, lang))
        interval = self.settings.capture_interval()
        for item in self.interval_items:
            item.setTitle_(interval_label(item.tag(), lang))
            item.setState_(int(item.tag() == interval))
        try: saved = self.settings.language()
        except ValueError: saved = "system"
        for item in self.language_items:
            choice = CHOICES[item.tag()]
            item.setTitle_(t("language." + choice, lang))
            item.setState_(int(choice == saved))


SCREEN_RECORDING_PANE = "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"


class SetupDialogs:
    """The dialogs of onboarding.run (first-run guide). Plain object: onboarding.py never imports AppKit."""
    def _alert(self, title, body, buttons):
        alert = NSAlert.alloc().init()
        alert.setMessageText_(title)
        alert.setInformativeText_(body)
        for button in buttons: alert.addButtonWithTitle_(button)   # first button: the default (Return)
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        return alert

    def permission(self, lang):
        alert = self._alert(t("setup.permission.title", lang), t("setup.permission.body", lang),
                            (t("setup.permission.open", lang), t("setup.permission.quit", lang)))
        return alert.runModal() != NSAlertSecondButtonReturn

    def error(self, text):
        self._alert(text, "", ()).runModal()                 # no button given: AppKit shows its own default OK

    def report(self, text, lang):
        self._alert(t("setup.report.title", lang), text, ()).runModal()   # short title; the long text goes in the body

    def choose(self, options, lang):
        """Checkboxes, all off. Returns the ids of the ticked ones; none when the user skips."""
        alert = self._alert(t("setup.clients.title", lang), t("setup.clients.body", lang),
                            (t("setup.clients.connect", lang), t("setup.clients.skip", lang)))
        boxes = [NSButton.checkboxWithTitle_target_action_(name, None, None) for _, name in options]
        for box in boxes: box.setState_(0)
        stack = NSStackView.stackViewWithViews_(boxes)
        stack.setOrientation_(1)            # NSUserInterfaceLayoutOrientationVertical
        stack.setAlignment_(NSLayoutAttributeLeading)
        stack.setSpacing_(6)
        stack.setFrameSize_((300, 24 * len(boxes)))
        alert.setAccessoryView_(stack)
        if alert.runModal() == NSAlertSecondButtonReturn: return []
        return [client for (client, _), box in zip(options, boxes) if int(box.state()) == 1]


def screen_recording():
    """(preflight, request, open_settings) for the first-run guide. The only place that asks macOS about Screen Recording."""
    import Quartz
    return (Quartz.CGPreflightScreenCaptureAccess, Quartz.CGRequestScreenCaptureAccess,
            lambda: NSWorkspace.sharedWorkspace().openURL_(NSURL.URLWithString_(SCREEN_RECORDING_PANE)))


class CocoaStop:
    def __init__(self, controller):
        self.controller = controller
        self.event = controller.stop

    def is_set(self): return self.event.is_set()

    def wait(self, seconds):
        deadline = time.monotonic() + seconds
        while not self.is_set() and time.monotonic() < deadline:
            app = NSApplication.sharedApplication()
            event = app.nextEventMatchingMask_untilDate_inMode_dequeue_(NSEventMaskAny, NSDate.dateWithTimeIntervalSinceNow_(0.1), NSDefaultRunLoopMode, True)
            if event is not None: app.sendEvent_(event)
            app.updateWindows()
        self.controller.refresh()
        return self.is_set()


def submenu(controller, menu, action, tags):
    """Parent item with one child per tag; titles are set by refresh()."""
    parent = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("", None, "")
    children, items = NSMenu.alloc().init(), []
    for tag in tags:
        item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("", action, "")
        item.setTag_(tag)
        item.setTarget_(controller)
        children.addItem_(item)
        items.append(item)
    parent.setSubmenu_(children)
    menu.addItem_(parent)
    return parent, items


def main():
    import signal
    from .capture import run
    from .locking import lock
    from .platforms.macos import ScreenRecordingDenied
    app = NSApplication.sharedApplication()
    settings = Settings.environment()
    settings.prepare()
    lang = resolve(settings)
    # First run (permission, init, assistants): before the status item and before capture.lock, so nothing is captured meanwhile.
    preflight, request, open_settings = screen_recording()
    try:
        if onboarding.run(settings, SetupDialogs(), lang, preflight=preflight, request=request, open_settings=open_settings) == onboarding.QUIT:
            return
    except Exception as error:
        SetupDialogs().error(t("error.start", lang, error=type(error).__name__))   # a dialog that failed must not end in a traceback
        return
    controller = MenuController.alloc().init()
    controller.settings = settings
    controller.stop = threading.Event()
    controller.item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
    menu = NSMenu.alloc().init()
    menu.setAutoenablesItems_(False)
    controller.today_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("", "openToday:", "")
    controller.today_item.setTarget_(controller)
    menu.addItem_(controller.today_item)
    menu.addItem_(NSMenuItem.separatorItem())
    controller.toggle_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("", "toggle:", "")
    controller.toggle_item.setTarget_(controller)
    menu.addItem_(controller.toggle_item)
    controller.interval_parent, controller.interval_items = submenu(controller, menu, "interval:", INTERVALS)
    controller.language_parent, controller.language_items = submenu(controller, menu, "language:", range(len(CHOICES)))
    menu.addItem_(NSMenuItem.separatorItem())
    controller.delete_parent, controller.delete_items = submenu(controller, menu, "deleteRecent:", quick.WINDOWS)
    menu.addItem_(NSMenuItem.separatorItem())
    controller.indexer_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("", None, "")
    controller.indexer_item.setEnabled_(False)
    menu.addItem_(controller.indexer_item)
    controller.connect_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("", "connectClient:", "")
    controller.connect_item.setTarget_(controller)
    menu.addItem_(controller.connect_item)
    controller.login = launch.login_service()
    controller.login_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("", "loginToggle:", "")
    controller.login_item.setTarget_(controller)
    menu.addItem_(controller.login_item)
    menu.addItem_(NSMenuItem.separatorItem())
    controller.quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("", "quit:", "")
    controller.quit_item.setTarget_(controller)
    menu.addItem_(controller.quit_item)
    controller.item.setMenu_(menu)
    controller.workers, controller.indexer_note = None, "stopped"
    controller.refresh()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: controller.stop.set())
    try:
        with lock(settings.root / "capture.lock"):
            start_indexer(controller, settings)
            run(settings, stop=CocoaStop(controller))
    except Exception as error:
        controller.showError(t("setup.permission.lost" if isinstance(error, ScreenRecordingDenied) else "error.start", controller.lang(), error=type(error).__name__))
    finally:
        stop_indexer(controller)
        NSStatusBar.systemStatusBar().removeStatusItem_(controller.item)


def start_indexer(controller, settings):
    """Run the indexer as a child of the app (#34), after offering to remove an old LaunchAgent."""
    lang = controller.lang()

    def ask_remove():
        alert = NSAlert.alloc().init()
        alert.setMessageText_(t("legacy.title", lang))
        alert.setInformativeText_(t("legacy.body", lang, label=launch.LEGACY_LABEL))
        alert.addButtonWithTitle_(t("legacy.remove", lang))    # first button: the default (Return)
        alert.addButtonWithTitle_(t("legacy.keep", lang))
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        return alert.runModal() != NSAlertSecondButtonReturn

    controller.workers, note = launch.start_indexer(settings, ask_remove, controller.showError, lang)
    controller.indexer_note = note or "stopped"
    controller.refresh()


def stop_indexer(controller):
    launch.stop_indexer(controller.workers)
