"""Raw capture log, and the curation pass that folds it into the ledger."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .brain import Brain, BrainError, ScriptedBrain, Turn, extract_json
from .store import ContextStore

SLUG_RE = re.compile(r"[^a-z0-9]+")

CURATOR_SYSTEM = """You curate one person's knowledge store.

You are given raw notes they typed, plus the entries already in the store that
those notes appear to touch. Fold the notes into the store.

Rules:
- Prefer updating an existing entry over creating a near-duplicate one.
- If a note contradicts a live entry, update that entry. Do not keep both as
  true; the store's history mechanism preserves the old version for you.
- Keep the body as prose a colleague could read cold. No bullet soup.
- Never invent facts the notes and entries do not support.
- Preserve who owns a fact and where it came from.

Reply with JSON only:

{"operations":[{"id":"stable-kebab-id","title":"one readable line",
"kind":"note|decision|risk|metric|person|customer","subdir":"notes",
"body":"the full replacement prose for this entry","reason":"why this changed"}]}
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slug(text: str, limit: int = 48) -> str:
    return SLUG_RE.sub("-", text.lower()).strip("-")[:limit] or "note"


@dataclass
class Capture:
    id: str
    ts: str
    author: str
    text: str
    source: str = "cli"
    status: str = "pending"
    entry_id: str = ""

    @classmethod
    def new(cls, author: str, text: str, source: str = "cli") -> "Capture":
        ts = utcnow()
        return cls(
            id=f"cap-{ts.replace(':', '').replace('-', '')}-{slug(text, 16)}",
            ts=ts,
            author=author,
            text=text.strip(),
            source=source,
        )


class CaptureLog:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, capture: Capture) -> Capture:
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(capture), ensure_ascii=False) + "\n")
        return capture

    def all(self) -> list[Capture]:
        if not self.path.exists():
            return []
        rows: dict[str, Capture] = {}
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                record = json.loads(line)
                rows[record["id"]] = Capture(**record)
        return list(rows.values())

    def pending(self) -> list[Capture]:
        return [c for c in self.all() if c.status == "pending"]

    def resolve(self, capture: Capture, status: str, entry_id: str = "") -> None:
        capture.status = status
        capture.entry_id = entry_id
        self.append(capture)


@dataclass
class Operation:
    id: str
    title: str
    body: str
    kind: str = "note"
    subdir: str = "notes"
    reason: str = ""

    @classmethod
    def parse(cls, raw: dict[str, Any]) -> "Operation | None":
        if not str(raw.get("id", "")).strip() or not str(raw.get("body", "")).strip():
            return None
        return cls(
            id=slug(str(raw["id"])),
            title=str(raw.get("title") or raw["id"]).strip(),
            body=str(raw["body"]).strip(),
            kind=str(raw.get("kind", "note")),
            subdir=str(raw.get("subdir", "notes")),
            reason=str(raw.get("reason", "")),
        )


@dataclass
class Curator:
    store: ContextStore
    log: CaptureLog
    brain: Brain
    author: str
    applied: list[Operation] = field(default_factory=list)
    fallback_reason: str = ""

    def curate(self) -> list[Operation]:
        pending = self.log.pending()
        if not pending:
            return []

        joined = "\n\n".join(f"- ({c.ts}, {c.author}) {c.text}" for c in pending)
        related = self.store.context_block(joined, k=5)
        prompt = (
            f"# Raw notes to fold in\n{joined}\n\n"
            f"# Entries these appear to touch\n{related}\n\n"
            f"The author is {self.author}. Emit the operations."
        )

        operations: list[Operation] = []
        if isinstance(self.brain, ScriptedBrain):
            self.fallback_reason = "no model provider configured"
        else:
            try:
                raw = self.brain.think(CURATOR_SYSTEM, [Turn("user", prompt)])
                payload = extract_json(raw)
                operations = [
                    op for op in (Operation.parse(r) for r in payload.get("operations") or []) if op
                ]
                if not operations:
                    self.fallback_reason = f"model returned no usable operations: {raw[:160]}"
            except BrainError as exc:
                self.fallback_reason = f"model call failed: {exc}"

        if not operations:
            operations = [self._fallback(c) for c in pending]

        for operation in operations:
            entry = self.store.write(
                entry_id=operation.id,
                title=operation.title,
                body=operation.body,
                owner=self.author,
                kind=operation.kind,
                tags=["curated"],
                source="cli",
                subdir=operation.subdir,
                actor=f"curator:{self.author}",
            )
            self.store.record(
                {
                    "type": "curate",
                    "actor": f"curator:{self.author}",
                    "id": entry.id,
                    "reason": operation.reason,
                    "captures": [c.id for c in pending],
                }
            )
            self.applied.append(operation)

        for capture in pending:
            self.log.resolve(capture, "curated", entry_id=operations[0].id if operations else "")
        return operations

    def _fallback(self, capture: Capture) -> Operation:
        first, _, rest = capture.text.partition("\n")
        title = first.strip().rstrip(".")[:80] or "Untitled note"
        return Operation(
            id=slug(title),
            title=title,
            body=(rest.strip() or capture.text.strip()),
            reason=f"verbatim capture {capture.id}",
        )
