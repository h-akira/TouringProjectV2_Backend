"""Validation of a ride and its route chunks sent by the Android app (slice 2 spec §6.2)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from lib.request import BadRequest, UUID_RE, body_json, finite_number

RIDE_NAME_MAX = 40
STATUSES = ("recording", "paused", "ended")
MAX_SEGMENTS = 1000
MAX_POINTS = 300
MAX_SEQ = 99999
SEQ_RE = re.compile(r"^[0-9]{1,5}$")


@dataclass(frozen=True)
class RideInput:
    name: str
    status: str
    segments: list
    auto_ended: bool
    updated_at: str


def _iso(value: Any, field: str) -> str:
    """A time with its time zone, normalised to UTC with milliseconds so that stored values compare as text."""
    if not isinstance(value, str):
        raise BadRequest(f"{field} must be a date-time with a time zone")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise BadRequest(f"{field} must be a date-time with a time zone") from None
    if parsed.tzinfo is None:
        raise BadRequest(f"{field} must be a date-time with a time zone")
    utc = parsed.astimezone(timezone.utc)
    return utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{utc.microsecond // 1000:03d}Z"


def ride_id(event: dict) -> str:
    value = (event.get("pathParameters") or {}).get("rideId") or ""
    if not UUID_RE.match(value):
        raise BadRequest("rideId must be a lowercase UUID")
    return value


def chunk_seq(event: dict) -> int:
    value = (event.get("pathParameters") or {}).get("seq") or ""
    if not SEQ_RE.match(value):
        raise BadRequest(f"seq must be 0-{MAX_SEQ}")
    return int(value)


def _segments(value: Any, status: str) -> list:
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_SEGMENTS:
        raise BadRequest(f"segments must be a list of 1-{MAX_SEGMENTS}")
    segments = []
    for i, raw in enumerate(value):
        if not isinstance(raw, dict):
            raise BadRequest("each segment must be an object")
        started = _iso(raw.get("startedAt"), "startedAt")
        ended = None if raw.get("endedAt") is None else _iso(raw.get("endedAt"), "endedAt")
        last = i == len(value) - 1
        # Only a recording ride has an open segment, and only its last one.
        if ended is None and not (last and status == "recording"):
            raise BadRequest("only the last segment of a recording ride may be open")
        if ended is not None and last and status == "recording":
            raise BadRequest("a recording ride's last segment must be open")
        if ended is not None and ended < started:
            raise BadRequest("a segment cannot end before it starts")
        if segments and started < (segments[-1]["endedAt"] or ""):
            raise BadRequest("segments must not overlap")
        segments.append({"startedAt": started, "endedAt": ended})
    return segments


def parse_ride(event: dict) -> RideInput:
    data = body_json(event)
    name = data.get("name")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > RIDE_NAME_MAX:
        raise BadRequest(f"name must be 1-{RIDE_NAME_MAX} characters")
    status = data.get("status")
    if status not in STATUSES:
        raise BadRequest("status must be one of recording, paused, ended")
    auto_ended = data.get("autoEnded")
    if not isinstance(auto_ended, bool):
        raise BadRequest("autoEnded must be true or false")
    if auto_ended and status != "ended":
        raise BadRequest("only an ended ride can have ended automatically")
    return RideInput(name.strip(), status, _segments(data.get("segments"), status), auto_ended, _iso(data.get("updatedAt"), "updatedAt"))


def _point(raw: Any) -> dict:
    if not isinstance(raw, dict):
        raise BadRequest("each point must be an object")
    lat, lon = finite_number(raw.get("lat")), finite_number(raw.get("lon"))
    if lat is None or lon is None or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise BadRequest("lat and lon must be a position")
    accuracy = raw.get("accuracy")
    if accuracy is not None and (finite_number(accuracy) is None or accuracy < 0):
        raise BadRequest("accuracy must be a non-negative number or null")
    segment = raw.get("segment")
    if isinstance(segment, bool) or not isinstance(segment, int) or not 0 <= segment < MAX_SEGMENTS:
        raise BadRequest(f"segment must be 0-{MAX_SEGMENTS - 1}")
    return {"t": _iso(raw.get("t"), "t"), "lat": lat, "lon": lon, "accuracy": finite_number(accuracy), "segment": segment}


def parse_route(event: dict) -> list:
    points = body_json(event).get("points")
    if not isinstance(points, list) or not 1 <= len(points) <= MAX_POINTS:
        raise BadRequest(f"points must be a list of 1-{MAX_POINTS}")
    return [_point(p) for p in points]
