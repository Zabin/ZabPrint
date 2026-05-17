"""Pattern → frame-indexed event stream.

A `Pattern` is a list of rows; each row has one optional `PsgEvent` per
channel (4 channels). `compile_song(patterns, order, …)` walks the patterns
in `order`, converts row indices to frame numbers using a configurable
bpm/rows-per-beat/fps, and returns a sorted event list.
"""
from __future__ import annotations

from dataclasses import dataclass

from .psg import PsgEvent, pack_stream, parse_stream


def frames_per_row(*, bpm: int, rows_per_beat: int, fps: int = 60) -> int:
    """Frames per tracker row at the given tempo. Rounded to nearest int."""
    return round(60 * fps / (bpm * rows_per_beat))


@dataclass
class Pattern:
    """rows[row_idx][channel_idx] -> PsgEvent | None."""
    rows: list[list]

    @property
    def length(self) -> int:
        return len(self.rows)


def compile_song(patterns: list[Pattern], order: list[int],
                 *, bpm: int = 60, rows_per_beat: int = 4,
                 fps: int = 60) -> list[PsgEvent]:
    fpr = frames_per_row(bpm=bpm, rows_per_beat=rows_per_beat, fps=fps)
    events: list[PsgEvent] = []
    row_offset = 0
    for pat_idx in order:
        pat = patterns[pat_idx]
        for row_idx, row in enumerate(pat.rows):
            frame = (row_offset + row_idx) * fpr
            for ev in row:
                if ev is None:
                    continue
                events.append(PsgEvent(frame, ev.channel, ev.op, ev.param))
        row_offset += pat.length
    events.sort(key=lambda e: (e.frame, e.channel, e.op))
    return events


def serialize_song(events: list[PsgEvent]) -> bytes:
    return pack_stream(events)


def parse_song(blob: bytes) -> list[PsgEvent]:
    return parse_stream(blob)
