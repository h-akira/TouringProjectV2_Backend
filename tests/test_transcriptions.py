"""Tests for POST /transcriptions, GET /transcriptions/{transcriptionId} and the worker's part (moto)."""
import base64
import json

from handlers import transcriptions, worker
from handlers.common import parse_iso
from lib import store
from lib.request import MAX_AUDIO_BYTES, MIN_AUDIO_BYTES
from test_worker import Recorder

USER = "rider01"
AUDIO = b"\x00\x00" * (MIN_AUDIO_BYTES // 2 * 4)


def post(body, user=USER):
    return transcriptions.handler({"httpMethod": "POST", "headers": {"x-user-name": user}, "body": json.dumps(body)}, None)


def get(transcription_id, user=USER):
    event = {"httpMethod": "GET", "headers": {"x-user-name": user}, "pathParameters": {"transcriptionId": transcription_id}}
    return transcriptions.handler(event, None)


def accepted(aws, audio=AUDIO):
    result = post({"audio": base64.b64encode(audio).decode()})
    assert result["statusCode"] == 202
    return json.loads(result["body"])["transcriptionId"]


def messages(aws):
    got = aws.sqs.receive_message(QueueUrl=aws.queue_url, MaxNumberOfMessages=10).get("Messages", [])
    return [json.loads(m["Body"]) for m in got]


def audio_keys(aws):
    return [o["Key"] for o in aws.s3.list_objects_v2(Bucket=aws.bucket, Prefix="audio/").get("Contents", [])]


def test_a_recording_is_accepted_queued_and_kept_for_a_day(aws):
    transcription_id = accepted(aws)
    item = store.get_transcription(USER, transcription_id)
    assert item["status"] == "pending" and item["audioKey"] == f"audio/{transcription_id}.pcm"
    assert item["expiresAt"] - int(parse_iso(item["receivedAt"]).timestamp()) == 86400
    assert audio_keys(aws) == [f"audio/{transcription_id}.pcm"]
    assert messages(aws) == [{"kind": "transcription", "userName": USER, "transcriptionId": transcription_id}]


def test_while_it_waits_it_is_processing(aws):
    transcription_id = accepted(aws)
    body = json.loads(get(transcription_id)["body"])
    assert body == {"transcriptionId": transcription_id, "status": "processing", "text": None, "failure": None}


def test_the_worker_turns_it_into_text_without_the_agent_and_drops_the_audio(aws):
    transcription_id = accepted(aws)
    rec = Recorder(transcript="道の駅の先に眺めのいい駐車場")
    worker.process_transcription(USER, transcription_id, rec.steps())
    assert [c[0] for c in rec.calls] == ["transcribe"]
    assert json.loads(get(transcription_id)["body"]) == {"transcriptionId": transcription_id, "status": "done",
                                                         "text": "道の駅の先に眺めのいい駐車場", "failure": None}
    assert audio_keys(aws) == []


def test_silence_is_no_speech(aws):
    transcription_id = accepted(aws)
    worker.process_transcription(USER, transcription_id, Recorder(transcript="").steps())
    body = json.loads(get(transcription_id)["body"])
    assert body["status"] == "failed" and body["failure"] == "no_speech" and body["text"] is None


def test_a_failed_transcription_is_reported_and_drops_the_audio(aws):
    transcription_id = accepted(aws)
    worker.process_transcription(USER, transcription_id, Recorder(stt_error=RuntimeError("stream broke")).steps())
    body = json.loads(get(transcription_id)["body"])
    assert body["status"] == "failed" and body["failure"] == "transcribe_failed"
    assert audio_keys(aws) == []


def test_a_second_delivery_does_nothing(aws):
    transcription_id = accepted(aws)
    rec = Recorder()
    worker.process_transcription(USER, transcription_id, rec.steps())
    worker.process_transcription(USER, transcription_id, rec.steps())
    assert [c[0] for c in rec.calls] == ["transcribe"]


def test_the_worker_handler_tells_a_transcription_from_an_ask(aws, monkeypatch):
    transcription_id = accepted(aws)
    rec = Recorder(transcript="メモ")
    monkeypatch.setattr(worker, "DEFAULT_STEPS", rec.steps())
    body = json.dumps({"kind": "transcription", "userName": USER, "transcriptionId": transcription_id})
    worker.handler({"Records": [{"body": body}]}, None)
    assert store.get_transcription(USER, transcription_id)["text"] == "メモ"


def test_unknown_or_another_users_transcription_is_404(aws):
    transcription_id = accepted(aws)
    assert get(transcription_id, user="someone")["statusCode"] == 404
    assert get("00000000-0000-4000-8000-000000000000")["statusCode"] == 404
    assert get("not-a-uuid")["statusCode"] == 404


def test_bad_audio_is_400_and_queues_nothing(aws):
    for body in ({}, {"audio": "@@@"}, {"audio": base64.b64encode(b"\x00" * (MIN_AUDIO_BYTES - 2)).decode()},
                 {"audio": base64.b64encode(b"\x00" * (MAX_AUDIO_BYTES + 2)).decode()}, {"text": "文字は受けない"}):
        result = post(body)
        assert result["statusCode"] == 400 and json.loads(result["body"])["error"] == "bad_request"
    assert messages(aws) == [] and audio_keys(aws) == []
    assert post({"audio": base64.b64encode(AUDIO).decode()}, user="BAD")["statusCode"] == 400


def test_a_stalled_transcription_is_failed_by_the_redelivery(aws):
    transcription_id = accepted(aws)
    # Taken long before the steps' clock (T0 + a few seconds): the worker that took it is gone.
    assert store.claim_transcription(USER, transcription_id, "2026-10-16T02:50:00.000Z") is not None
    worker.process_transcription(USER, transcription_id, Recorder().steps())
    item = store.get_transcription(USER, transcription_id)
    assert item["status"] == "failed" and item["failure"] == "transcribe_failed"


def test_a_transcription_is_read_consistently(aws, monkeypatch):
    from lib import clients
    transcription_id = accepted(aws)
    table = clients.table()
    seen = []
    original = table.get_item

    def spy(**params):
        seen.append(params)
        return original(**params)

    monkeypatch.setattr(table, "get_item", spy)
    get(transcription_id)
    assert seen and all(p.get("ConsistentRead") is True for p in seen)


def test_a_recording_that_cannot_be_queued_is_503_and_leaves_no_record_or_audio(aws, monkeypatch):
    # Nothing would ever take the record, so it is not left pending, and the recording is not kept (R4-04).
    def broken(**params):
        raise RuntimeError("queue unavailable")

    monkeypatch.setattr(transcriptions.clients.sqs(), "send_message", broken)
    result = post({"audio": base64.b64encode(AUDIO).decode()})
    assert result["statusCode"] == 503 and json.loads(result["body"]) == {"error": "unavailable"}
    assert [i["sk"] for i in aws.table.scan()["Items"] if i["sk"].startswith("TRANSCRIPTION#")] == []
    assert audio_keys(aws) == []
