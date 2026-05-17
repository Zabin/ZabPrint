"""TDD oracle for fixed-point math used by physics.s on the GBA.

The Python implementation must be bit-identical to what the ARM port computes,
so every test asserts EXACT integer values, not float approximations.

Conventions:
  Q16.16  - 32-bit signed, 16 fractional bits.  ONE = 0x00010000.
  Q12.20  - 32-bit signed, 20 fractional bits.  ONE = 0x00100000.
  brad    - "binary radian", 16-bit unsigned. 0x10000 == 2*pi (full circle),
            matching GBA BIOS ArcTan2 convention.
"""
import math
import pytest

from toolchain.fixedpoint import (
    Q16, Q20, FX_PI_BRAD, FX_HALFPI_BRAD,
    to_q16, from_q16, to_q20, from_q20,
    fx_mul_q16, fx_div_q16, fx_sqrt_q16,
    fx_mul_q20, fx_div_q20,
    fx_sin, fx_cos, fx_atan2,
    sat32, asr32,
)


# ---------------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------------

def test_to_q16_one():
    assert to_q16(1.0) == 0x00010000

def test_to_q16_half():
    assert to_q16(0.5) == 0x00008000

def test_to_q16_negative_one():
    assert to_q16(-1.0) == -0x00010000

def test_to_q16_round_trip_small():
    for v in [0.0, 0.25, -0.25, 1.5, -3.75]:
        assert from_q16(to_q16(v)) == v

def test_to_q20_one():
    assert to_q20(1.0) == 0x00100000

def test_to_q20_range_fits_signed_32():
    # Q12.20 max positive ~ 2047.999...
    big = to_q20(2047.5)
    assert -2**31 <= big < 2**31


# ---------------------------------------------------------------------------
# Saturation / arithmetic shift right (match ARM behavior)
# ---------------------------------------------------------------------------

def test_sat32_clamps_high():
    assert sat32(2**31) == 0x7FFFFFFF
    assert sat32(2**40) == 0x7FFFFFFF

def test_sat32_clamps_low():
    assert sat32(-2**31 - 1) == -0x80000000
    assert sat32(-2**40) == -0x80000000

def test_sat32_passthrough():
    assert sat32(0) == 0
    assert sat32(12345) == 12345
    assert sat32(-12345) == -12345

def test_asr32_positive():
    assert asr32(0x40, 1) == 0x20

def test_asr32_negative_sign_extends():
    # -8 >> 1 == -4 in arithmetic shift
    assert asr32(-8, 1) == -4
    # -1 >> any == -1
    assert asr32(-1, 30) == -1


# ---------------------------------------------------------------------------
# Q16.16 multiplication
# ---------------------------------------------------------------------------

def test_fx_mul_q16_one_times_one():
    assert fx_mul_q16(Q16, Q16) == Q16

def test_fx_mul_q16_half_times_half():
    # 0.5 * 0.5 = 0.25
    assert fx_mul_q16(to_q16(0.5), to_q16(0.5)) == to_q16(0.25)

def test_fx_mul_q16_negative():
    # -1.5 * 2 = -3
    assert fx_mul_q16(to_q16(-1.5), to_q16(2.0)) == to_q16(-3.0)

def test_fx_mul_q16_truncation_matches_arm_smull_asr():
    # 0.1 * 0.1 in Q16: float is ~0.01. ARM does smull then asr #16 (signed).
    # Verify the truncated integer matches a hand calculation.
    a = to_q16(0.1)  # 6553
    b = to_q16(0.1)  # 6553
    # 6553 * 6553 = 42941809; >> 16 = 655 (asr).
    assert fx_mul_q16(a, b) == 655

def test_fx_mul_q16_negative_truncation_is_asr_not_floor():
    # -0.1 * 0.1: -6553 * 6553 = -42941809; asr #16 = -656 (sign-fills).
    a = to_q16(-0.1)
    b = to_q16(0.1)
    assert fx_mul_q16(a, b) == -656


# ---------------------------------------------------------------------------
# Q16.16 division
# ---------------------------------------------------------------------------

def test_fx_div_q16_one_over_one():
    assert fx_div_q16(Q16, Q16) == Q16

def test_fx_div_q16_one_over_two():
    assert fx_div_q16(Q16, to_q16(2.0)) == to_q16(0.5)

def test_fx_div_q16_negative():
    assert fx_div_q16(to_q16(-3.0), to_q16(2.0)) == to_q16(-1.5)

def test_fx_div_q16_by_zero_returns_max_int():
    # Sentinel value: divide-by-zero must not crash; physics avoids this case,
    # but the function must be defined. Convention: return INT32_MAX for x/0.
    assert fx_div_q16(Q16, 0) == 0x7FFFFFFF
    assert fx_div_q16(-Q16, 0) == -0x80000000


# ---------------------------------------------------------------------------
# Q16.16 square root
# ---------------------------------------------------------------------------

def test_fx_sqrt_q16_zero():
    assert fx_sqrt_q16(0) == 0

def test_fx_sqrt_q16_one():
    assert fx_sqrt_q16(Q16) == Q16

def test_fx_sqrt_q16_four():
    assert fx_sqrt_q16(to_q16(4.0)) == to_q16(2.0)

def test_fx_sqrt_q16_two_approx():
    # sqrt(2) in Q16: round to nearest unit. True value 92681.9... => 92681 or 92682.
    r = fx_sqrt_q16(to_q16(2.0))
    assert abs(r - 92682) <= 1

def test_fx_sqrt_q16_negative_returns_zero():
    # Defined behavior: sqrt of negative -> 0 (physics never feeds negatives).
    assert fx_sqrt_q16(-Q16) == 0

def test_fx_sqrt_q16_large_value():
    # sqrt(1000) ~ 31.6227... in Q16 -> 2072601.something
    r = fx_sqrt_q16(to_q16(1000.0))
    expected = int(math.sqrt(1000.0) * 65536)
    assert abs(r - expected) <= 1


# ---------------------------------------------------------------------------
# Q12.20 (for position; same algorithm, different shift)
# ---------------------------------------------------------------------------

def test_fx_mul_q20_one():
    assert fx_mul_q20(Q20, Q20) == Q20

def test_fx_mul_q20_large_position():
    # 1000 wu * 2 = 2000 wu, must not overflow.
    r = fx_mul_q20(to_q20(1000.0), to_q20(2.0))
    assert r == to_q20(2000.0)

def test_fx_div_q20_one_over_one():
    assert fx_div_q20(Q20, Q20) == Q20


# ---------------------------------------------------------------------------
# Sin / cos via 1024-entry quarter LUT, brad input
# ---------------------------------------------------------------------------

def test_fx_sin_zero():
    assert fx_sin(0) == 0

def test_fx_cos_zero():
    assert fx_cos(0) == Q16

def test_fx_sin_quarter_circle():
    # 90 degrees = 0x4000 brads. sin(90) = 1.0
    assert fx_sin(FX_HALFPI_BRAD) == Q16

def test_fx_cos_quarter_circle():
    # cos(90) = 0
    assert fx_cos(FX_HALFPI_BRAD) == 0

def test_fx_sin_half_circle():
    # sin(180) = 0
    assert fx_sin(FX_PI_BRAD) == 0

def test_fx_cos_half_circle():
    # cos(180) = -1
    assert fx_cos(FX_PI_BRAD) == -Q16

def test_fx_sin_three_quarter():
    # sin(270) = -1
    assert fx_sin(0xC000) == -Q16

def test_fx_cos_three_quarter():
    assert fx_cos(0xC000) == 0

def test_fx_sin_wraps_full_circle():
    # sin(360) == sin(0)
    assert fx_sin(0x10000 & 0xFFFF) == fx_sin(0)

def test_fx_sin_45_degrees():
    # 45 degrees = 0x2000 brads. sin(45) ~ 0.7071 -> 46340 in Q16.
    r = fx_sin(0x2000)
    expected = int(math.sin(math.pi / 4) * 65536)
    assert abs(r - expected) <= 64  # quarter-LUT quantization tolerance

def test_fx_sin_cos_identity_random():
    # sin^2 + cos^2 ~ 1 within LUT quantization
    for brad in [0x0123, 0x1234, 0x2345, 0x5678, 0x9ABC, 0xDEF0]:
        s = fx_sin(brad)
        c = fx_cos(brad)
        ss = fx_mul_q16(s, s)
        cc = fx_mul_q16(c, c)
        total = ss + cc
        # Allow ~0.5% drift from LUT quantization
        assert abs(total - Q16) < Q16 // 200


# ---------------------------------------------------------------------------
# atan2 (brad output to match BIOS SWI 0x09)
# ---------------------------------------------------------------------------

def test_fx_atan2_east():
    # atan2(0, +x) = 0
    assert fx_atan2(0, Q16) == 0

def test_fx_atan2_north():
    # atan2(+y, 0) = 90 deg = 0x4000
    assert fx_atan2(Q16, 0) == FX_HALFPI_BRAD

def test_fx_atan2_west():
    # atan2(0, -x) = 180 deg = 0x8000
    assert fx_atan2(0, -Q16) == FX_PI_BRAD

def test_fx_atan2_south():
    # atan2(-y, 0) = 270 deg = 0xC000
    assert fx_atan2(-Q16, 0) == 0xC000

def test_fx_atan2_origin_is_zero():
    # Degenerate: both zero -> defined as 0 to avoid NaN.
    assert fx_atan2(0, 0) == 0

def test_fx_atan2_45_degrees():
    # atan2(1, 1) ~ 45 deg = 0x2000
    r = fx_atan2(Q16, Q16)
    assert abs(r - 0x2000) <= 4

def test_fx_atan2_135_degrees():
    r = fx_atan2(Q16, -Q16)
    assert abs(r - 0x6000) <= 4

def test_fx_atan2_round_trip_sin_atan():
    # Take a brad angle, compute unit vector via sin/cos, atan2 should recover it
    for brad in [0x0345, 0x1567, 0x3789, 0x5ABC, 0x9111, 0xC234]:
        s = fx_sin(brad)
        c = fx_cos(brad)
        back = fx_atan2(s, c)
        # Allow ~0.1% (about 64 brad)
        diff = (back - brad) & 0xFFFF
        if diff > 0x8000:
            diff = 0x10000 - diff
        assert diff <= 64, f"brad {brad:04X}, recovered {back:04X}, diff {diff}"
