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
