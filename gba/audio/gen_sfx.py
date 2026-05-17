"""Emit every sfx as both a `.bin` (raw signed-8-bit PCM) and a `.wav` preview.

Future ROM integration: `data.s` `.incbin`s each `.bin` at a known offset;
`src/sound.s` plays via DirectSound A/B (timer-clocked 16384 Hz DMA).
"""
from __future__ import annotations

from pathlib import Path

from .pcm import (
    SAMPLE_RATE,
    thrust_hiss, grapple_click, grapple_reel,
    dew_whine, dew_impact, ui_beep,
    success_sting, fail_sting,
)
from .wav import write_wav_u8


_BUILD = Path(__file__).resolve().parent.parent / "build"


def _sec(s: float) -> int:
    return int(SAMPLE_RATE * s)


SFX_TABLE = [
    ("sfx_thrust",        lambda: thrust_hiss(_sec(0.50))),
    ("sfx_grapple_click", lambda: grapple_click(_sec(0.15))),
    ("sfx_grapple_reel",  lambda: grapple_reel(_sec(1.50))),
    ("sfx_dew_whine",     lambda: dew_whine(_sec(0.40))),
    ("sfx_dew_impact",    lambda: dew_impact(_sec(0.20))),
    ("sfx_lock",          lambda: ui_beep(72, _sec(0.10))),
    ("sfx_menu",          lambda: ui_beep(67, _sec(0.08))),
    ("sfx_success",       success_sting),
    ("sfx_fail",          fail_sting),
]


def main() -> None:
    audio_dir = _BUILD / "audio"
    preview_dir = _BUILD / "preview"
    audio_dir.mkdir(parents=True, exist_ok=True)
    preview_dir.mkdir(parents=True, exist_ok=True)

    for name, synth in SFX_TABLE:
        samples = synth()
        (audio_dir / f"{name}.bin").write_bytes(samples)
        write_wav_u8(preview_dir / f"{name}.wav", samples, rate=SAMPLE_RATE)

    print(f"Wrote {len(SFX_TABLE)} sfx bins/wavs.")


if __name__ == "__main__":
    main()
