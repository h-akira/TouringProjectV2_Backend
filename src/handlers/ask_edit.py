"""PUT /asks/{askId}/memo and DELETE /asks/{askId}: the app's changes to an ask it keeps (slice 3 spec §6.2).
PUT /asks/{askId}/offline: an ask that never reached the Backend, kept by the app (slice 4 spec §4.4)."""
from __future__ import annotations

from handlers.common import deleted, iso, log, no_content, parse_iso, response, utc_now
from lib import address, offline, request, rides, store
from lib.geo import settled_heading
from lib.request import BadRequest, user_name


def handler(event, context):
    try:
        user = user_name(event)
        ask_id = request.path_id(event, "askId")
        if event.get("httpMethod") == "DELETE":
            store.delete_ask(user, ask_id, iso(utc_now()))
            log({"event": "ask_deleted", "askId": ask_id})
            return no_content()
        if (event.get("resource") or "").endswith("/offline"):
            return _offline(event, user, ask_id)
        return _memo(event, user, ask_id)
    except BadRequest as error:
        return response(400, {"error": "bad_request", "message": str(error)})
    except store.Deleted:
        return deleted()


def _memo(event: dict, user: str, ask_id: str) -> dict:
    memo, updated_at = rides.parse_ask_memo(event)
    applied = store.put_ask_memo(user, ask_id, memo, updated_at)
    if not applied and store.get_ask(user, ask_id) is None:
        return response(404, {"error": "not_found"})
    log({"event": "ask_memo_saved", "askId": ask_id, "applied": applied, "hasMemo": memo is not None})
    return response(200, {"askId": ask_id, "applied": applied})


def _conflict() -> dict:
    """409: the id is an ask the Backend took in; an unreached ask never overwrites it."""
    return response(409, {"error": "conflict"})


def _offline(event: dict, user: str, ask_id: str) -> dict:
    unreached = offline.parse_offline_ask(event)
    # A send arriving after a deletion is refused before the place is looked up (as for point memos, Backend #17).
    if store.has_deletion_mark(user, [("ask", ask_id), ("ride", unreached.ride_id)]):
        raise store.Deleted()
    stored = store.get_ask(user, ask_id, consistent=True)
    if stored is not None and stored.get("status") != "offline":
        return _conflict()
    if stored is not None and stored["updatedAt"] >= unreached.updated_at:
        applied, kept = False, stored
    else:
        # Taken from the first PUT that has a heading, apart from the position (Backend #31): a first PUT with a
        # position but no heading keeps its position, and a later one gives the heading, as the place does.
        heading = (stored or {}).get("headingDegrees")
        if heading is None:
            heading = settled_heading(unreached.heading, unreached.location, unreached.heading_sample,
                                      parse_iso(unreached.asked_at))
        # Settled on the first PUT that has one, like the place and the heading (Backend #21).
        location = (stored or {}).get("location") or unreached.location
        kept = {
            "userName": user,
            "rideId": unreached.ride_id,
            # Named as for the asks the Backend takes in, so that every ask reads back alike.
            "receivedAt": unreached.asked_at,
            "location": location,
            "updatedAt": unreached.updated_at,
            # Settled on the first PUT, like a point memo's; a failed lookup is tried again.
            "address": (stored or {}).get("address") or (
                address.describe_location(location["latitude"], location["longitude"]) if location else None),
            "headingDegrees": heading,
            "savedAt": iso(utc_now()),
        }
        applied = store.put_offline_ask(user, ask_id, kept)
        if not applied:
            kept = store.get_ask(user, ask_id, consistent=True) or kept
            if kept.get("status") != "offline":
                return _conflict()
    log({"event": "offline_ask_saved", "askId": ask_id, "rideId": unreached.ride_id, "applied": applied,
         "hasPlace": kept.get("address") is not None})
    return response(200, {"askId": ask_id, "applied": applied, "address": kept.get("address"),
                          "headingDegrees": kept.get("headingDegrees")})
