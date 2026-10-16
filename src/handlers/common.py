"""Helpers shared by the Lambda handlers."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

_log = logging.getLogger("trv2.backend")
_log.setLevel(logging.INFO)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    """UTC, millisecond precision, trailing Z."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.astimezone(timezone.utc).microsecond // 1000:03d}Z"


def parse_iso(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)


def response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json; charset=utf-8"},
        "body": json.dumps(body, ensure_ascii=False),
    }


def log(record: dict) -> None:
    # One JSON line per event. Callers must not pass question text, answers or positions.
    print(json.dumps(record, ensure_ascii=False))
