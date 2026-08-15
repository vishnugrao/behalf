import json
from dataclasses import replace

import pytest

from behalf.capture import CaptureLog
from behalf.chat import ChatSession
from behalf.config import Config
from behalf.persona import Persona
from behalf.store import ContextStore

ENTRY = """---
id: launch
title: Launch is 17 March
kind: decision
owner: vishnu
status: active
tags: []
confidence: 0.9
valid_from: '2026-01-01'
updated_at: '2026-01-01T00:00:00+00:00'
source: manual
---

GA slipped to 17 March when tenant isolation was late.
"""


class Replay:
    name = "replay"

    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []

    def think(self, system, turns):
        self.prompts.append((system, turns))
        return self.replies.pop(0)


@pytest.fixture
def session(tmp_path):
    ledger = tmp_path / "ledger" / "notes"
    ledger.mkdir(parents=True)
    (ledger / "a.md").write_text(ENTRY)
    cfg = replace(
        Config(),
        ledger_dir=tmp_path / "ledger",
        state_dir=tmp_path / "state",
        out_dir=tmp_path / "out",
        embedder="hashing",
    )
    persona = Persona(
        key="vishnu", person="Vishnu Rao", role="engineering lead", remit="", obligation=""
    )

    def make(*replies):
        return ChatSession(
            persona=persona,
            store=ContextStore(cfg),
            brain=Replay(*replies),
            log=CaptureLog(cfg.capture_path),
        )

    return make


def test_a_question_searches_before_answering(session):
    chat = session(
        json.dumps({"action": "search", "query": "launch date"}),
        json.dumps({"action": "answer", "text": "17 March [launch]."}),
    )
    assert chat.ask("when is launch?") == "17 March [launch]."
    assert chat.trace and chat.trace[0].startswith("search(")


def test_reading_an_entry_returns_its_content(session):
    chat = session(
        json.dumps({"action": "read", "id": "launch"}),
        json.dumps({"action": "answer", "text": "done"}),
    )
    chat.ask("read the launch entry")
    observation = chat.brain.prompts[-1][1][-1].content
    assert "tenant isolation" in observation


def test_reading_a_missing_entry_says_so_instead_of_failing(session):
    chat = session(
        json.dumps({"action": "read", "id": "nope"}),
        json.dumps({"action": "answer", "text": "not in my store"}),
    )
    chat.ask("read nope")
    assert "no entry" in chat.brain.prompts[-1][1][-1].content


def test_an_update_is_captured(session):
    chat = session(
        json.dumps({"action": "capture", "text": "batch three slipped"}),
        json.dumps({"action": "answer", "text": "captured"}),
    )
    chat.ask("batch three slipped")
    pending = chat.log.pending()
    assert len(pending) == 1
    assert pending[0].text == "batch three slipped"
    assert pending[0].author == "Vishnu Rao"


def test_the_prompt_binds_the_session_to_one_persona_and_one_store(session):
    chat = session(json.dumps({"action": "answer", "text": "hi"}))
    chat.ask("who are you?")
    system = chat.brain.prompts[0][0]
    assert "You are Vishnu Rao, engineering lead." in system
    collapsed = " ".join(system.split())
    assert "your colleagues run their own copies" in collapsed
    assert "you cannot see theirs" in collapsed
    assert "If your store does not contain something, say so" in collapsed


def test_prose_instead_of_json_is_passed_through(session):
    chat = session("I do not have that in my store.")
    assert chat.ask("anything?") == "I do not have that in my store."


def test_an_unknown_action_is_corrected_rather_than_crashing(session):
    chat = session(
        json.dumps({"action": "teleport"}),
        json.dumps({"action": "answer", "text": "recovered"}),
    )
    assert chat.ask("go") == "recovered"
    assert "unknown action" in chat.brain.prompts[-1][1][-1].content


def test_a_runaway_loop_is_bounded(session):
    chat = session(*[json.dumps({"action": "search", "query": "x"})] * 20)
    assert "gave up" in chat.ask("loop forever")


def test_history_carries_across_turns(session):
    chat = session(
        json.dumps({"action": "answer", "text": "first"}),
        json.dumps({"action": "answer", "text": "second"}),
    )
    chat.ask("one")
    chat.ask("two")
    roles = [t.role for t in chat.history]
    assert roles == ["user", "assistant", "user", "assistant"]
