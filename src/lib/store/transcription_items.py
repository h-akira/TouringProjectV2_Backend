"""Transcriptions: the recording of a point memo, turned into text only (07 UC-6)."""
from __future__ import annotations

from typing import Optional

from lib import clients
from lib.store._dynamo import _claim, _fail_stalled, _from_item, _set_clause, _to_item


def transcription_key(user: str, transcription_id: str) -> dict:
    return {"pk": f"USER#{user}", "sk": f"TRANSCRIPTION#{transcription_id}"}


def create_transcription(item: dict) -> None:
    clients.table().put_item(Item=_to_item(item))


def discard_transcription(user: str, transcription_id: str) -> None:
    """Removes a transcription that was never queued: no worker would take it."""
    clients.table().delete_item(Key=transcription_key(user, transcription_id))


def claim_transcription(user: str, transcription_id: str, now_iso: str) -> Optional[dict]:
    """pending -> processing, once. None if already claimed or missing."""
    return _claim(transcription_key(user, transcription_id), now_iso)


def fail_stalled_transcription(user: str, transcription_id: str, stale_before_iso: str) -> bool:
    """Like fail_stalled_ask, for a transcription: failed as transcribe_failed."""
    return _fail_stalled(transcription_key(user, transcription_id),
                         {"status": "failed", "failure": "transcribe_failed"}, stale_before_iso)


def finish_transcription(user: str, transcription_id: str, fields: dict) -> None:
    values = _to_item(fields)
    expression, names, placeholders = _set_clause(values)
    clients.table().update_item(
        Key=transcription_key(user, transcription_id),
        UpdateExpression=expression,
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=placeholders,
    )


def get_transcription(user: str, transcription_id: str, consistent: bool = False) -> Optional[dict]:
    item = clients.table().get_item(Key=transcription_key(user, transcription_id), ConsistentRead=consistent).get("Item")
    return _from_item(item) if item else None
