# memory.md — cross-session state for the GBA space game

Last updated by Claude after the "Finish the game" pass.

## Current state of the world

- Branch: `claude/gba-space-game-Xwd0A` (pushed to origin)
- Tests: **319 passing** (`python -m pytest gba/tests/` is green)
- ROM: `gba/build.py` produces `gba/build/game.gba` (2 MiB) that boots
  cleanly in mGBA. Drift physics, A-button projectile, two shootable
  planets that respawn at LCG positions, green-pixel score bar.

## Layer ledger

| Layer | Status | Commit |
|-------|--------|--------|
| 1 — Fixed-point math reference | done | `ae56702` |
| 2 — Two-body integrator (Python sim) | done | `7b2f596` |
| 3 — ARM + Thumb encoders | done | `20c5d4c` |
| 4 — Two-pass assembler | done | `7265429` |
| 5 — Cartridge header + packer | done | `fea63a9` |
| 6 — Asset packer + procedural assets | done | `10a40a0` + `1ca8368` |
| 7 — Audio (PSG tracker + 8-bit PCM) | done | `26bc374` + `286eb8c` |
| 8a — ARMv4 interpreter + fx_mul_q16 | done | `57c39bb` |
| 8b — fx_div_q16, fx_sqrt_q16, fx_atan2 | done | `07a948e` |
| 8c — sin/cos LUT, Cowell step | **not started** | — |
| 9a — Minimal ROM (boots, splash) | done | `508ecad` |
| 9b — D-pad ship + starfield + planets | done | `4b0bad5` |
| 9c — Drift physics + projectile | done | `22ab75d` |
| 9d — Shootable planets + score + respawn | done | `7fad1d9` |

## What's bit-identical to its Python reference

`tests/test_physics_asm.py` validates these against `toolchain/fixedpoint.py`:

| ARM routine | Coverage |
|-------------|----------|
| `fx_mul_q16` | 9 goldens + 2000 random pairs |
| `fx_div_q16` | 10 goldens + 500 random pairs |
| `fx_sqrt_q16` | 5 goldens + ~320 inputs over full positive 32-bit |
| `fx_atan2` | 5 cardinal goldens + ~210 random (y, x) pairs |
| `udiv64` (internal) | 6 goldens |

The interpreter (`toolchain/armsim.py`) covers every instruction
`encode_arm.py` emits plus BIOS SWI 0x06 (Div), 0x0D (Sqrt), 0x09
(ArcTan2). Multi-region memory landed for the ROM smoke tests.

## What's deliberately deferred

* `fx_sin` / `fx_cos`: needs the 1024-entry Q16 LUT embedded. Plan: emit
  `src/sin_lut.bin` from a Python script, `.incbin` it from physics.s,
  table-lookup with quarter-circle folding. Reference is `fx_sin` /
  `fx_cos` in `toolchain/fixedpoint.py`.
* Cowell two-body integrator step: pure math, just glue-code over the
  primitives. Python reference is `toolchain/orbit.py::step`.
* Mode-0 tile engine, OAM sprites, font + text HUD. The current ROM is
  Mode 3 bitmap. Real release-quality games use tiles.
* Asset / audio `.incbin` integration. The procedural blobs exist on
  disk in `build/audio/` and `build/assets/` but are not bundled into
  game.gba. Plan: a `data.s` that `.incbin`s every blob with labels.
* Audio playback driver (`src/sound.s`).
* Mission system, upgrades, grapple/DEW combat.

## Game-state IWRAM map (current crt0.s)

```
0x03000000  ship_x_q16     ship_y_q16     ship_vx_q16    ship_vy_q16
0x03000010  prev_keys      proj_x_q16     proj_y_q16     proj_vx_q16
0x03000020  proj_vy_q16    proj_active    p1_x (int)     p1_y (int)
0x03000030  p1_alive       p2_x           p2_y           p2_alive
0x03000040  frame_count    score
```

80 bytes / 20 words. `init_z` zero-fills the whole block on boot then
seeds non-zero values (positions, alive flags).

## ROM layout

```
0x00..0x03   entry branch  (hand-encoded 0xEA00002E by build.py)
0x04..0x9F   Nintendo logo
0xA0..0xAB   title "ZABSPACE"
0xAC..0xAF   game code "ZSPE"
0xB0..0xBF   maker code, fixed bytes, checksum, padding
0xC0..       payload (= _start onwards from src/crt0.s)
... up to 2 MiB, 0xFF padded
```

`build.py` assembles `src/*.s` (currently crt0.s + physics.s) with
`base_addr=0x080000C0` so labels resolve correctly. Then prepends
the hand-encoded entry branch and runs through `pack_rom()`.

## Test count history

| Pass | Tests | Note |
|------|-------|------|
| Pre-Layer 7 | 200 | Asset packer + assets done |
| Layer 7 | 241 | +41 audio tests |
| Layer 8a | 275 | +24 armsim + +10 physics_asm |
| Layer 8b | 305 | +30 across div/sqrt/atan2 |
| ROM 9a | 313 | +8 ROM build smoke |
| ROM 9b | 317 | +4 ROM-execute (with multi-region armsim) |
| ROM 9c | 318 | +1 A-button spawn test |
| ROM 9d | 319 | +1 planet+score init test |

## Assembler quirks to remember (also in CLAUDE.md)

1. Labels starting with `.` are parsed as directives. Use plain names.
2. `.global` and `.space` aren't implemented.
3. `mov #imm` immediates must be rotated-imm-encodable; otherwise
   `ldr =VALUE` (literal pool).
4. `split_cond` matches cond before S — extending this for new
   instructions: cond first, then S.
5. `.ltorg` must be reachable within ±4 KiB of every `ldr =`.
6. Shifted-register operands (`mov r0, r1, lsl #N`) come in as a
   separate comma-split operand; `_tryparse_arm_dp` merges them.

## Audio decisions (locked with the user during Milestone B)

* Mood: "ambient drift" — wave-channel pad + sparse arp + soft hiss.
* Preview format: native GBA rate (~16384 Hz, 8-bit signed).
* Title theme: 16 seconds, four distinct measures (Dm → F → B♭ → A).
  V2 dropped pad volume (peak 102 → 63) and added the per-measure
  variation in response to "less drone, less repetition" feedback.
* SFX set (all approved): thrust hiss, grapple click + reel,
  DEW whine + impact, lock-on, menu, success sting, fail sting.

## Visual decisions (locked with the user during Milestone A)

* Grappler is the tug-style ship; Lancer is the needle. Re-drawn after
  user feedback that the original silhouettes were too generic
  (commit `1ca8368`).

## Things that have surprised me

* The `bx` instruction masks the LSB of LR (Thumb interwork). The
  armsim sentinel must be even — `_SENTINEL_LR = 0xDEADBEEE`.
* `mov r0, r0, lsl #16` truncates to 32 bits, so the naive
  `sqrt(x << 16)` overflows for `x >= 0x10000`. Hence the Newton
  iteration + `udiv64` in `fx_sqrt_q16`.
* The cart packer's payload-at-0xC0 contract means we hand-encode the
  entry branch in `build.py` — we can't let the assembler emit it,
  because the assembler would compute the wrong relative offset.

## How to continue

The most natural next pass (Layer 8c) would:

1. Write a Python generator that emits a 4096-byte (1024 × 4-byte word)
   sin LUT to `src/sin_lut.bin` matching `fixedpoint.fx_sin`.
2. Add `.incbin "src/sin_lut.bin"` and label `sin_lut:` in physics.s.
3. Implement `fx_sin(brad)` as a quarter-LUT lookup with mirror/negate
   per quadrant, exactly like the Python reference.
4. Add bit-identity tests for `fx_sin` / `fx_cos`.
5. Then the Cowell `physics_step` becomes pure glue.

If the next pass is gameplay-facing: switch to Mode 0 tiles + OAM
sprites, port the procedural ship art into a 4bpp tileset, wire it
through `data.s` via `.incbin`. That's a bigger task — probably
half a session on its own.
