"""PSG channel synthesis + event-stream encoder.

The synth helpers (`square_samples`, `wave_samples`, `noise_samples`) produce
8-bit signed PCM at a given sample rate so the WAV preview matches what the
GBA will play. Periods follow GB Pan Docs conventions:

- Square channels: f = 131072 / (2048 - n)   (n is the 11-bit period register).
- Wave channel:    f = 65536  / (2048 - n)   (full 32-sample cycle).
- Noise channel:   LFSR with 15-bit taps; clocked once every `divider` samples.

The event encoder packs `(frame, channel, op, param)` into 4 bytes; streams end
with the terminator 0xFFFFFFFF. The runtime ARM driver in `src/sound.s` will
consume these streams one row per VBlank.
"""
from __future__ import annotations

import math
from typing import NamedTuple

# --- channel ids ---
SQ1, SQ2, WAVE, NOISE = 0, 1, 2, 3

# --- op codes ---
OP_NOTE_ON     = 0
OP_NOTE_OFF    = 1
OP_VOL         = 2
OP_DUTY        = 3
OP_SWEEP       = 4
OP_WAVE_TABLE  = 5

DEFAULT_RATE = 16384


class PsgEvent(NamedTuple):
    frame: int
    channel: int
    op: int
    param: int


def note_to_period(midi: int) -> int:
    """11-bit period register value for the GB square channel.

    f = 131072 / (2048 - n)  =>  n = 2048 - round(131072/f)
    """
    freq = 440.0 * (2.0 ** ((midi - 69) / 12.0))
    n = 2048 - round(131072.0 / freq)
    return max(0, min(2047, n))


def _clip_s8(v: int) -> int:
    if v > 127:
        return 127
    if v < -128:
        return -128
    return v


def square_samples(period: int, duty: int, vol: int,
                   n: int, rate: int = DEFAULT_RATE) -> bytes:
    """8-bit signed square wave.

    period: 0..2047 (GB-style); duty: 0..3 (12.5/25/50/75%); vol: 0..15.
    """
    if vol <= 0 or period >= 2048 or n <= 0:
        return bytes(max(0, n))
    freq = 131072.0 / (2048 - period)
    duty_pct = (0.125, 0.25, 0.50, 0.75)[duty & 3]
    amp = (vol * 127) // 15
    out = bytearray(n)
    for i in range(n):
        phase = (i * freq / rate) % 1.0
        s = amp if phase < duty_pct else -amp
        out[i] = s & 0xFF
    return bytes(out)


def wave_samples(table, period: int, vol: int,
                 n: int, rate: int = DEFAULT_RATE) -> bytes:
    """8-bit signed PCM from a 32-step, 4-bit wave table.

    Wave-channel pitch: f = 65536 / (2048 - period). Each output sample picks
    one of the 32 table entries; the entry is centered (table[k]-7) and scaled
    by vol/15. Values clamp into signed 8-bit range.
    """
    if vol <= 0 or period >= 2048 or n <= 0:
        return bytes(max(0, n))
    if len(table) < 32:
        raise ValueError("wave table must have at least 32 entries")
    cycle_freq = 65536.0 / (2048 - period)
    samples_per_cycle = rate / cycle_freq
    out = bytearray(n)
    for i in range(n):
        idx = int((i / samples_per_cycle * 32)) % 32
        v = table[idx] & 0xF
        s = ((v - 7) * vol * 16) // 15
        out[i] = _clip_s8(s) & 0xFF
    return bytes(out)


def noise_samples(divider: int, vol: int,
                  n: int, rate: int = DEFAULT_RATE) -> bytes:
    """15-bit LFSR noise. `divider` controls how often the LFSR advances.

    GB noise XORs bits 0 and 1; that bit becomes the new bit 14 (output is
    inverted bit 0). Output amplitude scales linearly with `vol`.
    """
    if vol <= 0 or n <= 0:
        return bytes(max(0, n))
    divider = max(1, divider)
    amp = (vol * 127) // 15
    out = bytearray(n)
    lfsr = 0x7FFF
    counter = 0
    bit = 0
    for i in range(n):
        if counter <= 0:
            new_bit = ((lfsr & 1) ^ ((lfsr >> 1) & 1)) & 1
            lfsr = (lfsr >> 1) | (new_bit << 14)
            bit = (~lfsr) & 1
            counter = divider
        counter -= 1
        s = amp if bit else -amp
        out[i] = s & 0xFF
    return bytes(out)


# --- event packing ---

def pack_event(ev: PsgEvent) -> bytes:
    """4-byte packed event: [frame_lo, frame_hi, (channel<<4)|op, param]."""
    return bytes([
        ev.frame & 0xFF,
        (ev.frame >> 8) & 0xFF,
        ((ev.channel & 0xF) << 4) | (ev.op & 0xF),
        ev.param & 0xFF,
    ])


_TERMINATOR = b'\xff\xff\xff\xff'


def pack_stream(events) -> bytes:
    """Concatenated 4-byte events + 0xFFFFFFFF terminator."""
    return b''.join(pack_event(e) for e in events) + _TERMINATOR


def parse_stream(blob: bytes) -> list[PsgEvent]:
    """Inverse of `pack_stream` (stops at the terminator)."""
    out = []
    i = 0
    while i + 4 <= len(blob):
        chunk = blob[i:i + 4]
        if chunk == _TERMINATOR:
            break
        frame = chunk[0] | (chunk[1] << 8)
        ch = (chunk[2] >> 4) & 0xF
        op = chunk[2] & 0xF
        param = chunk[3]
        out.append(PsgEvent(frame, ch, op, param))
        i += 4
    return out
