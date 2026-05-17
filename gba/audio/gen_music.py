"""Compose the title theme and flight loop as PSG event streams.

Mood (user-locked): "ambient drift" — sustained WAVE pad, sparse SQ1 arp,
soft NOISE hiss bed. Tempo is slow on purpose. Each track emits:

  build/audio/<name>.bin   — packed event stream (with terminator)
  build/preview/<name>.wav — 8-bit signed @ 16384 Hz preview
"""
from __future__ import annotations

from pathlib import Path

from .psg import (
    PsgEvent, SQ1, WAVE, NOISE,
    OP_NOTE_ON, OP_NOTE_OFF, OP_VOL, OP_DUTY, OP_SWEEP,
)
from .tracker import Pattern, compile_song, serialize_song, frames_per_row
from .wav import render_song_to_wav


_BUILD = Path(__file__).resolve().parent.parent / "build"


def _ev(channel: int, op: int, param: int) -> PsgEvent:
    # `compile_song` rewrites the frame from row index, so use 0 here.
    return PsgEvent(0, channel, op, param)


# --- Title theme (D minor pad, sparse arp) ---
TITLE_PAD_LOW    = 50   # D3
TITLE_PAD_FIFTH  = 57   # A3
ARP_NOTES        = [62, 65, 69, 72, 69, 65]   # D4 F4 A4 C5 A4 F4


def _title_pattern() -> Pattern:
    rows: list[list] = [[] for _ in range(16)]

    # WAVE: slow chord — root, then fifth halfway, with a drifting volume curve
    rows[0].append(_ev(WAVE, OP_VOL, 6))
    rows[0].append(_ev(WAVE, OP_NOTE_ON, TITLE_PAD_LOW))
    rows[4].append(_ev(WAVE, OP_VOL, 5))
    rows[8].append(_ev(WAVE, OP_NOTE_ON, TITLE_PAD_FIFTH))
    rows[12].append(_ev(WAVE, OP_VOL, 7))

    # SQ1: low-volume 12.5%-duty arp, one note every two rows
    rows[0].append(_ev(SQ1, OP_VOL, 4))
    rows[0].append(_ev(SQ1, OP_DUTY, 0))
    for k, midi in enumerate(ARP_NOTES):
        r = (k * 2) % 16
        rows[r].append(_ev(SQ1, OP_NOTE_ON, midi))

    # NOISE: continuous quiet drift
    rows[0].append(_ev(NOISE, OP_SWEEP, 16))
    rows[0].append(_ev(NOISE, OP_VOL, 2))
    rows[0].append(_ev(NOISE, OP_NOTE_ON, 0))

    return Pattern(rows=rows)


# --- Flight loop (lower drone, even sparser) ---
FLIGHT_PAD_LOW   = 45   # A2
FLIGHT_PAD_FIFTH = 52   # E3
FLIGHT_HITS      = [50, 52, 50, 45]   # short bass squares, one per measure quarter


def _flight_pattern() -> Pattern:
    rows: list[list] = [[] for _ in range(16)]

    rows[0].append(_ev(WAVE, OP_VOL, 7))
    rows[0].append(_ev(WAVE, OP_NOTE_ON, FLIGHT_PAD_LOW))
    rows[6].append(_ev(WAVE, OP_VOL, 5))
    rows[10].append(_ev(WAVE, OP_VOL, 6))
    rows[10].append(_ev(WAVE, OP_NOTE_ON, FLIGHT_PAD_FIFTH))

    rows[0].append(_ev(SQ1, OP_VOL, 3))
    rows[0].append(_ev(SQ1, OP_DUTY, 2))  # 50% duty for warmer bass
    for k, midi in enumerate(FLIGHT_HITS):
        r = (k * 4) % 16
        rows[r].append(_ev(SQ1, OP_NOTE_ON, midi))
        rows[(r + 2) % 16].append(_ev(SQ1, OP_NOTE_OFF, 0))

    rows[0].append(_ev(NOISE, OP_SWEEP, 20))
    rows[0].append(_ev(NOISE, OP_VOL, 1))
    rows[0].append(_ev(NOISE, OP_NOTE_ON, 0))

    return Pattern(rows=rows)


def _compile_and_render(pattern: Pattern, order: list[int], *,
                        bpm: int, name: str) -> tuple[Path, Path]:
    events = compile_song([pattern], order, bpm=bpm, rows_per_beat=4)
    blob = serialize_song(events)

    audio_dir = _BUILD / "audio"
    preview_dir = _BUILD / "preview"
    audio_dir.mkdir(parents=True, exist_ok=True)
    preview_dir.mkdir(parents=True, exist_ok=True)

    bin_path = audio_dir / f"{name}.bin"
    bin_path.write_bytes(blob)

    fpr = frames_per_row(bpm=bpm, rows_per_beat=4)
    total_rows = len(pattern.rows) * len(order)
    total_frames = total_rows * fpr
    wav_path = preview_dir / f"{name}.wav"
    render_song_to_wav(events, total_frames, path=wav_path)
    return bin_path, wav_path


def main() -> None:
    _compile_and_render(_title_pattern(),  [0] * 4, bpm=60, name="music_title")   # ~16 s
    _compile_and_render(_flight_pattern(), [0] * 6, bpm=54, name="music_flight")  # ~26 s
    print(f"Wrote music bins to {_BUILD/'audio'} and WAVs to {_BUILD/'preview'}")


if __name__ == "__main__":
    main()
