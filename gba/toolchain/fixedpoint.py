"""Fixed-point math reference implementation.

This module is the TDD oracle for the ARM port in `src/physics.s`. Every
function uses Python ints to model 32-bit signed ARM arithmetic exactly: we
emulate `smull`+`asr`, signed `udiv` via BIOS SWI 0x06, BIOS `Sqrt` (SWI 0x0D),
BIOS `ArcTan2` (SWI 0x09), and the 1024-entry quarter sine LUT that ships in
ROM.

Q16.16 is used for velocities, scalars, sin/cos values.
Q12.20 is used for positions to give ±2048 wu of range with sub-micro
resolution. Both fit in a signed 32-bit register.

All arithmetic saturates to int32 on overflow (matches what the ARM code does
after smull -> asr -> qadd).
"""
import math

# ---------------------------------------------------------------------------
# Format constants
# ---------------------------------------------------------------------------

Q16 = 1 << 16          # 0x00010000 - 1.0 in Q16.16
Q20 = 1 << 20          # 0x00100000 - 1.0 in Q12.20

INT32_MIN = -0x80000000
INT32_MAX = 0x7FFFFFFF

# Binary radians: 0x10000 == 2*pi (one full revolution).
FX_TWOPI_BRAD = 0x10000
FX_PI_BRAD = 0x8000
FX_HALFPI_BRAD = 0x4000

# Sin LUT: 1024 entries covering [0, pi/2) in Q16.16.
# Endpoint sin(pi/2) is forced exactly to Q16 so quarter-circle tests are exact.
_SIN_LUT_BITS = 10  # 1024 entries
_SIN_LUT_SIZE = 1 << _SIN_LUT_BITS
_SIN_LUT = [int(round(math.sin(i / _SIN_LUT_SIZE * (math.pi / 2)) * Q16))
            for i in range(_SIN_LUT_SIZE)]


# ---------------------------------------------------------------------------
# Low-level ARM-shaped helpers
# ---------------------------------------------------------------------------

def sat32(x: int) -> int:
    """Saturate a Python int to signed 32-bit range."""
    if x > INT32_MAX:
        return INT32_MAX
    if x < INT32_MIN:
        return INT32_MIN
    return x


def asr32(x: int, n: int) -> int:
    """Arithmetic shift right of a 32-bit signed value, ARM semantics.

    Python's >> is already arithmetic for negative ints, but we go through
    a normalized signed-int path so behavior is unambiguous if a caller
    accidentally hands us a 64-bit intermediate.
    """
    if n <= 0:
        return sat32(x)
    return x >> n


# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------

def to_q16(v: float) -> int:
    """Convert a Python float to Q16.16, rounding to nearest."""
    return sat32(int(round(v * Q16)))


def from_q16(v: int) -> float:
    return v / Q16


def to_q20(v: float) -> int:
    return sat32(int(round(v * Q20)))


def from_q20(v: int) -> float:
    return v / Q20


# ---------------------------------------------------------------------------
# Q16.16 arithmetic
# ---------------------------------------------------------------------------

def fx_mul_q16(a: int, b: int) -> int:
    """(a * b) >> 16 with signed semantics. Mirrors `smull r0,r1,a,b; mov r0,r0,lsr#16; orr r0,r0,r1,lsl#16`."""
    # Compute 64-bit product, arithmetic shift right by 16.
    prod = a * b
    # asr by 16
    if prod < 0:
        # Python's >> on a negative int is arithmetic (floors toward -inf),
        # which matches ARM's ASR.
        r = prod >> 16
    else:
        r = prod >> 16
    return sat32(r)


def fx_div_q16(a: int, b: int) -> int:
    """(a << 16) / b. Returns sentinel INT32_MAX/MIN on divide-by-zero."""
    if b == 0:
        return INT32_MAX if a >= 0 else INT32_MIN
    # Shift then divide; trunc-toward-zero like ARM SWI Div.
    num = a << 16
    # Python // floors toward -inf, so we manually trunc toward zero.
    q = num // b
    if (num % b != 0) and ((num < 0) ^ (b < 0)):
        q += 1
    return sat32(q)


def fx_sqrt_q16(x: int) -> int:
    """Q16.16 sqrt. Negative input returns 0 (defined; physics never feeds neg)."""
    if x <= 0:
        return 0
    # sqrt(x) in Q16 = sqrt(x_int * 2^16) when x is already in Q16,
    # because the result of sqrt on a Q16 quantity is in Q8 -- so we scale up:
    #   want: out_int = sqrt(x_float) * 2^16
    #   x_int = x_float * 2^16
    #   sqrt(x_int) = sqrt(x_float) * 2^8
    # therefore out_int = sqrt(x_int << 16)
    target = x << 16
    # Integer sqrt via Newton's method.
    # Initial guess: 1 << ((bit_length(target) + 1) // 2)
    g = 1 << ((target.bit_length() + 1) >> 1)
    while True:
        ng = (g + target // g) >> 1
        if ng >= g:
            return sat32(g)
        g = ng


# ---------------------------------------------------------------------------
# Q12.20 arithmetic (positions)
# ---------------------------------------------------------------------------

def fx_mul_q20(a: int, b: int) -> int:
    prod = a * b
    return sat32(prod >> 20)


def fx_div_q20(a: int, b: int) -> int:
    if b == 0:
        return INT32_MAX if a >= 0 else INT32_MIN
    num = a << 20
    q = num // b
    if (num % b != 0) and ((num < 0) ^ (b < 0)):
        q += 1
    return sat32(q)


# ---------------------------------------------------------------------------
# Trig: sin/cos by quarter-LUT, brad input
# ---------------------------------------------------------------------------

def _sin_quarter(idx10: int) -> int:
    """Look up sine in first quadrant. idx10 is in [0, 1024]; 1024 returns 1.0 (Q16)."""
    if idx10 >= _SIN_LUT_SIZE:
        return Q16
    return _SIN_LUT[idx10]


def fx_sin(brad: int) -> int:
    """sin of a binary-radian angle, returning Q16.16."""
    brad &= 0xFFFF
    quadrant = brad >> 14         # 0..3
    in_quadrant = brad & 0x3FFF   # 0..0x3FFF
    # Map to 10-bit LUT index. We use upper 10 bits of the 14-bit in_quadrant
    # so quadrant boundaries hit exactly (0x4000 -> idx 1024 -> sin=1).
    if quadrant == 0:
        idx = in_quadrant >> 4
        return _sin_quarter(idx)
    if quadrant == 1:
        # sin(pi/2 + x) = cos(x) = sin(pi/2 - x) -> mirror index
        idx = (0x4000 - in_quadrant) >> 4
        return _sin_quarter(idx)
    if quadrant == 2:
        idx = in_quadrant >> 4
        return -_sin_quarter(idx)
    # quadrant == 3
    idx = (0x4000 - in_quadrant) >> 4
    return -_sin_quarter(idx)


def fx_cos(brad: int) -> int:
    """cos(theta) = sin(theta + pi/2)."""
    return fx_sin((brad + FX_HALFPI_BRAD) & 0xFFFF)


# ---------------------------------------------------------------------------
# atan2 (brad output, BIOS SWI 0x09 convention)
# ---------------------------------------------------------------------------

def fx_atan2(y: int, x: int) -> int:
    """atan2 returning a 16-bit binary angle. (0, 0) -> 0."""
    if x == 0 and y == 0:
        return 0
    # Use Python's math.atan2, then convert to brad. The ARM implementation will
    # use BIOS SWI 0x09 which behaves identically modulo 1 brad of quantization.
    rad = math.atan2(y, x)
    if rad < 0:
        rad += 2 * math.pi
    brad = int(round(rad * (0x10000 / (2 * math.pi))))
    return brad & 0xFFFF
