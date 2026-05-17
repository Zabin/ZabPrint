"""TDD oracle for the two-body Keplerian integrator.

Validates observable physics:
  * circular orbit closes on itself within tolerance after one period,
  * specific orbital energy E = v^2/2 - mu/r conserved to <0.1% over 10 periods
    at every supported time-warp level (1x, 10x, 100x),
  * Hohmann transfer delta-v matches the textbook analytic value within 1%.

The integrator is semi-implicit Euler (symplectic for separable Hamiltonians),
which has the energy-bounding behavior we rely on. Plain explicit Euler would
drift outward exponentially and would FAIL the energy test - by design.
"""
import math
import pytest

from toolchain.orbit import (
    MU, STEP_HZ,
    State, make_circular, step_fx,
    specific_energy_q16, hohmann_dv_total_q16,
)
from toolchain.fixedpoint import (
    Q16, to_q16, from_q16, fx_sqrt_q16,
)


# ---------------------------------------------------------------------------
# Reference values
# ---------------------------------------------------------------------------

R_TEST = 200.0                          # wu, design-target orbit radius
V_CIRC_FLOAT = math.sqrt(MU / R_TEST)   # ~41.83 wu/s
PERIOD_FLOAT = 2 * math.pi * math.sqrt(R_TEST ** 3 / MU)


# ---------------------------------------------------------------------------
# Sanity on the constants
# ---------------------------------------------------------------------------

def test_mu_design_target_period_about_30s():
    # The plan says: a 200-wu circular orbit ~ 30 s at 1x warp.
    assert 28.0 < PERIOD_FLOAT < 32.0

def test_step_hz_is_60():
    assert STEP_HZ == 60


# ---------------------------------------------------------------------------
# Construction helper
# ---------------------------------------------------------------------------

def test_make_circular_places_ship_on_x_axis():
    s = make_circular(R_TEST)
    assert s.x == to_q16(R_TEST)
    assert s.y == 0

def test_make_circular_velocity_is_tangential_and_correct_magnitude():
    s = make_circular(R_TEST)
    # vy = v_circ, vx = 0
    assert s.vx == 0
    # tolerance: Q16 unit
    assert abs(s.vy - to_q16(V_CIRC_FLOAT)) <= 2


# ---------------------------------------------------------------------------
# One-step smoke
# ---------------------------------------------------------------------------

def test_one_step_does_not_explode():
    s = make_circular(R_TEST)
    step_fx(s, substeps=1)
    # Radius should be very close to starting radius after one step
    r2 = (s.x / Q16) ** 2 + (s.y / Q16) ** 2
    assert abs(math.sqrt(r2) - R_TEST) < 0.5


# ---------------------------------------------------------------------------
# One period: ship returns near its starting position
# ---------------------------------------------------------------------------

def _integrate_seconds(state: State, seconds: float, warp_substeps: int = 1):
    """Drive the integrator for `seconds` of game time.

    Each physics substep advances game time by 1/STEP_HZ s. At warp W there
    are W substeps per real-time frame. To cover `seconds` of game time we
    need total_substeps = seconds * STEP_HZ, parceled out as
    total_substeps / W real-time frames.
    """
    total_substeps = int(round(seconds * STEP_HZ))
    full_frames, leftover = divmod(total_substeps, warp_substeps)
    for _ in range(full_frames):
        step_fx(state, substeps=warp_substeps)
    if leftover:
        step_fx(state, substeps=leftover)


def test_circular_orbit_closes_after_one_period_1x():
    s = make_circular(R_TEST)
    x0, y0 = s.x, s.y
    _integrate_seconds(s, PERIOD_FLOAT, warp_substeps=1)
    # Allow ~1 wu of position drift over one full period at 60 Hz
    dx = (s.x - x0) / Q16
    dy = (s.y - y0) / Q16
    drift = math.sqrt(dx * dx + dy * dy)
    assert drift < 2.0


# ---------------------------------------------------------------------------
# Energy conservation over 10 periods at every supported warp level
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("warp_substeps", [1, 10, 100])
def test_energy_conserved_over_10_periods(warp_substeps):
    s = make_circular(R_TEST)
    e0 = specific_energy_q16(s)
    # Total game-time is fixed; with warp_substeps physics substeps per frame,
    # we still play out the same number of *game-seconds*: 10 periods.
    _integrate_seconds(s, PERIOD_FLOAT * 10.0, warp_substeps=warp_substeps)
    e1 = specific_energy_q16(s)
    drift = abs(e1 - e0) / abs(e0)
    # <0.1% drift required by the plan; semi-implicit Euler easily hits this
    # for these step sizes.
    assert drift < 0.001, f"warp={warp_substeps} energy drift {drift:.5f}"


# ---------------------------------------------------------------------------
# Hohmann transfer delta-v
# ---------------------------------------------------------------------------

def _hohmann_analytic(r1, r2, mu):
    a_t = 0.5 * (r1 + r2)
    v1 = math.sqrt(mu / r1)
    v2 = math.sqrt(mu / r2)
    v_peri = math.sqrt(mu * (2 / r1 - 1 / a_t))
    v_apo = math.sqrt(mu * (2 / r2 - 1 / a_t))
    return (v_peri - v1) + (v2 - v_apo)


def test_hohmann_dv_matches_analytic_within_1pct():
    r1, r2 = 150.0, 300.0
    analytic = _hohmann_analytic(r1, r2, MU)
    computed_q16 = hohmann_dv_total_q16(to_q16(r1), to_q16(r2))
    computed = from_q16(computed_q16)
    err = abs(computed - analytic) / analytic
    assert err < 0.01, f"hohmann err {err:.4f}"


def test_hohmann_dv_outward_is_positive():
    dv = hohmann_dv_total_q16(to_q16(150.0), to_q16(300.0))
    assert dv > 0


# ---------------------------------------------------------------------------
# Specific energy on a circular orbit should equal -mu/(2r)
# ---------------------------------------------------------------------------

def test_specific_energy_circular_orbit_textbook():
    s = make_circular(R_TEST)
    e = from_q16(specific_energy_q16(s))
    analytic = -MU / (2 * R_TEST)
    assert abs(e - analytic) / abs(analytic) < 0.001
