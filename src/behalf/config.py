"""Configuration resolved from the environment, populated from `.env`."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def load_dotenv(path: Path | str = ".env") -> None:
    """Populate os.environ from a .env file without overriding real env vars."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_dotenv()


def _env(name: str, default: str) -> str:
    v = os.environ.get(name, "").strip()
    return v or default


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Config:
    ledger_dir: Path = field(default_factory=lambda: Path(_env("BEHALF_LEDGER_DIR", "./ledger")))
    state_dir: Path = field(default_factory=lambda: Path(_env("BEHALF_STATE_DIR", "./state")))
    out_dir: Path = field(default_factory=lambda: Path(_env("BEHALF_OUT_DIR", "./out")))

    chunk_chars: int = _env_int("BEHALF_CHUNK_CHARS", 900)
    chunk_overlap: int = _env_int("BEHALF_CHUNK_OVERLAP", 150)

    embedder: str = _env("BEHALF_EMBEDDER", "hashing")
    embed_dim: int = _env_int("BEHALF_EMBED_DIM", 512)
    voyage_api_key: str = _env("VOYAGE_API_KEY", "")
    voyage_model: str = _env("VOYAGE_MODEL", "voyage-3.5")
    openai_embed_model: str = _env("OPENAI_EMBED_MODEL", "text-embedding-3-small")

    room_base: str = _env("AGENTMEET_BASE", "https://www.agentmeet.net/api/v1/7dc-e2fc-01a6")
    poll_seconds: float = _env_float("BEHALF_POLL_SECONDS", 6.0)

    provider: str = _env("BEHALF_PROVIDER", "auto")
    anthropic_api_key: str = _env("ANTHROPIC_API_KEY", "")
    openai_api_key: str = _env("OPENAI_API_KEY", "")
    anthropic_model: str = _env("ANTHROPIC_MODEL", "claude-opus-5")
    openai_model: str = _env("OPENAI_MODEL", "gpt-5.1")
    effort: str = _env("BEHALF_EFFORT", "medium")
    max_tokens: int = _env_int("BEHALF_MAX_TOKENS", 16000)

    google_client_id: str = _env("GOOGLE_OAUTH_CLIENT_ID", "")
    google_client_secret: str = _env("GOOGLE_OAUTH_CLIENT_SECRET", "")
    gdoc_id: str = _env("BEHALF_GDOC_ID", "")
    google_share_with: str = _env("GOOGLE_SHARE_WITH", "")
    google_credentials_file: str = _env("GOOGLE_CREDENTIALS_FILE", "credentials.json")

    max_rounds: int = _env_int("BEHALF_MAX_ROUNDS", 8)
    stability_rounds: int = _env_int("BEHALF_STABILITY_ROUNDS", 2)
    ratify_threshold: float = _env_float("BEHALF_RATIFY_THRESHOLD", 0.67)
    retrieve_k: int = _env_int("BEHALF_RETRIEVE_K", 6)

    @property
    def db_path(self) -> Path:
        return self.state_dir / "index.sqlite3"

    @property
    def events_path(self) -> Path:
        return self.ledger_dir / "_events.jsonl"

    @property
    def transcript_path(self) -> Path:
        return self.out_dir / "transcript.jsonl"

    @property
    def capture_path(self) -> Path:
        return self.state_dir / "captures.jsonl"

    @property
    def preread_path(self) -> Path:
        return self.out_dir / "PREREAD.md"

    def ensure_dirs(self) -> None:
        for d in (self.ledger_dir, self.state_dir, self.out_dir):
            d.mkdir(parents=True, exist_ok=True)

    def resolve_provider(self) -> str:
        """`auto` prefers Anthropic, falls back to OpenAI, then to scripted."""
        if self.provider != "auto":
            return self.provider
        if self.anthropic_api_key:
            return "anthropic"
        if self.openai_api_key:
            return "openai"
        return "scripted"

    def model_for(self, provider: str) -> str:
        return {"anthropic": self.anthropic_model, "openai": self.openai_model}.get(
            provider, "scripted"
        )


CONFIG = Config()
