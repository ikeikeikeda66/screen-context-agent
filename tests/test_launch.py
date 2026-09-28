"""macOS app services (#34): the indexer as a child of the menu bar app, start at login, and the
old LaunchAgent. Fake processes and services; one test runs the real indexer CLI on an empty store."""
import json
import subprocess
import sys
import time
from types import SimpleNamespace
import pytest
from test_core import settings
from screen_context import launch, quick
from screen_context.desktop import CommandProcess, Workers


class Child:
    """subprocess.Popen as far as CommandProcess uses it."""
    def __init__(self, argv, **kwargs):
        self.argv, self.kwargs, self.returncode, self.terminated = argv, kwargs, None, False
    def poll(self): return self.returncode
    def terminate(self): self.terminated = True; self.returncode = 0
    def wait(self, timeout=None):
        if self.returncode is None: raise subprocess.TimeoutExpired(self.argv, timeout)
        return self.returncode


def popen_log():
    started = []
    def popen(argv, **kwargs):
        started.append(Child(argv, **kwargs))
        return started[-1]
    return started, popen


# --- the indexer under desktop.Workers ----------------------------------------------------------

def test_indexer_workers_run_the_cli_for_this_data_folder(settings, tmp_path):
    started, popen = popen_log()
    workers = launch.indexer_workers(settings, home=tmp_path, popen=popen)
    workers.start()
    [child] = started
    assert child.argv == [sys.executable, "-m", "screen_context.cli", "index", "--watch"]
    assert child.kwargs["env"]["SCREEN_CONTEXT_HOME"] == str(settings.root)
    assert (tmp_path / "Library" / "Logs" / "ScreenContext" / "indexer.log").exists()
    assert workers.poll() == {"index": "running"}
    with pytest.raises(RuntimeError): workers.start()                          # no second indexer


def test_the_frozen_app_runs_the_indexer_through_its_launcher(settings, tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", "macosx_app", raising=False)
    monkeypatch.setenv("EXECUTABLEPATH", "/Applications/ScreenContext.app/Contents/MacOS/ScreenContext")
    started, popen = popen_log()
    launch.indexer_workers(settings, home=tmp_path, popen=popen).start()
    assert started[0].argv == ["/Applications/ScreenContext.app/Contents/MacOS/ScreenContext", "index", "--watch"]


def test_a_crashed_indexer_is_restarted_then_given_up(settings, tmp_path):
    started, popen = popen_log()
    workers = launch.indexer_workers(settings, home=tmp_path, popen=popen)
    workers.max_restarts = 2
    workers.start()
    for expected in (2, 3):
        started[-1].returncode = 1
        assert workers.poll() == {"index": "running"} and len(started) == expected
    started[-1].returncode = 1
    assert workers.poll() == {"index": "failed"} and len(started) == 3 and workers.stopping


def test_stop_terminates_the_child_and_it_counts_as_stopped(settings, tmp_path):
    started, popen = popen_log()
    workers = launch.indexer_workers(settings, home=tmp_path, popen=popen)
    workers.start()
    launch.stop_indexer(workers, timeout=0)
    assert started[0].terminated and workers.poll() == {"index": "stopped"}
    launch.stop_indexer(None)                                                  # nothing started


def test_command_process_join_waits_at_most_the_timeout():
    child = Child(["x"])
    process = CommandProcess(["x"], popen=lambda argv, **kw: child)
    assert process.exitcode is None and not process.is_alive()
    process.join(0)                                                            # before start: no error
    process.start()
    assert process.is_alive() and process.exitcode is None
    process.join(0)                                                            # still running: returns
    process.terminate()
    assert not process.is_alive() and process.exitcode == 0


def test_the_indexer_cli_exits_cleanly_on_sigterm(settings, tmp_path):
    """The real `index --watch` on an empty plaintext store: the app's stop() must end it with 0."""
    process = CommandProcess([sys.executable, "-m", "screen_context.cli", "index", "--watch"],
                             env={**quick.child_env(settings), "PATH": "/usr/bin:/bin"}, log=tmp_path / "indexer.log")
    process.start()
    deadline = time.monotonic() + 20
    while not (settings.root / "index-status.json").exists() and time.monotonic() < deadline: time.sleep(.1)
    assert process.is_alive(), (tmp_path / "indexer.log").read_text()
    process.terminate()
    process.join(20)
    assert process.exitcode == 0, (tmp_path / "indexer.log").read_text()


def test_workers_without_a_command_still_use_multiprocessing(tmp_path):
    from test_desktop import Event, Process
    from screen_context.config import Settings
    workers = Workers(Settings(tmp_path), SimpleNamespace(Event=Event, Process=Process))
    workers.start()
    assert set(workers.processes) == {"index", "capture"}
    workers.stop()                                                             # no terminate() on these
    assert workers.stop_event.signaled


# --- the menu bar app's startup path ------------------------------------------------------------

class Started:
    def __init__(self, fail=False): self.fail, self.started, self.processes = fail, False, {}
    def start(self):
        if self.fail: raise OSError("spawn failed")
        self.started = True


@pytest.mark.parametrize("legacy, answer, removed, expected", [
    (None, None, None, "started"),
    ("loaded", True, True, "started"),
    ("installed", True, True, "started"),
    ("loaded", False, None, "legacy"),
    ("installed", False, None, "legacy"),
    ("loaded", True, False, "legacy"),
])
def test_start_indexer_handles_the_old_agent(settings, legacy, answer, removed, expected):
    asked, told, made = [], [], []
    def workers(s):
        made.append(Started())
        return made[-1]
    running, note = launch.start_indexer(settings, lambda: asked.append(1) or answer, told.append,
                                         legacy=lambda: legacy, remove=lambda: removed, workers=workers)
    assert bool(asked) == bool(legacy)
    if expected == "started":
        assert running is made[0] and running.started and note is None and told == []
    else:
        assert running is None and note == "legacy" and made == []
        assert bool(told) == (removed is False)                                # removal failure is reported
        if told: assert "launchctl bootout" in told[0]


def test_start_indexer_reports_a_spawn_failure(settings):
    told = []
    running, note = launch.start_indexer(settings, lambda: True, told.append, legacy=lambda: None, workers=lambda s: Started(fail=True))
    assert running is None and note == "failed" and "OSError" in told[0]


# --- the old LaunchAgent ------------------------------------------------------------------------

def launchctl(loaded):
    calls = []
    def run(argv, **kwargs):
        calls.append(argv)
        if argv[1] == "bootout": loaded[0] = False
        return SimpleNamespace(returncode=0 if (argv[1] == "print" and loaded[0]) else 113)
    return calls, run


def test_legacy_agent_states(tmp_path):
    calls, run = launchctl([True])
    assert launch.legacy_agent(tmp_path, run) == "loaded"
    assert calls[0][:2] == ["launchctl", "print"] and calls[0][2].endswith("/" + launch.LEGACY_LABEL)
    _, run = launchctl([False])
    assert launch.legacy_agent(tmp_path, run) is None
    plist = launch.legacy_plist(tmp_path)
    plist.parent.mkdir(parents=True)
    plist.write_text("<plist/>")
    assert launch.legacy_agent(tmp_path, run) == "installed"


def test_removing_the_legacy_agent_unloads_it_and_keeps_the_file_disabled(tmp_path):
    plist = launch.legacy_plist(tmp_path)
    plist.parent.mkdir(parents=True)
    plist.write_text("<plist/>")
    loaded = [True]
    calls, run = launchctl(loaded)
    assert launch.remove_legacy_agent(tmp_path, run)
    assert ["launchctl", "bootout"] == calls[0][:2] and not loaded[0]
    assert not plist.exists() and plist.with_name(plist.name + ".disabled").read_text() == "<plist/>"


def test_removing_reports_an_agent_that_stays_loaded(tmp_path):
    def run(argv, **kwargs): return SimpleNamespace(returncode=0)              # bootout "fails": still loaded
    assert not launch.remove_legacy_agent(tmp_path, run)


# --- start at login -----------------------------------------------------------------------------

class Service:
    def __init__(self, status, after_register=None, unregister_ok=True):
        self.value, self.after_register, self.unregister_ok, self.calls = status, after_register, unregister_ok, []
    def status(self): return self.value
    def registerAndReturnError_(self, error):
        self.calls.append("register")
        self.value = self.after_register
        return self.value == launch.ENABLED, None
    def unregisterAndReturnError_(self, error):
        self.calls.append("unregister")
        if self.unregister_ok: self.value = launch.NOT_REGISTERED
        return self.unregister_ok, None


@pytest.mark.parametrize("service, result, settings_opened", [
    (Service(launch.NOT_REGISTERED, after_register=launch.ENABLED), "enabled", False),
    (Service(launch.NOT_REGISTERED, after_register=launch.REQUIRES_APPROVAL), "approval", True),
    (Service(launch.NOT_REGISTERED, after_register=launch.NOT_FOUND), "failed", False),
    (Service(launch.REQUIRES_APPROVAL, after_register=launch.REQUIRES_APPROVAL), "approval", True),
    (Service(launch.ENABLED), "disabled", False),
    (Service(launch.ENABLED, unregister_ok=False), "failed", False),
])
def test_toggle_login(service, result, settings_opened):
    opened = []
    assert launch.toggle_login(service, lambda: opened.append(1)) == result
    assert bool(opened) is settings_opened


def test_login_item_state_and_availability():
    assert launch.login_enabled(Service(launch.ENABLED))
    assert not launch.login_enabled(Service(launch.REQUIRES_APPROVAL)) and not launch.login_enabled(None)
    assert launch.login_service() is None                                      # from source: only the bundle can register
