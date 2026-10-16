"""Tests for GET /asks/{askId} (moto)."""
import json

from handlers import result
from lib import store

USER, ASK = "rider01", "11111111-1111-4111-8111-111111111111"


def call(ask_id=ASK, user=USER):
    return result.handler({"headers": {"x-user-name": user}, "pathParameters": {"askId": ask_id}}, None)


def put(**fields):
    store.create_ask({**store.ask_key(USER, ASK), "askId": ASK, "timings": {"receivedAt": "2026-10-16T03:00:00.000Z"}, **fields})


def test_pending_is_reported_as_processing(aws):
    put(status="pending")
    body = json.loads(call()["body"])
    assert body == {"askId": ASK, "status": "processing", "transcript": None, "answer": None, "audio": [], "error": None,
                    "timings": {"receivedAt": "2026-10-16T03:00:00.000Z"}}


def test_completed_has_presigned_audio(aws):
    aws.s3.put_object(Bucket=aws.bucket, Key=f"answers/{ASK}.mp3", Body=b"mp3")
    put(status="completed", transcript="T", answer="A", answerAudioKey=f"answers/{ASK}.mp3")
    body = json.loads(call()["body"])
    assert body["status"] == "completed" and body["answer"] == "A" and body["transcript"] == "T"
    assert body["audio"][0]["seq"] == 1
    url = body["audio"][0]["url"]
    assert f"answers/{ASK}.mp3" in url and "X-Amz-Expires=600" in url


def test_failed_keeps_answer_for_device_tts(aws):
    put(status="failed", error="tts_failed", answer="A")
    body = json.loads(call()["body"])
    assert body["status"] == "failed" and body["error"] == "tts_failed" and body["answer"] == "A" and body["audio"] == []


def test_missing_is_404(aws):
    assert call()["statusCode"] == 404


def test_other_user_gets_404(aws):
    put(status="completed", answer="A")
    response = call(user="someoneelse")
    assert response["statusCode"] == 404
    assert json.loads(response["body"]) == {"error": "not_found"}


def test_malformed_id_is_404_and_bad_user_is_400(aws):
    assert call(ask_id="../etc")["statusCode"] == 404
    assert call(user="X")["statusCode"] == 400
