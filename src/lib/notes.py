"""Validation of a point memo sent by the Android app (slice 3 spec §6.2, US-D-08)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from lib.request import BadRequest, body_json, heading_sample, position
from lib.rides import utc_time

NOTE_TEXT_MAX = 2000


@dataclass(frozen=True)
class NoteInput:
    at: str
    location: Optional[dict]
    heading_sample: Optional[dict]
    text: str
    updated_at: str


def parse_note(event: dict) -> NoteInput:
    data = body_json(event)
    location = None
    if data.get("location") is not None:
        # The app writes the note from its own fix, so a broken position is its mistake (unlike an ask's).
        location = position(data.get("location"))
        if location is None:
            raise BadRequest("location must be a position or null")
    text = data.get("text")
    if not isinstance(text, str) or not text.strip() or len(text) > NOTE_TEXT_MAX:
        raise BadRequest(f"text must be 1-{NOTE_TEXT_MAX} characters")
    return NoteInput(utc_time(data.get("at"), "at"), location, heading_sample(data.get("headingSample")), text.strip(),
                     utc_time(data.get("updatedAt"), "updatedAt"))
