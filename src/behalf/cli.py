"""behalf — a personal context store and the agent that argues from it."""
from __future__ import annotations

import argparse
import json
import sys

from .agent import AgentRun
from .brain import build_brain
from .capture import Capture, CaptureLog, Curator
from .config import CONFIG
from .roster import Roster, load_roster
from .scale import run_scale_test
from .store import ContextStore


def _roster() -> Roster:
    return load_roster()


def _author(explicit: str | None = None) -> str:
    if explicit:
        return explicit
    roster = _roster()
    return roster.by_key(roster.me).principal.split("(")[0].strip()


def _apply_convergence(roster: Roster) -> None:
    """config.yaml sets the defaults; environment variables still win."""
    import os

    for key, env in (
        ("max_rounds", "BEHALF_MAX_ROUNDS"),
        ("stability_rounds", "BEHALF_STABILITY_ROUNDS"),
        ("ratify_threshold", "BEHALF_RATIFY_THRESHOLD"),
    ):
        if key in roster.convergence and env not in os.environ:
            os.environ[env] = str(roster.convergence[key])


def cmd_index(_: argparse.Namespace) -> int:
    store = ContextStore(CONFIG)
    print(json.dumps(store.stats(), indent=2))
    store.close()
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    store = ContextStore(CONFIG)
    results = store.search(" ".join(args.query), k=args.k, include_superseded=args.all)
    if not results:
        print("no matches")
    for r in results:
        flag = "" if r.entry.status == "active" else f" ({r.entry.status})"
        print(f"{r.score:6.3f}  [{r.entry.id}]{flag} {r.entry.title}")
        if args.verbose:
            print("        " + r.passage.replace("\n", "\n        ")[:400])
    store.close()
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    store = ContextStore(CONFIG)
    for entry in store.history(args.id):
        print(f"[{entry.id}] {entry.status:11} {entry.updated_at}  {entry.title}")
    store.close()
    return 0


def cmd_note(args: argparse.Namespace) -> int:
    text = " ".join(args.text) if args.text else sys.stdin.read()
    if not text.strip():
        print("nothing to capture", file=sys.stderr)
        return 1
    log = CaptureLog(CONFIG.capture_path)
    capture = log.append(Capture.new(_author(args.author), text, source=args.source))
    print(f"captured {capture.id}")
    if args.curate:
        return cmd_curate(argparse.Namespace(author=args.author))
    print(f"{len(log.pending())} pending · run `behalf curate` to fold them in")
    return 0


def cmd_curate(args: argparse.Namespace) -> int:
    store = ContextStore(CONFIG)
    log = CaptureLog(CONFIG.capture_path)
    curator = Curator(store=store, log=log, brain=build_brain(CONFIG), author=_author(args.author))
    operations = curator.curate()
    if not operations:
        print("nothing pending")
    for op in operations:
        print(f"[{op.id}] {op.title}" + (f" — {op.reason}" if op.reason else ""))
    store.close()
    return 0


def cmd_captures(args: argparse.Namespace) -> int:
    for capture in CaptureLog(CONFIG.capture_path).all():
        if args.pending and capture.status != "pending":
            continue
        target = f" -> [{capture.entry_id}]" if capture.entry_id else ""
        print(f"{capture.ts}  {capture.status:8}{target}  {capture.text[:90]}")
    return 0


def cmd_chat(args: argparse.Namespace) -> int:
    """Interactive capture. Plain text is a note; slash commands do the rest."""
    store = ContextStore(CONFIG)
    log = CaptureLog(CONFIG.capture_path)
    author = _author(args.author)
    print(f"behalf · {author} · plain text captures a note. /ask /curate /pending /quit")

    try:
        while True:
            try:
                line = input("> ").strip()
            except EOFError:
                break
            if not line:
                continue
            if line in {"/quit", "/exit"}:
                break
            if line.startswith("/ask "):
                for r in store.search(line[5:], k=5):
                    print(f"  {r.score:5.3f} [{r.entry.id}] {r.entry.title}")
                continue
            if line == "/pending":
                for c in log.pending():
                    print(f"  {c.ts}  {c.text[:80]}")
                continue
            if line == "/curate":
                curator = Curator(store, log, build_brain(CONFIG), author)
                for op in curator.curate() or []:
                    print(f"  wrote [{op.id}] {op.title}")
                continue
            capture = log.append(Capture.new(author, line, source="chat"))
            print(f"  captured {capture.id}")
    finally:
        store.close()
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    """Non-interactive write, for adapters (email, Slack, cron)."""
    body = args.body or sys.stdin.read()
    store = ContextStore(CONFIG)
    entry = store.write(
        entry_id=args.id, title=args.title, body=body, owner=args.owner,
        kind=args.kind, tags=args.tag, source=args.source, subdir=args.subdir,
        actor=f"ingest:{args.source}",
    )
    print(f"wrote [{entry.id}] {entry.title} -> {entry.path}")
    if entry.supersedes:
        print(f"  superseded {', '.join(entry.supersedes)} (audit trail kept)")
    store.close()
    return 0


def cmd_roster(_: argparse.Namespace) -> int:
    roster = _roster()
    print(f"room    {roster.room_base}")
    print(f"meeting {roster.meeting}")
    print(f"me      {roster.me}")
    for i, agent in enumerate(roster.agents):
        mark = " (scribe)" if agent.scribe else ""
        print(f"  {i}. {agent.name:<20} {agent.key:<10} {agent.principal}{mark}")
    return 0


def cmd_agent(args: argparse.Namespace) -> int:
    roster = _roster()
    _apply_convergence(roster)
    agent = roster.by_key(args.role or roster.me)
    names = [n.strip() for n in args.roster.split(",") if n.strip()] or roster.names
    return AgentRun(
        cfg=CONFIG,
        role=agent,
        roster=names,
        meeting=args.meeting or roster.meeting,
        scribe=args.scribe or agent.scribe,
    ).run()


def cmd_scale(args: argparse.Namespace) -> int:
    roster = _roster()
    _apply_convergence(roster)
    report = run_scale_test(CONFIG, roster, size=args.agents, stagger=args.stagger)
    print(report.table())
    print(f"\nreport  {CONFIG.out_dir / 'scale-report.json'}")
    print(f"logs    {CONFIG.out_dir / 'agents'}")
    return 0 if all(r.exit_code == 0 for r in report.results) else 1


def cmd_preread(_: argparse.Namespace) -> int:
    if CONFIG.preread_path.exists():
        print(CONFIG.preread_path.read_text(encoding="utf-8"))
        return 0
    print("no pre-read generated yet", file=sys.stderr)
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="behalf", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("index", help="sync the vector index with the ledger").set_defaults(func=cmd_index)
    sub.add_parser("roster", help="show the configured room and agents").set_defaults(func=cmd_roster)
    sub.add_parser("preread", help="print the current one-pager").set_defaults(func=cmd_preread)

    search = sub.add_parser("search", help="vector search the context store")
    search.add_argument("query", nargs="+")
    search.add_argument("-k", type=int, default=6)
    search.add_argument("--all", action="store_true", help="include superseded entries")
    search.add_argument("-v", "--verbose", action="store_true")
    search.set_defaults(func=cmd_search)

    history = sub.add_parser("history", help="walk an entry's supersede chain")
    history.add_argument("id")
    history.set_defaults(func=cmd_history)

    note = sub.add_parser("note", help="capture an update in your own words")
    note.add_argument("text", nargs="*")
    note.add_argument("--author", default="")
    note.add_argument("--source", default="cli")
    note.add_argument("--curate", action="store_true", help="fold it in immediately")
    note.set_defaults(func=cmd_note)

    curate = sub.add_parser("curate", help="fold pending captures into the ledger")
    curate.add_argument("--author", default="")
    curate.set_defaults(func=cmd_curate)

    captures = sub.add_parser("captures", help="show the capture log")
    captures.add_argument("--pending", action="store_true")
    captures.set_defaults(func=cmd_captures)

    chat = sub.add_parser("chat", help="interactive capture and lookup")
    chat.add_argument("--author", default="")
    chat.set_defaults(func=cmd_chat)

    ingest = sub.add_parser("ingest", help="write an entry directly (for adapters)")
    ingest.add_argument("--id", required=True)
    ingest.add_argument("--title", required=True)
    ingest.add_argument("--owner", required=True)
    ingest.add_argument("--body", default="")
    ingest.add_argument("--kind", default="note")
    ingest.add_argument("--source", default="manual")
    ingest.add_argument("--subdir", default="notes")
    ingest.add_argument("--tag", action="append", default=[])
    ingest.set_defaults(func=cmd_ingest)

    agent = sub.add_parser("agent", help="run your agent in the room")
    agent.add_argument("--role", default="", help="agent key from config.yaml; defaults to `me`")
    agent.add_argument("--roster", default="")
    agent.add_argument("--meeting", default="")
    agent.add_argument("--scribe", action="store_true")
    agent.set_defaults(func=cmd_agent)

    scale = sub.add_parser("scale", help="run N process-isolated agents against one room")
    scale.add_argument("--agents", type=int, default=3)
    scale.add_argument("--stagger", type=float, default=1.5)
    scale.set_defaults(func=cmd_scale)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
