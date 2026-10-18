"""PUT /rides/{rideId} and PUT /rides/{rideId}/route/{seq}: the app sends its rides (07 UC-7, slice 2 spec §6.2).
Reading them back comes with slice 3."""
from __future__ import annotations

from handlers.common import iso, log, response, utc_now
from lib import rides, store
from lib.request import BadRequest, user_name


def handler(event, context):
    try:
        user = user_name(event)
        ride_id = rides.ride_id(event)
        if (event.get("pathParameters") or {}).get("seq") is not None:
            return _route(event, user, ride_id)
        return _ride(event, user, ride_id)
    except BadRequest as error:
        return response(400, {"error": "bad_request", "message": str(error)})


def _ride(event: dict, user: str, ride_id: str) -> dict:
    ride = rides.parse_ride(event)
    applied = store.put_ride(user, ride_id, {
        "name": ride.name,
        "status": ride.status,
        "segments": ride.segments,
        "autoEnded": ride.auto_ended,
        "updatedAt": ride.updated_at,
        "savedAt": iso(utc_now()),
    })
    log({"event": "ride_saved", "rideId": ride_id, "status": ride.status, "applied": applied})
    # An older copy is not an error: the app has nothing to resend (slice 2 spec §6.2).
    return response(200, {"rideId": ride_id, "applied": applied})


def _route(event: dict, user: str, ride_id: str) -> dict:
    seq = rides.chunk_seq(event)
    points = rides.parse_route(event)
    store.put_route_chunk(user, ride_id, seq, points, iso(utc_now()))
    log({"event": "route_saved", "rideId": ride_id, "seq": seq, "points": len(points)})
    return response(200, {"rideId": ride_id, "seq": seq})
