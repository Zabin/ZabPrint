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
