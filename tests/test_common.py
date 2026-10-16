"""Tests for the shared handler helpers and the health check."""
import json
from datetime import datetime, timezone

from handlers import common, health


def test_iso_is_utc_with_millis_and_z():
    dt = datetime(2026, 10, 16, 12, 0, 1, 234567, tzinfo=timezone.utc)
    assert common.iso(dt) == "2026-10-16T12:00:01.234Z"


def test_parse_iso_round_trips_and_accepts_offsets():
    assert common.parse_iso("2026-10-16T12:00:01.234Z") == datetime(2026, 10, 16, 12, 0, 1, 234000, tzinfo=timezone.utc)
    assert common.parse_iso("2026-10-16T21:00:00+09:00") == datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)


def test_response_is_json_utf8():
    result = common.response(400, {"message": "日本語"})
    assert result["statusCode"] == 400
    assert result["headers"]["Content-Type"] == "application/json; charset=utf-8"
    assert json.loads(result["body"]) == {"message": "日本語"}
    assert "日本語" in result["body"]


def test_health():
    result = health.handler({}, None)
    assert result["statusCode"] == 200
    assert json.loads(result["body"]) == {"status": "ok"}
