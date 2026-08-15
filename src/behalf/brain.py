"""Model backends: Anthropic Messages, OpenAI Responses, or an offline script."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Protocol

from .config import Config

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


class BrainError(RuntimeError):
    pass


@dataclass
class Turn:
    role: str
    content: str


class Brain(Protocol):
    name: str

    def think(self, system: str, turns: list[Turn]) -> str: ...


class AnthropicBrain:
    def __init__(self, cfg: Config) -> None:
        import anthropic

        self.model = cfg.anthropic_model
        self.max_tokens = cfg.max_tokens
        self.effort = cfg.effort
        self.name = f"anthropic:{self.model}"
        self.client = anthropic.Anthropic(api_key=cfg.anthropic_api_key or None)

    def think(self, system: str, turns: list[Turn]) -> str:
        with self.client.messages.stream(
            model=self.model,
            max_tokens=self.max_tokens,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            output_config={"effort": self.effort},
            messages=[{"role": t.role, "content": t.content} for t in turns],
        ) as stream:
            message = stream.get_final_message()

        if message.stop_reason == "refusal":
            raise BrainError(f"model declined: {getattr(message, 'stop_details', None)}")
        return "".join(b.text for b in message.content if b.type == "text").strip()


class OpenAIBrain:
    def __init__(self, cfg: Config) -> None:
        from openai import OpenAI

        self.model = cfg.openai_model
        self.max_tokens = cfg.max_tokens
        self.effort = cfg.effort
        self.name = f"openai:{self.model}"
        self.client = OpenAI(api_key=cfg.openai_api_key or None)

    def think(self, system: str, turns: list[Turn]) -> str:
        response = self.client.responses.create(
            model=self.model,
            instructions=system,
            input=[{"role": t.role, "content": t.content} for t in turns],
            max_output_tokens=self.max_tokens,
            reasoning={"effort": self.effort},
        )
        if response.status == "incomplete":
            reason = getattr(response.incomplete_details, "reason", "unknown")
            used = getattr(response.usage.output_tokens_details, "reasoning_tokens", 0)
            raise BrainError(
                f"response truncated ({reason}); {used} of {self.max_tokens} output tokens went "
                "to reasoning. Raise BEHALF_MAX_TOKENS or lower BEHALF_EFFORT."
            )
        text = (response.output_text or "").strip()
        if not text:
            raise BrainError(f"empty response (status={response.status})")
        return text


class ScriptedBrain:
    name = "scripted"

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg

    def think(self, system: str, turns: list[Turn]) -> str:
        from .scripted import scripted_reply

        return scripted_reply(system, turns)


def build_brain(cfg: Config) -> Brain:
    provider = cfg.resolve_provider()
    if provider == "anthropic":
        return AnthropicBrain(cfg)
    if provider == "openai":
        return OpenAIBrain(cfg)
    if provider == "scripted":
        return ScriptedBrain(cfg)
    raise ValueError(f"unknown provider {provider!r}; expected anthropic, openai or scripted")


def extract_json(text: str) -> dict:
    """Pull the structured trailer out of a reply, tolerating prose around it."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else None
    if candidate is None:
        tagged = re.search(r"<state>\s*(\{.*?\})\s*</state>", text, re.DOTALL)
        candidate = tagged.group(1) if tagged else None
    if candidate is None:
        match = _JSON_BLOCK.search(text)
        candidate = match.group(0) if match else None
    if candidate is None:
        return {}
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
