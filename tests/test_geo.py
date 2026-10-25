"""Tests for distance, bearing and the heading rules."""
from datetime import datetime, timedelta, timezone

import pytest

from lib import geo

NOW = datetime(2026, 10, 16, 3, 0, tzinfo=timezone.utc)
HERE = {"latitude": 35.6812, "longitude": 139.7671}
SOUTH_60M = {"latitude": 35.68066, "longitude": 139.7671}


def sample(point, seconds_ago):
    at = NOW - timedelta(seconds=seconds_ago)
    return {**point, "at": at.strftime("%Y-%m-%dT%H:%M:%S.000Z")}


def test_bearing_and_distance():
    assert geo.bearing_degrees(SOUTH_60M, HERE) == pytest.approx(0, abs=0.5)
    assert geo.haversine_meters(SOUTH_60M, HERE) == pytest.approx(60, abs=1)


@pytest.mark.parametrize("bearing, label", [(0, "北"), (90, "東"), (180, "南"), (225, "南西"), (359, "北")])
def test_compass(bearing, label):
    assert geo.compass(bearing) == label


def test_heading_from_a_recent_sample():
    assert geo.heading_degrees(HERE, sample(SOUTH_60M, 10), NOW) == pytest.approx(0, abs=0.5)


def test_heading_none_without_location_or_sample():
    assert geo.heading_degrees(None, sample(SOUTH_60M, 10), NOW) is None
    assert geo.heading_degrees(HERE, None, NOW) is None


def test_heading_none_when_barely_moved():
    near = {"latitude": 35.68118, "longitude": 139.7671}
    assert geo.heading_degrees(HERE, sample(near, 10), NOW) is None


@pytest.mark.parametrize("seconds_ago", [geo.MAX_SAMPLE_AGE_SECONDS + 1, -(geo.MAX_FUTURE_SKEW_SECONDS + 10)])
def test_heading_none_when_sample_is_stale_or_in_future(seconds_ago):
    assert geo.heading_degrees(HERE, sample(SOUTH_60M, seconds_ago), NOW) is None


def test_small_device_clock_skew_is_tolerated():
    assert geo.heading_degrees(HERE, sample(SOUTH_60M, -5), NOW) == pytest.approx(0, abs=0.5)


def test_settled_heading_takes_the_apps_degrees():
    # The app works the heading out from the ride's route (adr/0013); its sample is not used then.
    assert geo.settled_heading(123.44, HERE, sample(SOUTH_60M, 10), NOW) == 123.4


def test_settled_heading_falls_back_to_an_older_apps_sample():
    assert geo.settled_heading(None, HERE, sample(SOUTH_60M, 10), NOW) == pytest.approx(0, abs=0.1)


def test_settled_heading_reads_almost_north_as_zero():
    # 359.96 rounds to 360.0, which is north (Backend #12).
    assert geo.settled_heading(359.96, HERE, None, NOW) == 0.0


def test_settled_heading_is_none_without_degrees_or_sample():
    assert geo.settled_heading(None, HERE, None, NOW) is None
