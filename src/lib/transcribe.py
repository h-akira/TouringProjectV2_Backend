"""Streaming transcription of a finished PCM recording (adr/0002: sent all at once, not paced)."""
from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator

from amazon_transcribe.client import TranscribeStreamingClient
from amazon_transcribe.handlers import TranscriptResultStreamHandler
from amazon_transcribe.model import TranscriptEvent

CHUNK_BYTES = 8 * 1024
SAMPLE_RATE = 16000


def chunks(audio: bytes) -> Iterator[bytes]:
    for start in range(0, len(audio), CHUNK_BYTES):
        yield audio[start:start + CHUNK_BYTES]


def join_finals(finals: list[str]) -> str:
    return "".join(finals).strip()


class _Collector(TranscriptResultStreamHandler):
    def __init__(self, stream) -> None:
        super().__init__(stream)
        self.finals: list[str] = []

    async def handle_transcript_event(self, transcript_event: TranscriptEvent) -> None:
        for result in transcript_event.transcript.results:
            if not result.is_partial and result.alternatives:
                self.finals.append(result.alternatives[0].transcript)


async def _transcribe(audio: bytes) -> str:
    client = TranscribeStreamingClient(region=os.environ.get("AWS_REGION", "ap-northeast-1"))
    stream = await client.start_stream_transcription(
        language_code="ja-JP", media_sample_rate_hz=SAMPLE_RATE, media_encoding="pcm"
    )
    collector = _Collector(stream.output_stream)

    async def send() -> None:
        for chunk in chunks(audio):
            await stream.input_stream.send_audio_event(audio_chunk=chunk)
        await stream.input_stream.end_stream()

    await asyncio.gather(send(), collector.handle_events())
    return join_finals(collector.finals)


def transcribe_pcm(audio: bytes) -> str:
    return asyncio.run(_transcribe(audio))
