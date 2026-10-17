"""Answer audio: Polly neural voice with compression, raised by the rider's chosen amount, stored in S3 as WAV."""
from __future__ import annotations

import os
from typing import Any
from xml.sax.saxutils import escape

from lib import clients, loudness


def build_ssml(text: str) -> str:
    # DRC helps the answer stand out against wind and navigation prompts. The volume is raised afterwards:
    # Polly's prosody volume stops at +6 dB.
    return f'<speak><amazon:effect name="drc">{escape(text)}</amazon:effect></speak>'


def answer_key(ask_id: str) -> str:
    return f"answers/{ask_id}.wav"


def synthesize(ask_id: str, text: str, volume_db: int, polly: Any = None, s3: Any = None) -> str:
    response = (polly or clients.polly()).synthesize_speech(
        Text=build_ssml(text),
        TextType="ssml",
        OutputFormat="pcm",
        SampleRate=str(loudness.SAMPLE_RATE),
        VoiceId=os.environ.get("POLLY_VOICE_ID", "Kazuha"),
        Engine="neural",
        LanguageCode="ja-JP",
    )
    key = answer_key(ask_id)
    (s3 or clients.s3()).put_object(
        Bucket=os.environ["AUDIO_BUCKET"], Key=key, Body=loudness.wav(loudness.louder(response["AudioStream"].read(), volume_db)),
        ContentType="audio/wav",
    )
    return key
