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

## Controls

| Input     | Action                                    |
|-----------|-------------------------------------------|
| Up        | Prograde burn (raises apogee)             |
| Down      | Retrograde burn (lowers apogee)           |
| Left      | Radial-in burn (rotates apsides CW)       |
| Right     | Radial-out burn (rotates apsides CCW)     |
| A         | Grapple (Grappler class) / engage DEW (Lancer class) |
| B         | Fire DEW beam (Lancer) / release grapple  |
| R         | Time-warp up (1x → 10x → 100x → 1x)      |
| L         | Plane change (costs 25 ΔV)                |
| SELECT    | Toggle ECI / RIC reference frame          |
| START     | (reserved)                                |

Burns are single impulses — tap once per maneuver. Each impulse costs 1 unit
of ΔV. ΔV refills by 25 on each mission completion.

## HUD

```
DV  ▓▓▓▓▓▓▓░  87       ← ΔV remaining (cyan bar + numeric)
a   ▓▓▓▓▓▓▓░  40       ← player semi-major axis in px
e   ▓░░░░░░░  05       ← player eccentricity × 100
Ta  ▓▓▓▓▓▓░░  38       ← target semi-major axis
Te  ▓░░░░░░░  02       ← target eccentricity × 100

WRP 1   MIS DENY   VIEW ECI   PLN 0     ← mode indicators
                                         (bottom of screen)
SCORE 0000
```

**ECI** (Earth-Centred Inertial) — planet at screen centre; orbits are fixed
paths in space. Use for burn planning.

**RIC** (Radial-In-track-Cross) — active target at screen centre; your position
is shown relative to the target's orbital frame. Use for final approach and
proximity operations.

Orbit-path prediction: each body's next 64 integration steps are shown as
dashed coloured dots — dim cyan (player), dim red/green/cyan-grey (targets).
Paths recompute automatically after every burn.

## Missions (Five Ds)

Missions cycle automatically through five doctrinal objective types. Current
mission is shown in the HUD's `MIS` field.

| Mission | Objective                                                              |
|---------|------------------------------------------------------------------------|
| DENY    | Hold within 12 px of the target for 2.5 s (150 frames). Stays in RIC range — no weapons needed. |
| DGRD    | Deplete target health to 0 with the DEW beam.                          |
| DSRP    | Land a DEW hit while the target is near periapsis (ν < 22°).          |
| DSTR    | Complete a full grapple-tow to the graveyard orbit.                    |
| DECV    | Match the target's orbit — same semi-major axis, eccentricity, and plane — and hold for 1.5 s. |

Each completion awards 5 score points and 25 ΔV, then advances to the next
mission type with a new randomly-chosen target.

**Hard-kill penalty:** the DSTR mission spawns 4 debris objects on the target's
trajectory. They orbit indefinitely and deal −1 score + 10 ΔV drain on contact.

## Orbital Mechanics Reference

| Burn direction | Effect on orbit          |
|----------------|--------------------------|
| Prograde (↑)   | Raises apogee; increases a and e if at periapsis |
| Retrograde (↓) | Lowers apogee; decreases a and e if at periapsis |
| Radial-out (→) | Rotates apsides CCW; changes e but not a         |
| Radial-in (←)  | Rotates apsides CW                               |
| Plane change   | Toggles between two inclination planes (costs 25 ΔV) |

A **Hohmann transfer** (raise/lower to match target's semi-major axis) is two
burns: one prograde at your current apsis to set the transfer orbit, then
another when you reach the opposite apsis to circularise.

The **DECV** (Deceive) mission is the full rendezvous: match `a`, `e`, and
orbital plane. Watch the `a` and `e` bars in the HUD until your bars align
with the target's `Ta` and `Te` bars.

## Layout

```
gba/
  toolchain/   pure-Python ARM7TDMI + Thumb assembler, linker, cart packer
  assets/      procedural graphics generators (palettes, fonts, planets, ships, UI)
  audio/       PSG + DirectSound PCM music and sfx generators
  src/         hand-authored ARM / Thumb assembly (the game itself)
  tests/       pytest suite (356 tests, every layer)
  build/       (gitignored) ROM + previews
```
