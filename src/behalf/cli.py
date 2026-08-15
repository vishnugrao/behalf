"""behalf — your context store, and the agent that speaks as you."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .agent import AgentRun
from .brain import build_brain
from .capture import Capture, CaptureLog, Curator
from .chat import ChatSession
from .config import CONFIG
from .gdoc import GoogleDocError, GoogleDocPublisher
from .persona import Room, load_room
from .store import ContextStore


def _room() -> Room:
    return load_room()


def _author(explicit: str | None = None) -> str:
    if explicit:
        return explicit
    room = _room()
    return room.by_key(room.me).person


def _apply_convergence(room: Room) -> None:
    for key, env in (
        ("max_rounds", "BEHALF_MAX_ROUNDS"),
        ("stability_rounds", "BEHALF_STABILITY_ROUNDS"),
        ("ratify_threshold", "BEHALF_RATIFY_THRESHOLD"),
    ):
        if key in room.convergence and env not in os.environ:
            os.environ[env] = str(room.convergence[key])


def _publisher(room: Room, extra_emails: list[str]) -> GoogleDocPublisher:
    recipients = list(room.google.get("share_with") or [])
    recipients += [p.email for p in room.personas if p.email]
    recipients += [e for e in CONFIG.google_share_with.split(",") if e.strip()]
    recipients += extra_emails
    return GoogleDocPublisher(
        state_dir=CONFIG.state_dir,
        title=str(room.google.get("document_title") or f"{room.meeting} — pre-read"),
        client_id=CONFIG.google_client_id,
        client_secret=CONFIG.google_client_secret,
        share_with=recipients,
        document_id=CONFIG.gdoc_id,
        credentials_file=Path(CONFIG.google_credentials_file),
    )


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
    if curator.fallback_reason:
        print(f"verbatim capture only — {curator.fallback_reason}", file=sys.stderr)
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
    room = _room()
    persona = room.by_key(args.persona or room.me)
    store = ContextStore(CONFIG)
    brain = build_brain(CONFIG)
    session = ChatSession(
        persona=persona, store=store, brain=brain, log=CaptureLog(CONFIG.capture_path)
    )

    print(f"behalf · you are {persona.person} · brain {brain.name} · store {store.stats()['live_entries']} entries")
    print("Ask it anything about your own store, or just tell it what changed. /raw /pending /quit")

    try:
        while True:
            try:
                line = input("\n> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not line:
                continue
            if line.lower() in {"/quit", "/exit", "quit", "exit", ":q"}:
                break
            if line == "/pending":
                for c in session.log.pending():
                    print(f"  {c.ts}  {c.text[:80]}")
                continue
            if line.startswith("/raw "):
                for r in store.search(line[5:], k=5):
                    print(f"  {r.score:5.3f} [{r.entry.id}] {r.entry.title}")
                continue

            answer = session.ask(line)
            for step in session.trace:
                print(f"  · {step}")
            print(f"\n{answer}")
    finally:
        store.close()
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
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


def cmd_who(_: argparse.Namespace) -> int:
    room = _room()
    print(f"room     {room.base}")
    print(f"meeting  {room.meeting}")
    print(f"this machine runs  {room.by_key(room.me).person}  (--persona {room.me})")
    print("\nturn order:")
    for i, persona in enumerate(room.personas):
        mark = " · scribe, publishes the doc" if persona.scribe else ""
        print(f"  {i}. {persona.person:<20} {persona.key:<8} {persona.role}{mark}")
    return 0


def cmd_agent(args: argparse.Namespace) -> int:
    room = _room()
    _apply_convergence(room)
    persona = room.by_key(args.persona or room.me)

    run = AgentRun(
        cfg=CONFIG,
        persona=persona,
        roster=room.names,
        meeting=args.meeting or room.meeting,
        scribe=args.scribe or persona.scribe,
        publisher=None if args.no_doc else _publisher(room, args.share),
    )

    if args.dry_run:
        print(f"persona   {persona.person} ({persona.key})")
        print(f"role      {persona.role}")
        print(f"scribe    {run.scribe}")
        print(f"roster    {', '.join(room.names)}")
        print(f"position  {run.position}")
        print(f"brain     {run.brain.name}")
        print("---")
        print(run.system_prompt())
        run.store.close()
        return 0

    return run.run()


def cmd_publish(args: argparse.Namespace) -> int:
    if not CONFIG.preread_path.exists():
        print("no pre-read to publish yet — run your agent first", file=sys.stderr)
        return 1
    room = _room()
    publisher = _publisher(room, args.share)
    try:
        print(publisher.publish(CONFIG.preread_path.read_text(encoding="utf-8")))
    except GoogleDocError as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


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
    sub.add_parser("who", help="show the room, the turn order and who you are").set_defaults(func=cmd_who)
    sub.add_parser("preread", help="print the current one-pager").set_defaults(func=cmd_preread)

    search = sub.add_parser("search", help="hybrid search over your store")
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

    curate = sub.add_parser("curate", help="fold pending captures into your ledger")
    curate.add_argument("--author", default="")
    curate.set_defaults(func=cmd_curate)

    captures = sub.add_parser("captures", help="show the capture log")
    captures.add_argument("--pending", action="store_true")
    captures.set_defaults(func=cmd_captures)

    chat = sub.add_parser("chat", help="ask your own store questions, or tell it what changed")
    chat.add_argument("--author", default="")
    chat.add_argument("--persona", default="")
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

    agent = sub.add_parser("agent", help="join the room as one persona (one process, one person)")
    agent.add_argument("--persona", default="", help="persona key from config.yaml; defaults to `me`")
    agent.add_argument("--meeting", default="")
    agent.add_argument("--scribe", action="store_true", help="force this process to publish the doc")
    agent.add_argument("--share", action="append", default=[], metavar="EMAIL",
                       help="also share the Google Doc with this address (repeatable)")
    agent.add_argument("--no-doc", action="store_true", help="skip the Google Doc, write locally only")
    agent.add_argument("--dry-run", action="store_true", help="print the resolved persona and exit")
    agent.set_defaults(func=cmd_agent)

    publish = sub.add_parser("publish", help="push the current pre-read to the shared Google Doc")
    publish.add_argument("--share", action="append", default=[], metavar="EMAIL")
    publish.set_defaults(func=cmd_publish)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
