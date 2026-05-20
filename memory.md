# memory.md — cross-session state for the GBA space game

Last updated after Layer 8m (LAP cumulative Δφ + path uses semi-major
axis + grapple range re-check) playtest fixes.

## Current state of the world

- Branch: `claude/gba-space-game-Xwd0A` (pushed to origin)
- Tests: **360 passing** (`cd gba && python -m pytest tests/` is green)
- ROM: `gba/build.py` produces `gba/build/game.gba` (2 MiB) that boots in
  mGBA. Mode 3 bitmap. Full feature list:
  - Real two-body orbital physics around one primary; player + 3 targets.
  - 4 directional D-pad burns (in-track / radial) at 1 ΔV per impulse.
  - Time-warp 1× / 10× / 100× (R / L cycle).
  - SELECT toggles ECI ↔ RIC views.
  - A grapple (capture + tow to graveyard). B DEW beam (range 70 px,
    cooldown 30 fr, target dies at 3 hits).
  - L plane change (25 ΔV).
  - Five-D mission FSM (DENY / DGRD / DSRP / DSTR / DECV) with completion
    checks against the live orbital elements.
  - DENY + DSRP have a 50-orbit fail timer (Layer 8h).
  - Hold-at-risk DENY (proximity over time).
  - Persistent debris on Destroy completion (4 slots, drains DV + score).
  - Sensor-cone fog-of-war (off-cone targets dimmed).
  - Predicted orbit paths drawn as dashed dim pixels (64 substeps per body,
    recomputed on burn / respawn).
  - Labelled HUD with 4×6 pixel font (DV, a, e, Ta, Te + WRP, MIS, VIEW,
    PLN, LAP, SCORE).

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
| 8c.2 — Element HUD (a / e bars) | done | `08c588f` |
| 8c.3 — Directional burns + ΔV economy | done | `9853867` |
| 8c.4 — Time warp (R / L cycle) | done | `a6e27fa` |
| 8c.5 — RIC ↔ ECI frame toggle | done | `c900a20` |
| 8c.6+7 — Mission FSM + hold-at-risk DENY | done | `a885fde` |
| 8c.8 — DEW (B, omnidirectional, cooldown) | done | `89c864c` |
| 8c.9 — Sensor-cone fog-of-war | done | `6393d81` |
| 8c.10 — Plane change (L, 25 ΔV) | done | `922ec84` |
| 8c.10b — Control remap to in-track / radial | done | `291b0f5` |
| 8c.11 — Debris persistence (Destroy) | done | `f540c3f` |
| 8c.11b — Grapple weapon (A) | done | `f540c3f` |
| 8c.12 — Polish + idle smoke | done | `61ea8d4` |
| 8e — Labeled HUD with 4×6 pixel font | done | `979e284` + `d53ff01` |
| 8f — Bottom-half VRAM clear fix | done | `f67924b` |
| 8g — Orbit-path prediction (dashed lines) | done | `f67924b` |
| 8g.b — stmia-based fast VRAM clear (anti-flicker) | done | `5e3fc46` |
| 8h — Orbit counter + 50-orbit fail timer | done | `4a2589e` |
| 8g.2 — Full-orbit dashed paths (256 substeps) + spread refresh | done | `98161ab` |
| 8i — Phase-based LAP wrap detection | done | `af990ac` |
| 8j — DEW respawn-in-place + RIC tracks mission target + per-mission reroll | done | `eb79b32` |
| 8k — Per-body period-aware path coverage + grapple-tow teleport fix | done | `877dc00` |
| 8m — LAP cumulative Δφ + path uses semi-major axis + grapple range re-check | done | `d6fbec8` |
| 9a — Minimal ROM (boots, splash) | done | `508ecad` |
| 9b — D-pad ship + starfield + planets | done | `4b0bad5` |
| 9c — Drift physics + projectile | done (replaced) | `22ab75d` |
| 9d — Shootable planets + score + respawn | done (replaced) | `7fad1d9` |

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
* Mode-0 tile engine, OAM sprites. The current ROM is Mode 3 bitmap.
  Real release-quality games use tiles.
* Asset / audio `.incbin` integration. The procedural blobs exist on
  disk in `build/audio/` and `build/assets/` but are not bundled into
  game.gba.
* Audio playback driver (`src/sound.s`).
* True 3D inclination (currently a 2D `plane` flag stand-in).
* In-game ship-class select (Grappler vs Lancer); both weapons are
  unconditionally available.
* Upgrades (delta-V tank, weapon range, weapon cooldown).

## Game-state IWRAM map (current crt0.s — post-8h)

```
0x000  player          { x_q16, y_q16, vx_q16, vy_q16 }    16 B  (ECI)
0x010  prev_keys                                            4 B
0x014  score                                                4 B
0x018  frame_count                                          4 B
0x01C  ship_dv                                              4 B   (Q16; 0..DV_MAX)
0x020  target 0        { x, y, vx, vy }                    16 B  (ECI Q16)
0x030  target 1                                            16 B
0x040  target 2                                            16 B
0x050  player_elements { a, e, omega, nu }                 16 B  (Q16)
0x060  target0_elements (cached for HUD)                   16 B
0x070  warp                                                 4 B   (1, 10, 100)
0x074  view_mode                                            4 B   (0=ECI, 1=RIC)
0x078  ric_target_x / ric_target_y                          8 B
0x080  ric_R̂_x / ric_R̂_y                                  8 B
0x088  ric_Î_x / ric_Î_y                                   8 B
0x090  mission_id                                           4 B
0x094  orbit_count                                          4 B   (8h: resets on cycle)
0x098  mission_target                                       4 B   (0..2)
0x09C  hold_timers[3]                                      12 B
0x0A8  dew_cooldown                                         4 B
0x0AC  target healths[3]                                   12 B
0x0B8  player_plane                                         4 B
0x0BC  target_planes[3]                                    12 B
0x0C8  grapple_target / grapple_timer                       8 B
0x0D0  debris[4] { x, y, vx, vy, alive, age, pad, pad }    128 B
0x150  sensor_dir                                           4 B   (Q16 brad)
0x154  path_dirty                                           4 B   (4 low bits)
0x158  prev_phase                                           4 B   (8m: 16-bit, prev frame's position phase)
0x15C  cum_phase                                            4 B   (8m: signed 32-bit Σ Δphase; ±0x10000 = 1 lap)
0x160  path_player [256 points * 8 B]                    2048 B  (full orbit)
0x960  path_target0                                       2048 B
0x1160 path_target1                                       2048 B
0x1960 path_target2                                       2048 B
0x2160 end                                                ~8.5 KB total
```

`init_z` zero-fills 100 words (`mov r2, #100`, covers 0..0x190) on boot
then seeds non-zero values (player + target ECI states, ship_dv = DV_MAX,
warp = 1, healths, planes, grapple = -1, path_dirty = 0xF). The 8 KiB
path-cache region above 0x160 deliberately is NOT pre-zeroed: dirty=0xF
makes `_refresh_paths` overwrite every cache byte before the renderer
reads it. Keeping init_z short is important because every test in
`test_rom_execute.py` runs the ROM for a budgeted number of armsim
instructions.

`_refresh_paths` recomputes **at most one body's path per frame** (player
first, then T0/T1/T2). Each `_predict_path` is ~360K armsim instructions
(256 substeps × cowell_step, each cowell_step has 3 fx_div_q16 calls and
udiv64 alone is ~448 instructions). Doing all 4 in one frame would burn
~1.5M instructions and visibly stutter on the GBA. Spreading is cheap
because dirty bits are normally 0 (only set on burn / respawn).

## Control mapping (current)

  D-pad burns (edge-detected, 1 ΔV each, BURN_DV = 1/16 px/frame):
    Right  -> +in-track   (~prograde for circular orbits)
    Left   -> -in-track   (~retrograde)
    Up     -> +radial     (away from primary)
    Down   -> -radial     (toward primary)
  A      -> grapple (capture nearest in-range target, tow to graveyard)
  B      -> DEW beam (range 70 px, cooldown 30 fr, kills at 3 hits)
  L      -> plane change (costs 25 ΔV)
  R      -> warp up cycle (1 -> 10 -> 100 -> 1)
  SELECT -> toggle ECI / RIC view
  START  -> reserved

## HUD layout (post-8e, post-8h)

```
y= 2..7   DV  ▓▓▓▓▓▓▓░  87       <- cyan bar + decimal (out of 100)
y=10..15  a   ▓▓▓▓▓▓▓░  40       <- cyan bar + px units
y=18..23  e   ▓░░░░░░░  05       <- yellow bar + e*100
y=26..31  Ta  ▓▓▓▓▓▓░░  38       <- dim cyan; target a
y=34..39  Te  ▓░░░░░░░  02       <- dim yellow; target e*100
y=44      WRP 1   MIS DENY 12   VIEW ECI   PLN 0   LAP 12
y=145     SCORE 0000
```

`LAP` shows `S_ORBIT_COUNT` (elapsed orbits since the mission started).
Yellow when DENY or DSRP and `ORBIT_LIMIT - count <= 10`.

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

`build.py` assembles `src/*.s` (crt0.s + physics.s) with
`base_addr=0x080000C0` so labels resolve correctly. Then prepends
the hand-encoded entry branch and runs through `pack_rom()`.

## Test count history

| Pass | Tests | Note |
|------|-------|------|
| Pre-Layer 7 | 200 | Asset packer + assets done |
| Layer 7 | 241 | +41 audio tests |
| Layer 8a | 275 | +24 armsim + +10 physics_asm |
| Layer 8b | 305 | +30 across div / sqrt / atan2 |
| ROM 9a-d | 319 | ROM build smoke + early gameplay |
| 8c.0 (Cowell) | 325 | +5 cowell_step + 1 ROM rewrites |
| 8c.1 (elements) | 329 | +4 element goldens + fuzz |
| 8c.2 (HUD) | 331 | +2 |
| 8c.3 (burns) | 333 | +2 |
| 8c.4 (warp) | 336 | +3 |
| 8c.5 (RIC) | 339 | +3 |
| 8c.6+7 (mission FSM + hold) | 340 | +1 |
| 8c.8 (DEW) | 342 | +2 |
| 8c.10 (plane) | 344 | +2 |
| 8c.11 (grapple + debris) | 348 | +4 |
| 8c.9 (sensor cone) | 350 | +2 |
| 8e (labeled HUD) | 354 | +4 |
| 8f + 8g (clear fix + orbit paths) | 357 | +3 |
| 8h (orbit counter) | 360 | +3 (deny / dsrp fail + count reset) |
| 8i (phase-based LAP) | 361 | +1 (real-orbit circular wrap) |
| 8j (DEW respawn + RIC + reroll) | 364 | +3 (respawn-in-place, reroll, RIC mission target) |
| 8k (period-aware paths + grapple fix) | 368 | +4 (cowell_step_dt × 2, _compute_path_dt, path closes) |
| 8m (LAP cum-Δ, path uses a not r, grapple range re-check) | **374** | +7 -1 (lap algo / eccentric path / grapple release) |

## Assembler quirks to remember (also in CLAUDE.md)

1. Labels starting with `.` are parsed as directives. Use plain names.
2. `.global` and `.space` aren't implemented.
3. `mov #imm` immediates must be rotated-imm-encodable; otherwise
   `ldr =VALUE` (literal pool). E.g. `mov r2, #600` fails;
   `ldr r2, =600` works.
4. `split_cond` matches cond before S — extending this for new
   instructions: cond first, then S.
5. `.ltorg` must be reachable within ±4 KiB of every `ldr =`.
6. Shifted-register operands (`mov r0, r1, lsl #N`) come in as a
   separate comma-split operand; `_tryparse_arm_dp` merges them.
   Register-shifted operands (`mov r0, r1, lsl r2`) are not
   supported by the assembler — use `cmp` + `moveq` cascades.
7. `stmia` operands tokenise per-comma, so `{r1, r2, r3, r4, r5, r6,
   r7, r8}` mis-parses. Use range syntax: `{r1-r8}`.

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

## Performance / VRAM-clear notes

* Mode 3 framebuffer = 240 × 160 × 2 B = 76 800 B. Naive byte-pair clear
  cost ~230 K cycles per frame and caused tearing (commit `5e3fc46`).
* Current clear uses `stmia r0!, {r1-r8}` (8 registers = 16 px / iter)
  × 2400 iters → ~40 K cycles. Fits inside the ~83 K VBlank window.
* Clear-loop count is `=19200` (words, not pixels: 19 200 × 4 B =
  76 800 B). Earlier `=9600` cleared only the top half (Layer 8f bug).

## Things that have surprised me

* `bx` masks the LSB of LR for Thumb interwork. The armsim sentinel
  must be even — `_SENTINEL_LR = 0xDEADBEEE`.
* `mov r0, r0, lsl #16` truncates to 32 bits, so the naive
  `sqrt(x << 16)` overflows for `x >= 0x10000`. Hence the Newton
  iteration + `udiv64` in `fx_sqrt_q16`.
* The cart packer's payload-at-0xC0 contract means we hand-encode the
  entry branch in `build.py` — the assembler would compute the wrong
  relative offset.
* Element-compute overwrites `S_PLAYER_EL+12` each frame, so orbit-wrap
  tests can't inject `cur_nu` directly. They reset the player to a
  known periapsis state via a `_reset_player_to_periapsis` helper
  and let the kernel produce the desired ν.
* The font has no 'B' glyph (small set). Labels like "ORB" were
  rejected by the assembler; "LAP" was chosen instead (L/A/P all
  exist).

## How to continue

Natural next passes, ordered by leverage:

1. **`fx_sin` / `fx_cos` LUT in ARM.** Emit a 4 KiB Q16 LUT to
   `src/sin_lut.bin`, `.incbin` from physics.s, implement quarter-LUT
   lookup with quadrant fold. Unlocks proper trajectory projection
   over arbitrary anomalies (not just 64 substeps of forward
   integration) and a cleaner DEW raycast.
2. **Asset / audio `.incbin` integration.** A `data.s` that bundles
   the procedural blobs from `build/audio/` and `build/assets/`, plus
   the runtime ARM playback driver (`src/sound.s`). Unlocks music + sfx
   in the ROM.
3. **In-game ship-class select.** Title screen with A/B between
   Grappler (only A wired) and Lancer (only B wired). Currently both
   are unconditionally available.
4. **Upgrades.** ΔV tank, weapon range, weapon cooldown — each earned
   on N mission completions.
5. **True 3D inclination.** Add `z, vz` to bodies; rewrite `cowell_step`
   for 3 components; project to screen. Replaces the 2D `plane` flag.
