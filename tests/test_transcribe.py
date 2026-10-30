"""Tests for the transcription helpers (the streaming call itself is checked by the smoke test)."""
from lib import transcribe


def test_join_finals():
    assert transcribe.join_finals(["右手に見える", "山は何？ "]) == "右手に見える山は何？"
    assert transcribe.join_finals([]) == ""
    assert transcribe.join_finals(["  "]) == ""


def test_chunks_cover_the_audio():
    audio = bytes(range(256)) * 100
    chunks = list(transcribe.chunks(audio))
    assert b"".join(chunks) == audio
    assert all(len(c) <= transcribe.CHUNK_BYTES for c in chunks)


def test_a_transcription_that_takes_too_long_is_cut(monkeypatch):
    import asyncio

    import pytest

    async def slow(audio):
        await asyncio.sleep(5)
        return "never"

    monkeypatch.setattr(transcribe, "_transcribe", slow)
    with pytest.raises(TimeoutError):
        transcribe.transcribe_pcm(b"\x00\x00", timeout=0.05)
