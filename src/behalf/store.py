"""The context store: the single surface agents read from and write to."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .config import Config
from .embed import build_embedder
from .index import Hit, VectorIndex
from .ledger import Entry, append_event, load_entries, read_events, upsert


@dataclass
class Retrieved:
    entry: Entry
    score: float
    passage: str


class ContextStore:
    def __init__(self, cfg: Config) -> None:
        cfg.ensure_dirs()
        self.cfg = cfg
        self.embedder = build_embedder(cfg)
        self.index = VectorIndex(cfg.db_path, self.embedder)
        self._entries: dict[str, Entry] = {}
        self.reload()

    def reload(self) -> dict[str, int]:
        entries = load_entries(self.cfg.ledger_dir)
        self._entries = {e.id: e for e in entries}
        return self.index.sync(entries, self.cfg.chunk_chars, self.cfg.chunk_overlap)

    def close(self) -> None:
        self.index.close()

    @property
    def live(self) -> list[Entry]:
        return [e for e in self._entries.values() if e.status == "active"]

    def get(self, entry_id: str) -> Entry | None:
        return self._entries.get(entry_id)

    def history(self, entry_id: str) -> list[Entry]:
        """Walk the supersede chain backwards from a live entry."""
        chain: list[Entry] = []
        entry = self._entries.get(entry_id)
        while entry is not None:
            chain.append(entry)
            prior = entry.supersedes[0] if entry.supersedes else None
            entry = self._entries.get(prior) if prior else None
        return chain

    def search(self, query: str, k: int | None = None, include_superseded: bool = False) -> list[Retrieved]:
        k = k or self.cfg.retrieve_k
        allowed = None if include_superseded else {e.id for e in self.live}
        hits: list[Hit] = self.index.search(query, k=k * 2, allowed=allowed)

        best: dict[str, Retrieved] = {}
        for hit in hits:
            entry = self._entries.get(hit.entry_id)
            if entry is None or hit.entry_id in best:
                continue
            best[hit.entry_id] = Retrieved(entry=entry, score=hit.score, passage=hit.text)
            if len(best) >= k:
                break
        return list(best.values())

    def context_block(self, query: str, k: int | None = None) -> str:
        results = self.search(query, k)
        if not results:
            return "(no matching entries in the context store)"
        return "\n\n---\n\n".join(
            f"score={r.score:.3f}\n{r.entry.as_context()}" for r in results
        )

    def write(
        self,
        *,
        entry_id: str,
        title: str,
        body: str,
        owner: str,
        kind: str = "note",
        tags: Iterable[str] = (),
        source: str = "agent",
        subdir: str = "notes",
        actor: str = "agent",
    ) -> Entry:
        entry = upsert(
            self.cfg.ledger_dir,
            self.cfg.events_path,
            entry_id=entry_id,
            title=title,
            body=body,
            owner=owner,
            kind=kind,
            tags=tags,
            source=source,
            subdir=subdir,
            actor=actor,
        )
        self.reload()
        return entry

    def record(self, event: dict) -> None:
        append_event(self.cfg.events_path, event)

    def events(self) -> list[dict]:
        return read_events(self.cfg.events_path)

    def stats(self) -> dict[str, object]:
        return {
            **self.index.stats(),
            "live_entries": len(self.live),
            "total_entries": len(self._entries),
            "events": len(self.events()),
        }
