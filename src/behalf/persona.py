"""Personas loaded from config.yaml. List order is turn order."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path(os.environ.get("BEHALF_CONFIG", "config.yaml"))


@dataclass(frozen=True)
class Persona:
    key: str
    person: str
    role: str
    remit: str
    obligation: str
    email: str = ""
    retrieval_bias: list[str] = field(default_factory=list)
    scribe: bool = False

    def brief(self) -> str:
        return (
            f"You are {self.person}, {self.role}.\n"
            f"What you are responsible for: {self.remit}\n"
            f"How you behave in this room: {self.obligation}"
        )


@dataclass(frozen=True)
class Room:
    personas: list[Persona]
    meeting: str
    base: str
    me: str
    convergence: dict[str, Any]
    google: dict[str, Any]

    @property
    def names(self) -> list[str]:
        return [p.person for p in self.personas]

    def by_key(self, key: str) -> Persona:
        for persona in self.personas:
            if persona.key == key:
                return persona
        raise SystemExit(
            f"no persona {key!r} in config.yaml; have {[p.key for p in self.personas]}"
        )


def load_room(path: Path | str = DEFAULT_CONFIG_PATH) -> Room:
    path = Path(path)
    if not path.exists():
        raise SystemExit(f"missing {path}. Copy config.yaml from the repo root or set BEHALF_CONFIG.")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    entries = raw.get("personas") or []
    if not entries:
        raise SystemExit(f"{path} defines no personas")

    personas = [
        Persona(
            key=str(p["key"]),
            person=str(p["person"]),
            role=str(p.get("role", "")).strip(),
            remit=str(p.get("remit", "")).strip(),
            obligation=" ".join(str(p.get("obligation", "")).split()),
            email=str(p.get("email", "")).strip(),
            retrieval_bias=[str(x) for x in (p.get("retrieval_bias") or [])],
            scribe=bool(p.get("scribe", False)),
        )
        for p in entries
    ]
    if not any(p.scribe for p in personas):
        personas[0] = Persona(**{**personas[0].__dict__, "scribe": True})

    room = raw.get("room") or {}
    return Room(
        personas=personas,
        meeting=os.environ.get("BEHALF_MEETING") or str(room.get("meeting", "untitled meeting")),
        base=os.environ.get("AGENTMEET_BASE") or str(room.get("base", "")),
        me=os.environ.get("BEHALF_PERSONA") or str(raw.get("me") or personas[0].key),
        convergence=raw.get("convergence") or {},
        google=raw.get("google") or {},
    )
