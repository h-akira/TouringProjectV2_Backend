"""DynamoDB's mechanics under the records: values in and out of items, the deletion marks, the transactions that
refuse a write to a deleted record, and the retries on a transaction in progress."""
from __future__ import annotations

import json
import time
from collections.abc import Callable
from decimal import Decimal
from typing import Any, Optional

from botocore.exceptions import ClientError

from lib import clients

_CONDITION_FAILED = "ConditionalCheckFailedException"
_CANCELLED = "TransactionCanceledException"
_CONFLICT = "TransactionConflictException"
# A write that meets a transaction on the same item fails at once; botocore does not retry it (Backend #18).
_CONFLICT_TRIES = 3
# Reads of deletion marks left unprocessed are tried again up to this many reads in all (Backend #30).
_MARK_READS = 5
_sleep: Callable[[float], None] = time.sleep


class _Conflict(Exception):
    """A transaction on the same item was in progress; trying again a moment later will do."""


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


def _set_clause(values: dict) -> tuple:
    """(expression, names, values) for SET #k0 = :v0, ... over the converted item values."""
    names = {f"#k{i}": key for i, key in enumerate(values)}
    expression = "SET " + ", ".join(f"#k{i} = :v{i}" for i in range(len(values)))
    return expression, names, {f":v{i}": value for i, value in enumerate(values.values())}


def deleted_key(user: str, kind: str, record_id: str) -> dict:
    """kind is ask, ride or note."""
    return {"pk": f"USER#{user}", "sk": f"DELETED#{kind.upper()}#{record_id}"}


def has_deletion_mark(user: str, marks: list) -> bool:
    """Whether any of the (kind, id) marks exists, read consistently in one batch (Backend #24). Used before costly
    work on a write that would be refused anyway; the write itself still checks the marks in its transaction, so
    marks still left unread after _MARK_READS reads count as none."""
    table = clients.table()
    keys = [deleted_key(user, kind, record_id) for kind, record_id in marks]
    request = {table.name: {"Keys": keys, "ConsistentRead": True, "ProjectionExpression": "pk"}} if keys else {}
    for attempt in range(_MARK_READS):
        if not request:
            break
        if attempt:
            _sleep(0.05 * 2 ** (attempt - 1))
        page = table.meta.client.batch_get_item(RequestItems=request)
        if page.get("Responses", {}).get(table.name):
            return True
        request = page.get("UnprocessedKeys") or {}
    return False


def _retrying_conflicts(write: Callable[[], Any]) -> Any:
    """Runs write, trying again twice (after 50 and 100 ms) while a transaction on the same item is in progress."""
    for attempt in range(_CONFLICT_TRIES):
        try:
            return write()
        except _Conflict:
            if attempt == _CONFLICT_TRIES - 1:
                raise
        except ClientError as error:
            if error.response["Error"]["Code"] != _CONFLICT or attempt == _CONFLICT_TRIES - 1:
                raise
        _sleep(0.05 * 2 ** attempt)


def mark_deleted(user: str, kind: str, record_id: str, deleted_at: str, ride_id: Optional[str] = None) -> None:
    """Writes the deletion mark; marking again keeps one. Marks never expire (adr/0009)."""
    item = _to_item({**deleted_key(user, kind, record_id), "kind": kind, "id": record_id, "rideId": ride_id,
                     "deletedAt": deleted_at})
    _retrying_conflicts(lambda: clients.table().put_item(Item=item))


def _write_unless_deleted(write: dict, marks: list) -> bool:
    """Runs one transaction write (a Put or an Update) unless one of the deletion marks exists, atomically, so that a
    deletion that lands at the same time cannot be undone. True when written; False when the write's own condition
    failed. Raises Deleted when a mark exists. The table's client takes plain values, as the table does. A deletion
    marking the same record at that moment cancels the transaction; it is tried again, and then sees the mark."""
    table = clients.table()
    checks = [{"ConditionCheck": {"TableName": table.name, "Key": mark, "ConditionExpression": "attribute_not_exists(pk)"}}
              for mark in marks]

    def attempt() -> bool:
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
            if "TransactionConflict" in codes:
                raise _Conflict() from None
            raise
        return True

    return _retrying_conflicts(attempt)


def _claim(key: dict, now_iso: str) -> Optional[dict]:
    """pending -> processing, once, noting when (claimedAt). None when it is not pending or missing."""
    try:
        result = clients.table().update_item(
            Key=key,
            UpdateExpression="SET #s = :processing, claimedAt = :now",
            ConditionExpression="#s = :pending",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":processing": "processing", ":pending": "pending", ":now": now_iso},
            ReturnValues="ALL_NEW",
        )
    except ClientError as error:
        if error.response["Error"]["Code"] == _CONDITION_FAILED:
            return None
        raise
    return _from_item(result["Attributes"])


def _fail_stalled(key: dict, fields: dict, stale_before_iso: str) -> bool:
    """processing -> failed (with fields) when it was taken before stale_before_iso: the worker that took it is gone.
    False when it is not processing, was taken since, or has no claim time (taken before claimedAt existed)."""
    values = _to_item(fields)
    expression, names, placeholders = _set_clause(values)
    try:
        clients.table().update_item(
            Key=key,
            UpdateExpression=expression,
            ConditionExpression="#s = :processing AND attribute_exists(claimedAt) AND claimedAt < :stale",
            ExpressionAttributeNames={**names, "#s": "status"},
            ExpressionAttributeValues={**placeholders, ":processing": "processing", ":stale": stale_before_iso},
        )
    except ClientError as error:
        if error.response["Error"]["Code"] == _CONDITION_FAILED:
            return False
        raise
    return True
