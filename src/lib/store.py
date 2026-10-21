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
    try:
        result = clients.table().update_item(
            Key=ask_key(user, ask_id),
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


def get_ask(user: str, ask_id: str) -> Optional[dict]:
    item = clients.table().get_item(Key=ask_key(user, ask_id)).get("Item")
    return _from_item(item) if item else None


def ride_key(user: str, ride_id: str) -> dict:
    return {"pk": f"USER#{user}", "sk": f"RIDE#{ride_id}"}


def route_key(user: str, ride_id: str, seq: int) -> dict:
    # Zero-padded so that the chunks of a ride sort in order.
    return {"pk": f"USER#{user}", "sk": f"RIDE#{ride_id}#ROUTE#{seq:05d}"}


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
