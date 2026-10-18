"""Records in one DynamoDB table: pk USER#<name>, sk ASK#<id>, CONV#<id>, RIDE#<id> or RIDE#<id>#ROUTE#<seq>."""
from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Optional

from botocore.exceptions import ClientError

from lib import clients

_CONDITION_FAILED = "ConditionalCheckFailedException"


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


def update_ask(user: str, ask_id: str, fields: dict) -> None:
    values = _to_item(fields)
    if not values:
        return
    names = {f"#k{i}": key for i, key in enumerate(values)}
    expression = "SET " + ", ".join(f"#k{i} = :v{i}" for i in range(len(values)))
    clients.table().update_item(
        Key=ask_key(user, ask_id),
        UpdateExpression=expression,
        ExpressionAttributeNames=names,
        ExpressionAttributeValues={f":v{i}": value for i, value in enumerate(values.values())},
    )


def get_ask(user: str, ask_id: str) -> Optional[dict]:
    item = clients.table().get_item(Key=ask_key(user, ask_id)).get("Item")
    return _from_item(item) if item else None


def ride_key(user: str, ride_id: str) -> dict:
    return {"pk": f"USER#{user}", "sk": f"RIDE#{ride_id}"}


def route_key(user: str, ride_id: str, seq: int) -> dict:
    # Zero-padded so that the chunks of a ride sort in order.
    return {"pk": f"USER#{user}", "sk": f"RIDE#{ride_id}#ROUTE#{seq:05d}"}


def put_ride(user: str, ride_id: str, fields: dict) -> bool:
    """Writes the ride unless a newer one is stored (updatedAt, normalised UTC text). False when it was older."""
    item = {**ride_key(user, ride_id), "rideId": ride_id, **fields}
    try:
        clients.table().put_item(
            Item=_to_item(item),
            ConditionExpression="attribute_not_exists(pk) OR updatedAt < :u",
            ExpressionAttributeValues={":u": fields["updatedAt"]},
        )
    except ClientError as error:
        if error.response["Error"]["Code"] == _CONDITION_FAILED:
            return False
        raise
    return True


def put_route_chunk(user: str, ride_id: str, seq: int, points: list, saved_at: str) -> None:
    """A chunk is replaced whole: sending it again leaves one copy."""
    clients.table().put_item(Item=_to_item({**route_key(user, ride_id, seq), "rideId": ride_id, "seq": seq, "points": points, "savedAt": saved_at}))
