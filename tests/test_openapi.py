"""The OpenAPI document is valid and covers the implemented routes."""
from pathlib import Path

import yaml
from openapi_spec_validator import validate

SPEC = yaml.safe_load((Path(__file__).parent.parent / "openapi.yaml").read_text(encoding="utf-8"))


def test_is_valid_openapi():
    validate(SPEC)


def test_routes():
    assert set(SPEC["paths"]) == {"/health", "/asks", "/asks/{askId}", "/rides/{rideId}", "/rides/{rideId}/route/{seq}"}
    assert set(SPEC["paths"]["/asks"]) == {"post"}
    assert set(SPEC["paths"]["/asks/{askId}"]) == {"get"}
    assert set(SPEC["paths"]["/rides/{rideId}"]) == {"put"}
    assert set(SPEC["paths"]["/rides/{rideId}/route/{seq}"]) == {"put"}


def test_the_ride_limits_match_the_validation():
    from lib import rides
    schemas = SPEC["components"]["schemas"]
    assert schemas["RideRequest"]["properties"]["name"]["maxLength"] == rides.RIDE_NAME_MAX
    assert schemas["RideRequest"]["properties"]["status"]["enum"] == list(rides.STATUSES)
    assert schemas["RouteChunk"]["properties"]["points"]["maxItems"] == rides.MAX_POINTS


def test_error_reasons_match_contract():
    reasons = SPEC["components"]["schemas"]["AskResult"]["properties"]["error"]["enum"]
    assert set(reasons) - {None} == {"no_speech", "transcribe_failed", "agent_failed", "tts_failed"}
