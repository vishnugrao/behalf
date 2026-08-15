"""Hybrid retrieval over ledger chunks: embedding cosine fused with BM25."""
from __future__ import annotations

import math
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np

from .embed import Embedder
from .ledger import Chunk, Entry, chunk_entry, content_hash

WORD_RE = re.compile(r"[a-z0-9]+")
RRF_K = 60.0
BM25_K1 = 1.5
BM25_B = 0.75
SUFFIXES = ("ations", "ation", "ingly", "ering", "ings", "edly", "ing", "ers", "er", "ed", "es", "s")


def stem(word: str) -> str:
    for suffix in SUFFIXES:
        if len(word) > len(suffix) + 2 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


LINK_RE = re.compile(r"\[[a-z0-9][\w\-@.]*\]")


def terms_of(text: str) -> list[str]:
    return [stem(w) for w in WORD_RE.findall(LINK_RE.sub(" ", text.lower()))]

SCHEMA = """
CREATE TABLE IF NOT EXISTS chunks (
    key         TEXT PRIMARY KEY,
    entry_id    TEXT NOT NULL,
    ordinal     INTEGER NOT NULL,
    text        TEXT NOT NULL,
    hash        TEXT NOT NULL,
    embedder    TEXT NOT NULL,
    vector      BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS chunks_entry ON chunks(entry_id);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT NOT NULL);
"""


@dataclass
class Hit:
    entry_id: str
    key: str
    score: float
    text: str


class VectorIndex:
    def __init__(self, db_path: Path, embedder: Embedder) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(db_path)
        self.db.executescript(SCHEMA)
        self.embedder = embedder

    def close(self) -> None:
        self.db.close()

    def sync(self, entries: Sequence[Entry], chunk_chars: int, overlap: int) -> dict[str, int]:
        wanted: dict[str, Chunk] = {}
        for e in entries:
            for c in chunk_entry(e, chunk_chars, overlap):
                wanted[c.key] = c

        cur = self.db.execute("SELECT key, hash, embedder FROM chunks")
        have = {k: (h, emb) for k, h, emb in cur.fetchall()}

        stale = [
            c for k, c in wanted.items()
            if k not in have
            or have[k][0] != content_hash(c.text)
            or have[k][1] != self.embedder.name
        ]
        removed = [k for k in have if k not in wanted]

        if removed:
            self.db.executemany("DELETE FROM chunks WHERE key = ?", [(k,) for k in removed])

        if stale:
            vecs = self.embedder.encode([c.text for c in stale])
            self.db.executemany(
                "INSERT OR REPLACE INTO chunks"
                " (key, entry_id, ordinal, text, hash, embedder, vector)"
                " VALUES (?,?,?,?,?,?,?)",
                [
                    (
                        c.key, c.entry_id, c.ordinal, c.text,
                        content_hash(c.text), self.embedder.name,
                        vecs[i].astype(np.float32).tobytes(),
                    )
                    for i, c in enumerate(stale)
                ],
            )

        self.db.execute(
            "INSERT OR REPLACE INTO meta (k, v) VALUES ('embedder', ?)", (self.embedder.name,)
        )
        self.db.commit()
        return {"indexed": len(wanted), "reembedded": len(stale), "removed": len(removed)}

    def _bm25(self, query: str, docs: Sequence[str]) -> np.ndarray:
        terms = terms_of(query)
        if not terms:
            return np.zeros(len(docs), dtype=np.float32)

        tokenised = [terms_of(d) for d in docs]
        lengths = np.array([len(t) or 1 for t in tokenised], dtype=np.float32)
        avg_len = float(lengths.mean())
        counts = [Counter(t) for t in tokenised]
        n_docs = len(docs)

        scores = np.zeros(n_docs, dtype=np.float32)
        for term in set(terms):
            containing = sum(1 for c in counts if term in c)
            if containing == 0:
                continue
            idf = math.log(1 + (n_docs - containing + 0.5) / (containing + 0.5))
            freqs = np.array([c.get(term, 0) for c in counts], dtype=np.float32)
            denom = freqs + BM25_K1 * (1 - BM25_B + BM25_B * lengths / avg_len)
            scores += idf * (freqs * (BM25_K1 + 1)) / np.maximum(denom, 1e-6)
        return scores

    def search(self, query: str, k: int = 6, allowed: set[str] | None = None) -> list[Hit]:
        rows = self.db.execute("SELECT key, entry_id, text, vector FROM chunks").fetchall()
        if allowed is not None:
            rows = [r for r in rows if r[1] in allowed]
        if not rows:
            return []

        matrix = np.vstack([np.frombuffer(r[3], dtype=np.float32) for r in rows])
        dense = matrix @ self.embedder.encode([query])[0]
        lexical = self._bm25(query, [r[2] for r in rows])

        dense_weight = 0.5 if self.embedder.name.startswith("hashing") else 1.0

        fused = np.zeros(len(rows), dtype=np.float32)
        for scores, weight in ((dense, dense_weight), (lexical, 1.0)):
            ranking = np.argsort(-scores)
            for rank, idx in enumerate(ranking):
                if scores[idx] > 0:
                    fused[idx] += weight / (RRF_K + rank + 1)

        ceiling = float(fused.max()) or 1.0
        order = np.argsort(-fused)[: max(k, 1)]
        return [
            Hit(entry_id=rows[i][1], key=rows[i][0], score=float(fused[i]) / ceiling, text=rows[i][2])
            for i in order
            if fused[i] > 0.0
        ]

    def stats(self) -> dict[str, object]:
        n_chunks = self.db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        n_entries = self.db.execute("SELECT COUNT(DISTINCT entry_id) FROM chunks").fetchone()[0]
        emb = self.db.execute("SELECT v FROM meta WHERE k='embedder'").fetchone()
        return {"chunks": n_chunks, "entries": n_entries, "embedder": emb[0] if emb else None}
