"""Validation of an unreached ask sent by the Android app: one that never reached the Backend (slice 4 spec §4.4,
US-C-09)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from lib.request import UUID_RE, BadRequest, body_json, heading_sample, position
from lib.rides import utc_time


@dataclass(frozen=True)
class OfflineAskInput:
    asked_at: str
    location: Optional[dict]
    heading_sample: Optional[dict]
    ride_id: str
    updated_at: str


def parse_offline_ask(event: dict) -> OfflineAskInput:
    data = body_json(event)
    location = None
    if data.get("location") is not None:
        # The app keeps the ask from its own fix, so a broken position is its mistake (as for a point memo).
        location = position(data.get("location"))
        if location is None:
            raise BadRequest("location must be a position or null")
    ride_id = data.get("rideId")
    # Asks start only while a ride is recording (adr/0008), so an unreached ask always has its ride.
    if not isinstance(ride_id, str) or not UUID_RE.match(ride_id):
        raise BadRequest("rideId must be a lowercase UUID")
    return OfflineAskInput(utc_time(data.get("askedAt"), "askedAt"), location, heading_sample(data.get("headingSample")),
                           ride_id, utc_time(data.get("updatedAt"), "updatedAt"))
