"""Windows desktop control window (beta); dependencies and UI are loaded on entry only."""
import multiprocessing
import sys
from pathlib import Path


def cli_command():
    if getattr(sys, "frozen", False):
        return [str(Path(sys.executable).parent.parent / "screen-context" / "screen-context.exe")]
    return [sys.executable, "-m", "screen_context.cli"]


def main():
    if sys.platform != "win32":
        raise SystemExit("This desktop application requires Windows.")
    import tkinter as tk
    from tkinter import ttk, messagebox
    from .clients import CLIENTS, render
    from .config import Settings
    from .desktop import Workers, status_text
    from .i18n import CHOICES, resolve, t
    from .locking import lock
    from . import store

    settings = Settings.environment()
    lang = lambda: resolve(settings)
    root = tk.Tk()
    root.title(t("win.title", lang()))
    root.geometry("670x470")
    root.minsize(600, 440)
    if settings.plaintext:
        messagebox.showerror(t("win.plaintext.title", lang()), t("win.plaintext.body", lang()))
        root.destroy()
        return
    settings.root.mkdir(parents=True, exist_ok=True)
    guard = lock(settings.root / "desktop.lock")
    try: guard.__enter__()
    except OSError:
        messagebox.showinfo(t("win.running.title", lang()), t("win.running.body", lang()))
        root.destroy()
        return
    workers = Workers(settings)
    closing = False
    # (widget, message key, format values); refreshed when the language changes.
    texts = []

    def label(parent, key, **options):
        widget = ttk.Label(parent, **options)
        texts.append((widget, key, {}))
        return widget

    body = ttk.Frame(root, padding=20)
    body.pack(fill="both", expand=True)
    top = ttk.Frame(body)
    top.pack(fill="x")
    label(top, "win.heading", font=("", 18)).pack(side="left")
    picker = ttk.Combobox(top, state="readonly", width=18)
    picker.pack(side="right")
    label(top, "win.language").pack(side="right", padx=6)
    label(body, "win.description").pack(anchor="w", pady=8)
    state = tk.StringVar()
    capture = tk.StringVar()
    index = tk.StringVar()
    ttk.Label(body, textvariable=state).pack(anchor="w", pady=8)
    label(body, "win.last_result").pack(anchor="w")
    ttk.Label(body, textvariable=capture).pack(anchor="w")
    ttk.Label(body, textvariable=index).pack(anchor="w", pady=5)
    buttons = ttk.Frame(body)
    buttons.pack(anchor="w", pady=12)

    def start():
        try:
            # Validate decryption and FTS before spawning capture.
            store.initialize(settings)
            with store.connect(settings, readonly=True) as db:
                db.execute("SELECT count(*) FROM frames_fts").fetchone()
            settings.policy()
            workers.start()
        except Exception as error:
            messagebox.showerror(t("win.start_failed.title", lang()), t("win.start_failed.body", lang(), error=type(error).__name__))

    def pause():
        try:
            path = settings.root / "paused"
            if path.exists(): path.unlink()
            else: path.touch(mode=0o600)
        except OSError:
            messagebox.showerror(t("win.pause_failed.title", lang()), t("win.pause_failed.body", lang()))

    def show_connection():
        win = tk.Toplevel(root)
        win.title(t("win.mcp.title", lang()))
        row = ttk.Frame(win, padding=(12, 12, 12, 0))
        row.pack(fill="x")
        ttk.Label(row, text=t("win.mcp.client", lang())).pack(side="left")
        client = tk.StringVar(value="generic")
        ttk.Combobox(row, textvariable=client, values=list(CLIENTS), state="readonly", width=16).pack(side="left", padx=6)
        where = tk.StringVar()
        ttk.Label(win, text=t("win.mcp.body", lang()), padding=(12, 8)).pack(anchor="w")
        ttk.Label(win, textvariable=where, padding=(12, 0)).pack(anchor="w")
        text = tk.Text(win, width=82, height=17)
        text.pack(padx=12, pady=8)

        def update(*_):
            where.set(CLIENTS[client.get()])
            text.configure(state="normal")
            text.delete("1.0", "end")
            text.insert("1.0", render(client.get(), cli_command(), settings))
            text.configure(state="disabled")
        client.trace_add("write", update)
        update()

    start_button = ttk.Button(buttons, command=start)
    start_button.pack(side="left", padx=3)
    texts.append((start_button, "win.start", {}))
    pause_button = ttk.Button(buttons, command=pause)
    pause_button.pack(side="left", padx=3)
    stop_button = ttk.Button(buttons, command=workers.stop)
    stop_button.pack(side="left", padx=3)
    texts.append((stop_button, "win.stop", {}))
    connection_button = ttk.Button(body, command=show_connection)
    connection_button.pack(anchor="w")
    texts.append((connection_button, "win.connection", {}))
    folder = ttk.Label(body, wraplength=620)
    folder.pack(anchor="w", pady=12)
    texts.append((folder, "win.data_folder", {"path": str(settings.root)}))

    def apply_language():
        current = lang()
        root.title(t("win.title", current))
        for widget, key, values in texts:
            widget.configure(text=t(key, current, **values))
        try: saved = settings.language()
        except ValueError: saved = "system"
        picker.configure(values=[t("language." + c, current) for c in CHOICES])
        picker.current(CHOICES.index(saved))

    def choose_language(_event):
        try: settings.set_language(CHOICES[picker.current()])
        except (OSError, ValueError):
            messagebox.showerror(t("win.pause_failed.title", lang()), t("error.language", lang()))
        apply_language()

    picker.bind("<<ComboboxSelected>>", choose_language)
    apply_language()

    def close():
        nonlocal closing
        closing = True
        workers.stop()
        state.set(t("win.state.closing", lang()))

    def refresh():
        current = lang()
        states = workers.poll()
        alive = any(value == "running" for value in states.values())
        paused = (settings.root / "paused").exists()
        if closing:
            if not alive:
                root.destroy()
                return
        elif "failed" in states.values(): state.set(t("win.state.failed", current))
        elif workers.stopping and alive: state.set(t("win.state.stopping", current))
        elif alive: state.set(t("win.state.paused" if paused else "win.state.running", current))
        else: state.set(t("win.state.stopped", current))
        start_button.configure(state="disabled" if alive or closing else "normal")
        pause_button.configure(text=t("win.resume" if paused else "win.pause", current), state="disabled" if closing else "normal")
        capture.set(status_text(settings.root / "capture-status.json", current))
        index.set(status_text(settings.root / "index-status.json", current))
        root.after(1000, refresh)

    root.protocol("WM_DELETE_WINDOW", close)
    try:
        refresh()
        root.mainloop()
    finally:
        workers.stop()
        for p in workers.processes.values(): p.join()
        guard.__exit__(None, None, None)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
