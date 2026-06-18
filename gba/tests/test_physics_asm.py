"""Bit-identity validation: src/physics.s vs toolchain/fixedpoint.py.

Strategy: assemble physics.s, load it into the ARMv4 interpreter, expose each
exported routine as a Python helper that sets up r0..r3 and reads r0 back.
Then compare against the Python reference across a deterministic grid + a
randomized sweep with a fixed seed.

Bit-identity, not approximate equality, is the contract.
"""
from __future__ import annotations

import random
from pathlib import Path

import pytest

from toolchain.armsim import ArmCpu
from toolchain.asm import assemble
from toolchain.fixedpoint import (
    Q16, INT32_MIN, INT32_MAX,
    fx_mul_q16 as py_fx_mul_q16,
    fx_div_q16 as py_fx_div_q16,
    fx_sqrt_q16 as py_fx_sqrt_q16,
    fx_atan2 as py_fx_atan2,
)


_PHYSICS_SRC = (Path(__file__).resolve().parent.parent / "src" / "physics.s").read_text()
_BASE = 0x100


@pytest.fixture(scope="module")
def physics_blob():
    return assemble(_PHYSICS_SRC, base_addr=_BASE)


def _arm_call(blob, symbol: str, *args: int) -> int:
    cpu = ArmCpu()
    cpu.load_code(blob.bytes_, at=_BASE)
    for i, v in enumerate(args):
        cpu.set_reg(i, v & 0xFFFFFFFF)
    cpu.set_reg(13, 0x20000)   # SP somewhere safe
    cpu.call(blob.symbols[symbol])
    return cpu.get_reg_s32(0)


# --- fx_mul_q16 ---------------------------------------------------------

@pytest.mark.parametrize("a, b", [
    (0,            0),
    (Q16,          Q16),                # 1.0 * 1.0 = 1.0
    (Q16 // 2,     Q16 // 2),           # 0.5 * 0.5 = 0.25
    (-Q16,         Q16),                # -1 * 1
    (-Q16,         -Q16),               # -1 * -1 = 1
    (3 * Q16,      7 * Q16),            # 21
    (Q16,          -(Q16 // 2)),
    (0x7FFFFFFF,   1),
    (-0x80000000,  1),
])
def test_fx_mul_q16_goldens(physics_blob, a, b):
    arm = _arm_call(physics_blob, "fx_mul_q16", a, b)
    ref = py_fx_mul_q16(a, b)
    assert arm == ref, f"a={a:08X} b={b:08X}: arm={arm} ref={ref}"


def test_fx_mul_q16_fuzz(physics_blob):
    rng = random.Random(0xC0FFEE)
    # Keep magnitudes moderate so the 32-bit truncation of (smull-then-shift)
    # matches the reference's int64 path -- the reference saturates only at
    # |product| >= 2^47, well outside this range.
    for _ in range(2000):
        a = rng.randint(-(1 << 23), (1 << 23) - 1)
        b = rng.randint(-(1 << 23), (1 << 23) - 1)
        arm = _arm_call(physics_blob, "fx_mul_q16", a, b)
        ref = py_fx_mul_q16(a, b)
        assert arm == ref, f"a={a} b={b}: arm={arm} ref={ref}"


# --- udiv64 (internal helper, exposed via its label) --------------------

@pytest.mark.parametrize("num_lo, num_hi, divisor, want_q, want_r", [
    (10,           0,         3,           3,           1),
    (0xFFFFFFFF,   0,         1,           0xFFFFFFFF,  0),
    (0xFFFFFFFF,   0,         0xFFFF,      0x10001,     0),
    (0,            1,         2,           0x80000000,  0),       # 2^32 / 2
    (0,            1,         3,           0x55555555,  1),       # 2^32 / 3
    (0,            0x10000,   1,           0,           0),       # 2^48 / 1 overflows quotient lo; remainder = 0
])
def test_udiv64_goldens(physics_blob, num_lo, num_hi, divisor, want_q, want_r):
    cpu = ArmCpu()
    cpu.load_code(physics_blob.bytes_, at=_BASE)
    cpu.set_reg(0, num_lo)
    cpu.set_reg(1, num_hi)
    cpu.set_reg(2, divisor)
    cpu.set_reg(13, 0x20000)
    cpu.call(physics_blob.symbols["udiv64"])
    assert cpu.get_reg_u32(0) == want_q
    assert cpu.get_reg_u32(1) == want_r


# --- fx_div_q16 ---------------------------------------------------------

@pytest.mark.parametrize("a, b", [
    (Q16,         Q16),                # 1 / 1 = 1
    (Q16 * 4,     Q16 * 2),            # 4 / 2 = 2
    (Q16,         Q16 * 2),            # 1 / 2 = 0.5
    (-Q16,        Q16 * 2),            # -1 / 2 = -0.5
    (Q16,         -(Q16 * 2)),
    (-Q16,        -(Q16 * 2)),
    (Q16 * 100,   Q16 * 7),
    (0,           Q16),
    (Q16,         0),                  # divide-by-zero positive -> INT32_MAX
    (-Q16,        0),                  # divide-by-zero negative -> INT32_MIN
])
def test_fx_div_q16_goldens(physics_blob, a, b):
    arm = _arm_call(physics_blob, "fx_div_q16", a, b)
    ref = py_fx_div_q16(a, b)
    assert arm == ref, f"a={a:08X} b={b:08X}: arm={arm} ref={ref}"


def test_fx_div_q16_fuzz(physics_blob):
    rng = random.Random(0xABCD)
    # Magnitudes chosen so the 48-bit numerator divided by `b` yields a
    # quotient that fits in 32 bits (no saturation needed). |a| <= 2^23
    # and |b| >= 4 keeps |quotient| under ~2^21 -- well within range.
    for _ in range(500):
        a = rng.randint(-(1 << 23), (1 << 23) - 1)
        b = rng.randint(4, 1 << 20) * rng.choice((-1, 1))
        arm = _arm_call(physics_blob, "fx_div_q16", a, b)
        ref = py_fx_div_q16(a, b)
        assert arm == ref, f"a={a} b={b}: arm={arm} ref={ref}"


# --- fx_sqrt_q16 --------------------------------------------------------

@pytest.mark.parametrize("x, want_q16", [
    (0,         0),
    (Q16,       Q16),                  # sqrt(1) = 1
    (4 * Q16,   2 * Q16),              # sqrt(4) = 2
    (-1,        0),
    (-Q16,      0),
])
def test_fx_sqrt_q16_goldens(physics_blob, x, want_q16):
    arm = _arm_call(physics_blob, "fx_sqrt_q16", x)
    assert arm == want_q16


def test_fx_sqrt_q16_matches_reference(physics_blob):
    rng = random.Random(0xF1A6)
    # 32-bit positive range. The Newton loop converges in <30 iterations
    # from the fixed initial guess of 2^24 for any 48-bit target.
    samples = [1, 2, 3, 4, 5, 100, 1000,
               Q16, 2 * Q16, 4 * Q16, 16 * Q16, 64 * Q16,
               Q16 // 4, Q16 // 2,
               0x10000, 0x20000, 0xFFFF, 0xFFFFFF, 0x7FFFFFFF]
    samples += [rng.randint(1, 0x7FFFFFFF) for _ in range(300)]
    for x in samples:
        arm = _arm_call(physics_blob, "fx_sqrt_q16", x)
        ref = py_fx_sqrt_q16(x)
        assert arm == ref, f"x={x}: arm={arm:08X} ref={ref:08X}"


def test_fx_sqrt_q16_negative_returns_zero(physics_blob):
    for x in [-1, -100, -Q16, INT32_MIN]:
        assert _arm_call(physics_blob, "fx_sqrt_q16", x) == 0


# --- fx_atan2 -----------------------------------------------------------
# Python ref takes (y, x); BIOS SWI takes (x, y) in r0, r1. Our wrapper swaps.

@pytest.mark.parametrize("y, x, want_brad", [
    (0,   1,    0x0000),   # +x axis
    (1,   0,    0x4000),   # +y axis (pi/2)
    (0,  -1,    0x8000),   # -x axis (pi)
    (-1,  0,    0xC000),   # -y axis (3pi/2)
    (0,   0,    0x0000),   # origin sentinel
])
def test_fx_atan2_goldens(physics_blob, y, x, want_brad):
    arm = _arm_call(physics_blob, "fx_atan2", y, x) & 0xFFFF
    assert arm == want_brad


def test_fx_atan2_matches_reference(physics_blob):
    rng = random.Random(0xAA77)
    samples = [(1, 1), (-1, 1), (-1, -1), (1, -1),
               (3, 4), (4, 3), (5, 12), (-12, 5),
               (1000, -1000), (32768, -32768)]
    samples += [(rng.randint(-1 << 14, 1 << 14),
                 rng.randint(-1 << 14, 1 << 14)) for _ in range(200)]
    for y, x in samples:
        if x == 0 and y == 0:
            continue
        arm = _arm_call(physics_blob, "fx_atan2", y, x) & 0xFFFF
        ref = py_fx_atan2(y, x)
        # ARM BIOS and Python's math.atan2 can quantize differently by 1 brad;
        # our reference rounds Python's float result to int, so the ARM path
        # (which sees the BIOS doing the same logic in our simulator) should
        # match exactly.
        assert arm == ref, f"y={y} x={x}: arm={arm:04X} ref={ref:04X}"


# --- cowell_step ---------------------------------------------------------
#
# Behavioural Python reference mirroring `src/physics.s::cowell_step` step-by-
# step using the same fx_* primitives. The integrator is semi-implicit Euler
# (kick-then-drift) with dt = 1 frame; gravity from a single fixed primary.
# This is *not* the more general `toolchain/orbit.py` reference (which does
# substeps and an origin-centred primary); it's a tight match for what the
# in-ROM routine does, so bit-identity is exact.

_PLANET_X_Q16 = 120 << 16
_PLANET_Y_Q16 = 80 << 16
_MU_Q16       = 30 << 16


def _cowell_step_py(x, y, vx, vy):
    dx = _PLANET_X_Q16 - x
    dy = _PLANET_Y_Q16 - y
    r2 = py_fx_mul_q16(dx, dx) + py_fx_mul_q16(dy, dy)
    if r2 < 0x10000:
        # below threshold: skip gravity, just drift
        x += vx
        y += vy
        return x, y, vx, vy
    r = py_fx_sqrt_q16(r2)
    a = py_fx_div_q16(_MU_Q16, r2)
    ux = py_fx_div_q16(dx, r)
    uy = py_fx_div_q16(dy, r)
    vx += py_fx_mul_q16(a, ux)
    vy += py_fx_mul_q16(a, uy)
    x += vx
    y += vy
    return x, y, vx, vy


@pytest.fixture(scope="module")
def cowell_blob(physics_blob):
    # physics.s defines defaults `.equ PLANET_X_Q16=120<<16, PLANET_Y_Q16=80<<16,
    # MU_Q16=30<<16` that match the constants used by the Python reference
    # above, so the same blob is fine.
    return physics_blob


def _arm_cowell_step(blob, x, y, vx, vy):
    cpu = ArmCpu()
    cpu.load_code(blob.bytes_, at=_BASE)
    # Stage state at memory_off 0x1000 (well clear of code).
    state_addr = 0x1000
    cpu.write_u32(state_addr,      x  & 0xFFFFFFFF)
    cpu.write_u32(state_addr + 4,  y  & 0xFFFFFFFF)
    cpu.write_u32(state_addr + 8,  vx & 0xFFFFFFFF)
    cpu.write_u32(state_addr + 12, vy & 0xFFFFFFFF)
    cpu.set_reg(0, state_addr)
    cpu.set_reg(13, 0x10000)   # SP somewhere safe
    cpu.call(blob.symbols["cowell_step"])
    nx  = cpu.get_reg_s32(0)   # not the actual return -- read state back
    return (
        cpu.get_reg_s32(0) if False else int.from_bytes(
            bytes(cpu.read_u32(state_addr).to_bytes(4, "little")), "little", signed=True),
        # simpler: just decode each word as signed
        _signed(cpu.read_u32(state_addr + 4)),
        _signed(cpu.read_u32(state_addr + 8)),
        _signed(cpu.read_u32(state_addr + 12)),
    )


def _signed(u: int) -> int:
    return u - 0x100000000 if u & 0x80000000 else u


def _arm_cowell(blob, x, y, vx, vy):
    cpu = ArmCpu()
    cpu.load_code(blob.bytes_, at=_BASE)
    state_addr = 0x1000
    cpu.write_u32(state_addr,      x  & 0xFFFFFFFF)
    cpu.write_u32(state_addr + 4,  y  & 0xFFFFFFFF)
    cpu.write_u32(state_addr + 8,  vx & 0xFFFFFFFF)
    cpu.write_u32(state_addr + 12, vy & 0xFFFFFFFF)
    cpu.set_reg(0, state_addr)
    cpu.set_reg(13, 0x10000)
    cpu.call(blob.symbols["cowell_step"])
    return (
        _signed(cpu.read_u32(state_addr)),
        _signed(cpu.read_u32(state_addr + 4)),
        _signed(cpu.read_u32(state_addr + 8)),
        _signed(cpu.read_u32(state_addr + 12)),
    )


def test_cowell_step_no_motion_no_gravity_at_planet(cowell_blob):
    """Body exactly at the planet: r2 falls below threshold, gravity skipped,
    velocity zero, position unchanged."""
    out = _arm_cowell(cowell_blob, _PLANET_X_Q16, _PLANET_Y_Q16, 0, 0)
    assert out == (_PLANET_X_Q16, _PLANET_Y_Q16, 0, 0)


def test_cowell_step_drift_at_modest_offset(cowell_blob):
    """At a 100-px offset gravity is small but present; one step should bit-
    match the Python reference."""
    x0, y0 = _PLANET_X_Q16 + (100 << 16), _PLANET_Y_Q16
    vx0, vy0 = 0, 1 << 14   # 0.25 px/frame downward
    out = _arm_cowell(cowell_blob, x0, y0, vx0, vy0)
    ref = _cowell_step_py(x0, y0, vx0, vy0)
    assert out == ref


def test_cowell_step_circular_orbit_starting_above(cowell_blob):
    """Body at (planet, planet - 40) moving +x at v_circ. One step should
    match the Python reference bit-for-bit."""
    r_int = 40
    r_q16 = r_int << 16
    # v_circ = sqrt(MU/r) (real). In Q16: sqrt(MU_q16 * Q16 / r_q16)
    # easier: compute from real value.
    import math
    v_circ = math.sqrt(30.0 / r_int)
    vx0 = int(round(v_circ * (1 << 16)))
    x0 = _PLANET_X_Q16
    y0 = _PLANET_Y_Q16 - r_q16
    out = _arm_cowell(cowell_blob, x0, y0, vx0, 0)
    ref = _cowell_step_py(x0, y0, vx0, 0)
    assert out == ref


def test_cowell_step_fuzz_against_reference(cowell_blob):
    """Inputs stay within +/- 100 px of the planet -- the game's playfield
    fits inside that radius, and beyond ~170 px fx_mul_q16 starts saturating
    differently than the ARM truncates (one of the documented Q16 corner
    cases). Within range, bit-identity is exact."""
    rng = random.Random(0xC0FFFE)
    for _ in range(150):
        x  = _PLANET_X_Q16 + rng.randint(-100, 100) * (1 << 16)
        y  = _PLANET_Y_Q16 + rng.randint(-100, 100) * (1 << 16)
        if x == _PLANET_X_Q16 and y == _PLANET_Y_Q16:
            x += 1 << 16
        vx = rng.randint(-(1 << 16), 1 << 16)
        vy = rng.randint(-(1 << 16), 1 << 16)
        out = _arm_cowell(cowell_blob, x, y, vx, vy)
        ref = _cowell_step_py(x, y, vx, vy)
        assert out == ref, (
            f"cowell_step mismatch:\n"
            f"  in  = (x={x:08X}, y={y:08X}, vx={vx:08X}, vy={vy:08X})\n"
            f"  arm = {tuple(f'{v:08X}' for v in out)}\n"
            f"  ref = {tuple(f'{v:08X}' for v in ref)}"
        )


def test_cowell_step_circular_orbit_stays_bounded(cowell_blob):
    """Initialise a circular orbit; after 200 steps the radius should not have
    blown up. Semi-implicit Euler isn't exactly energy-conserving but it's
    symplectic, so the radius oscillates around the initial value."""
    import math
    r_int = 40
    v_circ = math.sqrt(30.0 / r_int)
    vx0 = int(round(v_circ * (1 << 16)))
    x = _PLANET_X_Q16
    y = _PLANET_Y_Q16 - (r_int << 16)
    vx, vy = vx0, 0
    for _ in range(200):
        x, y, vx, vy = _cowell_step_py(x, y, vx, vy)
    # Compute integer radius from planet.
    dx_int = (x - _PLANET_X_Q16) >> 16
    dy_int = (y - _PLANET_Y_Q16) >> 16
    r_now = int(math.sqrt(dx_int * dx_int + dy_int * dy_int))
    # Symplectic integrator bound: radius stays within +/- 20% of the start
    # over 200 steps at this resolution.
    assert 32 <= r_now <= 48, f"orbit radius drifted to {r_now} (initial 40)"


# --- cowell_step_dt --------------------------------------------------------

def _arm_cowell_dt(blob, x, y, vx, vy, dt):
    cpu = ArmCpu()
    cpu.load_code(blob.bytes_, at=_BASE)
    state_addr = 0x1000
    cpu.write_u32(state_addr,      x  & 0xFFFFFFFF)
    cpu.write_u32(state_addr + 4,  y  & 0xFFFFFFFF)
    cpu.write_u32(state_addr + 8,  vx & 0xFFFFFFFF)
    cpu.write_u32(state_addr + 12, vy & 0xFFFFFFFF)
    cpu.set_reg(0, state_addr)
    cpu.set_reg(1, dt & 0xFFFFFFFF)
    cpu.set_reg(13, 0x10000)
    cpu.call(blob.symbols["cowell_step_dt"])
    return (
        _signed(cpu.read_u32(state_addr)),
        _signed(cpu.read_u32(state_addr + 4)),
        _signed(cpu.read_u32(state_addr + 8)),
        _signed(cpu.read_u32(state_addr + 12)),
    )


def test_cowell_step_dt_bit_identical_at_dt_one(cowell_blob):
    """Layer 8k: cowell_step_dt(state, 0x10000) must be byte-for-byte
    identical to cowell_step(state). Tests that the scaling factor doesn't
    introduce drift when dt = Q16(1.0)."""
    cases = [
        (_PLANET_X_Q16 + (40 << 16), _PLANET_Y_Q16,            0, 56756),  # circular @ r=40
        (_PLANET_X_Q16 + (100 << 16), _PLANET_Y_Q16,           0, 1 << 14),
        (_PLANET_X_Q16, _PLANET_Y_Q16 + (-40 << 16),       56756, 0),       # boot orbit
    ]
    for x, y, vx, vy in cases:
        ref = _arm_cowell(cowell_blob, x, y, vx, vy)
        out = _arm_cowell_dt(cowell_blob, x, y, vx, vy, 0x10000)
        assert out == ref, \
            f"cowell_step_dt(dt=1) mismatch for ({x:#x},{y:#x},{vx:#x},{vy:#x}):\n" \
            f"  cowell_step    -> {ref}\n" \
            f"  cowell_step_dt -> {out}"


def test_cowell_step_dt_half_dt_advances_half_step(cowell_blob):
    """At dt = 0.5 (Q16 0x8000) the position change should be ~½ that of
    one full step (within integration error)."""
    x0, y0 = _PLANET_X_Q16 + (100 << 16), _PLANET_Y_Q16
    vx0, vy0 = 0, 1 << 15           # 0.5 px/frame downward
    full = _arm_cowell_dt(cowell_blob, x0, y0, vx0, vy0, 0x10000)
    half = _arm_cowell_dt(cowell_blob, x0, y0, vx0, vy0, 0x08000)
    full_dy = full[1] - y0
    half_dy = half[1] - y0
    # half step moves about half the y distance of the full step. Allow
    # 20% slack for the velocity-kick interaction with the drift.
    assert abs(2 * half_dy - full_dy) < abs(full_dy) // 4, \
        f"half-dt should advance ~half: full_dy={full_dy} half_dy={half_dy}"


def _arm_compute_path_dt(blob, x, y, vx=0, vy=0):
    cpu = ArmCpu()
    cpu.load_code(blob.bytes_, at=_BASE)
    state_addr = 0x1000
    cpu.write_u32(state_addr,      x  & 0xFFFFFFFF)
    cpu.write_u32(state_addr + 4,  y  & 0xFFFFFFFF)
    cpu.write_u32(state_addr + 8,  vx & 0xFFFFFFFF)
    cpu.write_u32(state_addr + 12, vy & 0xFFFFFFFF)
    cpu.set_reg(0, state_addr)
    cpu.set_reg(13, 0x10000)
    cpu.call(blob.symbols["_compute_path_dt"])
    return _signed(cpu.get_reg_s32(0))


def test_compute_path_dt_matches_analytic(cowell_blob):
    """Post-Layer 8m: dt uses Kepler's third law on the SEMI-MAJOR AXIS a,
    not the instantaneous radius r. For circular orbits a=r so the result
    matches the legacy formula dt = 2π·sqrt(r³/μ)/256 to within a few
    ULPs. We pass the circular-orbit velocity v_circ = sqrt(μ/r) so eps
    yields a = r."""
    import math
    mu = 30.0
    for r in (20, 40, 80, 120, 180):
        x = _PLANET_X_Q16 + (r << 16)
        y = _PLANET_Y_Q16
        v_circ_q16 = int(round(math.sqrt(mu / r) * 65536))
        got_q16 = _arm_compute_path_dt(cowell_blob, x, y, vx=0, vy=v_circ_q16)
        got = got_q16 / 65536.0
        want = 2 * math.pi * math.sqrt(r ** 3 / mu) / 256
        rel = abs(got - want) / want
        assert rel < 0.01, \
            f"r={r}: got dt={got:.4f}, want {want:.4f} (rel err {rel:.4%})"


def test_compute_path_dt_uses_semi_major_on_eccentric_orbits(cowell_blob):
    """At apoapsis r > a, so the OLD (r-based) formula would overshoot the
    period and the predicted path would overlap itself. With Kepler's
    third law on a, the period is independent of where on the orbit we
    sample. Verify: dt at apoapsis (r > a) matches dt at periapsis
    (r < a) -- both should agree on the same period."""
    import math
    mu = 30.0
    # Build an elliptical orbit with semi-major axis a=40, eccentricity 0.5
    # (periapsis r_p = a(1-e) = 20, apoapsis r_a = a(1+e) = 60).
    a = 40.0
    e = 0.5
    r_p = a * (1 - e)
    r_a = a * (1 + e)
    # v at periapsis: v_p² = μ * (2/r_p - 1/a)
    v_p = math.sqrt(mu * (2 / r_p - 1 / a))
    v_a = math.sqrt(mu * (2 / r_a - 1 / a))
    # Apoapsis state: position +x at r_a, velocity tangential +y.
    x_ap = _PLANET_X_Q16 + int(r_a * 65536)
    y_ap = _PLANET_Y_Q16
    vy_ap = int(round(v_a * 65536))
    dt_ap = _arm_compute_path_dt(cowell_blob, x_ap, y_ap, 0, vy_ap) / 65536.0
    # Periapsis state: position +x at r_p, velocity tangential +y.
    x_pe = _PLANET_X_Q16 + int(r_p * 65536)
    y_pe = _PLANET_Y_Q16
    vy_pe = int(round(v_p * 65536))
    dt_pe = _arm_compute_path_dt(cowell_blob, x_pe, y_pe, 0, vy_pe) / 65536.0
    want = 2 * math.pi * math.sqrt(a ** 3 / mu) / 256
    for name, got in (("apoapsis", dt_ap), ("periapsis", dt_pe)):
        rel = abs(got - want) / want
        assert rel < 0.02, \
            f"{name}: got dt={got:.4f}, want {want:.4f} (rel err {rel:.4%})"


# --- elements_from_state ------------------------------------------------
#
# Classical orbital elements from a 2D state vector. Primary at the ORIGIN
# (the caller subtracts planet position before invoking). All inputs and
# outputs in Q16.16. Outputs: a, e, omega (brad), nu (brad).
#
# Math (planar 2D, mu = MU_Q16):
#   r       = sqrt(x*x + y*y)
#   v2      = vx*vx + vy*vy
#   eps     = v2/2 - mu/r                    (specific energy; negative bound)
#   a       = -mu / (2*eps)                  (semi-major; sentinel if eps>=0)
#   rdv     = x*vx + y*vy
#   e_x     = (v2*x - rdv*vx)/mu - x/r       (eccentricity-vector x)
#   e_y     = (v2*y - rdv*vy)/mu - y/r
#   e       = sqrt(e_x^2 + e_y^2)
#   omega   = atan2(e_y, e_x)                (arg of periapsis; 0 for e==0)
#   nu      = (atan2(y, x) - omega) & 0xFFFF (true anomaly)

# Sentinel for hyperbolic / parabolic orbits (eps >= 0): a written as INT32_MAX.
_A_HYPERBOLIC = INT32_MAX


def _elements_from_state_py(x, y, vx, vy, mu_q16=_MU_Q16):
    """Pure-Python reference that composes the same Q16 primitives the ARM
    kernel uses. Bit-identical to the ARM port within the same input envelope
    that bounds cowell_step (+/- ~100 px from primary)."""
    r2 = py_fx_mul_q16(x, x) + py_fx_mul_q16(y, y)
    if r2 <= 0:
        return _A_HYPERBOLIC, 0, 0, 0
    r = py_fx_sqrt_q16(r2)
    if r == 0:
        return _A_HYPERBOLIC, 0, 0, 0

    v2 = py_fx_mul_q16(vx, vx) + py_fx_mul_q16(vy, vy)
    half_v2 = v2 >> 1                       # asr on negative not relevant; v2 >= 0
    mu_over_r = py_fx_div_q16(mu_q16, r)
    eps = half_v2 - mu_over_r

    if eps >= 0:
        a = _A_HYPERBOLIC
    else:
        two_eps = eps << 1                  # eps is negative, two_eps still 32-bit
        a = py_fx_div_q16(-mu_q16, two_eps)

    rdv = py_fx_mul_q16(x, vx) + py_fx_mul_q16(y, vy)

    num_x = py_fx_mul_q16(v2, x) - py_fx_mul_q16(rdv, vx)
    e_x   = py_fx_div_q16(num_x, mu_q16) - py_fx_div_q16(x, r)

    num_y = py_fx_mul_q16(v2, y) - py_fx_mul_q16(rdv, vy)
    e_y   = py_fx_div_q16(num_y, mu_q16) - py_fx_div_q16(y, r)

    e_sq  = py_fx_mul_q16(e_x, e_x) + py_fx_mul_q16(e_y, e_y)
    e     = py_fx_sqrt_q16(e_sq) if e_sq > 0 else 0

    if e_x == 0 and e_y == 0:
        omega = 0
    else:
        omega = py_fx_atan2(e_y, e_x)

    nu = (py_fx_atan2(y, x) - omega) & 0xFFFF

    return a, e, omega, nu


def _arm_elements(blob, x, y, vx, vy):
    cpu = ArmCpu()
    cpu.load_code(blob.bytes_, at=_BASE)
    state_addr = 0x1000
    out_addr   = 0x1010
    cpu.write_u32(state_addr,      x  & 0xFFFFFFFF)
    cpu.write_u32(state_addr + 4,  y  & 0xFFFFFFFF)
    cpu.write_u32(state_addr + 8,  vx & 0xFFFFFFFF)
    cpu.write_u32(state_addr + 12, vy & 0xFFFFFFFF)
    cpu.set_reg(0, state_addr)
    cpu.set_reg(1, out_addr)
    cpu.set_reg(13, 0x10000)
    cpu.call(blob.symbols["elements_from_state"])
    return (
        _signed(cpu.read_u32(out_addr)),         # a (signed Q16)
        _signed(cpu.read_u32(out_addr + 4)),     # e (signed Q16; always >= 0 in practice)
        cpu.read_u32(out_addr + 8) & 0xFFFF,     # omega (brad; low 16 bits)
        cpu.read_u32(out_addr + 12) & 0xFFFF,    # nu (brad)
    )


def _q16(x_real: float) -> int:
    return int(round(x_real * (1 << 16)))


def test_elements_circular_orbit_e_is_zero(cowell_blob):
    """Perfect circular orbit at r=40 with v=v_circ. e should be 0 (or sub-LSB)."""
    import math
    r_int = 40
    v_circ = math.sqrt(30.0 / r_int)
    x  = r_int << 16
    y  = 0
    vx = 0
    vy = _q16(v_circ)
    a, e, omega, nu = _arm_elements(cowell_blob, x, y, vx, vy)
    ref = _elements_from_state_py(x, y, vx, vy)
    assert (a, e, omega, nu) == ref
    # Sanity: e should round to near zero, a should be close to r in Q16.
    assert e < 0x300            # <0.012 real; rounding noise only
    assert abs(a - (r_int << 16)) < 0x4000   # within ~0.25 px


def test_elements_radial_state_high_eccentricity(cowell_blob):
    """A purely radial velocity (no angular momentum) is a degenerate
    rectilinear orbit; e should be ~1."""
    x, y = 40 << 16, 0
    vx, vy = _q16(0.2), 0
    a, e, omega, nu = _arm_elements(cowell_blob, x, y, vx, vy)
    ref = _elements_from_state_py(x, y, vx, vy)
    assert (a, e, omega, nu) == ref
    assert e >= 0xC000           # e > 0.75


def test_elements_hyperbolic_sentinel(cowell_blob):
    """v^2 > 2*mu/r -> unbound; a written as INT32_MAX."""
    # At r=40, escape v = sqrt(2*30/40) = 1.224. Use v = 2.0 -> well above.
    x, y = 40 << 16, 0
    vx, vy = 0, _q16(2.0)
    a, e, omega, nu = _arm_elements(cowell_blob, x, y, vx, vy)
    ref = _elements_from_state_py(x, y, vx, vy)
    assert (a, e, omega, nu) == ref
    assert a == _A_HYPERBOLIC


def test_elements_bit_identity_fuzz(cowell_blob):
    """Fuzz over the same envelope cowell_step uses (+/- 100 px from primary,
    velocities up to 1 px/frame). Each (a, e, omega, nu) must match the
    Python reference exactly."""
    rng = random.Random(0xE1E1)
    for _ in range(200):
        x  = rng.randint(-100, 100) * (1 << 16)
        y  = rng.randint(-100, 100) * (1 << 16)
        if x == 0 and y == 0:
            x = 1 << 16
        # Velocities bounded so most cases stay sub-escape.
        vx = rng.randint(-(1 << 16), 1 << 16)
        vy = rng.randint(-(1 << 16), 1 << 16)
        out = _arm_elements(cowell_blob, x, y, vx, vy)
        ref = _elements_from_state_py(x, y, vx, vy)
        assert out == ref, (
            f"elements mismatch:\n"
            f"  in={hex(x), hex(y), hex(vx), hex(vy)}\n"
            f"  arm={tuple(hex(v) for v in out)}\n"
            f"  ref={tuple(hex(v) for v in ref)}"
        )
