"""Markdown-plus-frontmatter entries with an append-only event log."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml

FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)

VALID_STATUS = {"active", "superseded", "draft"}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


@dataclass
class Entry:
    """One fact cluster in the ledger."""

    id: str
    title: str
    body: str
    path: Path
    owner: str = "unknown"
    kind: str = "note"
    status: str = "active"
    tags: list[str] = field(default_factory=list)
    confidence: float = 0.8
    valid_from: str = ""
    updated_at: str = ""
    source: str = "manual"
    supersedes: list[str] = field(default_factory=list)
    superseded_by: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def frontmatter(self) -> dict[str, Any]:
        fm: dict[str, Any] = {
            "id": self.id,
            "title": self.title,
            "kind": self.kind,
            "owner": self.owner,
            "status": self.status,
            "tags": self.tags,
            "confidence": self.confidence,
            "valid_from": self.valid_from,
            "updated_at": self.updated_at,
            "source": self.source,
        }
        if self.supersedes:
            fm["supersedes"] = self.supersedes
        if self.superseded_by:
            fm["superseded_by"] = self.superseded_by
        fm.update(self.extra)
        return fm

    def to_markdown(self) -> str:
        fm = yaml.safe_dump(self.frontmatter, sort_keys=False, allow_unicode=True)
        return f"---\n{fm}---\n\n{self.body.strip()}\n"

    def digest(self) -> str:
        """Stable hash of everything that affects retrieval."""
        return content_hash(
            f"{self.title}\n{self.status}\n{self.owner}\n{','.join(self.tags)}\n{self.body}"
        )

    def as_context(self) -> str:
        """Rendering handed to a model. Compact, but keeps provenance."""
        head = (
            f"[{self.id}] {self.title}\n"
            f"kind={self.kind} owner={self.owner} status={self.status} "
            f"confidence={self.confidence} valid_from={self.valid_from} source={self.source}"
        )
        if self.superseded_by:
            head += f" superseded_by={self.superseded_by}"
        return f"{head}\n{self.body.strip()}"


def parse_entry(path: Path) -> Entry:
    raw = path.read_text(encoding="utf-8")
    m = FRONTMATTER_RE.match(raw)
    if not m:
        raise ValueError(f"{path}: missing YAML frontmatter")
    fm = yaml.safe_load(m.group(1)) or {}
    body = m.group(2)

    known = {
        "id", "title", "kind", "owner", "status", "tags", "confidence",
        "valid_from", "updated_at", "source", "supersedes", "superseded_by",
    }
    extra = {k: v for k, v in fm.items() if k not in known}

    entry = Entry(
        id=str(fm.get("id") or path.stem),
        title=str(fm.get("title") or path.stem),
        body=body,
        path=path,
        owner=str(fm.get("owner", "unknown")),
        kind=str(fm.get("kind", "note")),
        status=str(fm.get("status", "active")),
        tags=list(fm.get("tags") or []),
        confidence=float(fm.get("confidence", 0.8)),
        valid_from=str(fm.get("valid_from", "")),
        updated_at=str(fm.get("updated_at", "")),
        source=str(fm.get("source", "manual")),
        supersedes=list(fm.get("supersedes") or []),
        superseded_by=str(fm.get("superseded_by", "")),
        extra=extra,
    )
    if entry.status not in VALID_STATUS:
        raise ValueError(f"{path}: status must be one of {sorted(VALID_STATUS)}")
    return entry


def load_entries(ledger_dir: Path) -> list[Entry]:
    entries: list[Entry] = []
    for p in sorted(ledger_dir.rglob("*.md")):
        if p.name.startswith("_") or "README" in p.name:
            continue
        entries.append(parse_entry(p))
    ids = [e.id for e in entries]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"duplicate entry ids in ledger: {sorted(dupes)}")
    return entries


def append_event(events_path: Path, event: dict[str, Any]) -> dict[str, Any]:
    event = {"ts": utcnow(), **event}
    events_path.parent.mkdir(parents=True, exist_ok=True)
    with events_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    return event


def read_events(events_path: Path) -> list[dict[str, Any]]:
    if not events_path.exists():
        return []
    out = []
    for line in events_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def write_entry(entry: Entry) -> Path:
    entry.updated_at = utcnow()
    entry.path.parent.mkdir(parents=True, exist_ok=True)
    entry.path.write_text(entry.to_markdown(), encoding="utf-8")
    return entry.path


def supersede(old: Entry, new: Entry, events_path: Path, actor: str) -> None:
    new.supersedes = sorted(set(new.supersedes) | {old.id})
    old.status = "superseded"
    old.superseded_by = new.id
    write_entry(new)
    write_entry(old)
    append_event(
        events_path,
        {
            "type": "supersede",
            "actor": actor,
            "old_id": old.id,
            "new_id": new.id,
            "title": new.title,
        },
    )


def upsert(
    ledger_dir: Path,
    events_path: Path,
    *,
    entry_id: str,
    title: str,
    body: str,
    owner: str,
    kind: str = "note",
    tags: Iterable[str] = (),
    source: str = "manual",
    confidence: float = 0.8,
    subdir: str = "notes",
    actor: str = "system",
) -> Entry:
    """Create an entry, or retire the existing one to `<id>@<n>` and replace it."""
    existing = {e.id: e for e in load_entries(ledger_dir)}
    path = ledger_dir / subdir / f"{entry_id}.md"

    new = Entry(
        id=entry_id,
        title=title,
        body=body,
        path=path,
        owner=owner,
        kind=kind,
        tags=list(tags),
        source=source,
        confidence=confidence,
        valid_from=utcnow()[:10],
    )

    if entry_id in existing:
        old = existing[entry_id]
        if old.digest() == new.digest():
            return old
        rev = len([e for e in existing if e.startswith(f"{entry_id}@")]) + 1
        archived_id = f"{entry_id}@{rev}"
        archived = Entry(
            id=archived_id,
            title=old.title,
            body=old.body,
            path=old.path.with_name(f"{archived_id.replace('@', '-at-')}.md"),
            owner=old.owner,
            kind=old.kind,
            status="superseded",
            tags=old.tags,
            confidence=old.confidence,
            valid_from=old.valid_from,
            source=old.source,
            supersedes=old.supersedes,
            superseded_by=entry_id,
        )
        write_entry(archived)
        old.path.unlink(missing_ok=True)
        new.supersedes = [archived_id]
        write_entry(new)
        append_event(
            events_path,
            {
                "type": "update",
                "actor": actor,
                "id": entry_id,
                "archived_as": archived_id,
                "title": title,
                "source": source,
            },
        )
        return new

    write_entry(new)
    append_event(
        events_path,
        {"type": "create", "actor": actor, "id": entry_id, "title": title, "source": source},
    )
    return new


@dataclass
class Chunk:
    entry_id: str
    ordinal: int
    text: str

    @property
    def key(self) -> str:
        return f"{self.entry_id}#{self.ordinal}"


def chunk_entry(entry: Entry, size: int, overlap: int) -> list[Chunk]:
    """Chunk on paragraph boundaries, prefixed with the entry title."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", entry.body) if p.strip()]
    chunks: list[str] = []
    buf = ""
    for p in paras:
        if len(buf) + len(p) + 2 <= size:
            buf = f"{buf}\n\n{p}" if buf else p
        else:
            if buf:
                chunks.append(buf)
            if len(p) <= size:
                buf = p
            else:
                for i in range(0, len(p), size - overlap):
                    chunks.append(p[i : i + size])
                buf = ""
    if buf:
        chunks.append(buf)
    if not chunks:
        chunks = [entry.title]

    header = f"{entry.title} ({entry.kind}, owner {entry.owner})"
    return [Chunk(entry.id, i, f"{header}\n{c}") for i, c in enumerate(chunks)]
