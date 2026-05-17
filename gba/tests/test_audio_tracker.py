"""Layer 7 tracker compilation + (de)serialization tests."""
from audio.psg import (
    PsgEvent, SQ1, SQ2, WAVE, NOISE,
    OP_NOTE_ON, OP_VOL,
)
from audio.tracker import (
    Pattern, compile_song, serialize_song, parse_song, frames_per_row,
)


def _empty_row(width: int = 4) -> list:
    return [None] * width


def test_frames_per_row_bpm60_4rpb_is_15():
    # 60 fps, 60 bpm, 4 rows/beat -> 1 beat/sec = 60 frames/beat = 15 frames/row
    assert frames_per_row(bpm=60, rows_per_beat=4, fps=60) == 15


def test_frames_per_row_bpm120_4rpb_is_8_at_60fps():
    # 60 fps, 120 bpm, 4 rows/beat -> 0.5 sec/beat = 30 frames/beat = 7.5 -> 8
    assert frames_per_row(bpm=120, rows_per_beat=4, fps=60) == 8


def test_compile_song_row_to_frame_mapping():
    rows = [_empty_row() for _ in range(4)]
    rows[0][SQ1] = PsgEvent(0, SQ1, OP_NOTE_ON, 69)
    rows[2][SQ1] = PsgEvent(0, SQ1, OP_NOTE_ON, 76)
    pat = Pattern(rows=rows)
    events = compile_song([pat], [0], bpm=60, rows_per_beat=4, fps=60)
    # frames_per_row = 15
    frames = [e.frame for e in events]
    assert frames == [0, 30]
    assert events[0].param == 69
    assert events[1].param == 76


def test_compile_song_pattern_order_offsets_rows():
    rows = [_empty_row() for _ in range(4)]
    rows[0][SQ1] = PsgEvent(0, SQ1, OP_NOTE_ON, 60)
    pat = Pattern(rows=rows)
    events = compile_song([pat], [0, 0, 0], bpm=60, rows_per_beat=4, fps=60)
    # 3 patterns of 4 rows each = 12 rows total. The note-on at row 0 of each pattern
    # should land at frames 0, 60, 120.
    frames = sorted(e.frame for e in events)
    assert frames == [0, 60, 120]


def test_compile_song_monotonic_frames():
    rows = [_empty_row() for _ in range(8)]
    # interleave channels and add some events
    rows[0][WAVE] = PsgEvent(0, WAVE, OP_VOL, 6)
    rows[0][SQ1]  = PsgEvent(0, SQ1,  OP_VOL, 3)
    rows[2][SQ1]  = PsgEvent(0, SQ1,  OP_NOTE_ON, 69)
    rows[5][NOISE]= PsgEvent(0, NOISE,OP_VOL, 2)
    rows[7][WAVE] = PsgEvent(0, WAVE, OP_NOTE_ON, 48)
    pat = Pattern(rows=rows)
    events = compile_song([pat], [0], bpm=60, rows_per_beat=4, fps=60)
    for a, b in zip(events, events[1:]):
        assert a.frame <= b.frame


def test_serialize_parse_round_trip():
    rows = [_empty_row() for _ in range(4)]
    rows[0][SQ1] = PsgEvent(0, SQ1, OP_NOTE_ON, 60)
    rows[3][WAVE] = PsgEvent(0, WAVE, OP_VOL, 8)
    pat = Pattern(rows=rows)
    events = compile_song([pat], [0, 0], bpm=60, rows_per_beat=4)
    blob = serialize_song(events)
    assert parse_song(blob) == events


def test_serialize_empty_is_terminator():
    assert serialize_song([]) == b'\xff\xff\xff\xff'
