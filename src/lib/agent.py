"""Invoke the agent runtime (us-east-1) and read its SSE events (07 UC-8)."""
from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Optional

from botocore.exceptions import BotoCoreError, ClientError

from lib import clients

_RETRYABLE = "RetryableConflictException"


def session_id(user: str, conversation_id: str) -> str:
    """The runtime session of one user's conversation. Another user sending the same conversationId gets a session
    of their own, so nobody reaches someone else's context by knowing the ID (Backend issue #4). 64 hex characters,
    inside the runtime's 33-100."""
    return hashlib.sha256(f"{user}:{conversation_id}".encode("utf-8")).hexdigest()


class AgentError(RuntimeError):
    """The agent did not produce an answer; reported as agent_failed."""


@dataclass
class AgentReply:
    answer: str
    usage: dict
    model_id: str
    tools: list[str] = field(default_factory=list)
    first_event_at: Optional[float] = None


def parse_events(lines: Iterable[Any], clock: Callable[[], float] = time.time) -> AgentReply:
    tools: list[str] = []
    first: Optional[float] = None
    done: Optional[dict] = None
    for raw in lines:
        line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        if not line or not line.startswith("data:"):
            continue
        try:
            event = json.loads(line[len("data:"):].strip())
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        if first is None:
            first = clock()
        kind = event.get("type")
        if kind == "tool":
            tools.append(str(event.get("name", "")))
        elif kind == "done":
            done = event
        elif kind == "error":
            raise AgentError(f"{event.get('code')}: {event.get('message')}")
        elif kind is None and "error" in event:
            # The runtime's own error shape when the entrypoint raised.
            raise AgentError(str(event["error"]))
    if done is None or not str(done.get("answer", "")).strip():
        raise AgentError("no answer")
    return AgentReply(
        answer=str(done["answer"]).strip(),
        usage=done.get("usage") or {},
        model_id=str(done.get("modelId", "")),
        tools=tools,
        first_event_at=first,
    )


def invoke(
    prompt: str,
    location: Optional[dict],
    session_id: str,
    client: Any = None,
    attempts: int = 3,
    sleep: Callable[[float], None] = time.sleep,
) -> AgentReply:
    client = client or clients.agentcore()
    payload = json.dumps({"prompt": prompt, "location": location}, ensure_ascii=False).encode("utf-8")
    for attempt in range(attempts):
        try:
            response = client.invoke_agent_runtime(
                agentRuntimeArn=os.environ["AGENT_ARN"],
                runtimeSessionId=session_id,
                qualifier="DEFAULT",
                payload=payload,
            )
            return parse_events(response["response"].iter_lines())
        except ClientError as error:
            code = error.response["Error"]["Code"]
            if code == _RETRYABLE and attempt < attempts - 1:
                sleep(0.5 * (attempt + 1))
                continue
            raise AgentError(code) from error
        except BotoCoreError as error:
            # Timeouts and broken streams: not retried, the question may already be in the conversation.
            raise AgentError(type(error).__name__) from error
    raise AgentError("no attempts")
