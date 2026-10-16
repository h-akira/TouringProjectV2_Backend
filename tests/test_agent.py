"""Tests for invoking the agent runtime and reading its SSE events."""
import json

import pytest
from botocore.exceptions import ClientError

from lib.agent import AgentError, invoke, parse_events


def sse(*events):
    return [f"data: {json.dumps(e, ensure_ascii=False)}".encode() for e in events] + [b""]


DONE = {"type": "done", "answer": " 晴れです。 ", "stopReason": "end_turn",
        "usage": {"inputTokens": 100, "outputTokens": 10, "modelCalls": 2}, "modelId": "m"}


def test_parse_collects_tools_and_done():
    reply = parse_events(sse({"type": "text", "text": "調べます。"}, {"type": "tool", "name": "webSearch___WebSearch"}, DONE), clock=lambda: 42.0)
    assert reply.answer == "晴れです。"
    assert reply.tools == ["webSearch___WebSearch"]
    assert reply.usage == {"inputTokens": 100, "outputTokens": 10, "modelCalls": 2}
    assert reply.model_id == "m"
    assert reply.first_event_at == 42.0


def test_parse_ignores_noise_lines():
    reply = parse_events([b"", b": keep-alive", b"data: not json", "data: " + json.dumps(DONE)])
    assert reply.answer == "晴れです。"


def test_error_event_raises():
    with pytest.raises(AgentError, match="agent_failed: empty answer"):
        parse_events(sse({"type": "error", "code": "agent_failed", "message": "empty answer"}))


def test_runtime_level_error_shape_raises():
    with pytest.raises(AgentError, match="boom"):
        parse_events(sse({"error": "boom", "error_type": "RuntimeError"}))


def test_missing_or_empty_done_raises():
    with pytest.raises(AgentError, match="no answer"):
        parse_events(sse({"type": "text", "text": "x"}))
    with pytest.raises(AgentError, match="no answer"):
        parse_events(sse({**DONE, "answer": "  "}))


class Body:
    def __init__(self, lines):
        self.lines = lines

    def iter_lines(self):
        return iter(self.lines)


class FakeClient:
    def __init__(self, outcomes):
        self.outcomes, self.calls = list(outcomes), []

    def invoke_agent_runtime(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return {"response": Body(outcome)}


def conflict():
    return ClientError({"Error": {"Code": "RetryableConflictException", "Message": "retry"}}, "InvokeAgentRuntime")


def test_invoke_sends_payload_and_session():
    client = FakeClient([sse(DONE)])
    reply = invoke("P", {"latitude": 1.0, "longitude": 2.0, "headingDegrees": None}, "s" * 36, client=client)
    call = client.calls[0]
    assert reply.answer == "晴れです。"
    assert call["runtimeSessionId"] == "s" * 36
    assert call["qualifier"] == "DEFAULT"
    assert json.loads(call["payload"]) == {"prompt": "P", "location": {"latitude": 1.0, "longitude": 2.0, "headingDegrees": None}}


def test_invoke_retries_conflicts():
    sleeps = []
    client = FakeClient([conflict(), conflict(), sse(DONE)])
    assert invoke("P", None, "s" * 36, client=client, sleep=sleeps.append).answer == "晴れです。"
    assert sleeps == [0.5, 1.0]


def test_invoke_gives_up_after_attempts_and_on_other_errors():
    with pytest.raises(AgentError, match="RetryableConflictException"):
        invoke("P", None, "s" * 36, client=FakeClient([conflict()] * 3), sleep=lambda s: None)
    denied = ClientError({"Error": {"Code": "AccessDeniedException", "Message": "no"}}, "InvokeAgentRuntime")
    with pytest.raises(AgentError, match="AccessDeniedException"):
        invoke("P", None, "s" * 36, client=FakeClient([denied]), sleep=lambda s: None)
