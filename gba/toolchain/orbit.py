"""Two-body Keplerian integrator -- Python reference.

This is the TDD oracle for `src/orbit.s` and `src/physics.s` on the ARM port.
Arithmetic is done in Q16.16 throughout, modeling exactly what the ARM code
will compute (apart from BIOS Div / Sqrt quantization, which differs by at most
1 LSB and is irrelevant to the physics tests).

mu is the gravitational parameter of the primary. The design target is that a
200-wu circular orbit completes in ~30 s real-time at 1x time-warp.
"""
from dataclasses import dataclass
import math

from toolchain.fixedpoint import (
    Q16, to_q16, from_q16, fx_mul_q16, fx_div_q16, fx_sqrt_q16,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MU = 350_000        # wu^3 / s^2  -- chosen so 200 wu period ~ 30 s
STEP_HZ = 60        # physics base rate; one frame = 1/STEP_HZ s of game time
_DT_BASE_Q16 = (Q16 + STEP_HZ // 2) // STEP_HZ   # 1/60 in Q16.16, rounded


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

@dataclass
class State:
    """Spacecraft state in Q16.16: position (x, y) in wu, velocity in wu/s."""
    x: int
    y: int
    vx: int
    vy: int


def make_circular(r: float) -> State:
    """Place the ship at (r, 0) moving prograde (+y) at the circular speed for radius r."""
    v_circ = math.sqrt(MU / r)
    return State(x=to_q16(r), y=0, vx=0, vy=to_q16(v_circ))


# ---------------------------------------------------------------------------
# Integrator
# ---------------------------------------------------------------------------

def _tdiv(num: int, den: int) -> int:
    """Truncate-toward-zero division, matching ARM's SDIV / BIOS SWI 0x06."""
    if den == 0:
        return 0
    q = num // den
    if (num % den != 0) and ((num < 0) ^ (den < 0)):
        q += 1
    return q


def _step_one(s: State, dt_q16: int) -> None:
    """Single semi-implicit Euler substep, in-place."""
    x, y, vx, vy = s.x, s.y, s.vx, s.vy
    # |r|^2 in Q32 (would be a 64-bit intermediate on ARM, via SMULL+SMLAL).
    r_sq_raw = x * x + y * y
    if r_sq_raw <= 0:
        return
    # |r| in Q16: sqrt of Q32 = Q16.
    r_q16 = math.isqrt(r_sq_raw)
    if r_q16 == 0:
        return
    # Convert |r|^2 from Q32-raw to Q16: shift right by 16.
    r_sq_q16 = r_sq_raw >> 16
    # g = mu / |r|^2 in Q16. Result-format Q16: shift dividend by (16+16-0)=32.
    a_mag_q16 = (MU << 32) // r_sq_q16
    # a_vec = -a_mag * r_hat = -a_mag * (x, y) / |r|
    # (a_mag * x) is Q32 in raw; divide by r_q16 (Q16) to get back to Q16.
    ax = -_tdiv(a_mag_q16 * x, r_q16)
    ay = -_tdiv(a_mag_q16 * y, r_q16)
    # Semi-implicit Euler: kick then drift.
    vx += (ax * dt_q16) >> 16
    vy += (ay * dt_q16) >> 16
    x += (vx * dt_q16) >> 16
    y += (vy * dt_q16) >> 16
    s.x, s.y, s.vx, s.vy = x, y, vx, vy


def step_fx(s: State, substeps: int = 1) -> None:
    """Advance one frame with `substeps` physics substeps.

    Each substep ALWAYS advances game-time by 1/STEP_HZ s. Time-warp means
    more substeps per real-time frame, not larger steps:
      1x   warp -> 1 substep / frame  (60 game-Hz)
      10x  warp -> 10 substeps / frame
      100x warp -> 100 substeps / frame
    This keeps dt large enough to maintain Q16.16 precision at any warp level.
    """
    for _ in range(substeps):
        _step_one(s, _DT_BASE_Q16)


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

def specific_energy_q16(s: State) -> int:
    """E = v^2/2 - mu/r in Q16.16."""
    v_sq_raw = s.vx * s.vx + s.vy * s.vy  # Q32
    half_v_sq_q16 = v_sq_raw >> 17        # Q32 -> Q16 then /2 = >>17
    r_sq_raw = s.x * s.x + s.y * s.y
    if r_sq_raw <= 0:
        return 0
    r_q16 = math.isqrt(r_sq_raw)
    # mu/r in Q16: numerator must be (MU * Q16) in raw form, denominator is
    # r in Q16 (raw). To get the quotient in Q16, the numerator needs (MU<<32).
    mu_over_r_q16 = (MU << 32) // r_q16 if r_q16 > 0 else 0
    return half_v_sq_q16 - mu_over_r_q16


# ---------------------------------------------------------------------------
# Hohmann transfer
# ---------------------------------------------------------------------------

def hohmann_dv_total_q16(r1_q16: int, r2_q16: int) -> int:
    """Total impulsive delta-v for a Hohmann transfer between two circular orbits.

    delta_v = (v_peri - v_circ1) + (v_circ2 - v_apo)
    """
    r1 = from_q16(r1_q16)
    r2 = from_q16(r2_q16)
    a_t = 0.5 * (r1 + r2)
    v1 = math.sqrt(MU / r1)
    v2 = math.sqrt(MU / r2)
    v_peri = math.sqrt(MU * (2 / r1 - 1 / a_t))
    v_apo = math.sqrt(MU * (2 / r2 - 1 / a_t))
    return to_q16((v_peri - v1) + (v2 - v_apo))
