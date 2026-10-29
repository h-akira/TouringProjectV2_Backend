"""Asks: a question taken in, worked on by the worker, read back, given a memo, or kept by the app unreached."""
from __future__ import annotations

from typing import Optional

from botocore.exceptions import ClientError

from lib import clients
from lib.store._dynamo import (_CONDITION_FAILED, _claim, _from_item, _retrying_conflicts, _set_clause, _to_item,
                               _write_unless_deleted, deleted_key, mark_deleted)


def ask_key(user: str, ask_id: str) -> dict:
    return {"pk": f"USER#{user}", "sk": f"ASK#{ask_id}"}


def create_ask(item: dict) -> None:
    clients.table().put_item(Item=_to_item(item))


def discard_ask(user: str, ask_id: str) -> None:
    """Removes an ask that was never queued, leaving no deletion mark: the app never learnt of it."""
    clients.table().delete_item(Key=ask_key(user, ask_id))


def claim_ask(user: str, ask_id: str) -> Optional[dict]:
    """pending -> processing, once. None if already claimed or missing."""
    return _claim(ask_key(user, ask_id))


def update_ask(user: str, ask_id: str, fields: dict) -> bool:
    """Sets the fields on a stored ask. False when the ask is gone (deleted meanwhile): it is not written back."""
    values = _to_item(fields)
    if not values:
        return True
    expression, names, placeholders = _set_clause(values)
    try:
        clients.table().update_item(
            Key=ask_key(user, ask_id),
            UpdateExpression=expression,
            ConditionExpression="attribute_exists(pk)",
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=placeholders,
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


def put_offline_ask(user: str, ask_id: str, fields: dict) -> bool:
    """Sets an unreached ask's fields unless a newer version is stored, keeping its memo (written on its own path).
    False when it was not newer, or when the id belongs to an ask the Backend took in. Raises Deleted when the ask or
    its ride has been deleted (slice 4 spec §4.4)."""
    values = _to_item({"askId": ask_id, "status": "offline", **fields})
    expression, names, placeholders = _set_clause(values)
    update = {"Update": {
        "TableName": clients.table().name,
        "Key": ask_key(user, ask_id),
        "UpdateExpression": expression,
        "ConditionExpression": "attribute_not_exists(pk) OR (#s = :offline AND #u < :u)",
        "ExpressionAttributeNames": {**names, "#s": "status", "#u": "updatedAt"},
        "ExpressionAttributeValues": {**placeholders, ":offline": "offline", ":u": fields["updatedAt"]},
    }}
    return _write_unless_deleted(update, [deleted_key(user, "ask", ask_id), deleted_key(user, "ride", fields["rideId"])])


def get_ask(user: str, ask_id: str, consistent: bool = False) -> Optional[dict]:
    item = clients.table().get_item(Key=ask_key(user, ask_id), ConsistentRead=consistent).get("Item")
    return _from_item(item) if item else None


def delete_ask(user: str, ask_id: str, deleted_at: str) -> None:
    """Marks the ask deleted, then removes it. Deleting a missing ask still leaves the mark (adr/0009)."""
    # The ask may have been written a moment ago; its mark must still name its ride (Backend #18).
    stored = get_ask(user, ask_id, consistent=True)
    mark_deleted(user, "ask", ask_id, deleted_at, ride_id=(stored or {}).get("rideId"))
    # A memo PUT's transaction on the ask makes the delete fail for a moment (Backend #23).
    _retrying_conflicts(lambda: clients.table().delete_item(Key=ask_key(user, ask_id)))
