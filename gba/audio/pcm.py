"""8-bit signed PCM sfx synth.

Every helper returns `bytes` of signed-8-bit PCM at SAMPLE_RATE. Bytes are
the unsigned-byte representation of signed integers (`s & 0xFF`); interpret
each via `b - 256 if b >= 128 else b`.
"""
from __future__ import annotations

import math
import random

SAMPLE_RATE = 16384


def _clip_s8(v: float) -> int:
    iv = int(v)
    if iv > 127:
        return 127
    if iv < -128:
        return -128
    return iv


def _to_bytes(signed: list[int]) -> bytes:
    return bytes(s & 0xFF for s in signed)


def _attack_release(i: int, n: int, attack_frac: float = 0.05,
                    release_frac: float = 0.20) -> float:
    """Linear A/R envelope in [0, 1]. Sustain in between."""
    a = max(1, int(n * attack_frac))
    r = max(1, int(n * release_frac))
    if i < a:
        return i / a
    if i > n - r:
        return max(0.0, (n - i) / r)
    return 1.0


def thrust_hiss(n: int, *, peak: int = 80) -> bytes:
    """LFSR noise with a slow LFO; loopable hiss bed."""
    out = [0] * n
    lfsr = 0x7FFF
    for i in range(n):
        new_bit = ((lfsr & 1) ^ ((lfsr >> 1) & 1)) & 1
        lfsr = (lfsr >> 1) | (new_bit << 14)
        bit = (~lfsr) & 1
        env = _attack_release(i, n, attack_frac=0.08, release_frac=0.12)
        lfo = 0.82 + 0.18 * math.sin(2 * math.pi * 6.0 * i / SAMPLE_RATE)
        amp = peak * env * lfo
        out[i] = _clip_s8(amp if bit else -amp)
    return _to_bytes(out)


def grapple_click(n: int) -> bytes:
    """Exponential-decay click with a downward chirp."""
    out = [0] * n
    decay = SAMPLE_RATE * 0.025
    for i in range(n):
        env = math.exp(-i / decay)
        f = 800.0 - 600.0 * (i / max(1, n))
        s = 110.0 * env * math.sin(2 * math.pi * f * i / SAMPLE_RATE)
        out[i] = _clip_s8(s)
    return _to_bytes(out)


def grapple_reel(n: int) -> bytes:
    """Low rumble (square @ ~70 Hz + slow noise dust)."""
    out = [0] * n
    lfsr = 0x7FFF
    for i in range(n):
        if (i & 3) == 0:
            new_bit = ((lfsr & 1) ^ ((lfsr >> 1) & 1)) & 1
            lfsr = (lfsr >> 1) | (new_bit << 14)
        env = _attack_release(i, n, attack_frac=0.08, release_frac=0.15)
        sq = 50.0 if math.sin(2 * math.pi * 70.0 * i / SAMPLE_RATE) > 0 else -50.0
        noise = 28.0 * (1 if (lfsr & 1) else -1)
        out[i] = _clip_s8(env * (sq + noise))
    return _to_bytes(out)


def dew_whine(n: int) -> bytes:
    """Rising sine sweep, 600 -> 2000 Hz, with crackle in the tail."""
    out = [0] * n
    phase = 0.0
    for i in range(n):
        progress = i / max(1, n)
        f = 600.0 + 1400.0 * progress
        phase += 2 * math.pi * f / SAMPLE_RATE
        if progress < 0.1:
            env = progress / 0.1
        elif progress < 0.75:
            env = 1.0
        else:
            env = max(0.0, 1.0 - (progress - 0.75) / 0.25)
        s = 100.0 * env * math.sin(phase)
        if progress > 0.78:
            s += 25.0 * (1.0 if ((i * 31) % 7) < 3 else -1.0)
        out[i] = _clip_s8(s)
    return _to_bytes(out)


def dew_impact(n: int) -> bytes:
    """Crackle burst with fast decay."""
    out = [0] * n
    rng = random.Random(0xBEAD)
    decay = SAMPLE_RATE * 0.05
    for i in range(n):
        env = math.exp(-i / decay)
        out[i] = _clip_s8(rng.uniform(-1.0, 1.0) * 110.0 * env)
    return _to_bytes(out)


def ui_beep(midi: int, n: int) -> bytes:
    """Short square tone with fast A/R."""
    freq = 440.0 * (2.0 ** ((midi - 69) / 12.0))
    out = [0] * n
    for i in range(n):
        env = _attack_release(i, n, attack_frac=0.05, release_frac=0.30)
        phase = (i * freq / SAMPLE_RATE) % 1.0
        s = 90.0 * env * (1.0 if phase < 0.5 else -1.0)
        out[i] = _clip_s8(s)
    return _to_bytes(out)


def _sting(notes: list[int], lengths_sec: list[float]) -> bytes:
    parts = [ui_beep(m, int(SAMPLE_RATE * s))
             for m, s in zip(notes, lengths_sec)]
    return b''.join(parts)


def success_sting() -> bytes:
    # C5 - E5 - G5 (ascending major triad)
    return _sting([72, 76, 79], [0.15, 0.15, 0.32])


def fail_sting() -> bytes:
    # A4 - F4 - D4 (descending)
    return _sting([69, 65, 62], [0.15, 0.15, 0.32])
