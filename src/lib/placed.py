"""What a record keeps from the first version of it that had a value: the heading, the place and, for an unreached
ask, the position (slice 3 spec §6.2, Backend #17, #21, #31). Point memos and unreached asks both settle these."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from lib import address
from lib.geo import settled_heading


@dataclass(frozen=True)
class Placed:
    location: Optional[dict]
    heading: Optional[float]
    address: Optional[str]


def settle_first(stored: Optional[dict], location: Optional[dict], degrees: Optional[float], sample: Optional[dict],
                 at: datetime, *, keep_first_location: bool) -> Placed:
    """The heading and the place of the stored record are kept; they are worked out only while it has none (a failed
    place lookup, or a first version without a heading, is tried again by a later one). The position is kept the same
    way for an unreached ask; a point memo takes the one it is sent with. The heading is worked out from the position
    of the version at hand, the place from the position that is kept."""
    kept = stored or {}
    heading = kept.get("headingDegrees")
    if heading is None:
        heading = settled_heading(degrees, location, sample, at)
    where = (kept.get("location") or location) if keep_first_location else location
    place = kept.get("address") or (address.describe_location(where["latitude"], where["longitude"]) if where else None)
    return Placed(where, heading, place)
