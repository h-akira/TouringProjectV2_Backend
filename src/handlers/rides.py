"""PUT /rides/{rideId}, PUT /rides/{rideId}/route/{seq} and PUT /rides/{rideId}/notes/{noteId}: the app sends its
rides, their routes and their point memos (07 UC-7, slice 2 spec §6.2, slice 3 spec §6.2). DELETE /rides/{rideId} and
DELETE /rides/{rideId}/notes/{noteId} remove them and leave deletion marks (adr/0009). Reading them back comes later."""
from __future__ import annotations

from handlers.common import deleted, iso, log, no_content, parse_iso, response, utc_now
from lib import notes, placed, request, rides, store
from lib.request import BadRequest, user_name


def handler(event, context):
    try:
        user = user_name(event)
        ride_id = rides.ride_id(event)
        path = event.get("pathParameters") or {}
        if event.get("httpMethod") == "DELETE":
            return _delete(event, user, ride_id)
        if path.get("noteId") is not None:
            return _note(event, user, ride_id)
        if path.get("seq") is not None:
            return _route(event, user, ride_id)
        return _ride(event, user, ride_id)
    except BadRequest as error:
        return response(400, {"error": "bad_request", "message": str(error)})
    except store.Deleted:
        return deleted()


def _ride(event: dict, user: str, ride_id: str) -> dict:
    ride = rides.parse_ride(event)
    applied = store.put_ride(user, ride_id, {
        "name": ride.name,
        "status": ride.status,
        "segments": ride.segments,
        "autoEnded": ride.auto_ended,
        "updatedAt": ride.updated_at,
        # Sent whole with the ride: a ride without a memo drops the stored one (slice 3 spec §6.2).
        "memo": ride.memo,
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


def _note(event: dict, user: str, ride_id: str) -> dict:
    note_id = request.path_id(event, "noteId")
    note = notes.parse_note(event)
    # A send arriving after a deletion is refused before the place is looked up (Backend #17).
    if store.has_deletion_mark(user, [("note", note_id), ("ride", ride_id)]):
        raise store.Deleted()
    stored = store.get_note(user, ride_id, note_id)
    if stored is not None and stored["updatedAt"] >= note.updated_at:
        applied, kept = False, stored
    else:
        # The heading and the place are settled on the first PUT that has one (slice 3 spec §6.2, Backend #17). A
        # point memo takes the position it is sent with; a stored copy is read eventually consistently (review R4-05).
        got = placed.settle_first(stored, note.location, note.heading, note.heading_sample, parse_iso(note.at),
                                  keep_first_location=False)
        kept = {
            "at": note.at,
            "location": got.location,
            "text": note.text,
            "updatedAt": note.updated_at,
            "address": got.address,
            "headingDegrees": got.heading,
            "savedAt": iso(utc_now()),
        }
        applied = store.put_note(user, ride_id, note_id, kept)
        if not applied:
            kept = store.get_note(user, ride_id, note_id) or kept
    log({"event": "note_saved", "rideId": ride_id, "noteId": note_id, "applied": applied, "hasPlace": kept.get("address") is not None})
    return response(200, {"noteId": note_id, "applied": applied, "address": kept.get("address"),
                          "headingDegrees": kept.get("headingDegrees")})


def _delete(event: dict, user: str, ride_id: str) -> dict:
    # Deleting twice, or deleting what never arrived, is the same as deleting once (slice 3 spec §6.2).
    if (event.get("pathParameters") or {}).get("noteId") is not None:
        note_id = request.path_id(event, "noteId")
        store.delete_note(user, ride_id, note_id, iso(utc_now()))
        log({"event": "note_deleted", "rideId": ride_id, "noteId": note_id})
        return no_content()
    removed = store.delete_ride(user, ride_id, iso(utc_now()))
    log({"event": "ride_deleted", "rideId": ride_id, **removed})
    return no_content()
