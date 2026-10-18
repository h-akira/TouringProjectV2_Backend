"""SQS worker: transcribe -> settle facts -> agent -> speech, one ask at a time (spec §6.2)."""
from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from handlers.common import iso, log, parse_iso, utc_now
from lib import address, agent, clients, speech, store, transcribe
from lib.agent import AgentError, AgentReply, session_id
from lib.geo import heading_degrees
from lib.prompt import agent_location, build_prompt
from lib.request import DEFAULT_VOLUME_DB


@dataclass
class Steps:
    transcribe: Callable[[bytes], str]
    describe_location: Callable[[float, float], Optional[str]]
    invoke_agent: Callable[[str, Optional[dict], str], AgentReply]
    synthesize: Callable[[str, str, int], str]
    now: Callable[[], datetime]


DEFAULT_STEPS = Steps(transcribe.transcribe_pcm, address.describe_location, agent.invoke, speech.synthesize, utc_now)


def _durations(timings: dict) -> dict:
    order = ["receivedAt", "transcribedAt", "factsAt", "agentDoneAt", "synthesizedAt"]
    present = [(k, parse_iso(timings[k])) for k in order if timings.get(k)]
    result = {f"{a}->{b}": int((tb - ta).total_seconds() * 1000) for (a, ta), (b, tb) in zip(present, present[1:])}
    if len(present) > 1:
        result["total"] = int((present[-1][1] - present[0][1]).total_seconds() * 1000)
    return result


def _take_audio(key: str) -> bytes:
    bucket = os.environ["AUDIO_BUCKET"]
    try:
        return clients.s3().get_object(Bucket=bucket, Key=key)["Body"].read()
    finally:
        # The recording is only kept long enough to transcribe it (US-C-06.003).
        try:
            clients.s3().delete_object(Bucket=bucket, Key=key)
        except Exception as error:  # noqa: BLE001 - the 1-day lifecycle rule removes it anyway
            log({"event": "audio_delete_failed", "error": type(error).__name__})


def process(user: str, ask_id: str, steps: Steps) -> None:
    item = store.claim_ask(user, ask_id)
    if item is None:
        log({"event": "ask_skipped", "askId": ask_id})
        return
    try:
        _run(user, ask_id, item, steps)
    except Exception as error:  # noqa: BLE001 - never leave a claimed ask in processing
        log({"event": "ask_crashed", "askId": ask_id, "error": type(error).__name__})
        store.update_ask(user, ask_id, {"status": "failed", "error": "agent_failed"})


def _run(user: str, ask_id: str, item: dict, steps: Steps) -> None:
    timings = dict(item.get("timings") or {})
    outcome: dict = {}

    def mark(name: str) -> None:
        timings[name] = iso(steps.now())

    def finish(status: str, error: Optional[str] = None, **fields) -> None:
        outcome.update(fields)
        store.update_ask(user, ask_id, {"status": status, "error": error, "timings": timings, **fields})
        log({"event": "ask_done", "askId": ask_id, "status": status, "error": error, "inputType": item.get("inputType"),
             "durationsMs": _durations(timings), "usage": fields.get("usage"), "modelId": fields.get("modelId"),
             "tools": fields.get("tools")})

    question = item.get("question")
    transcript: Optional[str] = None
    if item.get("audioKey"):
        try:
            transcript = steps.transcribe(_take_audio(item["audioKey"]))
        except Exception as error:  # noqa: BLE001 - reported as transcribe_failed
            mark("transcribedAt")
            log({"event": "transcribe_error", "askId": ask_id, "error": type(error).__name__})
            finish("failed", "transcribe_failed")
            return
        mark("transcribedAt")
        if not transcript:
            finish("failed", "no_speech", transcript="")
            return
        question = transcript

    received_at = parse_iso(item["receivedAt"])
    location = item.get("location")
    heading = heading_degrees(location, item.get("headingSample"), received_at)
    place = steps.describe_location(location["latitude"], location["longitude"]) if location else None
    elapsed = (received_at - parse_iso(item["conversationStartedAt"])).total_seconds() if item.get("conversationStartedAt") else None
    prompt = build_prompt(question, received_at, location, place, heading, elapsed)
    mark("factsAt")
    facts = {"transcript": transcript, "address": place, "headingDegrees": round(heading, 1) if heading is not None else None}

    try:
        reply = steps.invoke_agent(prompt, agent_location(location, heading), session_id(user, item["conversationId"]))
    except Exception as error:  # noqa: BLE001 - AgentError or anything unexpected from the call
        mark("agentDoneAt")
        reason = str(error) if isinstance(error, AgentError) else type(error).__name__
        log({"event": "agent_error", "askId": ask_id, "error": reason})
        finish("failed", "agent_failed", **facts)
        return
    if reply.first_event_at is not None:
        timings["agentFirstEventAt"] = iso(datetime.fromtimestamp(reply.first_event_at, timezone.utc))
    mark("agentDoneAt")
    answered = {**facts, "answer": reply.answer, "usage": reply.usage, "modelId": reply.model_id, "tools": reply.tools}

    try:
        # Asks accepted before volumeDb existed have none; DynamoDB returns numbers as Decimal.
        key = steps.synthesize(ask_id, reply.answer, int(item.get("volumeDb", DEFAULT_VOLUME_DB)))
    except Exception as error:  # noqa: BLE001 - the App reads the answer with device TTS
        mark("synthesizedAt")
        log({"event": "tts_error", "askId": ask_id, "error": type(error).__name__})
        finish("failed", "tts_failed", **answered)
        return
    mark("synthesizedAt")
    finish("completed", None, answerAudioKey=key, **answered)


def handler(event, context):
    for record in event.get("Records", []):
        message = json.loads(record["body"])
        process(message["userName"], message["askId"], DEFAULT_STEPS)
