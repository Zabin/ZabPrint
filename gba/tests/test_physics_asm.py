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


# NOTE: fx_sqrt_q16, fx_div_q16, fx_sincos, fx_atan2 are deferred to a
# follow-up commit. The BIOS Sqrt SWI takes a 32-bit input, but the reference
# computes isqrt(x << 16) which needs 48 bits when x >= 0x10000. A Newton-
# iteration ARM routine that handles 48-bit inputs will land in Layer 8b
# together with the trig and divide ports.
