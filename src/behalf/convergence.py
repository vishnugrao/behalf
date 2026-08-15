"""Stopping rule: stability, then scrutiny, then ratification, under a cap."""
from __future__ import annotations

from dataclasses import dataclass, field

from .protocol import AgentState, Proposal


@dataclass
class Verdict:
    converged: bool
    reason: str
    stable_rounds: int
    ratified: list[str]
    outstanding: list[str]


@dataclass
class ConvergenceTracker:
    participants: set[str]
    stability_rounds: int = 2
    ratify_threshold: float = 0.67
    max_rounds: int = 8

    round_index: int = 0
    seen_claims: set[str] = field(default_factory=set)
    latest: dict[str, AgentState] = field(default_factory=dict)
    challenges_raised: int = 0
    challenges_answered: int = 0
    _quiet_rounds: int = 0
    _new_this_round: int = 0

    def observe(self, state: AgentState) -> int:
        """Record one message. Returns how many claims in it were new."""
        self.participants.add(state.agent)
        self.latest[state.agent] = state

        if state.intent == "challenge":
            self.challenges_raised += 1
        elif state.intent in {"revise", "support"} and self.challenges_raised:
            self.challenges_answered += 1

        fresh = 0
        for proposal in state.proposals:
            if proposal.key() not in self.seen_claims:
                self.seen_claims.add(proposal.key())
                fresh += 1
        self._new_this_round += fresh
        return fresh

    def close_round(self) -> None:
        self.round_index += 1
        if self._new_this_round == 0:
            self._quiet_rounds += 1
        else:
            self._quiet_rounds = 0
        self._new_this_round = 0

    @property
    def ratifiers(self) -> list[str]:
        return sorted(a for a, s in self.latest.items() if s.ratify)

    @property
    def holdouts(self) -> list[str]:
        return sorted(a for a, s in self.latest.items() if not s.ratify)

    @property
    def open_concerns(self) -> list[str]:
        concerns: list[str] = []
        for state in self.latest.values():
            concerns.extend(state.concerns)
        return concerns

    def agreed_proposals(self) -> list[Proposal]:
        """Deduplicate proposals across agents, keeping the richest evidence."""
        merged: dict[str, Proposal] = {}
        for state in self.latest.values():
            for proposal in state.proposals:
                existing = merged.get(proposal.key())
                if existing is None:
                    merged[proposal.key()] = Proposal(
                        claim=proposal.claim,
                        evidence=list(proposal.evidence),
                        kind=proposal.kind,
                    )
                else:
                    existing.evidence = sorted(set(existing.evidence) | set(proposal.evidence))
        return list(merged.values())

    def verdict(self) -> Verdict:
        heard = len(self.latest)
        ratified = self.ratifiers
        support = len(ratified) / heard if heard else 0.0
        stable = self._quiet_rounds >= self.stability_rounds
        scrutinised = self.challenges_raised > 0 and self.challenges_answered > 0

        if self.round_index >= self.max_rounds:
            return Verdict(True, "round cap reached", self._quiet_rounds, ratified, self.holdouts)
        if heard < max(2, len(self.participants)):
            return Verdict(False, "waiting for all participants", self._quiet_rounds, ratified, self.holdouts)
        if not stable:
            return Verdict(False, "new proposals still arriving", self._quiet_rounds, ratified, self.holdouts)
        if not scrutinised:
            return Verdict(False, "no challenge survived yet", self._quiet_rounds, ratified, self.holdouts)
        if support < self.ratify_threshold:
            return Verdict(
                False,
                f"ratification {support:.0%} below {self.ratify_threshold:.0%}",
                self._quiet_rounds,
                ratified,
                self.holdouts,
            )
        return Verdict(True, "stable, scrutinised and ratified", self._quiet_rounds, ratified, self.holdouts)
