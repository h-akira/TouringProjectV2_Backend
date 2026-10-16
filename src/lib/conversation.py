"""How long a conversation lasts before the App starts a new one (adr/0003).

Read from SSM so an admin can change it without a deploy; capped below the
agent runtime's idle timeout (60 min) so the App always resets first.
"""
from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import Optional

from handlers.common import log
from lib import clients

DEFAULT_MINUTES = 15
MAX_MINUTES = 55
CACHE_SECONDS = 60

_cache: Optional[tuple[int, float]] = None


def reset_cache() -> None:
    global _cache
    _cache = None


def _read() -> int:
    name = os.environ["CONVERSATION_RESET_PARAMETER"]
    try:
        raw = clients.ssm().get_parameter(Name=name)["Parameter"]["Value"]
        minutes = int(raw.strip())
    except Exception as error:  # noqa: BLE001 - never fail a question over this setting
        log({"event": "conversation_reset_default", "reason": type(error).__name__})
        return DEFAULT_MINUTES
    clamped = min(max(minutes, 1), MAX_MINUTES)
    if clamped != minutes:
        log({"event": "conversation_reset_clamped", "value": minutes, "used": clamped})
    return clamped


def reset_minutes(clock: Callable[[], float] = time.monotonic) -> int:
    global _cache
    now = clock()
    if _cache is not None and now - _cache[1] < CACHE_SECONDS:
        return _cache[0]
    minutes = _read()
    _cache = (minutes, now)
    return minutes
