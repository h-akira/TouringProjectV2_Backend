"""The OpenAPI document is valid and covers the implemented routes."""
from pathlib import Path

import yaml
from openapi_spec_validator import validate

SPEC = yaml.safe_load((Path(__file__).parent.parent / "openapi.yaml").read_text(encoding="utf-8"))


def test_is_valid_openapi():
    validate(SPEC)


def test_routes():
    assert {path: set(methods) for path, methods in SPEC["paths"].items()} == {
        "/health": {"get"},
        "/asks": {"post"},
        "/asks/{askId}": {"get", "delete"},
        "/asks/{askId}/memo": {"put"},
        "/rides/{rideId}": {"put", "delete"},
        "/rides/{rideId}/route/{seq}": {"put"},
        "/rides/{rideId}/notes/{noteId}": {"put", "delete"},
        "/transcriptions": {"post"},
        "/transcriptions/{transcriptionId}": {"get"},
    }


def test_the_memo_and_note_limits_match_the_validation():
    from lib import notes, rides
    schemas = SPEC["components"]["schemas"]
    assert schemas["RideRequest"]["properties"]["memo"]["maxLength"] == rides.MEMO_MAX
    assert schemas["AskMemoRequest"]["properties"]["memo"]["maxLength"] == rides.MEMO_MAX
    assert schemas["NoteRequest"]["properties"]["text"]["maxLength"] == notes.NOTE_TEXT_MAX


def test_transcription_failures_match_the_worker():
    failures = SPEC["components"]["schemas"]["TranscriptionResult"]["properties"]["failure"]["enum"]
    assert set(failures) - {None} == {"no_speech", "transcribe_failed"}


def test_the_ride_limits_match_the_validation():
    from lib import rides
    schemas = SPEC["components"]["schemas"]
    assert schemas["RideRequest"]["properties"]["name"]["maxLength"] == rides.RIDE_NAME_MAX
    assert schemas["RideRequest"]["properties"]["status"]["enum"] == list(rides.STATUSES)
    assert schemas["RouteChunk"]["properties"]["points"]["maxItems"] == rides.MAX_POINTS


def test_error_reasons_match_contract():
    reasons = SPEC["components"]["schemas"]["AskResult"]["properties"]["error"]["enum"]
    assert set(reasons) - {None} == {"no_speech", "transcribe_failed", "agent_failed", "tts_failed"}
