"""One process, one persona: retrieve, speak in turn, converge, publish."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass

from .brain import Brain, BrainError, Turn, build_brain, extract_json
from .chatroom import Chatroom, Message
from .config import Config
from .convergence import ConvergenceTracker
from .persona import Persona
from .protocol import AgentState, render_message, strip_state
from .store import ContextStore
from .summary import render_preread

SYSTEM_TEMPLATE = """{brief}

You are speaking as yourself, in the first person. The other voices in this
room are your colleagues, each represented the same way. Say "I" and "my
team", never "on behalf of {person}" — you are {person} here.

Everything you know comes from your own context store, retrieved below.
Together the room maintains a ONE PAGE pre-read that everyone must read before
the meeting: "{meeting}".

How you conduct yourself:
- Ground every claim in your retrieved context. Cite entry ids like [atlas-launch].
- If two entries disagree, say so. A live disagreement is a line on the page,
  not something to smooth over.
- Never restate a colleague's point as if it were yours. Add, challenge, or agree.
- Be brief. Three tight sentences beat a paragraph.
- {obligation}

Reply with what you want your colleagues to read, then exactly one <state> trailer:

<state>{{"intent":"propose|challenge|support|revise|ratify|abstain",
"proposals":[{{"claim":"one sentence a reader must know","evidence":["entry-id"],
"kind":"fact|decision|risk|ask|conflict"}}],
"concerns":["what is still unresolved"],"ratify":false,"confidence":0.0}}</state>

Set ratify true only when the page as it stands is something you would put your
own name to, with your concerns addressed.
"""


@dataclass
class AgentRun:
    cfg: Config
    persona: Persona
    roster: list[str]
    meeting: str
    scribe: bool = False
    publisher: object | None = None

    def __post_init__(self) -> None:
        self.store = ContextStore(self.cfg)
        self.brain: Brain = build_brain(self.cfg)
        self.room = Chatroom(self.cfg.room_base, self.persona.person)
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
    def name(self) -> str:
        return self.persona.person

    @property
    def position(self) -> int:
        return self.roster.index(self.name)

    def log(self, text: str) -> None:
        print(f"[{self.name}] {text}", flush=True)

    def system_prompt(self) -> str:
        return SYSTEM_TEMPLATE.format(
            brief=self.persona.brief(),
            person=self.persona.person,
            meeting=self.meeting,
            obligation=self.persona.obligation,
        )

    def drain(self) -> list[Message]:
        fresh = [m for m in self.room.read() if m.agent_name != self.name]
        for message in fresh:
            known = message.agent_name in self.roster
            payload = extract_json(message.content) if known else {}
            if payload:
                self.tracker.observe(AgentState.from_dict(message.agent_name, payload))
            self.transcript.append(message)
            tag = "" if known else " (not in roster, ignored for convergence)"
            self.log(f"heard {message.agent_name}{tag}: {strip_state(message.content)[:120]}")
        return fresh

    def turns_taken(self, agent: str) -> int:
        if agent == self.name:
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

    def standing_query(self) -> str:
        return " ".join([self.meeting, self.persona.remit, *self.persona.retrieval_bias])

    def current_query(self) -> str:
        recent = " ".join(strip_state(m.content) for m in self.transcript[-3:])
        return " ".join([self.meeting, recent])[:1200]

    def compose(self) -> tuple[str, AgentState]:
        context = self.store.context_for(self.standing_query(), self.current_query())
        conversation = "\n\n".join(
            f"{m.agent_name}: {m.content}" for m in self.transcript[-8:]
        ) or "(you are opening the discussion)"

        verdict = self.tracker.verdict()
        prompt = (
            f"# Retrieved from your context store\n{context}\n\n"
            f"# The room so far\n{conversation}\n\n"
            f"# Where the room stands\nround {self.tracker.round_index}; {verdict.reason}; "
            f"agreed by {verdict.ratified or 'nobody'}; "
            f"open concerns: {self.tracker.open_concerns or 'none'}\n\n"
            "Take your turn."
        )
        raw = self.brain.think(self.system_prompt(), [Turn("user", prompt)])
        return strip_state(raw), AgentState.from_dict(self.name, extract_json(raw))

    def speak(self) -> None:
        try:
            prose, state = self.compose()
        except BrainError as exc:
            self.log(f"brain error, abstaining: {exc}")
            prose, state = f"I could not form a view this round ({exc}).", AgentState(self.name)

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
                self.close_finished_rounds()

                if self.my_turn() and self.spoken < self.cfg.max_rounds:
                    self.speak()
                    self.close_finished_rounds()

                verdict = self.tracker.verdict()
                if verdict.converged and self.completed_rounds() > 0:
                    self.log(f"converged after {self.tracker.round_index} rounds: {verdict.reason}")
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
            owner=self.persona.person,
            kind="decision",
            tags=["preread", "generated"],
            source="agent",
            subdir="decisions",
            actor=self.name,
            archive=False,
        )

        link = ""
        if self.publisher is not None:
            try:
                link = self.publisher.publish(page)
                self.log(f"pushed to Google Doc {link}")
            except Exception as exc:
                self.log(f"Google Doc publish failed: {exc}")

        self.room.send(
            "Pre-read committed to the context store as [preread-current]"
            + (f" and pushed to {link}" if link else "")
            + f". Agreed by {', '.join(self.tracker.ratifiers) or 'nobody'}; "
            f"not agreed by {', '.join(self.tracker.holdouts) or 'nobody'}.\n\n{page}"
        )
        self.log(f"published {self.cfg.preread_path}")

    def persist_transcript(self) -> None:
        with self.cfg.transcript_path.open("a", encoding="utf-8") as fh:
            for message in self.transcript:
                if message.agent_name == self.name:
                    fh.write(json.dumps(message.__dict__, ensure_ascii=False) + "\n")
