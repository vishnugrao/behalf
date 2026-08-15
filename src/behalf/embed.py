"""Embedding backends. Changing the embedder name re-embeds the index."""
from __future__ import annotations

import hashlib
import re
from typing import Protocol, Sequence

import numpy as np

TOKEN_RE = re.compile(r"[a-z0-9]+")


class Embedder(Protocol):
    dim: int
    name: str

    def encode(self, texts: Sequence[str]) -> np.ndarray: ...


def _normalise(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


def _tokens(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())


class HashingEmbedder:
    """Signed feature hashing over unigrams, bigrams and character 4-grams."""

    name = "hashing-v1"

    def __init__(self, dim: int = 512) -> None:
        self.dim = dim

    def _bucket(self, feature: str) -> tuple[int, float]:
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        n = int.from_bytes(digest, "big")
        return n % self.dim, 1.0 if (n >> 63) & 1 else -1.0

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            toks = _tokens(text)
            joined = " ".join(toks)
            features: list[tuple[str, float]] = [(t, 1.0) for t in toks]
            features += [(f"{a}_{b}", 1.4) for a, b in zip(toks, toks[1:])]
            features += [(joined[i : i + 4], 0.35) for i in range(max(0, len(joined) - 3))]
            for feature, weight in features:
                idx, sign = self._bucket(feature)
                out[row, idx] += sign * weight
        return _normalise(out)


class OpenAIEmbedder:
    def __init__(self, api_key: str, model: str) -> None:
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key or None)
        self.model = model
        self.name = f"openai:{model}"
        self.dim = 1536

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        response = self.client.embeddings.create(model=self.model, input=list(texts))
        vectors = np.array([d.embedding for d in response.data], dtype=np.float32)
        self.dim = vectors.shape[1]
        return _normalise(vectors)


class VoyageEmbedder:
    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model
        self.name = f"voyage:{model}"
        self.dim = 1024

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        import json
        import urllib.request

        request = urllib.request.Request(
            "https://api.voyageai.com/v1/embeddings",
            data=json.dumps({"input": list(texts), "model": self.model}).encode(),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=60) as resp:
            payload = json.loads(resp.read())
        vectors = np.array([d["embedding"] for d in payload["data"]], dtype=np.float32)
        self.dim = vectors.shape[1]
        return _normalise(vectors)


def build_embedder(cfg) -> Embedder:
    kind = cfg.embedder
    if kind == "hashing":
        return HashingEmbedder(cfg.embed_dim)
    if kind == "openai":
        if not cfg.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required for BEHALF_EMBEDDER=openai")
        return OpenAIEmbedder(cfg.openai_api_key, cfg.openai_embed_model)
    if kind == "voyage":
        if not cfg.voyage_api_key:
            raise RuntimeError("VOYAGE_API_KEY is required for BEHALF_EMBEDDER=voyage")
        return VoyageEmbedder(cfg.voyage_api_key, cfg.voyage_model)
    raise ValueError(f"unknown embedder {kind!r}; expected hashing, openai or voyage")
