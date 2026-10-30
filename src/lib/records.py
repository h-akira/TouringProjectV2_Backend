"""A user's records as GET /records reads them back, for taking over on another device (slice 4 spec §6.2, adr/0010)."""
from __future__ import annotations

import base64
import binascii
import json
from typing import Optional

from lib import asks
from lib.request import BadRequest

# DynamoDB refuses a longer sort key in ExclusiveStartKey (Backend #22).
MAX_SORT_KEY_BYTES = 1024


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
    if not isinstance(data, dict) or not isinstance(data.get("sk"), str) or not data["sk"] \
            or len(data["sk"].encode("utf-8")) > MAX_SORT_KEY_BYTES:
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
        return asks.record_view(item)
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
