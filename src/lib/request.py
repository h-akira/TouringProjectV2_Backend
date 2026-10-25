"""Validation of the App's requests (07 UC-4, UC-5, UC-6)."""
from __future__ import annotations

import base64
import binascii
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

USER_NAME_RE = re.compile(r"^[a-z0-9]{3,20}$")
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
PCM_BYTES_PER_SECOND = 16000 * 2  # 16 kHz, mono, 16-bit
MIN_AUDIO_BYTES = PCM_BYTES_PER_SECOND // 4
MAX_AUDIO_BYTES = PCM_BYTES_PER_SECOND * 60
MAX_TEXT_CHARS = 500
# Polly's prosody volume stops at +6 dB (measured), so higher values would not be louder.
VOLUME_DB_CHOICES = (0, 3, 6)
DEFAULT_VOLUME_DB = 6


class BadRequest(ValueError):
    """The request is malformed; reported to the App as 400."""


@dataclass(frozen=True)
class AskInput:
    audio: Optional[bytes]
    text: Optional[str]
    location: Optional[dict]
    heading_sample: Optional[dict]
    conversation_id: Optional[str]
    volume_db: int = DEFAULT_VOLUME_DB
    ride_id: Optional[str] = None
    heading: Optional[float] = None


def _header(event: dict, name: str) -> Optional[str]:
    for key, value in (event.get("headers") or {}).items():
        if key.lower() == name:
            return value
    return None


def user_name(event: dict) -> str:
    value = _header(event, "x-user-name")
    if not isinstance(value, str) or not USER_NAME_RE.match(value):
        raise BadRequest("x-user-name must be 3-20 lowercase letters or digits")
    return value


def finite_number(value: Any) -> Optional[float]:
    """The value as a finite float, or None. An integer too large for a float is not a number here."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) else None


def position(value: Any) -> Optional[dict]:
    """A position, or None when it is missing or broken (the question still goes ahead)."""
    if not isinstance(value, dict):
        return None
    lat, lon = finite_number(value.get("latitude")), finite_number(value.get("longitude"))
    if lat is None or lon is None or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        return None
    return {"latitude": lat, "longitude": lon}


def heading_value(value: Any) -> Optional[float]:
    """The heading the app worked out from the ride's route, in degrees clockwise from north (adr/0013), or None
    when it is missing or not in [0, 360) (the question still goes ahead without one)."""
    number = finite_number(value)
    return number if number is not None and 0 <= number < 360 else None


def heading_sample(value: Any) -> Optional[dict]:
    """The older position the heading is taken from, or None when it is missing or broken."""
    point = position(value)
    at = value.get("at") if isinstance(value, dict) else None
    if point is None or not isinstance(at, str):
        return None
    try:
        parsed = datetime.fromisoformat(at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    utc = parsed.astimezone(timezone.utc)
    return {**point, "at": utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{utc.microsecond // 1000:03d}Z"}


def body_json(event: dict) -> dict:
    raw = event.get("body") or ""
    try:
        if event.get("isBase64Encoded"):
            raw = base64.b64decode(raw).decode("utf-8")
        data = json.loads(raw)
    except (ValueError, binascii.Error):
        raise BadRequest("body must be a JSON object") from None
    if not isinstance(data, dict):
        raise BadRequest("body must be a JSON object")
    return data


def pcm_audio(audio_b64: Any) -> bytes:
    """0.25-60 seconds of 16 kHz mono 16-bit PCM, sent as base64 (adr/0002)."""
    if not isinstance(audio_b64, str):
        raise BadRequest("audio must be base64")
    try:
        audio = base64.b64decode(audio_b64, validate=True)
    except (binascii.Error, ValueError):
        raise BadRequest("audio must be base64") from None
    if not MIN_AUDIO_BYTES <= len(audio) <= MAX_AUDIO_BYTES or len(audio) % 2:
        raise BadRequest("audio must be 0.25-60 seconds of 16 kHz mono 16-bit PCM")
    return audio


def parse_transcription(event: dict) -> bytes:
    """POST /transcriptions: the recording of a point memo, to be turned into text only (07 UC-6)."""
    audio_b64 = body_json(event).get("audio")
    if audio_b64 is None:
        raise BadRequest("audio is required")
    return pcm_audio(audio_b64)


def parse_ask(event: dict) -> AskInput:
    data = body_json(event)
    audio_b64, text = data.get("audio"), data.get("text")
    if (audio_b64 is None) == (text is None):
        raise BadRequest("exactly one of audio and text is required")

    audio = pcm_audio(audio_b64) if audio_b64 is not None else None

    if text is not None:
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT_CHARS:
            raise BadRequest("text must be 1-500 characters")
        text = text.strip()

    conversation_id = data.get("conversationId")
    if conversation_id is not None and (not isinstance(conversation_id, str) or not UUID_RE.match(conversation_id)):
        raise BadRequest("conversationId must be a lowercase UUID")

    volume_db = data.get("volumeDb", DEFAULT_VOLUME_DB)
    if isinstance(volume_db, bool) or volume_db not in VOLUME_DB_CHOICES:
        raise BadRequest("volumeDb must be one of 0, 3, 6")

    # Sent only while a ride is recording (slice 2 spec §4.6).
    ride_id = data.get("rideId")
    if ride_id is not None and (not isinstance(ride_id, str) or not UUID_RE.match(ride_id)):
        raise BadRequest("rideId must be a lowercase UUID")

    return AskInput(
        audio, text, position(data.get("location")), heading_sample(data.get("headingSample")), conversation_id, int(volume_db), ride_id,
        heading_value(data.get("headingDegrees")),
    )
