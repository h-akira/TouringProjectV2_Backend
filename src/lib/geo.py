"""Distance, bearing and the rules for when a heading can be trusted."""
from __future__ import annotations

import math
from datetime import datetime
from typing import Optional

from handlers.common import parse_iso

MIN_DISTANCE_METERS = 5.0  # below this, GPS noise dominates the bearing
MAX_SAMPLE_AGE_SECONDS = 120  # an older sample says little about the current direction
MAX_FUTURE_SKEW_SECONDS = 30  # the sample time comes from the phone's clock, which may run a little ahead
_EARTH_RADIUS_METERS = 6_371_000.0
_COMPASS = ("北", "北北東", "北東", "東北東", "東", "東南東", "南東", "南南東",
            "南", "南南西", "南西", "西南西", "西", "西北西", "北西", "北北西")


def haversine_meters(a: dict, b: dict) -> float:
    lat1, lat2 = math.radians(a["latitude"]), math.radians(b["latitude"])
    dlat, dlon = lat2 - lat1, math.radians(b["longitude"] - a["longitude"])
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * _EARTH_RADIUS_METERS * math.asin(math.sqrt(h))


def bearing_degrees(a: dict, b: dict) -> float:
    """Initial bearing from a to b, clockwise from north, in [0, 360)."""
    lat1, lat2 = math.radians(a["latitude"]), math.radians(b["latitude"])
    dlon = math.radians(b["longitude"] - a["longitude"])
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return math.degrees(math.atan2(x, y)) % 360


def compass(bearing: float) -> str:
    return _COMPASS[round((bearing % 360) / 22.5) % 16]


def settled_heading(degrees: Optional[float], location: Optional[dict], sample: Optional[dict],
                    at: datetime) -> Optional[float]:
    """The heading kept with a record: the app's own (adr/0013), or, from an app older than that, the one taken from
    its sample. Rounded to a tenth of a degree, with 360 read as 0 (Backend #12)."""
    heading = degrees if degrees is not None else heading_degrees(location, sample, at)
    return round(heading, 1) % 360 if heading is not None else None


def heading_degrees(location: Optional[dict], sample: Optional[dict], received_at: datetime) -> Optional[float]:
    """Direction of travel from the older sample to the current position, or None."""
    if location is None or sample is None:
        return None
    age = (received_at - parse_iso(sample["at"])).total_seconds()
    if age < -MAX_FUTURE_SKEW_SECONDS or age > MAX_SAMPLE_AGE_SECONDS:
        return None
    if haversine_meters(sample, location) < MIN_DISTANCE_METERS:
        return None
    return bearing_degrees(sample, location)
