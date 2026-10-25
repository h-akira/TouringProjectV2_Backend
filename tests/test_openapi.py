"""The OpenAPI document is valid and covers the implemented routes."""
from pathlib import Path

import yaml
from openapi_spec_validator import validate

SPEC = yaml.safe_load((Path(__file__).parent.parent / "docs-parent" / "07a_openapi.yaml").read_text(encoding="utf-8"))


def test_is_valid_openapi():
    validate(SPEC)


def test_routes():
    assert {path: set(methods) for path, methods in SPEC["paths"].items()} == {
        "/health": {"get"},
        "/asks": {"post"},
        "/asks/{askId}": {"get", "delete"},
        "/asks/{askId}/memo": {"put"},
        "/asks/{askId}/offline": {"put"},
        "/rides/{rideId}": {"put", "delete"},
        "/rides/{rideId}/route/{seq}": {"put"},
        "/rides/{rideId}/notes/{noteId}": {"put", "delete"},
        "/transcriptions": {"post"},
        "/transcriptions/{transcriptionId}": {"get"},
        "/records": {"get"},
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


def test_the_ask_statuses_match_the_result():
    from handlers import result
    statuses = SPEC["components"]["schemas"]["AskResult"]["properties"]["status"]["enum"]
    assert set(statuses) == set(result._STATUS.values())


def test_the_heading_is_taken_on_every_path_that_takes_a_sample():
    # adr/0013: the app sends the heading it worked out wherever it used to send a sample.
    schemas = SPEC["components"]["schemas"]
    for name in ("AskRequest", "NoteRequest", "OfflineAskRequest"):
        properties = schemas[name]["properties"]
        assert "headingSample" in properties and properties["headingDegrees"]["type"] == "number"


def test_error_reasons_match_contract():
    reasons = SPEC["components"]["schemas"]["AskResult"]["properties"]["error"]["enum"]
    assert set(reasons) - {None} == {"no_speech", "transcribe_failed", "agent_failed", "tts_failed"}


def _samples():
    t = "2026-10-22T01:00:00.000Z"
    return [
        {"sk": "RIDE#r", "rideId": "r", "name": "n", "status": "ended", "segments": [], "autoEnded": False, "updatedAt": t},
        {"sk": "RIDE#r#ROUTE#00000", "rideId": "r", "seq": 0, "points": []},
        {"sk": "RIDE#r#NOTE#n", "rideId": "r", "noteId": "n", "at": t, "text": "x", "updatedAt": t},
        {"sk": "ASK#a", "askId": "a", "status": "offline", "receivedAt": t, "rideId": "r", "updatedAt": t},
        {"sk": "DELETED#RIDE#r", "kind": "ride", "id": "r", "deletedAt": t},
    ]


def test_the_records_schemas_name_exactly_what_the_handler_returns():
    from lib import records
    schemas = SPEC["components"]["schemas"]
    by_kind = {records.view(item)["kind"]: records.view(item) for item in _samples()}
    mapping = schemas["RecordItem"]["discriminator"]["mapping"]
    assert set(mapping) == set(by_kind)
    for kind, view in by_kind.items():
        schema = schemas[mapping[kind].rsplit("/", 1)[1]]
        assert set(schema["properties"]) == set(view) and set(schema["required"]) == set(view)
        assert schema["properties"]["kind"]["enum"] == [kind]


def test_the_ask_record_statuses_match_the_handler():
    from lib import records
    statuses = SPEC["components"]["schemas"]["AskRecord"]["properties"]["status"]["enum"]
    assert set(statuses) == set(records._ASK_STATUS.values())
