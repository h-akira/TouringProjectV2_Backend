"""An ask record: how it is made when the question is accepted (POST /asks) and how it is read back, by polling
(GET /asks/{askId}) and by taking over (GET /records). The shape of the record is settled here (07 UC-5, UC-7)."""
from __future__ import annotations

from datetime import datetime

from lib import store
from lib.common import iso
from lib.geo import settled_heading
from lib.request import AskInput

# An unreached ask is never processed (slice 4 spec §4.4); it is reported as such (Backend #25).
STATUS = {"pending": "processing", "processing": "processing", "completed": "completed", "failed": "failed",
          "offline": "offline"}


def status(item: dict) -> str:
    return STATUS.get(item.get("status"), "processing")


def new_ask(user: str, ask_id: str, ask: AskInput, conversation_id: str, started_at: str, now: datetime) -> dict:
    """The record of an ask that has just been accepted, before it is queued."""
    return {
        **store.ask_key(user, ask_id),
        "askId": ask_id,
        "userName": user,
        "conversationId": conversation_id,
        "conversationStartedAt": started_at,
        "status": "pending",
        "receivedAt": iso(now),
        "inputType": "audio" if ask.audio is not None else "text",
        "question": ask.text,
        "location": ask.location,
        "headingSample": ask.heading_sample,
        # Settled now: an ask that fails before the agent never gets the worker's settled heading (Backend #29).
        "headingDegrees": settled_heading(ask.heading, None, None, now),
        "volumeDb": ask.volume_db,
        "rideId": ask.ride_id,
        "timings": {"receivedAt": iso(now)},
    }


def poll_view(item: dict, ask_id: str, audio: list) -> dict:
    """The ask as the app polls it; audio is the presigned answer, already made."""
    return {
        "askId": ask_id,
        "status": status(item),
        "transcript": item.get("transcript"),
        "answer": item.get("answer"),
        "audio": audio,
        "error": item.get("error"),
        "timings": item.get("timings", {}),
        # What the device keeps with the ask (slice 2 spec §5.2, §6.1).
        "askedAt": item.get("receivedAt"),
        "address": item.get("address"),
        "headingDegrees": item.get("headingDegrees"),
    }


def record_view(item: dict) -> dict:
    """The ask as GET /records reads it back, for taking over on another device."""
    timings = item.get("timings") or {}
    # An answer the rider could hear: completed, or text whose speech failed (read with the device's TTS).
    answered = status(item) == "completed" or (item.get("error") == "tts_failed" and bool(item.get("answer")))
    conversation_id = item.get("conversationId")
    return {
        "kind": "ask",
        "askId": item["askId"],
        "status": status(item),
        "askedAt": item.get("receivedAt"),
        "question": item.get("question"),
        "transcript": item.get("transcript"),
        "answer": item.get("answer"),
        "error": item.get("error"),
        "answeredAt": (timings.get("synthesizedAt") or timings.get("agentDoneAt")) if answered else None,
        "location": item.get("location"),
        "address": item.get("address"),
        "headingDegrees": item.get("headingDegrees"),
        "inputType": item.get("inputType"),
        "conversationId": conversation_id,
        # The conversation breaks just before its first ask (US-C-03.004).
        "newConversation": conversation_id is not None and item.get("conversationStartedAt") == item.get("receivedAt"),
        "rideId": item.get("rideId"),
        "memo": item.get("memo"),
        "memoUpdatedAt": item.get("memoUpdatedAt"),
        # Only an unreached ask carries the time the app changed it (slice 4 spec §6.1).
        "updatedAt": item.get("updatedAt"),
    }
