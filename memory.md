# memory.md — cross-session state for the GBA space game

Last updated after Phase 8c orbital-realism pass (12-phase plan, 9 phases shipped).

## Current state of the world

- Branch: `claude/gba-space-game-Xwd0A` (pushed to origin)
- Tests: **344 passing** (`python -m pytest gba/tests/` is green)
- ROM: `gba/build.py` produces `gba/build/game.gba` (2 MiB). Real Cowell
  two-body physics around one primary; player + 3 targets orbit. D-pad
  fires orbital-frame impulses (Right = +in-track, Left = -in-track,
  Up = +radial, Down = -radial), each costing 1 ΔV unit from a 100-unit
  tank. R/L cycle time-warp 1×/10×/100×. SELECT toggles ECI / RIC
  views (RIC centres on target 0 with ZOOM=4). B fires omnidirectional
  DEW (range 70 px, cooldown 30 fr, target dies at 3 hits). START
  flips orbital plane (25 ΔV cost). Mission FSM cycles through the
  five Ds (Deny/Degrade/Disrupt/Destroy/Deceive); Deny + Degrade
  win conditions wired; Disrupt/Destroy/Deceive scaffolded but await
  grapple + element-match plumbing.

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
| 8c.0 — Cowell step (ARM) | done | `bb79d36` |
| 8c.1 — Elements kernel (a, e, ω, ν) | done | `ea8213f` |
| 8c.2 — Element HUD (player + target a/e bars) | done | `08c588f` |
| 8c.3 — Directional burns + ΔV economy | done | `9853867` |
| 8c.4 — Time warp (R/L cycle 1/10/100) | done | `a6e27fa` |
| 8c.5 — RIC ↔ ECI frame toggle (SELECT) | done | `c900a20` |
| 8c.6+7 — Mission FSM + hold-at-risk Deny | done | `a885fde` |
| 8c.8 — DEW (B, omnidirectional, cooldown) | done | `89c864c` |
| 8c.9 — Sensor-cone fog-of-war | **deferred** | — |
| 8c.10 — Plane change (START, 25 ΔV) | done | `922ec84` |
| 8c.10b — Control remap to in-track/radial | done | `291b0f5` |
| 8c.11 — Debris persistence | **deferred** (needs grapple) | — |
| 8c.12 — Polish + idle smoke | this commit | — |
| Grapple weapon | **deferred** | — |
| sin/cos LUT in ARM | **deferred** | — |
| 9a — Minimal ROM (boots, splash) | done | `508ecad` |
| 9b — D-pad ship + starfield + planets | done | `4b0bad5` |
| 9c — Drift physics + projectile | done (later replaced) | `22ab75d` |
| 9d — Shootable planets + score + respawn | done (later replaced) | `7fad1d9` |

## What's bit-identical to its Python reference

`tests/test_physics_asm.py` validates these against `toolchain/fixedpoint.py`:

| ARM routine | Coverage |
|-------------|----------|
| `fx_mul_q16` | 9 goldens + 2000 random pairs |
| `fx_div_q16` | 10 goldens + 500 random pairs |
| `fx_sqrt_q16` | 5 goldens + ~320 inputs over full positive 32-bit |
| `fx_atan2` | 5 cardinal goldens + ~210 random (y, x) pairs |
| `udiv64` (internal) | 6 goldens |
| `cowell_step` | 5 cases (circular, drift, fuzz of 150 random states, multi-step bound) |
| `elements_from_state` | 4 cases (circular e≈0, radial e≈1, hyperbolic sentinel, 200-pair fuzz) |

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

## Game-state IWRAM map (current crt0.s — Phase 8c)

```
0x000  player          { x_q16, y_q16, vx_q16, vy_q16 }    16 B (ECI)
0x010  prev_keys                                            4 B
0x014  score                                                4 B
0x018  frame_count                                          4 B
0x01C  ship_dv                                              4 B  (Q16; tank, 0..DV_MAX)
0x020  target 0        { x, y, vx, vy }                    16 B (ECI Q16)
0x030  target 1        { x, y, vx, vy }                    16 B
0x040  target 2        { x, y, vx, vy }                    16 B
0x050  player_elements { a, e, omega, nu }                 16 B (Q16)
0x060  target0_elements (cached for HUD)                   16 B
0x070  warp                                                 4 B  (1, 10, 100)
0x074  view_mode                                            4 B  (0 = ECI, 1 = RIC)
0x078  ric_target_x / ric_target_y                          8 B  (Q16)
0x080  ric_R̂_x / ric_R̂_y                                  8 B  (Q16)
0x088  ric_Î_x / ric_Î_y                                   8 B  (Q16)
0x090  mission_id / mission_progress / mission_target      12 B
0x09C  hold_timers[3]                                      12 B
0x0A8  dew_cooldown                                         4 B
0x0AC  target healths[3]                                   12 B
0x0B8  player_plane                                         4 B
0x0BC  target_planes[3]                                    12 B
0x0C8  end                                                200 B = 50 W
```

`init_z` zero-fills 50 words on boot; non-zero seeds (positions,
ship_dv, warp=1, target healths=3, target planes 0/1/0) follow.

## Control mapping (Phase 8c, user-locked)

  D-pad burns (edge-detected, 1 ΔV each, BURN_DV = 1/16 px/frame):
    Right  -> +in-track   (~prograde for circular orbits)
    Left   -> -in-track   (~retrograde)
    Up     -> +radial     (away from primary)
    Down   -> -radial     (toward primary)
  A      -> (reserved for grapple, not yet wired)
  B      -> DEW: hits nearest in-range, same-plane target (range 70 px)
  SELECT -> toggle ECI / RIC view
  START  -> plane change (costs 25 ΔV)
  R      -> warp up cycle (1 -> 10 -> 100 -> 1)
  L      -> warp down cycle

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
| Layer 8c.0 (Cowell) | 325 | +5 cowell_step + 1 ROM test rewrites |
| Layer 8c.1 (elements) | 329 | +4 elements_from_state goldens + fuzz |
| Layer 8c.2 (HUD) | 331 | +2 element-cache + bar paint |
| Layer 8c.3 (burns) | 333 | +2 ΔV + in-track burn |
| Layer 8c.4 (warp) | 336 | +3 warp toggle + acceleration |
| Layer 8c.5 (RIC) | 339 | +3 view toggle + RIC-centred paint |
| Layer 8c.6+7 (mission FSM + hold) | 340 | +1 mission state init |
| Layer 8c.8 (DEW) | 342 | +2 health init + B-press hit |
| Layer 8c.10 (plane) | 344 | +2 plane init + START toggle |

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
