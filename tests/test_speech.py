"""Tests for Polly SSML and storing the answer audio."""
import io

import pytest

from lib import speech


def test_ssml_is_escaped_and_louder():
    ssml = speech.build_ssml("A&B <C>", 6)
    assert ssml == '<speak><amazon:effect name="drc"><prosody volume="+6dB">A&amp;B &lt;C&gt;</prosody></amazon:effect></speak>'


def test_ssml_uses_the_chosen_volume():
    assert '<prosody volume="+0dB">' in speech.build_ssml("x", 0)
    assert '<prosody volume="+12dB">' in speech.build_ssml("x", 12)


class FakePolly:
    def __init__(self, error=None):
        self.error, self.calls = error, []

    def synthesize_speech(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return {"AudioStream": io.BytesIO(b"mp3-bytes")}


class FakeS3:
    def __init__(self):
        self.puts = []

    def put_object(self, **kwargs):
        self.puts.append(kwargs)


def test_synthesize_stores_mp3(monkeypatch):
    monkeypatch.setenv("POLLY_VOICE_ID", "Kazuha")
    polly, s3 = FakePolly(), FakeS3()
    key = speech.synthesize("abc", "晴れです。", 9, polly=polly, s3=s3)
    assert key == "answers/abc.mp3"
    call = polly.calls[0]
    assert '<prosody volume="+9dB">' in call["Text"]
    assert (call["TextType"], call["Engine"], call["VoiceId"], call["OutputFormat"], call["LanguageCode"]) == ("ssml", "neural", "Kazuha", "mp3", "ja-JP")
    assert s3.puts[0]["Bucket"] == "test-audio" and s3.puts[0]["Key"] == key and s3.puts[0]["Body"] == b"mp3-bytes"
    assert s3.puts[0]["ContentType"] == "audio/mpeg"


def test_polly_failure_raises():
    with pytest.raises(RuntimeError):
        speech.synthesize("abc", "x", 6, polly=FakePolly(RuntimeError("down")), s3=FakeS3())
