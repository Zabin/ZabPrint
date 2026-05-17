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


# --- Title theme (D minor → F → B♭ → A; quieter pad, varied arp) ---
# Each pattern is 16 rows = one measure at bpm=60 / 4 rpb (~4 s).
# Four distinct patterns play in sequence so the listener never hears the same
# arp twice in a row. Pad volume is held low (≤4/15) and the NOISE bed is
# either gone or very faint, per Milestone B feedback.

# (pad_root, pad_fifth, arp_notes) per pattern. arp_notes is 4 notes; each
# plays once at rows 0, 4, 8, 12 (so arp is much sparser than before).
TITLE_PATTERNS = [
    (50, 57, [62, 65, 69, 72]),  # i:    Dm  -> arp D F A C
    (53, 60, [65, 69, 72, 76]),  # III:  F   -> arp F A C E
    (46, 53, [58, 62, 65, 69]),  # VI:   B♭  -> arp B♭ D F A
    (45, 52, [57, 60, 64, 65]),  # V/i:  A   -> arp A C E F  (returns toward i)
]


def _title_pattern_variant(idx: int) -> Pattern:
    pad_root, pad_fifth, arp = TITLE_PATTERNS[idx]
    rows: list[list] = [[] for _ in range(16)]

    # WAVE pad: quiet, slow vol drift, fifth re-struck at the half-way mark.
    rows[0].append(_ev(WAVE, OP_VOL, 4))
    rows[0].append(_ev(WAVE, OP_NOTE_ON, pad_root))
    rows[6].append(_ev(WAVE, OP_VOL, 3))
    rows[8].append(_ev(WAVE, OP_NOTE_ON, pad_fifth))
    rows[12].append(_ev(WAVE, OP_VOL, 4))

    # SQ1 arp — 4 notes per measure (not 6), one every 4 rows; each row pair
    # is followed by a NOTE_OFF so the listener hears space between notes.
    rows[0].append(_ev(SQ1, OP_VOL, 3))
    rows[0].append(_ev(SQ1, OP_DUTY, 0))
    for k, midi in enumerate(arp):
        r = k * 4
        rows[r].append(_ev(SQ1, OP_NOTE_ON, midi))
        rows[r + 2].append(_ev(SQ1, OP_NOTE_OFF, 0))

    # NOISE bed: held quiet (vol 1) on patterns 0 and 2 only — silent on
    # 1 and 3 so the drift breathes.
    if idx in (0, 2):
        rows[0].append(_ev(NOISE, OP_SWEEP, 24))
        rows[0].append(_ev(NOISE, OP_VOL, 1))
        rows[0].append(_ev(NOISE, OP_NOTE_ON, 0))
    else:
        rows[0].append(_ev(NOISE, OP_VOL, 0))

    return Pattern(rows=rows)


def _title_patterns() -> list[Pattern]:
    return [_title_pattern_variant(i) for i in range(len(TITLE_PATTERNS))]


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


def _compile_and_render(patterns: list[Pattern], order: list[int], *,
                        bpm: int, name: str) -> tuple[Path, Path]:
    events = compile_song(patterns, order, bpm=bpm, rows_per_beat=4)
    blob = serialize_song(events)

    audio_dir = _BUILD / "audio"
    preview_dir = _BUILD / "preview"
    audio_dir.mkdir(parents=True, exist_ok=True)
    preview_dir.mkdir(parents=True, exist_ok=True)

    bin_path = audio_dir / f"{name}.bin"
    bin_path.write_bytes(blob)

    fpr = frames_per_row(bpm=bpm, rows_per_beat=4)
    total_rows = sum(patterns[i].length for i in order)
    total_frames = total_rows * fpr
    wav_path = preview_dir / f"{name}.wav"
    render_song_to_wav(events, total_frames, path=wav_path)
    return bin_path, wav_path


def main() -> None:
    # Title: four distinct measures played once each (~16 s at bpm=60).
    _compile_and_render(_title_patterns(), [0, 1, 2, 3],
                        bpm=60, name="music_title")
    # Flight: single drone measure, looped six times (~26 s at bpm=54).
    _compile_and_render([_flight_pattern()], [0] * 6,
                        bpm=54, name="music_flight")
    print(f"Wrote music bins to {_BUILD/'audio'} and WAVs to {_BUILD/'preview'}")


if __name__ == "__main__":
    main()
