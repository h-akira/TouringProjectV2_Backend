"""Tests for POST /asks (moto)."""
import base64
import json

from handlers import ask
from lib import store
from lib.request import MIN_AUDIO_BYTES

CID = "0b8e7c1e-3f1a-4f5e-9a51-2a0b2c6f7d10"


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
