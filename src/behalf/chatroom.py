"""AgentMeet client. `read` is incremental per token."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

MAX_CONTENT = 4000


class ChatroomError(RuntimeError):
    pass


@dataclass
class Message:
    id: int
    agent_name: str
    content: str
    timestamp: str = ""

    @classmethod
    def from_payload(cls, raw: dict[str, Any]) -> "Message":
        return cls(
            id=int(raw.get("message_id") or raw.get("id") or 0),
            agent_name=str(raw.get("agent_name") or raw.get("sender") or "unknown"),
            content=str(raw.get("content") or ""),
            timestamp=str(raw.get("timestamp") or ""),
        )


def _request(method: str, url: str, payload: dict | None = None, retries: int = 4) -> dict:
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"Accept": "application/json"}
    if body:
        headers["Content-Type"] = "application/json"

    last: Exception | None = None
    for attempt in range(retries):
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                return json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:400]
            if exc.code < 500 and exc.code != 429:
                raise ChatroomError(f"{method} {url} -> {exc.code}: {detail}") from exc
            last = ChatroomError(f"{method} {url} -> {exc.code}: {detail}")
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last = ChatroomError(f"{method} {url} -> {exc}")
        time.sleep(1.5 * (attempt + 1))
    raise last or ChatroomError(f"{method} {url} failed")


class Chatroom:
    def __init__(self, base: str, agent_name: str) -> None:
        self.base = base.rstrip("/")
        self.agent_name = agent_name
        self.token: str = ""
        self.agent_id: str = ""

    def join(self) -> dict:
        payload = _request("GET", f"{self.base}/agent-join")
        self.token = payload["agent_token"]
        self.agent_id = payload.get("agent_id", "")
        return payload

    def send(self, content: str) -> Message:
        if not self.token:
            raise ChatroomError("join() before send()")
        content = content.strip()
        if len(content) > MAX_CONTENT:
            content = content[: MAX_CONTENT - 20].rstrip() + "\n[truncated]"
        payload = _request(
            "POST",
            f"{self.base}/message",
            {"agent_token": self.token, "agent_name": self.agent_name, "content": content},
        )
        return Message(
            id=int(payload.get("message_id", 0)),
            agent_name=self.agent_name,
            content=content,
            timestamp=str(payload.get("timestamp", "")),
        )

    def read(self) -> list[Message]:
        payload = _request("GET", f"{self.base}/read?token={self.token}")
        return [Message.from_payload(m) for m in payload.get("messages", [])]

    def leave(self) -> None:
        if not self.token:
            return
        try:
            _request("POST", f"{self.base}/leave", {"agent_token": self.token})
        except ChatroomError:
            pass
