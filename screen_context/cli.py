import argparse
import json
import signal
import sys
import threading
from .config import Settings
from .service import PROFILES, PROFILE_ALIASES


def main():
    # Output is JSON for scripts. Frozen Windows builds ignore PYTHONIOENCODING and would write the
    # ANSI code page (cp932 on Japanese systems), which UTF-8 readers cannot decode (#44).
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"): stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Local screen context capture, index and MCP")
    sub = parser.add_subparsers(dest="command", required=True)
    for cmd in ("init", "status", "pause", "resume", "maintain", "health"): sub.add_parser(cmd)
    diary = sub.add_parser("diary-material"); diary.add_argument("date"); diary.add_argument("--budget", type=int, default=6000); diary.add_argument("--lang", choices=["en", "ja"])
    proposal = sub.add_parser("proposal"); proposal.add_argument("action", choices=["prepare", "finish", "simulate"])
    proposal.add_argument("--run-id"); proposal.add_argument("--response-file"); proposal.add_argument("--window", type=int, default=60); proposal.add_argument("--fresh", type=int, default=15)
    capture = sub.add_parser("capture"); capture.add_argument("--once", action="store_true")
    indexer = sub.add_parser("index"); indexer.add_argument("--watch", action="store_true")
    profiles = [*PROFILES, *PROFILE_ALIASES]
    mcp = sub.add_parser("serve"); mcp.add_argument("--profile", choices=profiles, default="standard"); mcp.add_argument("--transport", choices=["stdio", "http"], default="stdio"); mcp.add_argument("--port", type=int, default=8765)
    from .clients import CLIENTS
    config = sub.add_parser("mcp-config", help="Print the MCP server entry for a client")
    config.add_argument("--client", choices=list(CLIENTS), default="generic"); config.add_argument("--profile", choices=profiles, default="standard")
    config.add_argument("--name", help="Name for this client's token (default: the client). Running again replaces its token.")
    clients = sub.add_parser("clients", help="List or revoke MCP client tokens")
    clients.add_argument("action", choices=["list", "approve", "revoke"]); clients.add_argument("name", nargs="?")
    from .i18n import CHOICES
    language = sub.add_parser("language", help="Show or set the UI language"); language.add_argument("value", nargs="?", choices=CHOICES)
    purge = sub.add_parser("purge", help="Delete frames and everything derived from them (no undo)")
    purge.add_argument("--from", dest="since", help="local time, YYYY-MM-DD or YYYY-MM-DDTHH:MM")
    purge.add_argument("--to", dest="until", help="local time, exclusive"); purge.add_argument("--last", help="for example 15m, 2h, 1d")
    purge.add_argument("--app", help="bundle ID or process name"); purge.add_argument("--keyword"); purge.add_argument("--block", help="activity block ID")
    purge.add_argument("--excluded", action="store_true", help="frames the current policy excludes (hidden until now)")
    purge.add_argument("--yes", action="store_true", help="delete; without it, only show what would be deleted")
    check = sub.add_parser("pii-check", help="Show which sensitive-input rules a text file would trigger")
    check.add_argument("file")
    audit = sub.add_parser("audit", help="Show or export what each client read (user path only)")
    audit.add_argument("action", choices=["list", "export"]); audit.add_argument("--client")
    audit.add_argument("--since", help="YYYY-MM-DD, local time"); audit.add_argument("--limit", type=int, default=100)
    for cmd in ("export", "push"):
        p = sub.add_parser(cmd); p.add_argument("date")
    args = parser.parse_args()
    settings = Settings.environment()
    stop = threading.Event()
    if args.command != "serve":
        for sig in (signal.SIGINT, signal.SIGTERM): signal.signal(sig, lambda *_: stop.set())
    from . import store
    if args.command == "init":
        before, after = store.initialize(settings); result = {"root": str(settings.root), "encrypted": not settings.plaintext, "schema": [before, after]}
    elif args.command == "health":
        from .health import health
        result = health(settings)
    elif args.command == "diary-material":
        from .material import diary_markdown
        print(diary_markdown(settings, args.date, args.budget, lang=args.lang)); return
    elif args.command == "proposal":
        from . import runner
        if args.action == "finish":
            if not args.run_id or not args.response_file: parser.error("finish requires --run-id and --response-file")
            from pathlib import Path
            result = runner.finish(settings, args.run_id, Path(args.response_file).read_text(encoding="utf-8"))
        else:
            # simulate uses its own cursor so a dry run never consumes the real consumer's observations.
            outcome, material = runner.prepare(settings, consumer=runner.CONSUMER if args.action == "prepare" else "simulate", window_minutes=args.window, fresh_minutes=args.fresh)
            if outcome != "ready":
                # Last stdout line is a wake gate for a scheduler pre-run script: the agent is not started.
                print(json.dumps({"wakeAgent": False, "outcome": outcome})); return
            from .i18n import resolve
            print(runner.material_markdown(material, resolve(settings)))
            if args.action == "simulate":
                print("\n[simulate] run closed without delivery:", json.dumps(runner.finish(settings, material["run_id"], "[SILENT]")))
            return
    elif args.command == "purge":
        import time
        from datetime import datetime
        from . import purge
        try:
            since = datetime.fromisoformat(args.since).timestamp() if args.since else None
            until = datetime.fromisoformat(args.until).timestamp() if args.until else None
            if args.last: since = max(since or 0, time.time() - purge.duration(args.last))
            selector = {"since": since, "until": until, "app": args.app, "keyword": args.keyword, "block": args.block, "excluded": args.excluded}
            ids = purge.select(settings, **selector)
        except ValueError as error: parser.error(str(error))
        # Frames not yet OCRed match only on time and app; content selectors cannot see them.
        content = args.keyword or args.block or args.excluded
        spool_files = [] if content or (since is None and until is None) else purge.spooled(settings, since, until, args.app)
        if not args.yes:
            result = {**purge.plan(settings, ids, spool_files), "deleted": False,
                      "next": "Run again with --yes to delete. This cannot be undone."}
        elif not ids and not spool_files: result = {"frames": 0, "deleted": False}
        else: result = {**purge.execute(settings, ids, selector, spool_files), "deleted": True}
    elif args.command == "pii-check":
        from pathlib import Path
        from .config import DEFAULT_POLICY
        from .pii import scan
        from .sensitive import detect
        try: policy = settings.policy()
        except FileNotFoundError: policy = DEFAULT_POLICY  # works before init, with the defaults
        text = Path(args.file).read_text(encoding="utf-8")
        lines = text.splitlines()
        indexes, combinations = scan(lines, policy["pii_combinations"])
        result = {"drop_frame": detect(text, policy["sensitive_detectors"]), "combinations": combinations,
                  "redacted_lines": [{"line": i + 1, "text": lines[i]} for i in sorted(indexes)]}
    elif args.command == "audit":
        from datetime import datetime
        from . import audit
        try: since = datetime.strptime(args.since, "%Y-%m-%d").timestamp() if args.since else None
        except ValueError: parser.error("--since must be YYYY-MM-DD")
        if not 1 <= args.limit <= 100000: parser.error("--limit must be between 1 and 100000")
        entries = audit.rows(settings, args.client, since, args.limit)
        if args.action == "list": result = entries
        else:
            # Plaintext leaves the encrypted store here, so the export itself is audited.
            audit.record(settings, "user", "cli", "audit.export", params={"client": args.client, "since": args.since, "limit": args.limit}, count=len(entries))
            for entry in entries: print(json.dumps(entry, ensure_ascii=False))
            return
    elif args.command == "status":
        result = {"initialized": settings.db.exists(), "paused": (settings.root / "paused").exists(), "queued": len(list((settings.root / "spool").glob("*.frame"))), "encrypted": not settings.plaintext}
    elif args.command in ("pause", "resume"):
        if args.command == "pause": (settings.root / "paused").touch(mode=0o600)
        else: (settings.root / "paused").unlink(missing_ok=True)
        result = {"paused": args.command == "pause"}
    elif args.command == "capture":
        from .capture import run
        from .locking import lock
        with lock(settings.root / "capture.lock"): result = run(settings, args.once, stop)
    elif args.command == "index":
        import time
        from .indexer import drain, maintain
        from .locking import lock
        last_maintenance = 0
        with lock(settings.root / "indexer.lock"):
            while True:
                result = drain(settings)
                if time.monotonic()-last_maintenance > 3600:
                    maintain(settings); last_maintenance = time.monotonic()
                if not args.watch or stop.wait(5): break
    elif args.command == "maintain":
        from .indexer import maintain
        from .locking import lock
        with lock(settings.root / "indexer.lock"): result = maintain(settings)
    elif args.command == "mcp-config":
        from .access import issue
        from .clients import CLIENTS, cli_command, render
        from .service import profile_name
        if not settings.db.exists(): parser.error("run screen-context init first")
        profile = profile_name(args.profile)
        token = issue(settings, args.name or args.client, profile)
        name = args.name or args.client
        print(f"Add to: {CLIENTS[args.client]}. This replaces any earlier token for {name}. "
              f"On its first call, approve {name} in the ScreenContext app (or run: screen-context clients approve {name}).", file=sys.stderr)
        print(render(args.client, cli_command(), settings, token, profile)); return
    elif args.command == "clients":
        from . import access
        if args.action == "list": result = access.clients(settings)
        elif not args.name: parser.error(args.action + " requires a client name")
        elif args.action == "approve": access.decide(settings, args.name, True, "cli"); result = {"approved": args.name}
        else: access.revoke(settings, args.name); result = {"revoked": args.name}
    elif args.command == "language":
        from .i18n import resolve
        if args.value: settings.root.mkdir(parents=True, exist_ok=True, mode=0o700); settings.set_language(args.value)
        result = {"language": settings.language(), "effective": resolve(settings)}
    elif args.command == "serve":
        from .mcp_server import run
        run(settings, args.profile, args.transport, args.port); return
    else:
        from . import viking
        result = {"path": str(viking.export(settings, args.date))} if args.command == "export" else viking.push(settings, args.date)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__": main()
