"""Roster loaded from config.yaml. List order is turn order."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path(os.environ.get("BEHALF_CONFIG", "config.yaml"))


@dataclass(frozen=True)
class Agent:
    key: str
    name: str
    principal: str
    remit: str
    obligation: str
    retrieval_bias: list[str] = field(default_factory=list)
    scribe: bool = False

    def brief(self) -> str:
        return (
            f"You are {self.name}, acting on behalf of {self.principal}.\n"
            f"Remit: {self.remit}\n"
            f"Your standing obligation in this room: {self.obligation}"
        )


@dataclass(frozen=True)
class Roster:
    agents: list[Agent]
    meeting: str
    room_base: str
    me: str
    convergence: dict[str, Any]
    template: dict[str, Any]

    @property
    def names(self) -> list[str]:
        return [a.name for a in self.agents]

    def by_key(self, key: str) -> Agent:
        for agent in self.agents:
            if agent.key == key:
                return agent
        raise SystemExit(f"no agent {key!r} in roster; have {[a.key for a in self.agents]}")

    def by_index(self, index: int) -> Agent:
        if not 0 <= index < len(self.agents):
            raise SystemExit(f"agent index {index} out of range 0..{len(self.agents) - 1}")
        return self.agents[index]

    def grown_to(self, size: int) -> "Roster":
        """Return a roster of exactly `size` agents, synthesising extras."""
        if size <= len(self.agents):
            return Roster(self.agents[:size], self.meeting, self.room_base, self.me,
                          self.convergence, self.template)
        extras = [
            Agent(
                key=f"observer{n}",
                name=f"{self.template.get('name', 'Observer')}-{n}",
                principal=self.template.get("principal", "an unnamed stakeholder"),
                remit=self.template.get("remit", "cross-checking the summary"),
                obligation=self.template.get("obligation", "Add only what the room has missed."),
                retrieval_bias=list(self.template.get("retrieval_bias") or []),
            )
            for n in range(1, size - len(self.agents) + 1)
        ]
        return Roster(self.agents + extras, self.meeting, self.room_base, self.me,
                      self.convergence, self.template)


def load_roster(path: Path | str = DEFAULT_CONFIG_PATH) -> Roster:
    path = Path(path)
    if not path.exists():
        raise SystemExit(f"missing {path}. Copy config.yaml from the repo root or set BEHALF_CONFIG.")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    agents = [
        Agent(
            key=str(a["key"]),
            name=str(a["name"]),
            principal=str(a.get("principal", "an unnamed colleague")),
            remit=str(a.get("remit", "")).strip(),
            obligation=" ".join(str(a.get("obligation", "")).split()),
            retrieval_bias=[str(x) for x in (a.get("retrieval_bias") or [])],
            scribe=bool(a.get("scribe", False)),
        )
        for a in (raw.get("agents") or [])
    ]
    if not agents:
        raise SystemExit(f"{path} defines no agents")
    if not any(a.scribe for a in agents):
        agents[0] = Agent(**{**agents[0].__dict__, "scribe": True})

    room = raw.get("room") or {}
    return Roster(
        agents=agents,
        meeting=os.environ.get("BEHALF_MEETING") or str(room.get("meeting", "untitled meeting")),
        room_base=os.environ.get("AGENTMEET_BASE") or str(room.get("base", "")),
        me=os.environ.get("BEHALF_ME") or str(raw.get("me") or agents[0].key),
        convergence=raw.get("convergence") or {},
        template=raw.get("scale_template") or {},
    )
