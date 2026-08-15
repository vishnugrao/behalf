"""Chatroom wire format: prose for humans, one <state> JSON trailer for machines."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

STATE_OPEN = "<state>"
STATE_CLOSE = "</state>"

INTENTS = {"propose", "challenge", "support", "revise", "ratify", "abstain"}


@dataclass
class Proposal:
    """A single claimed line for the pre-read, tied back to the store."""

    claim: str
    evidence: list[str] = field(default_factory=list)
    kind: str = "fact"

    def key(self) -> str:
        words = re.findall(r"[a-z0-9]+", self.claim.lower())
        return " ".join(words)[:160]

    @classmethod
    def parse(cls, raw: Any) -> "Proposal | None":
        if isinstance(raw, str) and raw.strip():
            return cls(claim=raw.strip())
        if isinstance(raw, dict) and str(raw.get("claim", "")).strip():
            evidence = raw.get("evidence") or []
            if isinstance(evidence, str):
                evidence = [evidence]
            return cls(
                claim=str(raw["claim"]).strip(),
                evidence=[str(e) for e in evidence],
                kind=str(raw.get("kind", "fact")),
            )
        return None


@dataclass
class AgentState:
    """The machine-readable half of one chatroom message."""

    agent: str
    intent: str = "abstain"
    proposals: list[Proposal] = field(default_factory=list)
    concerns: list[str] = field(default_factory=list)
    ratify: bool = False
    confidence: float = 0.5

    @classmethod
    def from_dict(cls, agent: str, payload: dict) -> "AgentState":
        intent = str(payload.get("intent", "abstain")).lower()
        proposals = [
            p for p in (Proposal.parse(r) for r in payload.get("proposals") or []) if p
        ]
        concerns = [str(c) for c in (payload.get("concerns") or []) if str(c).strip()]
        try:
            confidence = float(payload.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        return cls(
            agent=agent,
            intent=intent if intent in INTENTS else "abstain",
            proposals=proposals,
            concerns=concerns,
            ratify=bool(payload.get("ratify", False)),
            confidence=max(0.0, min(1.0, confidence)),
        )

    def to_json(self) -> str:
        return json.dumps(
            {
                "intent": self.intent,
                "proposals": [
                    {"claim": p.claim, "evidence": p.evidence, "kind": p.kind}
                    for p in self.proposals
                ],
                "concerns": self.concerns,
                "ratify": self.ratify,
                "confidence": round(self.confidence, 2),
            },
            ensure_ascii=False,
        )


def render_message(prose: str, state: AgentState) -> str:
    return f"{prose.strip()}\n\n{STATE_OPEN}{state.to_json()}{STATE_CLOSE}"


def strip_state(content: str) -> str:
    if STATE_OPEN not in content:
        return content.strip()
    return content.split(STATE_OPEN, 1)[0].strip()
