"""Raise the answer audio beyond what Polly's prosody allows (it stops at +6 dB) without hard clipping."""
from __future__ import annotations

import array
import math
import struct

SAMPLE_RATE = 16000
# Above this share of full scale, peaks are bent smoothly towards full scale instead of being cut off.
KNEE = 0.5
FULL_SCALE = 32767


def louder(pcm: bytes, gain_db: int) -> bytes:
    """16-bit mono PCM raised by gain_db, with a soft limiter so loud parts stay within range."""
    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) - len(pcm) % 2])
    gain = 10 ** (gain_db / 20)
    out = array.array("h", bytes(len(samples) * 2))
    for i, sample in enumerate(samples):
        level = sample / 32768 * gain
        magnitude = abs(level)
        if magnitude > KNEE:
            magnitude = KNEE + (1 - KNEE) * math.tanh((magnitude - KNEE) / (1 - KNEE))
        out[i] = max(-FULL_SCALE, min(FULL_SCALE, round(math.copysign(magnitude, level) * 32768)))
    return out.tobytes()


def wav(pcm: bytes, sample_rate: int = SAMPLE_RATE) -> bytes:
    """A RIFF/WAVE file around 16-bit mono PCM."""
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + len(pcm), b"WAVE", b"fmt ", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16, b"data", len(pcm),
    )
    return header + pcm
