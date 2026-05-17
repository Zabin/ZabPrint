"""Layer 7 PSG synth + event-encoder tests."""
import pytest

from audio.psg import (
    PsgEvent, SQ1, SQ2, WAVE, NOISE,
    OP_NOTE_ON, OP_NOTE_OFF, OP_VOL, OP_DUTY, OP_SWEEP, OP_WAVE_TABLE,
    note_to_period, square_samples, wave_samples, noise_samples,
    pack_event, pack_stream, parse_stream,
)


def _as_signed(b: int) -> int:
    return b - 256 if b >= 128 else b


# --- note_to_period: golden derived inline from GB Pan Docs ---
# Pan Docs square channel: f = 131072 / (2048 - n)   =>   n = 2048 - 131072/f
# A4 = 440 Hz:  n = 2048 - round(131072/440) = 2048 - 298 = 1750 = 0x6D6
def test_note_to_period_a4_golden():
    assert note_to_period(69) == 1750

# C4 = 261.6256 Hz: n = 2048 - round(131072/261.6256) = 2048 - 501 = 1547
def test_note_to_period_c4_golden():
    assert note_to_period(60) == 1547


# --- square_samples ---
def test_square_samples_length():
    out = square_samples(period=1750, duty=2, vol=15, n=500)
    assert len(out) == 500


def test_square_samples_signed_range():
    out = square_samples(period=1750, duty=2, vol=15, n=1000)
    for b in out:
        s = _as_signed(b)
        assert -128 <= s <= 127


def test_square_samples_zero_crossings_a4():
    # period 1750 -> ~440 Hz; 16384 Hz rate; 1 second of audio -> ~880 transitions
    rate = 16384
    n = rate  # 1 second
    out = square_samples(period=1750, duty=2, vol=15, n=n, rate=rate)
    signed = [_as_signed(b) for b in out]
    transitions = sum(1 for i in range(1, n) if (signed[i] > 0) != (signed[i-1] > 0))
    # 440 Hz square in 1 s ~= 880 transitions (high->low and low->high). Allow +/-2.
    assert abs(transitions - 880) <= 4


def test_square_samples_zero_vol_is_silent():
    out = square_samples(period=1750, duty=2, vol=0, n=500)
    assert out == bytes(500)


# --- wave_samples ---
def test_wave_samples_length():
    table = [8] * 32
    out = wave_samples(table, period=1750, vol=15, n=400)
    assert len(out) == 400


def test_wave_samples_table_extremes():
    # alternating 0/15 should produce alternating extreme samples
    table = [0, 15] * 16
    out = wave_samples(table, period=512, vol=15, n=2048)
    signed = [_as_signed(b) for b in out]
    assert min(signed) <= -64
    assert max(signed) >= 64


def test_wave_samples_midlevel_table_is_quiet():
    table = [7] * 32  # near-mid value
    out = wave_samples(table, period=1750, vol=15, n=500)
    signed = [_as_signed(b) for b in out]
    assert max(abs(s) for s in signed) <= 16


# --- noise_samples ---
def test_noise_samples_length():
    assert len(noise_samples(divider=4, vol=15, n=750)) == 750


def test_noise_samples_signed_range():
    out = noise_samples(divider=4, vol=15, n=1000)
    for b in out:
        s = _as_signed(b)
        assert -128 <= s <= 127


def test_noise_samples_nonzero_rms():
    out = noise_samples(divider=4, vol=15, n=2000)
    signed = [_as_signed(b) for b in out]
    rms = (sum(s * s for s in signed) / len(signed)) ** 0.5
    assert rms > 30  # actual noise, not silence


def test_noise_samples_silence_at_zero_vol():
    out = noise_samples(divider=4, vol=0, n=500)
    assert out == bytes(500)


# --- event packing ---
def test_pack_event_layout():
    ev = PsgEvent(frame=0x0123, channel=2, op=3, param=0x5A)
    b = pack_event(ev)
    assert len(b) == 4
    assert b[0] == 0x23           # frame_lo
    assert b[1] == 0x01           # frame_hi
    assert b[2] == (2 << 4) | 3   # (channel<<4) | op
    assert b[3] == 0x5A


def test_pack_stream_terminator():
    out = pack_stream([PsgEvent(0, 0, 0, 0)])
    assert out[-4:] == b'\xff\xff\xff\xff'
    assert len(out) == 4 + 4


def test_pack_stream_empty_is_only_terminator():
    assert pack_stream([]) == b'\xff\xff\xff\xff'


def test_parse_pack_round_trip():
    events = [
        PsgEvent(0,    SQ1,   OP_VOL,        12),
        PsgEvent(0,    SQ1,   OP_DUTY,       1),
        PsgEvent(0,    SQ1,   OP_NOTE_ON,    69),
        PsgEvent(60,   SQ1,   OP_NOTE_OFF,   0),
        PsgEvent(60,   WAVE,  OP_NOTE_ON,    48),
        PsgEvent(120,  NOISE, OP_SWEEP,      8),
        PsgEvent(900,  WAVE,  OP_NOTE_OFF,   0),
    ]
    blob = pack_stream(events)
    assert parse_stream(blob) == events
