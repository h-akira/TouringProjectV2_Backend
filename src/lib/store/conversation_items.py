"""Conversations: when the first question of one arrived."""
from __future__ import annotations

from datetime import datetime

from botocore.exceptions import ClientError

from lib import clients
from lib.store._dynamo import _CONDITION_FAILED

# A conversation lasts 55 minutes at most (07 UC-5); its record only has to outlive that (Backend #2).
CONVERSATION_TTL_SECONDS = 24 * 60 * 60


def _conversation_key(user: str, conversation_id: str) -> dict:
    return {"pk": f"USER#{user}", "sk": f"CONV#{conversation_id}"}


def conversation_started_at(user: str, conversation_id: str, now_iso: str) -> str:
    """When this conversation's first question arrived (recorded on first sight)."""
    key = _conversation_key(user, conversation_id)
    expires_at = int(datetime.fromisoformat(now_iso.replace("Z", "+00:00")).timestamp()) + CONVERSATION_TTL_SECONDS
    try:
        clients.table().put_item(Item={**key, "startedAt": now_iso, "expiresAt": expires_at},
                                 ConditionExpression="attribute_not_exists(pk)")
        return now_iso
    except ClientError as error:
        if error.response["Error"]["Code"] != _CONDITION_FAILED:
            raise
    # Written by another first question a moment ago, so the read must see it.
    return clients.table().get_item(Key=key, ConsistentRead=True)["Item"]["startedAt"]
