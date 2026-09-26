import argparse
import json
import signal
import threading
from .config import Settings
from .service import PROFILES, PROFILE_ALIASES


def main():
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
    from .i18n import CHOICES
    language = sub.add_parser("language", help="Show or set the UI language"); language.add_argument("value", nargs="?", choices=CHOICES)
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
        from .clients import CLIENTS, cli_command, render
        from .service import profile_name
        import sys
        print("Add to: " + CLIENTS[args.client], file=sys.stderr)
        print(render(args.client, cli_command(), settings, profile_name(args.profile))); return
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
