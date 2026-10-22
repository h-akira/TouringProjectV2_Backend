"""A user's records as GET /records reads them back, for taking over on another device (slice 4 spec §6.2, adr/0010)."""
from __future__ import annotations

import base64
import binascii
import json
from typing import Optional

from lib.request import BadRequest

# As GET /asks/{askId} answers, plus the unreached asks the app sent (slice 4 spec §4.4).
_ASK_STATUS = {"pending": "processing", "processing": "processing", "completed": "completed", "failed": "failed",
               "offline": "offline"}


def encode_cursor(sort_key: str) -> str:
    return base64.urlsafe_b64encode(json.dumps({"sk": sort_key}).encode("utf-8")).decode("ascii").rstrip("=")


def decode_cursor(text: Optional[str]) -> Optional[str]:
    """The sort key to continue after, or None for the first page. Only the sort key is taken from the cursor."""
    if text is None:
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(text.encode("ascii") + b"=" * (-len(text) % 4)))
    except (ValueError, binascii.Error, UnicodeError):
        raise BadRequest("cursor must be one that GET /records returned") from None
    if not isinstance(data, dict) or not isinstance(data.get("sk"), str) or not data["sk"]:
        raise BadRequest("cursor must be one that GET /records returned")
    return data["sk"]


def view(item: dict) -> Optional[dict]:
    """The record as the app reads it back, or None for records it never sends or keeps (conversations,
    transcriptions)."""
    sort_key = item["sk"]
    if sort_key.startswith("DELETED#"):
        return {"kind": "deleted", "target": item["kind"], "id": item["id"], "rideId": item.get("rideId"),
                "deletedAt": item["deletedAt"]}
    if sort_key.startswith("ASK#"):
        return _ask(item)
    if not sort_key.startswith("RIDE#"):
        return None
    if "#ROUTE#" in sort_key:
        return {"kind": "route", "rideId": item["rideId"], "seq": item["seq"], "points": [_point(p) for p in item["points"]]}
    if "#NOTE#" in sort_key:
        return {"kind": "note", "rideId": item["rideId"], "noteId": item["noteId"], "at": item["at"],
                "location": item.get("location"), "text": item["text"], "updatedAt": item["updatedAt"],
                "address": item.get("address"), "headingDegrees": item.get("headingDegrees")}
    return {"kind": "ride", "rideId": item["rideId"], "name": item["name"], "status": item["status"],
            "segments": [_segment(s) for s in item["segments"]], "autoEnded": item["autoEnded"], "updatedAt": item["updatedAt"],
            "memo": item.get("memo")}


# Stored values lose their None fields, nested ones too; the app reads every field, so they come back as null.
def _segment(stored: dict) -> dict:
    return {"startedAt": stored["startedAt"], "endedAt": stored.get("endedAt")}


def _point(stored: dict) -> dict:
    return {"t": stored["t"], "lat": stored["lat"], "lon": stored["lon"], "accuracy": stored.get("accuracy"),
            "segment": stored["segment"]}


def _ask(item: dict) -> dict:
    status = _ASK_STATUS.get(item.get("status"), "processing")
    timings = item.get("timings") or {}
    # An answer the rider could hear: completed, or text whose speech failed (read with the device's TTS).
    answered = status == "completed" or (item.get("error") == "tts_failed" and bool(item.get("answer")))
    conversation_id = item.get("conversationId")
    return {
        "kind": "ask",
        "askId": item["askId"],
        "status": status,
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
