"""A page of a user's records, for taking over on another device."""
from __future__ import annotations

from typing import Optional

from lib import clients
from lib.store._dynamo import _from_item


def query_records(user: str, after: Optional[str], limit: Optional[int] = None) -> tuple:
    """One page of the user's records in sort-key order (one query, at most 1 MB), read consistently, and the sort key
    to continue after (None on the last page). The partition comes from the user alone (slice 4 spec §6.2)."""
    params: dict = {"KeyConditionExpression": "pk = :p", "ExpressionAttributeValues": {":p": f"USER#{user}"},
                    "ConsistentRead": True}
    if after is not None:
        params["ExclusiveStartKey"] = {"pk": f"USER#{user}", "sk": after}
    if limit is not None:
        params["Limit"] = limit
    page = clients.table().query(**params)
    last = page.get("LastEvaluatedKey")
    return [_from_item(item) for item in page.get("Items", [])], (last["sk"] if last else None)
