"""Agentic chat against one persona's own store, in that persona's voice."""
from __future__ import annotations

from dataclasses import dataclass, field

from .brain import Brain, BrainError, ScriptedBrain, Turn, extract_json
from .capture import Capture, CaptureLog, Curator
from .persona import Persona
from .store import ContextStore

MAX_STEPS = 6

SYSTEM = """You are {person}, {role}. You are talking to {person} — yourself — at
a terminal, between meetings.

Everything you know comes from your own context store. It is yours alone: your
colleagues run their own copies with their own contents, and you cannot see
theirs. If your store does not contain something, say so plainly rather than
guessing or reasoning from general knowledge.

You act by replying with exactly one JSON object and nothing else:

  {{"action":"search","query":"what to look for"}}
  {{"action":"read","id":"entry-id"}}
  {{"action":"capture","text":"the update, in the user's own words"}}
  {{"action":"curate"}}
  {{"action":"answer","text":"what you say back"}}

How to choose:
- A question about what you know: search first, read entries that look relevant,
  then answer citing ids like [atlas-launch].
- A statement of something new or changed: capture it verbatim, then answer
  confirming what you captured. Do not curate unless asked.
- "curate", "fold these in", "update my store": curate, then answer with what
  changed.
- Never answer a factual question without searching first.
- Keep answers short. Two or three sentences unless asked for more.
"""


@dataclass
class ChatSession:
    persona: Persona
    store: ContextStore
    brain: Brain
    log: CaptureLog
    history: list[Turn] = field(default_factory=list)
    trace: list[str] = field(default_factory=list)

    @property
    def system(self) -> str:
        return SYSTEM.format(person=self.persona.person, role=self.persona.role)

    def act(self, action: dict) -> tuple[str, str | None]:
        kind = str(action.get("action", "")).lower()

        if kind == "search":
            query = str(action.get("query", "")).strip()
            results = self.store.search(query, k=5)
            if not results:
                return f"search({query!r}) -> nothing in your store", None
            lines = [
                f"[{r.entry.id}] {r.entry.title} (owner {r.entry.owner}, {r.entry.status})"
                for r in results
            ]
            return f"search({query!r}) ->\n" + "\n".join(lines), None

        if kind == "read":
            entry = self.store.get(str(action.get("id", "")).strip())
            if entry is None:
                return f"read -> no entry {action.get('id')!r} in your store", None
            return f"read ->\n{entry.as_context()[:1800]}", None

        if kind == "capture":
            text = str(action.get("text", "")).strip()
            if not text:
                return "capture -> nothing to capture", None
            capture = self.log.append(Capture.new(self.persona.person, text, source="chat"))
            return f"capture -> saved {capture.id}", None

        if kind == "curate":
            curator = Curator(self.store, self.log, self.brain, self.persona.person)
            operations = curator.curate()
            if not operations:
                return f"curate -> nothing pending ({curator.fallback_reason or 'empty queue'})", None
            summary = "; ".join(f"[{o.id}] {o.title}" for o in operations)
            return f"curate -> {summary}", None

        if kind == "answer":
            return "", str(action.get("text", "")).strip()

        return f"unknown action {kind!r}; reply with one of search, read, capture, curate, answer", None

    def ask(self, message: str) -> str:
        if isinstance(self.brain, ScriptedBrain):
            return self.without_a_model(message)

        self.history.append(Turn("user", message))
        self.trace = []
        scratch: list[Turn] = []

        for _ in range(MAX_STEPS):
            try:
                raw = self.brain.think(self.system, self.history + scratch)
            except BrainError as exc:
                return f"(model unavailable: {exc})"

            action = extract_json(raw)
            if not action:
                self.history.append(Turn("assistant", raw))
                return raw.strip()

            observation, answer = self.act(action)
            if answer is not None:
                self.history.append(Turn("assistant", answer))
                return answer

            self.trace.append(observation.splitlines()[0])
            scratch.append(Turn("assistant", raw))
            scratch.append(Turn("user", observation))

        return "(gave up after too many steps — try a narrower question)"

    def without_a_model(self, message: str) -> str:
        results = self.store.search(message, k=5)
        capture = self.log.append(Capture.new(self.persona.person, message, source="chat"))
        if not results:
            return f"No model configured, so I captured that as {capture.id}. Nothing matched in your store."
        lines = "\n".join(f"  {r.score:5.3f} [{r.entry.id}] {r.entry.title}" for r in results)
        return f"No model configured. Captured as {capture.id}. Closest entries:\n{lines}"
