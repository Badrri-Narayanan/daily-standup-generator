"""`standup` command line: serve, generate, init, history."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from importlib import resources
from pathlib import Path

from pydantic import ValidationError

from . import generator
from .config import AppConfig, load_config
from .history import HistoryStore

DEFAULT_PORT = 8765


def _load(path: str | None) -> AppConfig | None:
    try:
        return load_config(path)
    except (ValidationError, ValueError, FileNotFoundError, OSError) as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return None


def _cmd_serve(args) -> int:
    cfg = _load(args.config)
    if cfg is None:
        return 2
    import uvicorn

    from .web.app import create_app

    print(f"Standup generator running at http://{args.host}:{args.port}")
    uvicorn.run(create_app(cfg), host=args.host, port=args.port, log_level="warning")
    return 0


def _cmd_generate(args) -> int:
    cfg = _load(args.config)
    if cfg is None:
        return 2
    result = generator.generate(
        cfg, plans=args.plans or "", blockers=args.blockers or "",
        since=date.fromisoformat(args.since) if args.since else None, save=not args.no_save,
    )
    for errors in result.bundle.source_errors.values():
        for e in errors:
            print(e, file=sys.stderr)
    print(result.prompt)
    return 0


def _normalise_url(url: str) -> str:
    url = url.strip().rstrip("/")
    return url if "://" in url else f"https://{url}"


def _cmd_init(args) -> int:
    target = Path(args.dir).expanduser()
    files = {"standup.yaml": "standup.example.yaml", ".env.example": "env.example"}
    existing = [name for name in files if (target / name).exists()]
    if existing:
        print(f"refusing to overwrite existing {', '.join(existing)} in {target}", file=sys.stderr)
        return 1
    target.mkdir(parents=True, exist_ok=True)
    pkg = resources.files("standup_generator").joinpath("templates")
    jira_url = args.jira_url
    if jira_url is None and sys.stdin.isatty():
        jira_url = input("Jira site URL (e.g. https://yourco.atlassian.net, blank to skip): ")
    for name, source in files.items():
        text = pkg.joinpath(source).read_text()
        if name == ".env.example" and jira_url and jira_url.strip():
            text = text.replace("JIRA_BASE_URL=\n", f"JIRA_BASE_URL={_normalise_url(jira_url)}\n")
        (target / name).write_text(text)
        print(f"wrote {target / name}")
    print("Next: copy .env.example to .env, fill in JIRA_BASE_URL and your tokens, and edit standup.yaml.")
    return 0


def _history_store(args) -> HistoryStore | None:
    cfg = _load(args.config)
    if cfg is None:
        return None
    if not cfg.history.enabled:
        print("history is disabled in config", file=sys.stderr)
        return None
    return HistoryStore(cfg.history.db_path)


def _cmd_history(args) -> int:
    store = _history_store(args)
    if store is None:
        return 2
    if args.action is None:
        for s in store.list(args.limit):
            mark = "✓" if s.has_final else " "
            print(f"{s.id:>4}  {s.created_at}  {mark}  {s.window_start[:10]} → {s.window_end[:10]}  {s.preview}")
        return 0
    entry = store.get(args.id)
    if entry is None:
        print(f"no history entry {args.id}", file=sys.stderr)
        return 1
    if args.action == "show":
        print(entry.prompt)
        print("\n----- Final standup -----\n")
        print(entry.final_standup or "(none saved)")
        return 0
    text = Path(args.file).read_text() if args.file else sys.stdin.read()
    store.set_final(args.id, text.strip())
    print(f"saved final standup for entry {args.id}")
    return 0


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="standup", description="Build a daily standup prompt from your work.")
    sub = p.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="run the local web app")
    serve.add_argument("--config")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=DEFAULT_PORT)
    serve.set_defaults(func=_cmd_serve)

    gen = sub.add_parser("generate", help="print the prompt to stdout")
    gen.add_argument("--config")
    gen.add_argument("--since", help="YYYY-MM-DD; overrides the last working day")
    gen.add_argument("--plans")
    gen.add_argument("--blockers")
    gen.add_argument("--no-save", action="store_true", help="don't record in history")
    gen.set_defaults(func=_cmd_generate)

    init = sub.add_parser("init", help="write example standup.yaml and .env.example")
    init.add_argument("--dir", default=".")
    init.add_argument("--jira-url", help="your Jira site, e.g. https://acme.atlassian.net")
    init.set_defaults(func=_cmd_init)

    hist = sub.add_parser("history", help="list past generations")
    hist.add_argument("--config")
    hist.add_argument("--limit", type=int, default=20)
    hist.set_defaults(func=_cmd_history, action=None)
    hsub = hist.add_subparsers(dest="action")
    show = hsub.add_parser("show", help="print one entry")
    show.add_argument("id", type=int)
    save = hsub.add_parser("save-final", help="save the AI's final standup (from --file or stdin)")
    save.add_argument("id", type=int)
    save.add_argument("--file")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
