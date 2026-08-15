"""Offline brain: a fixed per-role strategy over the same prompts, for tests and demos."""
from __future__ import annotations

import json
import re

from .protocol import STATE_CLOSE, STATE_OPEN

ENTRY_RE = re.compile(r"^\[([a-z0-9][\w\-@.]*)\]\s+(.+)$", re.MULTILINE)
KIND_RE = re.compile(r"kind=(\w+)")


def _entries(prompt: str) -> list[tuple[str, str, str, str]]:
    blocks = prompt.split("\n\n---\n\n")
    found: list[tuple[str, str, str, str]] = []
    for block in blocks:
        match = ENTRY_RE.search(block)
        if not match:
            continue
        kind_match = KIND_RE.search(block)
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        body = next(
            (ln for ln in lines if not ln.startswith(("[", "kind=", "score=", "#"))),
            match.group(2),
        )
        found.append((match.group(1), match.group(2), kind_match.group(1) if kind_match else "fact", body))
    return found


def _kind_for(entry_kind: str) -> str:
    return {
        "decision": "decision",
        "risk": "risk",
        "metric": "fact",
        "customer": "risk",
        "person": "fact",
    }.get(entry_kind, "fact")


def _wrap(prose: str, payload: dict) -> str:
    return f"{prose}\n\n{STATE_OPEN}{json.dumps(payload, ensure_ascii=False)}{STATE_CLOSE}"


def scripted_reply(system: str, turns) -> str:
    prompt = turns[-1].content if turns else ""
    entries = _entries(prompt)
    is_challenger = "challenger" in system
    room_is_empty = "you are opening the discussion" in prompt
    open_concerns = "open concerns: none" not in prompt
    stable = "new proposals still arriving" not in prompt

    top = entries[:3]
    proposals = [
        {
            "claim": f"{title.rstrip('.')} — {body[:150].rstrip('.')}",
            "evidence": [entry_id],
            "kind": _kind_for(kind),
        }
        for entry_id, title, kind, body in top
    ]

    if is_challenger and not stable:
        concern = (
            f"{top[0][1]} is being read as settled, but [{top[0][0]}] does not say who owns it."
            if top
            else "Nothing retrieved supports the framing so far."
        )
        return _wrap(
            "Before this hardens: "
            + concern
            + " I want that named before it goes on a page three people act on.",
            {
                "intent": "challenge",
                "proposals": proposals[:1],
                "concerns": [concern],
                "ratify": False,
                "confidence": 0.45,
            },
        )

    if room_is_empty:
        return _wrap(
            "Opening from the store. The lines below are the ones I would not want a "
            "colleague to walk in without.",
            {
                "intent": "propose",
                "proposals": proposals,
                "concerns": [],
                "ratify": False,
                "confidence": 0.7,
            },
        )

    if open_concerns and not is_challenger:
        return _wrap(
            "Taking the objection: the owning entry is cited inline below, which should "
            "close it. Adding one line the room has not covered.",
            {
                "intent": "revise",
                "proposals": proposals[:2],
                "concerns": [],
                "ratify": stable,
                "confidence": 0.75,
            },
        )

    return _wrap(
        "No new ground from me. The page as it stands is one I would stand behind.",
        {
            "intent": "ratify",
            "proposals": [],
            "concerns": [],
            "ratify": True,
            "confidence": 0.85,
        },
    )
