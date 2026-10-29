"""What a record keeps from the first version that had a value (slice 3 spec §6.2, Backend #17, #21, #31)."""
from datetime import datetime, timezone

from lib import address, placed

AT = datetime(2026, 10, 16, 12, 0, 0, tzinfo=timezone.utc)
HERE = {"latitude": 35.0, "longitude": 139.0}
THERE = {"latitude": 36.0, "longitude": 140.0}


def _describe(monkeypatch, calls):
    monkeypatch.setattr(address, "describe_location", lambda lat, lon: calls.append((lat, lon)) or f"{lat},{lon}")


def test_a_new_record_takes_everything_from_the_version_it_gets(monkeypatch):
    calls = []
    _describe(monkeypatch, calls)
    got = placed.settle_first(None, HERE, 90.04, None, AT, keep_first_location=True)
    assert got == placed.Placed(HERE, 90.0, "35.0,139.0")
    assert calls == [(35.0, 139.0)]


def test_a_heading_and_a_place_that_are_stored_are_kept(monkeypatch):
    calls = []
    _describe(monkeypatch, calls)
    stored = {"location": HERE, "headingDegrees": 10.0, "address": "stored place"}
    got = placed.settle_first(stored, THERE, 200.0, None, AT, keep_first_location=False)
    assert got == placed.Placed(THERE, 10.0, "stored place")
    assert calls == []


def test_the_position_is_kept_only_when_asked_to(monkeypatch):
    _describe(monkeypatch, [])
    stored = {"location": HERE, "address": "stored place"}
    assert placed.settle_first(stored, THERE, None, None, AT, keep_first_location=True).location == HERE
    assert placed.settle_first(stored, THERE, None, None, AT, keep_first_location=False).location == THERE
    # A first version without a position gives it up to a later one, as the heading does.
    assert placed.settle_first({}, THERE, None, None, AT, keep_first_location=True).location == THERE


def test_the_place_is_looked_up_for_the_position_that_is_kept(monkeypatch):
    calls = []
    _describe(monkeypatch, calls)
    stored = {"location": HERE}
    got = placed.settle_first(stored, THERE, None, None, AT, keep_first_location=True)
    assert got.address == "35.0,139.0" and calls == [(35.0, 139.0)]


def test_no_position_means_no_place_and_no_heading_from_a_sample(monkeypatch):
    _describe(monkeypatch, [])
    assert placed.settle_first(None, None, None, None, AT, keep_first_location=False) == placed.Placed(None, None, None)
