"""Helpers shared by the Lambda handlers: the shapes of their responses. Time and log helpers are in lib.common."""
from __future__ import annotations

import json
import os

from lib import clients
from lib.common import iso, log, parse_iso, utc_now  # noqa: F401 - handlers import them from here


def response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json; charset=utf-8"},
        "body": json.dumps(body, ensure_ascii=False),
    }


def deleted() -> dict:
    """410: the record, or its ride, was deleted; the app treats it as sent (slice 3 spec §5.4)."""
    return response(410, {"error": "deleted"})


def no_content() -> dict:
    return {"statusCode": 204, "headers": {}, "body": ""}


def discard_audio(key: str) -> None:
    """Removes a recording that was not kept; the 1-day lifecycle rule would remove it anyway."""
    try:
        clients.s3().delete_object(Bucket=os.environ["AUDIO_BUCKET"], Key=key)
    except Exception as error:  # noqa: BLE001
        log({"event": "audio_delete_failed", "error": type(error).__name__})
