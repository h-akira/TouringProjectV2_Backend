"""Coordinates to a Japanese address down to the town (no block numbers)."""
from __future__ import annotations

from typing import Any, Optional

from handlers.common import log
from lib import clients


def describe_location(latitude: float, longitude: float, client: Any = None) -> Optional[str]:
    """Prefecture + city + ward + town, or None when it cannot be resolved (never raises)."""
    try:
        result = (client or clients.geo()).reverse_geocode(
            QueryPosition=[longitude, latitude],  # longitude first
            MaxResults=1,
            Language="ja",
        )
    except Exception as error:  # noqa: BLE001 - the question goes ahead without an address
        log({"event": "reverse_geocode_failed", "error": type(error).__name__})
        return None
    items = result.get("ResultItems") or []
    if not items:
        return None
    address = items[0].get("Address") or {}
    region = (address.get("Region") or {}).get("Name") or ""
    locality = address.get("Locality") or (address.get("SubRegion") or {}).get("Name") or ""
    if not locality:
        return region or None
    place = f"{region}{locality}"
    for part in (address.get("District"), address.get("SubDistrict")):
        if part and part not in place:
            place += part
    return place
