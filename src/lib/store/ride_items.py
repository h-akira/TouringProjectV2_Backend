"""Rides with their route chunks and point memos, and the deletion of a ride with everything under it."""
from __future__ import annotations

from typing import Optional

from lib import clients
from lib.store._dynamo import _from_item, _retrying_conflicts, _to_item, _write_unless_deleted, deleted_key, mark_deleted


def ride_key(user: str, ride_id: str) -> dict:
    return {"pk": f"USER#{user}", "sk": f"RIDE#{ride_id}"}


def route_key(user: str, ride_id: str, seq: int) -> dict:
    # Zero-padded so that the chunks of a ride sort in order.
    return {"pk": f"USER#{user}", "sk": f"RIDE#{ride_id}#ROUTE#{seq:05d}"}


def note_key(user: str, ride_id: str, note_id: str) -> dict:
    # Under the ride, so that deleting the ride finds its notes with its route (slice 3 spec §6.1).
    return {"pk": f"USER#{user}", "sk": f"RIDE#{ride_id}#NOTE#{note_id}"}


def get_note(user: str, ride_id: str, note_id: str, consistent: bool = False) -> Optional[dict]:
    item = clients.table().get_item(Key=note_key(user, ride_id, note_id), ConsistentRead=consistent).get("Item")
    return _from_item(item) if item else None


def put_note(user: str, ride_id: str, note_id: str, fields: dict) -> bool:
    """Writes the note unless a newer one is stored. False when it was not newer. Raises Deleted when the note or its
    ride has been deleted."""
    item = {**note_key(user, ride_id, note_id), "noteId": note_id, "rideId": ride_id, **fields}
    put = {"Put": {"TableName": clients.table().name, "Item": _to_item(item),
                   "ConditionExpression": "attribute_not_exists(pk) OR updatedAt < :u",
                   "ExpressionAttributeValues": {":u": fields["updatedAt"]}}}
    return _write_unless_deleted(put, [deleted_key(user, "note", note_id), deleted_key(user, "ride", ride_id)])


def put_ride(user: str, ride_id: str, fields: dict) -> bool:
    """Writes the ride unless a newer one is stored (updatedAt, normalised UTC text). False when it was older.
    Raises Deleted when the ride has been deleted."""
    item = {**ride_key(user, ride_id), "rideId": ride_id, **fields}
    put = {"Put": {"TableName": clients.table().name, "Item": _to_item(item),
                   "ConditionExpression": "attribute_not_exists(pk) OR updatedAt < :u",
                   "ExpressionAttributeValues": {":u": fields["updatedAt"]}}}
    return _write_unless_deleted(put, [deleted_key(user, "ride", ride_id)])


def put_route_chunk(user: str, ride_id: str, seq: int, points: list, saved_at: str) -> None:
    """A chunk is replaced whole: sending it again leaves one copy. Raises Deleted when the ride has been deleted."""
    item = {**route_key(user, ride_id, seq), "rideId": ride_id, "seq": seq, "points": points, "savedAt": saved_at}
    _write_unless_deleted({"Put": {"TableName": clients.table().name, "Item": _to_item(item)}}, [deleted_key(user, "ride", ride_id)])


def _query_keys(user: str, prefix: str, ride_id: Optional[str] = None) -> list:
    """The records whose sort key starts with prefix (all pages); with ride_id, only those of that ride. Reads are
    consistent, so a record written just before a deletion is not missed."""
    params: dict = {"KeyConditionExpression": "pk = :p AND begins_with(sk, :s)", "ProjectionExpression": "pk, sk",
                    "ExpressionAttributeValues": {":p": f"USER#{user}", ":s": prefix}, "ConsistentRead": True}
    if ride_id is not None:
        params["FilterExpression"] = "rideId = :r"
        params["ExpressionAttributeValues"][":r"] = ride_id
    keys = []
    while True:
        page = clients.table().query(**params)
        keys += page.get("Items", [])
        if "LastEvaluatedKey" not in page:
            return keys
        params["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def _delete_all(keys: list) -> None:
    # The batch writer sends again what DynamoDB leaves unprocessed (UnprocessedItems), so no retry is added here.
    with clients.table().batch_writer() as batch:
        for key in keys:
            batch.delete_item(Key={"pk": key["pk"], "sk": key["sk"]})


def delete_note(user: str, ride_id: str, note_id: str, deleted_at: str) -> None:
    mark_deleted(user, "note", note_id, deleted_at, ride_id=ride_id)
    _retrying_conflicts(lambda: clients.table().delete_item(Key=note_key(user, ride_id, note_id)))


def delete_ride(user: str, ride_id: str, deleted_at: str) -> dict:
    """Marks the ride deleted, then removes it with its route, its notes and its asks, marking each note and ask too.
    The ride's mark goes first: from then on no note or chunk of it can be written, so the query below sees them all."""
    mark_deleted(user, "ride", ride_id, deleted_at)
    under = _query_keys(user, f"RIDE#{ride_id}")
    notes = [k for k in under if "#NOTE#" in k["sk"]]
    asks = _query_keys(user, "ASK#", ride_id=ride_id)
    for key in notes:
        mark_deleted(user, "note", key["sk"].rsplit("#", 1)[1], deleted_at, ride_id=ride_id)
    for key in asks:
        mark_deleted(user, "ask", key["sk"].split("#", 1)[1], deleted_at, ride_id=ride_id)
    _delete_all(under + asks)
    return {"notes": len(notes), "asks": len(asks), "chunks": sum("#ROUTE#" in k["sk"] for k in under)}
