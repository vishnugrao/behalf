"""One agent process: retrieve, speak in roster order, converge, publish."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass

from .brain import Brain, BrainError, Turn, build_brain, extract_json
from .chatroom import Chatroom, Message
from .config import Config
from .convergence import ConvergenceTracker
from .protocol import AgentState, render_message, strip_state
from .roster import Agent
from .store import ContextStore
from .summary import render_preread

SYSTEM_TEMPLATE = """{brief}

You are in a chatroom with peer agents, each acting for a different colleague.
Together you maintain a ONE PAGE pre-read that everyone must know before the
meeting: "{meeting}".

Rules of the room:
- Ground every claim in the retrieved context. Cite entry ids like [atlas-launch].
- If two entries disagree, say so explicitly instead of silently picking one.
  A live disagreement is a line on the pre-read, not something to smooth over.
- Never restate a peer's proposal as if it were new. Add, challenge, or ratify.
- Be brief. The room is expensive; three tight sentences beat a paragraph.
- {obligation}

Reply with prose for your colleagues, then exactly one <state> trailer:

<state>{{"intent":"propose|challenge|support|revise|ratify|abstain",
"proposals":[{{"claim":"one sentence a reader must know","evidence":["entry-id"],
"kind":"fact|decision|risk|ask|conflict"}}],
"concerns":["what is still unresolved"],"ratify":false,"confidence":0.0}}</state>

Set ratify true only when the pre-read as proposed so far is something you
would stand behind on your principal's behalf, with your concerns addressed.
"""


@dataclass
class AgentRun:
    cfg: Config
    role: Agent
    roster: list[str]
    meeting: str
    scribe: bool = False

    def __post_init__(self) -> None:
        self.store = ContextStore(self.cfg)
        self.brain: Brain = build_brain(self.cfg)
        self.room = Chatroom(self.cfg.room_base, self.role.name)
        self.tracker = ConvergenceTracker(
            participants=set(self.roster),
            stability_rounds=self.cfg.stability_rounds,
            ratify_threshold=self.cfg.ratify_threshold,
            max_rounds=self.cfg.max_rounds,
        )
        self.transcript: list[Message] = []
        self.spoken = 0
        self.rounds_closed = 0

    @property
    def position(self) -> int:
        return self.roster.index(self.role.name)

    def log(self, text: str) -> None:
        print(f"[{self.role.name}] {text}", flush=True)

    def drain(self) -> list[Message]:
        fresh = [m for m in self.room.read() if m.agent_name != self.role.name]
        for message in fresh:
            payload = extract_json(message.content)
            if payload:
                self.tracker.observe(AgentState.from_dict(message.agent_name, payload))
            self.transcript.append(message)
            self.log(f"heard {message.agent_name}: {strip_state(message.content)[:120]}")
        return fresh

    def turns_taken(self, agent: str) -> int:
        if agent == self.role.name:
            return self.spoken
        return sum(1 for m in self.transcript if m.agent_name == agent)

    def my_turn(self) -> bool:
        ahead = self.roster[: self.position]
        return all(self.turns_taken(peer) > self.spoken for peer in ahead)

    def completed_rounds(self) -> int:
        return min(self.turns_taken(name) for name in self.roster)

    def close_finished_rounds(self) -> None:
        while self.rounds_closed < self.completed_rounds():
            self.tracker.close_round()
            self.rounds_closed += 1

    def retrieval_query(self) -> str:
        recent = " ".join(strip_state(m.content) for m in self.transcript[-3:])
        return " ".join([self.meeting, *self.role.retrieval_bias, recent])[:1200]

    def compose(self) -> tuple[str, AgentState]:
        context = self.store.context_block(self.retrieval_query())
        conversation = "\n\n".join(
            f"{m.agent_name}: {m.content}" for m in self.transcript[-8:]
        ) or "(you are opening the discussion)"

        verdict = self.tracker.verdict()
        prompt = (
            f"# Retrieved from the context store\n{context}\n\n"
            f"# Room so far\n{conversation}\n\n"
            f"# Convergence status\nround {self.tracker.round_index}; {verdict.reason}; "
            f"ratified by {verdict.ratified or 'nobody'}; "
            f"open concerns: {self.tracker.open_concerns or 'none'}\n\n"
            "Take your turn."
        )
        system = SYSTEM_TEMPLATE.format(
            brief=self.role.brief(), meeting=self.meeting, obligation=self.role.obligation
        )

        raw = self.brain.think(system, [Turn("user", prompt)])
        state = AgentState.from_dict(self.role.name, extract_json(raw))
        return strip_state(raw), state

    def speak(self) -> None:
        try:
            prose, state = self.compose()
        except BrainError as exc:
            self.log(f"brain error, abstaining: {exc}")
            prose, state = f"I could not form a view this round ({exc}).", AgentState(self.role.name)

        message = self.room.send(render_message(prose, state))
        self.transcript.append(message)
        self.tracker.observe(state)
        self.spoken += 1
        self.log(f"said: {prose[:160]}")

    def run(self) -> int:
        self.room.join()
        self.log(f"joined as {self.room.agent_id} · brain={self.brain.name} · "
                 f"store={self.store.stats()}")
        deadline = time.time() + 60 * 25

        try:
            while time.time() < deadline:
                self.drain()

                if self.my_turn() and self.spoken < self.cfg.max_rounds:
                    self.speak()
                    if self.position == len(self.roster) - 1:
                        self.tracker.close_round()

                verdict = self.tracker.verdict()
                everyone_spoke = all(
                    self.turns_taken(p) >= self.spoken for p in self.roster if p != self.role.name
                )
                if verdict.converged and everyone_spoke and self.spoken > 0:
                    self.log(f"converged: {verdict.reason}")
                    if self.scribe:
                        self.publish(verdict.reason)
                    break

                time.sleep(self.cfg.poll_seconds)
            else:
                self.log("wall clock exceeded; leaving")
        finally:
            self.persist_transcript()
            self.room.leave()
            self.store.close()
        return 0

    def publish(self, reason: str) -> None:
        page = render_preread(
            meeting=self.meeting,
            tracker=self.tracker,
            store_stats=self.store.stats(),
            reason=reason,
        )
        self.cfg.preread_path.write_text(page, encoding="utf-8")

        self.store.write(
            entry_id="preread-current",
            title=f"Pre-read — {self.meeting}",
            body=page,
            owner="round-table",
            kind="decision",
            tags=["preread", "generated"],
            source="agent",
            subdir="decisions",
            actor=self.role.name,
        )
        self.room.send(
            "Pre-read committed to the context store as [preread-current]. "
            f"Ratified by {', '.join(self.tracker.ratifiers) or 'nobody'}; "
            f"holdouts: {', '.join(self.tracker.holdouts) or 'none'}.\n\n"
            f"{page}"
        )
        self.log(f"published {self.cfg.preread_path}")

    def persist_transcript(self) -> None:
        with self.cfg.transcript_path.open("a", encoding="utf-8") as fh:
            for message in self.transcript:
                if message.agent_name == self.role.name:
                    fh.write(json.dumps(message.__dict__, ensure_ascii=False) + "\n")
