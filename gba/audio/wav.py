"""Stdlib-only 8-bit mono WAV writer/reader.

RIFF 8-bit WAV is *unsigned*; our synth math is *signed*. The +/-128 shift
lives only at this boundary; everywhere else stays signed.
"""
from __future__ import annotations

import math
import wave
from pathlib import Path

from .psg import (
    DEFAULT_RATE, SQ1, SQ2, WAVE, NOISE,
    OP_NOTE_ON, OP_NOTE_OFF, OP_VOL, OP_DUTY, OP_SWEEP, OP_WAVE_TABLE,
    note_to_period, square_samples, wave_samples, noise_samples,
)


def write_wav_u8(path, samples: bytes, rate: int = DEFAULT_RATE) -> None:
    """Write signed-8-bit PCM `samples` to a 1-channel 8-bit WAV at `rate`."""
    unsigned = bytes((b + 128) & 0xFF for b in samples)
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(1)
        w.setframerate(rate)
        w.writeframes(unsigned)


def read_wav_u8(path) -> bytes:
    """Read an 8-bit mono WAV and return signed-8-bit `bytes`."""
    with wave.open(str(path), 'rb') as r:
        n = r.getnframes()
        frames = r.readframes(n)
    return bytes((b - 128) & 0xFF for b in frames)


def _default_smooth_wave() -> list[int]:
    """A soft 32-step pseudo-sine in the 0..15 4-bit table range."""
    return [int(round(7.5 + 7.0 * math.sin(2 * math.pi * i / 32))) & 0xF
            for i in range(32)]


def render_song_to_wav(events, total_frames: int, *,
                       path, rate: int = DEFAULT_RATE, fps: int = 60) -> None:
    """Frame-step PSG simulator → mixed 8-bit signed → WAV.

    Maintains a tiny 4-voice state machine. WAVE channel's default table is a
    soft pseudo-sine. NOISE responds to OP_SWEEP by treating the param as a
    sample-divider (advance LFSR every `param` output samples).
    """
    samples_per_frame = rate // fps
    n_total = total_frames * samples_per_frame
    mix = [0] * n_total

    voices = []
    for ch in range(4):
        voices.append({
            'period': 1024,
            'vol': 0,
            'duty': 2,
            'on': False,
            'wave_table': _default_smooth_wave() if ch == WAVE else None,
            'noise_div': 8,
        })

    by_frame: dict[int, list] = {}
    for ev in events:
        by_frame.setdefault(ev.frame, []).append(ev)

    for frame in range(total_frames):
        for ev in by_frame.get(frame, []):
            v = voices[ev.channel]
            if ev.op == OP_NOTE_ON:
                v['period'] = note_to_period(ev.param)
                v['on'] = True
            elif ev.op == OP_NOTE_OFF:
                v['on'] = False
            elif ev.op == OP_VOL:
                v['vol'] = ev.param & 0xF
            elif ev.op == OP_DUTY:
                v['duty'] = ev.param & 0x3
            elif ev.op == OP_SWEEP and ev.channel == NOISE:
                v['noise_div'] = max(1, ev.param)
            elif ev.op == OP_WAVE_TABLE and ev.channel == WAVE:
                pass  # could swap tables here

        offset = frame * samples_per_frame
        for ch, v in enumerate(voices):
            if not v['on'] or v['vol'] == 0:
                continue
            if ch in (SQ1, SQ2):
                buf = square_samples(v['period'], v['duty'], v['vol'],
                                     samples_per_frame, rate=rate)
            elif ch == WAVE:
                buf = wave_samples(v['wave_table'], v['period'], v['vol'],
                                   samples_per_frame, rate=rate)
            elif ch == NOISE:
                buf = noise_samples(v['noise_div'], v['vol'],
                                    samples_per_frame, rate=rate)
            else:
                continue
            for i, b in enumerate(buf):
                s = b - 256 if b >= 128 else b
                mix[offset + i] += s

    clipped = bytes(
        (max(-128, min(127, m)) & 0xFF) for m in mix
    )
    write_wav_u8(path, clipped, rate=rate)
