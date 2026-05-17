# ZABSPACE — GBA Space Exploration

A Game Boy Advance space-exploration ROM built entirely in Python: no devkitARM,
no GCC, no external assembler. Procedural art and audio. Real two-body orbital
physics for maneuvering, rendezvous, and combat.

## Build

```
python3 gba/build.py
```

Produces:
- `gba/build/game.gba` — 2 MiB cartridge image, runnable in mGBA.
- `gba/build/preview/*.png` — preview renders of every generated asset.
- `gba/build/preview/*.wav` — audio previews of music and sound effects.

## Test

```
python3 -m pytest gba/
```

The codebase is test-driven. Every layer — fixed-point math, two-body
integrator, ARM/Thumb encoders, assembler, linker, cart packer, asset packer,
audio synthesis, ARM physics port (under a Python ARM7TDMI interpreter) — has
a covering test that runs before any code in that layer is written.

## Layout

```
gba/
  toolchain/   pure-Python ARM7TDMI + Thumb assembler, linker, cart packer
  assets/      procedural graphics generators (palettes, fonts, planets, ships, UI)
  audio/       PSG + DirectSound PCM music and sfx generators
  src/         hand-authored ARM / Thumb assembly (the game itself)
  tests/       pytest suite covering every layer
  build/       (gitignored) ROM + previews
```

## Controls (in mGBA)

| Input        | Action                                  |
|--------------|-----------------------------------------|
| D-Pad        | Rotate ship / move cursor               |
| A            | Prograde burn                           |
| B            | Retrograde burn                         |
| L / R        | Time-warp down / up (1x, 10x, 100x, 1000x) |
| SELECT       | Cycle target lock                       |
| START        | Maneuver-node planner                   |

## Design

See `/root/.claude/plans/generate-a-space-exploration-purrfect-chipmunk.md`
for the architectural plan.
