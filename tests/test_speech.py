"""Tests for Polly SSML and storing the answer audio."""
import array
import io

import pytest

from lib import speech


def test_ssml_is_escaped_and_compressed():
    ssml = speech.build_ssml("A&B <C>")
    assert ssml == '<speak><amazon:effect name="drc">A&amp;B &lt;C&gt;</amazon:effect></speak>'


class FakePolly:
    def __init__(self, error=None):
        self.error, self.calls = error, []

    def synthesize_speech(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return {"AudioStream": io.BytesIO(array.array("h", [1000, -1000]).tobytes())}


class FakeS3:
    def __init__(self):
        self.puts = []

    def put_object(self, **kwargs):
        self.puts.append(kwargs)


def test_synthesize_stores_louder_wav(monkeypatch):
    monkeypatch.setenv("POLLY_VOICE_ID", "Kazuha")
    polly, s3 = FakePolly(), FakeS3()
    key = speech.synthesize("abc", "晴れです。", 9, polly=polly, s3=s3)
    assert key == "answers/abc.wav"
    call = polly.calls[0]
    assert (call["TextType"], call["Engine"], call["VoiceId"], call["OutputFormat"], call["SampleRate"], call["LanguageCode"]) == (
        "ssml", "neural", "Kazuha", "pcm", "16000", "ja-JP")
    body = s3.puts[0]["Body"]
    assert s3.puts[0]["Bucket"] == "test-audio" and s3.puts[0]["Key"] == key and s3.puts[0]["ContentType"] == "audio/wav"
    # +9 dB on a quiet sample: about 2.8 times, inside a WAV file.
    assert body[:4] == b"RIFF" and array.array("h", body[44:]).tolist() == [2818, -2818]


def test_polly_failure_raises():
    with pytest.raises(RuntimeError):
        speech.synthesize("abc", "x", 6, polly=FakePolly(RuntimeError("down")), s3=FakeS3())
