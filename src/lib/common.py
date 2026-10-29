"""Time and log helpers shared by the handlers and the libraries."""
from __future__ import annotations

import json
from datetime import datetime, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    """UTC, millisecond precision, trailing Z."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.astimezone(timezone.utc).microsecond // 1000:03d}Z"


def parse_iso(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)


def log(record: dict) -> None:
    # One JSON line per event. Callers must not pass question text, answers or positions.
    print(json.dumps(record, ensure_ascii=False))
