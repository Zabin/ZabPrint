"""Layer 7 PCM synth + WAV round-trip tests."""
import tempfile
from pathlib import Path

import pytest

from audio.pcm import (
    SAMPLE_RATE,
    thrust_hiss, grapple_click, grapple_reel,
    dew_whine, dew_impact, ui_beep,
    success_sting, fail_sting,
)
from audio.wav import write_wav_u8, read_wav_u8


def _as_signed(b: int) -> int:
    return b - 256 if b >= 128 else b


SFX_LENGTHS = {
    'thrust':         int(SAMPLE_RATE * 0.5),
    'grapple_click':  int(SAMPLE_RATE * 0.15),
    'grapple_reel':   int(SAMPLE_RATE * 1.5),
    'dew_whine':      int(SAMPLE_RATE * 0.4),
    'dew_impact':     int(SAMPLE_RATE * 0.2),
    'ui_beep':        int(SAMPLE_RATE * 0.1),
}


def test_thrust_hiss_length():
    assert len(thrust_hiss(SFX_LENGTHS['thrust'])) == SFX_LENGTHS['thrust']

def test_grapple_click_length():
    assert len(grapple_click(SFX_LENGTHS['grapple_click'])) == SFX_LENGTHS['grapple_click']

def test_grapple_reel_length():
    assert len(grapple_reel(SFX_LENGTHS['grapple_reel'])) == SFX_LENGTHS['grapple_reel']

def test_dew_whine_length():
    assert len(dew_whine(SFX_LENGTHS['dew_whine'])) == SFX_LENGTHS['dew_whine']

def test_dew_impact_length():
    assert len(dew_impact(SFX_LENGTHS['dew_impact'])) == SFX_LENGTHS['dew_impact']

def test_ui_beep_length():
    assert len(ui_beep(72, SFX_LENGTHS['ui_beep'])) == SFX_LENGTHS['ui_beep']


@pytest.mark.parametrize("synth,n", [
    (lambda n: thrust_hiss(n),         SFX_LENGTHS['thrust']),
    (lambda n: grapple_click(n),       SFX_LENGTHS['grapple_click']),
    (lambda n: grapple_reel(n),        SFX_LENGTHS['grapple_reel']),
    (lambda n: dew_whine(n),           SFX_LENGTHS['dew_whine']),
    (lambda n: dew_impact(n),          SFX_LENGTHS['dew_impact']),
    (lambda n: ui_beep(72, n),         SFX_LENGTHS['ui_beep']),
])
def test_sfx_signed_byte_range(synth, n):
    out = synth(n)
    assert len(out) == n
    for b in out:
        s = _as_signed(b)
        assert -128 <= s <= 127


def test_success_sting_nonempty_and_in_range():
    out = success_sting()
    assert len(out) > 0
    for b in out:
        assert -128 <= _as_signed(b) <= 127


def test_fail_sting_nonempty_and_in_range():
    out = fail_sting()
    assert len(out) > 0
    for b in out:
        assert -128 <= _as_signed(b) <= 127


def test_ui_beep_pitch_zero_crossings():
    # midi 72 = C5 = 523.25 Hz; in 0.5 s -> ~261.6 cycles
    # Each square-wave cycle flips sign twice -> ~523 sign flips.
    n = SAMPLE_RATE // 2
    out = ui_beep(72, n)
    signed = [_as_signed(b) for b in out]
    crossings = sum(1 for i in range(1, n) if (signed[i] > 0) != (signed[i - 1] > 0))
    assert abs(crossings - 523) <= 6


def test_wav_round_trip(tmp_path):
    # signed samples spanning the full range
    samples = bytes(b & 0xFF for b in [-128, -64, -1, 0, 1, 64, 127])
    p = tmp_path / "rt.wav"
    write_wav_u8(p, samples, rate=SAMPLE_RATE)
    back = read_wav_u8(p)
    assert back == samples


def test_wav_8bit_header(tmp_path):
    import wave
    p = tmp_path / "h.wav"
    write_wav_u8(p, bytes(100), rate=16384)
    with wave.open(str(p), 'rb') as w:
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 1
        assert w.getframerate() == 16384
        assert w.getnframes() == 100
