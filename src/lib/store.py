"""Records in one DynamoDB table: pk USER#<name>, sk ASK#<id>, CONV#<id>, RIDE#<id>, RIDE#<id>#ROUTE#<seq>,
RIDE#<id>#NOTE#<id>, DELETED#<KIND>#<id> or TRANSCRIPTION#<id>."""
from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Optional

from botocore.exceptions import ClientError

from lib import clients

_CONDITION_FAILED = "ConditionalCheckFailedException"
_CANCELLED = "TransactionCanceledException"


class Deleted(Exception):
    """The record, or the ride it belongs to, has a deletion mark (slice 3 spec §5.4, adr/0009)."""


def _to_item(value: Any) -> Any:
    """Floats become Decimal; None values are dropped."""
    return json.loads(json.dumps(_drop_none(value)), parse_float=Decimal)


def _drop_none(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _drop_none(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_drop_none(v) for v in value]
    return value


def _from_item(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {k: _from_item(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_from_item(v) for v in value]
    return value


def deleted_key(user: str, kind: str, record_id: str) -> dict:
    """kind is ask, ride or note."""
    return {"pk": f"USER#{user}", "sk": f"DELETED#{kind.upper()}#{record_id}"}


def mark_deleted(user: str, kind: str, record_id: str, deleted_at: str, ride_id: Optional[str] = None) -> None:
    """Writes the deletion mark; marking again keeps one. Marks never expire (adr/0009)."""
    clients.table().put_item(Item=_to_item({**deleted_key(user, kind, record_id), "kind": kind, "id": record_id,
                                            "rideId": ride_id, "deletedAt": deleted_at}))


def _write_unless_deleted(write: dict, marks: list) -> bool:
    """Runs one transaction write (a Put or an Update) unless one of the deletion marks exists, atomically, so that a
    deletion that lands at the same time cannot be undone. True when written; False when the write's own condition
    failed. Raises Deleted when a mark exists. The table's client takes plain values, as the table does."""
    table = clients.table()
    checks = [{"ConditionCheck": {"TableName": table.name, "Key": mark, "ConditionExpression": "attribute_not_exists(pk)"}}
              for mark in marks]
    try:
        table.meta.client.transact_write_items(TransactItems=[write, *checks])
    except ClientError as error:
        if error.response["Error"]["Code"] != _CANCELLED:
            raise
        codes = [reason.get("Code") for reason in error.response.get("CancellationReasons") or []]
        if "ConditionalCheckFailed" in codes[1:]:
            raise Deleted() from None
        if codes[:1] == ["ConditionalCheckFailed"]:
            return False
        raise
    return True


def ask_key(user: str, ask_id: str) -> dict:
    return {"pk": f"USER#{user}", "sk": f"ASK#{ask_id}"}


def _conversation_key(user: str, conversation_id: str) -> dict:
    return {"pk": f"USER#{user}", "sk": f"CONV#{conversation_id}"}


def conversation_started_at(user: str, conversation_id: str, now_iso: str) -> str:
    """When this conversation's first question arrived (recorded on first sight)."""
    key = _conversation_key(user, conversation_id)
    try:
        clients.table().put_item(Item={**key, "startedAt": now_iso}, ConditionExpression="attribute_not_exists(pk)")
        return now_iso
    except ClientError as error:
        if error.response["Error"]["Code"] != _CONDITION_FAILED:
            raise
    return clients.table().get_item(Key=key)["Item"]["startedAt"]


def create_ask(item: dict) -> None:
    clients.table().put_item(Item=_to_item(item))


def claim_ask(user: str, ask_id: str) -> Optional[dict]:
    """pending -> processing, once. None if already claimed or missing."""
    return _claim(ask_key(user, ask_id))


def _claim(key: dict) -> Optional[dict]:
    try:
        result = clients.table().update_item(
            Key=key,
            UpdateExpression="SET #s = :processing",
            ConditionExpression="#s = :pending",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":processing": "processing", ":pending": "pending"},
            ReturnValues="ALL_NEW",
        )
    except ClientError as error:
        if error.response["Error"]["Code"] == _CONDITION_FAILED:
            return None
        raise
    return _from_item(result["Attributes"])


def update_ask(user: str, ask_id: str, fields: dict) -> bool:
    """Sets the fields on a stored ask. False when the ask is gone (deleted meanwhile): it is not written back."""
    values = _to_item(fields)
    if not values:
        return True
    names = {f"#k{i}": key for i, key in enumerate(values)}
    expression = "SET " + ", ".join(f"#k{i} = :v{i}" for i in range(len(values)))
    try:
        clients.table().update_item(
            Key=ask_key(user, ask_id),
            UpdateExpression=expression,
            ConditionExpression="attribute_exists(pk)",
            ExpressionAttributeNames=names,
            ExpressionAttributeValues={f":v{i}": value for i, value in enumerate(values.values())},
        )
    except ClientError as error:
        if error.response["Error"]["Code"] == _CONDITION_FAILED:
            return False
        raise
    return True


def put_ask_memo(user: str, ask_id: str, memo: Optional[str], updated_at: str) -> bool:
    """Sets (or, for None, removes) the ask's memo unless a newer one is stored. False when the ask is missing or the
    memo is not newer. Raises Deleted when the ask has been deleted."""
    expression = "SET memoUpdatedAt = :u" + (", memo = :m" if memo is not None else " REMOVE memo")
    values = {":u": updated_at, **({":m": memo} if memo is not None else {})}
    update = {"Update": {"TableName": clients.table().name, "Key": ask_key(user, ask_id), "UpdateExpression": expression,
                         "ConditionExpression": "attribute_exists(pk) AND (attribute_not_exists(memoUpdatedAt) OR memoUpdatedAt < :u)",
                         "ExpressionAttributeValues": values}}
    return _write_unless_deleted(update, [deleted_key(user, "ask", ask_id)])


def get_ask(user: str, ask_id: str) -> Optional[dict]:
    item = clients.table().get_item(Key=ask_key(user, ask_id)).get("Item")
    return _from_item(item) if item else None


def ride_key(user: str, ride_id: str) -> dict:
    return {"pk": f"USER#{user}", "sk": f"RIDE#{ride_id}"}


def route_key(user: str, ride_id: str, seq: int) -> dict:
    # Zero-padded so that the chunks of a ride sort in order.
    return {"pk": f"USER#{user}", "sk": f"RIDE#{ride_id}#ROUTE#{seq:05d}"}


def note_key(user: str, ride_id: str, note_id: str) -> dict:
    # Under the ride, so that deleting the ride finds its notes with its route (slice 3 spec §6.1).
    return {"pk": f"USER#{user}", "sk": f"RIDE#{ride_id}#NOTE#{note_id}"}


def get_note(user: str, ride_id: str, note_id: str) -> Optional[dict]:
    item = clients.table().get_item(Key=note_key(user, ride_id, note_id)).get("Item")
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
    with clients.table().batch_writer() as batch:
        for key in keys:
            batch.delete_item(Key={"pk": key["pk"], "sk": key["sk"]})


def delete_ask(user: str, ask_id: str, deleted_at: str) -> None:
    """Marks the ask deleted, then removes it. Deleting a missing ask still leaves the mark (adr/0009)."""
    stored = get_ask(user, ask_id)
    mark_deleted(user, "ask", ask_id, deleted_at, ride_id=(stored or {}).get("rideId"))
    clients.table().delete_item(Key=ask_key(user, ask_id))


def delete_note(user: str, ride_id: str, note_id: str, deleted_at: str) -> None:
    mark_deleted(user, "note", note_id, deleted_at, ride_id=ride_id)
    clients.table().delete_item(Key=note_key(user, ride_id, note_id))


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


def transcription_key(user: str, transcription_id: str) -> dict:
    return {"pk": f"USER#{user}", "sk": f"TRANSCRIPTION#{transcription_id}"}


def create_transcription(item: dict) -> None:
    clients.table().put_item(Item=_to_item(item))


def claim_transcription(user: str, transcription_id: str) -> Optional[dict]:
    """pending -> processing, once. None if already claimed or missing."""
    return _claim(transcription_key(user, transcription_id))


def finish_transcription(user: str, transcription_id: str, fields: dict) -> None:
    values = _to_item(fields)
    names = {f"#k{i}": key for i, key in enumerate(values)}
    clients.table().update_item(
        Key=transcription_key(user, transcription_id),
        UpdateExpression="SET " + ", ".join(f"#k{i} = :v{i}" for i in range(len(values))),
        ExpressionAttributeNames=names,
        ExpressionAttributeValues={f":v{i}": value for i, value in enumerate(values.values())},
    )


def get_transcription(user: str, transcription_id: str) -> Optional[dict]:
    item = clients.table().get_item(Key=transcription_key(user, transcription_id)).get("Item")
    return _from_item(item) if item else None
