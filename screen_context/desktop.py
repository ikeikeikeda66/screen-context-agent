"""Desktop worker lifecycle. Importing this module never starts capture or UI."""
import json
import multiprocessing
import time
from datetime import datetime


def worker(kind, settings, stop):
    from .locking import lock
    with lock(settings.root / ("capture.lock" if kind == "capture" else "indexer.lock")):
        if kind == "capture":
            from .capture import run
            run(settings, stop=stop)
        elif kind == "index":
            from .indexer import drain, maintain
            last_maintenance = 0
            while not stop.is_set():
                drain(settings)
                if time.monotonic() - last_maintenance > 3600:
                    maintain(settings)
                    last_maintenance = time.monotonic()
                stop.wait(5)
        else:
            raise ValueError("Unknown worker")


class Workers:
    def __init__(self, settings, context=None, max_restarts=3, window=600):
        self.settings = settings
        self.context = context or multiprocessing.get_context("spawn")
        self.processes = {}
        self.stop_event = None
        self.stopping = False
        # A worker that crashes natively (for example inside the capture library when the session
        # locks, #47) is restarted, up to max_restarts per window seconds; beyond that it stays down.
        self.max_restarts, self.window, self.restarts = max_restarts, window, []

    def start(self):
        if any(p.is_alive() for p in self.processes.values()):
            raise RuntimeError("Workers are already running or stopping")
        for p in self.processes.values(): p.join(timeout=0)
        self.processes = {}
        self.stop_event = self.context.Event()
        self.stopping = False
        try:
            for kind in ("index", "capture"): self.spawn(kind)
        except Exception:
            self.stop()
            raise

    def spawn(self, kind):
        p = self.context.Process(target=worker, args=(kind, self.settings, self.stop_event), name="ScreenContext-"+kind)
        p.start()
        self.processes[kind] = p

    def may_restart(self):
        now = time.monotonic()
        self.restarts = [t for t in self.restarts if now - t < self.window]
        return len(self.restarts) < self.max_restarts

    def restart(self, kind):
        self.restarts.append(time.monotonic())
        if kind == "capture":
            # The crash leaves no status of its own; record it so the window shows that it happened.
            from .crypto import atomic_write
            atomic_write(self.settings.root / "capture-status.json",
                         json.dumps({"ts": time.time(), "status": "error", "error_type": "WorkerRestarted"}).encode())
        self.spawn(kind)

    def stop(self):
        self.stopping = True
        if self.stop_event is not None: self.stop_event.set()

    def poll(self):
        states = {}
        for kind, p in list(self.processes.items()):
            states[kind] = "running" if p.is_alive() else "stopped" if p.exitcode == 0 else "failed"
            if not p.is_alive(): p.join(timeout=0)
            if states[kind] == "failed" and not self.stopping and self.may_restart():
                self.restart(kind)
                states[kind] = "running"
        # A dead capture/indexer must not leave its peer running indefinitely.
        if states and not self.stopping and any(s != "running" for s in states.values()): self.stop()
        return states


def status_text(path, lang="en"):
    """Past result, explicitly not a claim that a worker is healthy now."""
    from .i18n import t
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        timestamp = datetime.fromtimestamp(float(data["ts"])).strftime("%m/%d %H:%M:%S")
        if "status" in data:
            value = t({"spooled": "status.spooled", "excluded": "status.excluded", "error": "status.error"}.get(data["status"], "status.other"), lang)
        else:
            value = t("status.indexed", lang, indexed=int(data.get("indexed", 0)), failed=int(data.get("failed", 0)))
        return f"{timestamp}　{value}"
    except (OSError, ValueError, KeyError, TypeError, OverflowError):
        return t("status.none", lang)


def mcp_config(command, settings, token, profile="standard"):
    from .clients import server_entry
    return {"mcpServers": {"screen-context": server_entry(command, settings, token, profile)}}
