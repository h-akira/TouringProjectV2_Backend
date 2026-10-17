"""Tests for raising the answer audio with a soft limiter."""
import array
import struct

from lib import loudness


def pcm(*samples: int) -> bytes:
    return array.array("h", samples).tobytes()


def samples(data: bytes) -> list[int]:
    out = array.array("h")
    out.frombytes(data)
    return list(out)


def test_zero_gain_keeps_quiet_samples():
    assert samples(loudness.louder(pcm(0, 1000, -1000), 0)) == [0, 1000, -1000]


def test_quiet_samples_get_the_full_gain():
    # +6 dB is about twice the amplitude; 1000 stays below the limiter's knee.
    assert samples(loudness.louder(pcm(1000, -1000), 6)) == [1995, -1995]


def test_loud_samples_are_limited_not_clipped():
    out = samples(loudness.louder(pcm(30000, -30000, 32767, -32768), 12))
    assert all(-32767 <= s <= 32767 for s in out)
    assert out[0] > 30000 and out[1] < -30000


def test_limiting_never_reverses_levels():
    # The loudest ones may meet at full scale, but a louder input never comes out quieter.
    out = samples(loudness.louder(pcm(10000, 15000, 20000, 25000, 30000), 12))
    assert out == sorted(out)


def test_levels_around_the_knee_stay_apart():
    out = samples(loudness.louder(pcm(4000, 6000, 8000, 10000, 12000), 12))
    assert out == sorted(out) and len(set(out)) == len(out)


def test_odd_trailing_byte_is_dropped():
    assert len(loudness.louder(pcm(100) + b"\x01", 0)) == 2


def test_wav_header_for_16khz_mono():
    body = loudness.wav(pcm(1, 2, 3))
    riff, size, wave, fmt, fmt_size, kind, channels, rate, byte_rate, align, bits, data, data_size = struct.unpack(
        "<4sI4s4sIHHIIHH4sI", body[:44]
    )
    assert (riff, wave, fmt, data) == (b"RIFF", b"WAVE", b"fmt ", b"data")
    assert (size, fmt_size, kind, channels, rate, byte_rate, align, bits, data_size) == (36 + 6, 16, 1, 1, 16000, 32000, 2, 16, 6)
    assert body[44:] == pcm(1, 2, 3)
