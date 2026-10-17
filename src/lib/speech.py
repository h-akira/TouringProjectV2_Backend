"""Answer audio: Polly neural voice with compression and the rider's volume boost, stored in S3."""
from __future__ import annotations

import os
from typing import Any
from xml.sax.saxutils import escape

from lib import clients


def build_ssml(text: str, volume_db: int) -> str:
    # DRC and a dB boost help the answer stand out against wind and navigation prompts.
    return f'<speak><amazon:effect name="drc"><prosody volume="+{volume_db}dB">{escape(text)}</prosody></amazon:effect></speak>'


def answer_key(ask_id: str) -> str:
    return f"answers/{ask_id}.mp3"


def synthesize(ask_id: str, text: str, volume_db: int, polly: Any = None, s3: Any = None) -> str:
    response = (polly or clients.polly()).synthesize_speech(
        Text=build_ssml(text, volume_db),
        TextType="ssml",
        OutputFormat="mp3",
        VoiceId=os.environ.get("POLLY_VOICE_ID", "Kazuha"),
        Engine="neural",
        LanguageCode="ja-JP",
    )
    key = answer_key(ask_id)
    (s3 or clients.s3()).put_object(
        Bucket=os.environ["AUDIO_BUCKET"], Key=key, Body=response["AudioStream"].read(), ContentType="audio/mpeg"
    )
    return key
