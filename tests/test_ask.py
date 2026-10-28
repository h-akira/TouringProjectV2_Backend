"""Tests for POST /asks (moto)."""
import base64
import json

from handlers import ask
from lib import store
from lib.request import MIN_AUDIO_BYTES

CID = "0b8e7c1e-3f1a-4f5e-9a51-2a0b2c6f7d10"
RID = "5c9a1f0e-2b3d-4e5f-8a6b-7c8d9e0f1a2b"


def call(body, user="rider01"):
    return ask.handler({"headers": {"x-user-name": user}, "body": json.dumps(body)}, None)


def messages(aws):
    got = aws.sqs.receive_message(QueueUrl=aws.queue_url, MaxNumberOfMessages=10).get("Messages", [])
    return [json.loads(m["Body"]) for m in got]


def test_text_question_is_accepted(aws):
    result = call({"text": "富士山の高さは？", "location": {"latitude": 35.6812, "longitude": 139.7671}})
    assert result["statusCode"] == 202
    body = json.loads(result["body"])
    item = store.get_ask("rider01", body["askId"])
    assert item["status"] == "pending" and item["inputType"] == "text" and item["question"] == "富士山の高さは？"
    assert item["conversationId"] == body["conversationId"]
    assert item["timings"]["receivedAt"] == item["receivedAt"]
    assert messages(aws) == [{"userName": "rider01", "askId": body["askId"]}]


def test_expiry_is_reset_minutes_after_receipt(aws):
    body = json.loads(call({"text": "Q"})["body"])
    item = store.get_ask("rider01", body["askId"])
    from handlers.common import parse_iso
    assert (parse_iso(body["conversationExpiresAt"]) - parse_iso(item["receivedAt"])).total_seconds() == 15 * 60


def test_audio_goes_to_s3(aws):
    audio = b"\x01\x00" * (MIN_AUDIO_BYTES // 2)
    body = json.loads(call({"audio": base64.b64encode(audio).decode()})["body"])
    item = store.get_ask("rider01", body["askId"])
    assert item["inputType"] == "audio" and item["audioKey"] == f"audio/{body['askId']}.pcm"
    assert aws.s3.get_object(Bucket=aws.bucket, Key=item["audioKey"])["Body"].read() == audio


def test_conversation_continues_and_keeps_start(aws):
    first = json.loads(call({"text": "Q1", "conversationId": CID})["body"])
    second = json.loads(call({"text": "Q2", "conversationId": CID})["body"])
    assert first["conversationId"] == second["conversationId"] == CID
    a, b = store.get_ask("rider01", first["askId"]), store.get_ask("rider01", second["askId"])
    assert a["conversationStartedAt"] == b["conversationStartedAt"] == a["receivedAt"]


def test_bad_request_leaves_nothing(aws):
    result = call({"audio": "AAA="})
    assert result["statusCode"] == 400
    assert json.loads(result["body"])["error"] == "bad_request"
    assert aws.table.scan()["Items"] == []
    assert aws.s3.list_objects_v2(Bucket=aws.bucket).get("KeyCount", 0) == 0
    assert messages(aws) == []


def test_bad_user_is_400(aws):
    assert call({"text": "Q"}, user="X")["statusCode"] == 400


def test_volume_is_stored(aws):
    body = json.loads(call({"text": "Q", "volumeDb": 3})["body"])
    assert store.get_ask("rider01", body["askId"])["volumeDb"] == 3


def test_volume_defaults_when_omitted(aws):
    body = json.loads(call({"text": "Q"})["body"])
    assert store.get_ask("rider01", body["askId"])["volumeDb"] == 6


def test_bad_volume_is_rejected(aws):
    result = call({"text": "Q", "volumeDb": 12})
    assert result["statusCode"] == 400
    assert aws.table.scan()["Items"] == []


def test_the_ride_id_is_kept_with_the_ask(aws):
    body = json.loads(call({"text": "Q", "rideId": RID})["body"])
    assert store.get_ask("rider01", body["askId"])["rideId"] == RID


def test_an_ask_outside_a_ride_has_no_ride_id(aws):
    body = json.loads(call({"text": "Q"})["body"])
    assert "rideId" not in store.get_ask("rider01", body["askId"])


def test_a_malformed_ride_id_is_400(aws):
    for bad in ("ride-1", RID.upper(), 12):
        result = call({"text": "Q", "rideId": bad})
        assert result["statusCode"] == 400 and "rideId" in json.loads(result["body"])["message"]


def test_a_location_too_large_for_a_float_is_dropped_not_a_crash(aws):
    result = call({"text": "Q", "location": {"latitude": 10 ** 400, "longitude": 139.0}})
    assert result["statusCode"] == 202
    assert "location" not in store.get_ask("rider01", json.loads(result["body"])["askId"])


def test_an_ask_that_cannot_be_queued_is_503_and_leaves_no_ask_or_audio(aws, monkeypatch):
    # Nothing would ever take a pending ask without its message, so it is removed (Backend #3).
    def broken(**params):
        raise RuntimeError("queue unavailable")

    monkeypatch.setattr(ask.clients.sqs(), "send_message", broken)
    audio = b"\x01\x00" * (MIN_AUDIO_BYTES // 2)
    result = call({"audio": base64.b64encode(audio).decode(), "rideId": RID})
    assert result["statusCode"] == 503 and json.loads(result["body"]) == {"error": "unavailable"}
    assert [i["sk"] for i in aws.table.scan()["Items"] if i["sk"].startswith("ASK#")] == []
    assert aws.s3.list_objects_v2(Bucket=aws.bucket).get("KeyCount") == 0


def test_the_apps_heading_is_kept_with_the_ask(aws):
    body = json.loads(call({"text": "右手の山は？", "location": {"latitude": 35.6812, "longitude": 139.7671},
                            "headingDegrees": 45.5})["body"])
    assert store.get_ask("rider01", body["askId"])["headingDegrees"] == 45.5


def test_the_apps_heading_is_rounded_when_the_ask_is_taken(aws):
    # An ask that fails before the agent keeps the heading it was taken with, so it is settled here (Backend #29).
    for sent, kept in [(359.96, 0), (12.3456789, 12.3)]:
        body = json.loads(call({"text": "Q", "headingDegrees": sent})["body"])
        assert store.get_ask("rider01", body["askId"])["headingDegrees"] == kept


def test_an_ask_with_only_a_sample_is_kept_without_a_heading_for_the_worker(aws):
    # An older app's sample is left to the worker; rounding at the ask does not invent a heading (Backend #29).
    sample = {"latitude": 35.6712, "longitude": 139.7671, "at": "2026-10-16T03:04:30.000Z"}
    body = json.loads(call({"text": "Q", "location": {"latitude": 35.6812, "longitude": 139.7671},
                            "headingSample": sample})["body"])
    item = store.get_ask("rider01", body["askId"])
    assert "headingDegrees" not in item and item["headingSample"]["latitude"] == 35.6712


def test_a_heading_out_of_range_is_not_kept(aws):
    result = call({"text": "Q", "headingDegrees": 400})
    assert result["statusCode"] == 202
    assert "headingDegrees" not in store.get_ask("rider01", json.loads(result["body"])["askId"])
