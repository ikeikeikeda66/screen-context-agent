"""Menu bar controls; capture stays on the Cocoa main thread."""
import time
import threading
import objc
from AppKit import NSApplication, NSStatusBar, NSVariableStatusItemLength, NSMenu, NSMenuItem, NSAlert, NSEventMaskAny
from Foundation import NSObject, NSDate, NSDefaultRunLoopMode
from .config import Settings
from .i18n import CHOICES, interval_label, resolve, t

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
        self.toggle_item.setTitle_(t("menu.resume" if paused else "menu.pause", lang))
        self.interval_parent.setTitle_(t("menu.interval", lang))
        self.language_parent.setTitle_(t("menu.language", lang))
        self.quit_item.setTitle_(t("menu.quit", lang))
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
    app = NSApplication.sharedApplication()
    settings = Settings.environment()
    settings.prepare()
    controller = MenuController.alloc().init()
    controller.settings = settings
    controller.stop = threading.Event()
    controller.item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
    menu = NSMenu.alloc().init()
    menu.setAutoenablesItems_(False)
    controller.toggle_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("", "toggle:", "")
    controller.toggle_item.setTarget_(controller)
    menu.addItem_(controller.toggle_item)
    controller.interval_parent, controller.interval_items = submenu(controller, menu, "interval:", INTERVALS)
    controller.language_parent, controller.language_items = submenu(controller, menu, "language:", range(len(CHOICES)))
    menu.addItem_(NSMenuItem.separatorItem())
    controller.quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("", "quit:", "")
    controller.quit_item.setTarget_(controller)
    menu.addItem_(controller.quit_item)
    controller.item.setMenu_(menu)
    controller.refresh()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: controller.stop.set())
    try:
        with lock(settings.root / "capture.lock"):
            run(settings, stop=CocoaStop(controller))
    except Exception as error:
        controller.showError(t("error.start", controller.lang(), error=type(error).__name__))
    finally:
        NSStatusBar.systemStatusBar().removeStatusItem_(controller.item)
