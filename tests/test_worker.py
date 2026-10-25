"""Tests for the worker pipeline with stubbed steps and moto storage."""
import json
from datetime import datetime, timedelta, timezone

from handlers import worker
from handlers.common import iso
from lib import store
from lib.agent import AgentError, AgentReply, parse_events, session_id

USER, ASK, CID = "rider01", "11111111-1111-4111-8111-111111111111", "33333333-3333-4333-8333-333333333333"
T0 = datetime(2026, 10, 16, 3, 0, tzinfo=timezone.utc)
HERE = {"latitude": 35.6812, "longitude": 139.7671}
SOUTH = {"latitude": 35.68066, "longitude": 139.7671, "at": "2026-10-16T02:59:50.000Z"}


class Recorder:
    def __init__(self, transcript="右手の山は？", answer="愛鷹山です。", agent_error=None, tts_error=None, stt_error=None):
        self.calls = []
        self.transcript, self.answer = transcript, answer
        self.agent_error, self.tts_error, self.stt_error = agent_error, tts_error, stt_error
        self.clock = T0

    def now(self):
        self.clock += timedelta(seconds=1)
        return self.clock

    def transcribe(self, audio):
        self.calls.append(("transcribe", len(audio)))
        if self.stt_error:
            raise self.stt_error
        return self.transcript

    def describe_location(self, lat, lon):
        self.calls.append(("address", lat, lon))
        return "東京都千代田区丸の内"

    def invoke_agent(self, prompt, location, session_id):
        self.calls.append(("agent", prompt, location, session_id))
        if self.agent_error:
            raise self.agent_error
        return AgentReply(answer=self.answer, usage={"inputTokens": 5}, model_id="m", tools=["nearby_places"], first_event_at=None)

    def synthesize(self, ask_id, text, volume_db):
        self.calls.append(("tts", ask_id, text, volume_db))
        if self.tts_error:
            raise self.tts_error
        return f"answers/{ask_id}.mp3"

    def steps(self):
        return worker.Steps(self.transcribe, self.describe_location, self.invoke_agent, self.synthesize, self.now)


def put(aws, audio=True, **extra):
    item = {**store.ask_key(USER, ASK), "askId": ASK, "userName": USER, "conversationId": CID,
            "conversationStartedAt": iso(T0 - timedelta(minutes=10)), "status": "pending", "receivedAt": iso(T0),
            "inputType": "audio" if audio else "text", "location": HERE, "headingSample": SOUTH, "timings": {"receivedAt": iso(T0)}, **extra}
    if audio:
        item["audioKey"] = f"audio/{ASK}.pcm"
        aws.s3.put_object(Bucket=aws.bucket, Key=item["audioKey"], Body=b"\x00\x00" * 8000)
    else:
        item.setdefault("question", "富士山の高さは？")
    store.create_ask(item)


def kinds(rec):
    return [c[0] for c in rec.calls]


def audio_exists(aws):
    return aws.s3.list_objects_v2(Bucket=aws.bucket, Prefix="audio/").get("KeyCount", 0) > 0


def test_audio_happy_path(aws):
    put(aws)
    rec = Recorder()
    worker.process(USER, ASK, rec.steps())
    item = store.get_ask(USER, ASK)
    assert kinds(rec) == ["transcribe", "address", "agent", "tts"]
    assert item["status"] == "completed" and item["transcript"] == "右手の山は？" and item["answer"] == "愛鷹山です。"
    assert item["answerAudioKey"] == f"answers/{ASK}.mp3" and item["usage"] == {"inputTokens": 5} and item["modelId"] == "m"
    assert item["address"] == "東京都千代田区丸の内" and round(item["headingDegrees"]) == 0
    assert set(item["timings"]) >= {"receivedAt", "transcribedAt", "factsAt", "agentDoneAt", "synthesizedAt"}
    assert not audio_exists(aws)


def test_agent_gets_facts_location_and_session(aws):
    put(aws)
    rec = Recorder()
    worker.process(USER, ASK, rec.steps())
    _, prompt, location, session = next(c for c in rec.calls if c[0] == "agent")
    assert "現在地の住所: 東京都千代田区丸の内" in prompt
    assert "会話の最初の質問から約10分後" in prompt
    assert prompt.endswith("質問: 右手の山は？")
    assert location["headingDegrees"] == 0.0 and session == session_id(USER, CID)


def test_the_apps_heading_wins_over_the_sample(aws):
    # The sample says north; the app's own heading (adr/0013) is the one used.
    put(aws, headingDegrees=90.0)
    rec = Recorder()
    worker.process(USER, ASK, rec.steps())
    _, prompt, location, _ = next(c for c in rec.calls if c[0] == "agent")
    assert "真北から90度" in prompt and location["headingDegrees"] == 90.0
    assert store.get_ask(USER, ASK)["headingDegrees"] == 90.0


def test_almost_north_is_kept_as_zero(aws):
    put(aws, headingDegrees=359.96, headingSample=None)
    worker.process(USER, ASK, Recorder().steps())
    assert store.get_ask(USER, ASK)["headingDegrees"] == 0


def test_text_question_skips_transcription(aws):
    put(aws, audio=False)
    rec = Recorder()
    worker.process(USER, ASK, rec.steps())
    item = store.get_ask(USER, ASK)
    assert kinds(rec) == ["address", "agent", "tts"]
    assert item["status"] == "completed" and "transcript" not in item and "transcribedAt" not in item["timings"]


def test_no_speech(aws):
    put(aws)
    rec = Recorder(transcript="")
    worker.process(USER, ASK, rec.steps())
    item = store.get_ask(USER, ASK)
    assert item["status"] == "failed" and item["error"] == "no_speech" and item["transcript"] == ""
    assert kinds(rec) == ["transcribe"]
    assert not audio_exists(aws)


def test_transcribe_failure_deletes_audio(aws):
    put(aws)
    rec = Recorder(stt_error=RuntimeError("stream broke"))
    worker.process(USER, ASK, rec.steps())
    item = store.get_ask(USER, ASK)
    assert item["status"] == "failed" and item["error"] == "transcribe_failed"
    assert not audio_exists(aws)


def test_agent_failure(aws):
    put(aws)
    rec = Recorder(agent_error=AgentError("agent_failed"))
    worker.process(USER, ASK, rec.steps())
    item = store.get_ask(USER, ASK)
    assert item["status"] == "failed" and item["error"] == "agent_failed" and item["transcript"] == "右手の山は？"
    assert "tts" not in kinds(rec)


def test_the_agent_error_log_has_the_code_only(aws, capsys):
    # The agent's message may carry part of the question; only its code is logged (Backend #8).
    put(aws)
    try:
        parse_events([b'data: {"type": "error", "code": "agent_failed", "message": "\\u53f3\\u624b"}'])
    except AgentError as error:
        raised = error
    worker.process(USER, ASK, Recorder(agent_error=raised).steps())
    logged = [json.loads(line) for line in capsys.readouterr().out.splitlines() if '"agent_error"' in line]
    assert logged and logged[0]["error"] == "agent_failed"


def test_tts_failure_keeps_answer(aws):
    put(aws)
    rec = Recorder(tts_error=RuntimeError("polly down"))
    worker.process(USER, ASK, rec.steps())
    item = store.get_ask(USER, ASK)
    assert item["status"] == "failed" and item["error"] == "tts_failed" and item["answer"] == "愛鷹山です。"
    assert "answerAudioKey" not in item


def test_no_location_means_no_address_lookup(aws):
    put(aws, audio=False, location=None, headingSample=None)
    rec = Recorder()
    worker.process(USER, ASK, rec.steps())
    _, prompt, location, _ = next(c for c in rec.calls if c[0] == "agent")
    assert "address" not in kinds(rec) and location is None and "現在地: 不明" in prompt


def test_second_delivery_does_nothing(aws):
    put(aws, audio=False)
    rec = Recorder()
    worker.process(USER, ASK, rec.steps())
    worker.process(USER, ASK, rec.steps())
    assert kinds(rec).count("agent") == 1 and kinds(rec).count("tts") == 1


def test_handler_reads_sqs_records(aws, monkeypatch):
    put(aws, audio=False)
    rec = Recorder()
    monkeypatch.setattr(worker, "DEFAULT_STEPS", rec.steps())
    worker.handler({"Records": [{"body": f'{{"userName": "{USER}", "askId": "{ASK}"}}'}]}, None)
    assert store.get_ask(USER, ASK)["status"] == "completed"


def test_unexpected_agent_exception_marks_failed(aws):
    put(aws, audio=False)
    rec = Recorder(agent_error=RuntimeError("stream reset"))
    worker.process(USER, ASK, rec.steps())
    item = store.get_ask(USER, ASK)
    assert item["status"] == "failed" and item["error"] == "agent_failed"


def test_answer_audio_uses_the_stored_volume(aws):
    put(aws, volumeDb=3)
    rec = Recorder()
    worker.process(USER, ASK, rec.steps())
    assert next(c for c in rec.calls if c[0] == "tts")[3] == 3


def test_asks_without_volume_use_the_default(aws):
    put(aws)
    rec = Recorder()
    worker.process(USER, ASK, rec.steps())
    assert next(c for c in rec.calls if c[0] == "tts")[3] == 6


def test_an_ask_deleted_while_it_is_answered_is_not_written_back(aws):
    put(aws, audio=False)
    rec = Recorder()
    agent = rec.invoke_agent

    def delete_then_answer(prompt, location, session):
        # The rider deletes the ask while the agent is answering (slice 3 spec §6.3).
        aws.table.delete_item(Key=store.ask_key(USER, ASK))
        return agent(prompt, location, session)

    rec.invoke_agent = delete_then_answer
    worker.process(USER, ASK, rec.steps())
    assert store.get_ask(USER, ASK) is None


def test_an_ask_deleted_before_a_crash_is_not_written_back_as_failed(aws):
    # The catch-all in process marks a crashed ask failed; it must not bring back an ask deleted meanwhile (Backend #19).
    put(aws, audio=False)
    rec = Recorder()

    def crash(lat, lon):
        store.delete_ask(USER, ASK, iso(T0))
        raise RuntimeError("unexpected")

    rec.describe_location = crash
    worker.process(USER, ASK, rec.steps())
    assert store.get_ask(USER, ASK) is None
