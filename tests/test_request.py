"""Tests for request validation."""
import base64
import json

import pytest

from lib.request import MAX_AUDIO_BYTES, MIN_AUDIO_BYTES, BadRequest, parse_ask, user_name

CID = "0b8e7c1e-3f1a-4f5e-9a51-2a0b2c6f7d10"


def event(body=None, headers=None, raw=None):
    return {"headers": headers if headers is not None else {"x-user-name": "rider01"}, "body": raw if raw is not None else json.dumps(body)}


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


@pytest.mark.parametrize("name", ["abc", "rider01", "a" * 20])
def test_user_name_ok(name):
    assert user_name(event({}, {"X-User-Name": name})) == name


@pytest.mark.parametrize("name", [None, "ab", "a" * 21, "Rider", "rider_01", "ライダー"])
def test_user_name_bad(name):
    headers = {} if name is None else {"x-user-name": name}
    with pytest.raises(BadRequest):
        user_name(event({}, headers))


def test_text_question():
    ask = parse_ask(event({"text": "  富士山の高さは？ "}))
    assert ask.text == "富士山の高さは？" and ask.audio is None and ask.conversation_id is None


def test_audio_question_with_location_and_sample():
    audio = b"\x01\x00" * (MIN_AUDIO_BYTES // 2)
    ask = parse_ask(event({
        "audio": b64(audio),
        "location": {"latitude": 35.6812, "longitude": 139.7671},
        "headingSample": {"latitude": 35.6807, "longitude": 139.7671, "at": "2026-10-16T12:00:00+09:00"},
        "conversationId": CID,
    }))
    assert ask.audio == audio
    assert ask.location == {"latitude": 35.6812, "longitude": 139.7671}
    assert ask.heading_sample == {"latitude": 35.6807, "longitude": 139.7671, "at": "2026-10-16T03:00:00.000Z"}
    assert ask.conversation_id == CID


@pytest.mark.parametrize("body", [{}, {"audio": "AAAA", "text": "x"}])
def test_exactly_one_of_audio_and_text(body):
    with pytest.raises(BadRequest, match="exactly one"):
        parse_ask(event(body))


@pytest.mark.parametrize("audio", [b"\x00" * (MIN_AUDIO_BYTES - 2), b"\x00" * (MAX_AUDIO_BYTES + 2), b"\x00" * (MIN_AUDIO_BYTES + 1)])
def test_audio_length_and_alignment(audio):
    with pytest.raises(BadRequest):
        parse_ask(event({"audio": b64(audio)}))


def test_audio_not_base64():
    with pytest.raises(BadRequest, match="base64"):
        parse_ask(event({"audio": "not base64!!"}))


@pytest.mark.parametrize("text", ["", "   ", "あ" * 501, 123])
def test_text_bad(text):
    with pytest.raises(BadRequest):
        parse_ask(event({"text": text}))


@pytest.mark.parametrize("raw", ["not json", "[]", ""])
def test_body_must_be_json_object(raw):
    with pytest.raises(BadRequest):
        parse_ask(event(raw=raw))


@pytest.mark.parametrize("cid", ["abc", CID.upper(), 5])
def test_conversation_id_must_be_lowercase_uuid(cid):
    with pytest.raises(BadRequest, match="conversationId"):
        parse_ask(event({"text": "Q", "conversationId": cid}))


@pytest.mark.parametrize(
    "location",
    [{"latitude": "35", "longitude": 139.0}, {"latitude": True, "longitude": 139.0}, {"latitude": 95.0, "longitude": 139.0}, "x"],
)
def test_broken_location_is_dropped(location):
    assert parse_ask(event({"text": "Q", "location": location})).location is None


@pytest.mark.parametrize("sample", [{"latitude": 35.0, "longitude": 139.0}, {"latitude": 35.0, "longitude": 139.0, "at": "yesterday"}, {"latitude": 35.0, "longitude": 139.0, "at": "2026-10-16T12:00:00"}])
def test_broken_heading_sample_is_dropped(sample):
    assert parse_ask(event({"text": "Q", "headingSample": sample})).heading_sample is None


def test_base64_encoded_body_is_decoded():
    raw = base64.b64encode(json.dumps({"text": "Q"}).encode()).decode()
    ask = parse_ask({"headers": {"x-user-name": "rider01"}, "body": raw, "isBase64Encoded": True})
    assert ask.text == "Q"


def test_volume_defaults_to_six():
    assert parse_ask(event({"text": "Q"})).volume_db == 6


@pytest.mark.parametrize("volume", [0, 3, 6, 9, 12])
def test_volume_choices(volume):
    assert parse_ask(event({"text": "Q", "volumeDb": volume})).volume_db == volume


@pytest.mark.parametrize("volume", [-3, 1, 15, "6", None, True, 6.5])
def test_volume_bad(volume):
    with pytest.raises(BadRequest):
        parse_ask(event({"text": "Q", "volumeDb": volume}))
