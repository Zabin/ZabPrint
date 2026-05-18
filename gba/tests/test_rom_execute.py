"""End-to-end ROM execution smoke test.

Loads `build/game.gba` into the ARMv4 interpreter with GBA-shaped memory
regions, pre-seeds the I/O registers so the vsync polls fall through, and
runs the boot path long enough to complete several frames.

The ROM implements an orbital sandbox: player + 3 targets orbit a single
primary at the screen centre. State at IWRAM 0x03000000:

   +0x00  player  { x_q16, y_q16, vx_q16, vy_q16 }
   +0x10  prev_keys
   +0x14  score
   +0x18  frame_count
   +0x20  target 0 { x_q16, y_q16, vx_q16, vy_q16 }
   +0x30  target 1
   +0x40  target 2
"""
from __future__ import annotations

import pytest

import build
from toolchain.armsim import ArmCpu


ROM_BASE   = 0x08000000
IWRAM_BASE = 0x03000000
VRAM_BASE  = 0x06000000
IO_BASE    = 0x04000000


@pytest.fixture(scope="module")
def rom_bytes() -> bytes:
    return build.build_rom()


class _FakeVCountCpu(ArmCpu):
    """Alternating VCOUNT reader so both crt0 vsync polls fall through in
    two reads."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._vcount_toggle = False

    def read_u16(self, addr: int) -> int:
        if addr == IO_BASE + 6:
            self._vcount_toggle = not self._vcount_toggle
            return 0 if self._vcount_toggle else 160
        return super().read_u16(addr)


def _make_cpu(rom: bytes, keyinput: int = 0xFFFF) -> _FakeVCountCpu:
    cpu = _FakeVCountCpu(regions=[
        (ROM_BASE,   2 * 1024 * 1024),
        (IWRAM_BASE, 32 * 1024),
        (VRAM_BASE,  96 * 1024),
        (IO_BASE,    1024),
    ])
    cpu.load_code(rom, at=ROM_BASE)
    cpu.write_u16(IO_BASE + 0x130, keyinput)
    cpu.regs[15] = ROM_BASE
    return cpu


def _s32(u: int) -> int:
    return u - 0x100000000 if u & 0x80000000 else u


def test_rom_runs_first_frame(rom_bytes):
    cpu = _make_cpu(rom_bytes)
    # Plenty of cycles for SP+DISPCNT setup, state init, and at least one
    # full frame (clear loop is ~38400 instructions on its own).
    cpu.run_for(400_000)
    assert cpu.read_u32(IO_BASE) == 0x0403, "DISPCNT should be mode 3 + BG2"


def test_rom_player_initial_position_q16(rom_bytes):
    """Player boots at (120, 40) -- 40 px above the central planet."""
    cpu = _make_cpu(rom_bytes)
    # Run just past the init-copy phase (small number of cycles).
    cpu.run_for(1500)
    assert cpu.read_u32(IWRAM_BASE + 0x00) == 120 << 16, "player_x should be 120 (Q16)"
    assert cpu.read_u32(IWRAM_BASE + 0x04) ==  40 << 16, "player_y should be 40 (Q16)"
    assert cpu.read_u32(IWRAM_BASE + 0x08) == 56756, "player_vx should be v_circ_40"
    assert cpu.read_u32(IWRAM_BASE + 0x0C) == 0, "player_vy should be 0"


def test_rom_targets_initial_orbits(rom_bytes):
    """All three targets boot at their seeded orbital states."""
    cpu = _make_cpu(rom_bytes)
    cpu.run_for(1500)
    # Target 0: (170, 80), v=(0, +50774)
    assert cpu.read_u32(IWRAM_BASE + 0x20) == 170 << 16
    assert cpu.read_u32(IWRAM_BASE + 0x24) ==  80 << 16
    assert cpu.read_u32(IWRAM_BASE + 0x28) == 0
    assert cpu.read_u32(IWRAM_BASE + 0x2C) == 50774
    # Target 1: (120, 110), v=(-65536, 0)
    assert cpu.read_u32(IWRAM_BASE + 0x30) == 120 << 16
    assert cpu.read_u32(IWRAM_BASE + 0x34) == 110 << 16
    assert _s32(cpu.read_u32(IWRAM_BASE + 0x38)) == -65536
    assert cpu.read_u32(IWRAM_BASE + 0x3C) == 0
    # Target 2: (60, 80), v=(0, -46341)
    assert cpu.read_u32(IWRAM_BASE + 0x40) ==  60 << 16
    assert cpu.read_u32(IWRAM_BASE + 0x44) ==  80 << 16
    assert cpu.read_u32(IWRAM_BASE + 0x48) == 0
    assert _s32(cpu.read_u32(IWRAM_BASE + 0x4C)) == -46341


def test_rom_score_starts_at_zero(rom_bytes):
    cpu = _make_cpu(rom_bytes)
    cpu.run_for(1500)
    assert cpu.read_u32(IWRAM_BASE + 0x14) == 0


def test_rom_element_cache_populated(rom_bytes):
    """After at least one frame, the element cache at S_PLAYER_EL (0x50) and
    S_TARGET_EL (0x60) should hold finite element values (a near orbital
    radius, e near zero for nearly-circular initial states)."""
    cpu = _make_cpu(rom_bytes)
    cpu.run_for(400_000)
    # Player boots at r=40, v=v_circ -> a ~ 40 in Q16 (= 40 << 16).
    a_player_q16 = _s32(cpu.read_u32(IWRAM_BASE + 0x50))
    # Allow ±8 px wobble from symplectic-Euler precession.
    assert (32 << 16) <= a_player_q16 <= (48 << 16), \
        f"player a should be near 40 Q16; got 0x{a_player_q16:08X}"
    e_player_q16 = cpu.read_u32(IWRAM_BASE + 0x54)
    # Circular -> e near zero. Allow up to 0.25 (Q16: 0x4000).
    assert e_player_q16 < 0x4000, f"player e should be small; got 0x{e_player_q16:08X}"


def test_rom_hud_a_bar_drawn(rom_bytes):
    """At y=3 (row 3), the player's a bar should paint cyan pixels (0x7FE0)
    starting at x=2 for a non-zero length. The clear loop spans most of each
    frame, so we poll over several windows to catch the post-render state."""
    cpu = _make_cpu(rom_bytes)
    pixel_addr = VRAM_BASE + ((3 * 240 + 2) * 2)
    seen_cyan = False
    for _ in range(20):
        cpu.run_for(50_000)
        if cpu.read_u16(pixel_addr) == 0x7FE0:
            seen_cyan = True
            break
    assert seen_cyan, "HUD a-bar pixel never observed cyan across 20 samples"


def test_rom_orbital_motion_advances_targets(rom_bytes):
    """After ~3 frames the targets have moved off their initial positions due
    to orbital integration. (Player too, but D-pad-free.)"""
    cpu = _make_cpu(rom_bytes)
    cpu.run_for(400_000)   # enough for several full frames

    t0_x = cpu.read_u32(IWRAM_BASE + 0x20)
    t0_y = cpu.read_u32(IWRAM_BASE + 0x24)
    # Target 0 boots at (170, 80) moving +y. After a few frames y has grown.
    assert t0_x != 170 << 16 or t0_y != 80 << 16, "target 0 should have moved"
    # Specifically y should be strictly larger (it was 0 vx, +50774 vy).
    assert t0_y > 80 << 16, f"target 0 y should be > 80<<16; got 0x{t0_y:08X}"


def test_rom_dew_fires_on_b_press(rom_bytes):
    """Holding B for the first frame triggers a DEW shot at the nearest in-
    range target. Boot positions: player (120, 40), target 0 (170, 80) ->
    d^2 = 4100, target 1 (120, 110) -> d^2 = 4900, target 2 (60, 80) -> 5200.
    DEW_RANGE_SQ = 4900, so targets 0 and 1 are in range but target 0 is
    closer. After the shot dew_cooldown sets to 30; target 0's health
    drops from 3 to 2; targets 1+2 are untouched."""
    cpu = _make_cpu(rom_bytes, keyinput=0xFFFF & ~0x02)
    cpu.run_for(80_000)
    cd = cpu.read_u32(IWRAM_BASE + 0xA8)
    assert cd >= 28, f"DEW should have fired (cooldown >= 28); got {cd}"
    health0 = cpu.read_u32(IWRAM_BASE + 0xAC + 0)
    assert health0 == 2, f"target 0 health should be 2 after one DEW hit; got {health0}"
    health1 = cpu.read_u32(IWRAM_BASE + 0xAC + 4)
    assert health1 == 3, f"target 1 untouched, should remain 3; got {health1}"


def test_rom_dew_inits_healths_to_three(rom_bytes):
    """All three targets start at DEW_INIT_HEALTH = 3."""
    cpu = _make_cpu(rom_bytes)
    cpu.run_for(1500)
    assert cpu.read_u32(IWRAM_BASE + 0xAC + 0) == 3
    assert cpu.read_u32(IWRAM_BASE + 0xAC + 4) == 3
    assert cpu.read_u32(IWRAM_BASE + 0xAC + 8) == 3


def test_rom_mission_state_initialised(rom_bytes):
    """mission_id (0=Deny), mission_target (0), hold_timers all zero at boot."""
    cpu = _make_cpu(rom_bytes)
    cpu.run_for(1500)
    assert cpu.read_u32(IWRAM_BASE + 0x90) == 0   # mission_id
    assert cpu.read_u32(IWRAM_BASE + 0x98) == 0   # mission_target
    assert cpu.read_u32(IWRAM_BASE + 0x9C) == 0   # hold_timer[0]
    assert cpu.read_u32(IWRAM_BASE + 0xA0) == 0   # hold_timer[1]
    assert cpu.read_u32(IWRAM_BASE + 0xA4) == 0   # hold_timer[2]


def test_rom_view_mode_defaults_to_eci(rom_bytes):
    cpu = _make_cpu(rom_bytes)
    cpu.run_for(1500)
    assert cpu.read_u32(IWRAM_BASE + 0x74) == 0


def test_rom_select_toggles_view_mode(rom_bytes):
    """Pressing SELECT (bit 2) once -> view_mode flips to 1 (RIC)."""
    cpu = _make_cpu(rom_bytes, keyinput=0xFFFF & ~0x04)
    cpu.run_for(80_000)
    assert cpu.read_u32(IWRAM_BASE + 0x74) == 1


def test_rom_ric_paints_target_at_screen_centre(rom_bytes):
    """In RIC mode, target 0 (the reference) must paint its 3x3 sprite at
    the screen centre (120, 80). Poll over several windows to catch a
    post-render state (clear loop fills most of each frame)."""
    cpu = _make_cpu(rom_bytes, keyinput=0xFFFF & ~0x04)
    pixel_addr = VRAM_BASE + ((80 * 240 + 120) * 2)
    seen_red = False
    for _ in range(20):
        cpu.run_for(50_000)
        if cpu.read_u16(pixel_addr) == 0x001F:
            seen_red = True
            break
    assert seen_red, "target 0 red sprite never observed at screen centre in RIC mode"


def test_rom_warp_inits_to_one(rom_bytes):
    """S_WARP at IWRAM 0x70 boots to 1 (real time)."""
    cpu = _make_cpu(rom_bytes)
    cpu.run_for(1500)
    assert cpu.read_u32(IWRAM_BASE + 0x70) == 1


def test_rom_r_cycles_warp_up(rom_bytes):
    """Pressing R once advances 1 -> 10."""
    cpu = _make_cpu(rom_bytes, keyinput=0xFFFF & ~0x100)
    cpu.run_for(80_000)
    assert cpu.read_u32(IWRAM_BASE + 0x70) == 10


def test_rom_warp_accelerates_orbit(rom_bytes):
    """At warp=1, target 0 advances slightly per frame. At warp=10, it
    advances ~10x as much in the same wall-clock cycles."""
    # Reference run: warp=1
    cpu_ref = _make_cpu(rom_bytes)
    cpu_ref.run_for(400_000)
    ref_y = _s32(cpu_ref.read_u32(IWRAM_BASE + 0x24)) >> 16

    # Warp run: press R once to get warp=10
    cpu_warp = _make_cpu(rom_bytes, keyinput=0xFFFF & ~0x100)
    cpu_warp.run_for(400_000)
    warp_y = _s32(cpu_warp.read_u32(IWRAM_BASE + 0x24)) >> 16

    # Target 0 starts at y=80 moving +y. After many substeps at warp=10
    # it should have travelled further from the start than at warp=1.
    assert abs(warp_y - 80) > abs(ref_y - 80), \
        f"warp=10 should advance target faster; got warp_y={warp_y} ref_y={ref_y}"


def test_rom_dv_inits_at_max(rom_bytes):
    """ship_dv at IWRAM 0x1C should boot to DV_MAX = 100 (Q16)."""
    cpu = _make_cpu(rom_bytes)
    cpu.run_for(1500)
    assert cpu.read_u32(IWRAM_BASE + 0x1C) == 0x00640000


def test_rom_prograde_burn_drains_dv(rom_bytes):
    """Holding Up triggers exactly one edge-detected prograde burn on the
    first frame; ship_dv decrements by one THRUST_COST unit (1<<16)."""
    cpu = _make_cpu(rom_bytes, keyinput=0xFFFF & ~0x40)
    cpu.run_for(400_000)
    dv = cpu.read_u32(IWRAM_BASE + 0x1C)
    # Multi-frame run: edge-detect means only ONE burn (first frame). After
    # that prev_keys == current_keys so bic returns 0 for the Up bit.
    assert dv == 0x00640000 - 0x00010000, \
        f"one burn should drop ship_dv by THRUST_COST; got 0x{dv:08X}"


def test_rom_prograde_burn_grows_speed(rom_bytes):
    """Prograde adds +BURN_DV along the unit v-vector. At boot v = (v_circ, 0),
    so prograde changes vx by +BURN_DV exactly. Orbital motion then evolves
    state, but |v| after one burn should remain strictly above the pre-burn
    circular-orbit |v|."""
    cpu = _make_cpu(rom_bytes, keyinput=0xFFFF & ~0x40)
    # Need enough cycles for: init -> first frame's vsync polls -> input
    # read -> burn dispatch -> cowell_step on 4 bodies -> clear loop. The
    # clear loop alone is ~38k instructions.
    cpu.run_for(80_000)
    vx = _s32(cpu.read_u32(IWRAM_BASE + 0x08))
    # Boot circular speed magnitude ~ 56756. After one prograde burn,
    # vx grew by +BURN_DV = 0x4000 in the burn block, then cowell_step
    # added the gravity kick (vy received a small negative bump, vx a
    # tiny one). |v| should be strictly above the boot circular value.
    assert vx > 56756, f"prograde should grow vx; got 0x{vx:08X}"


def test_rom_player_stays_bounded_under_orbit(rom_bytes):
    """No input: ship should stay roughly on a circle around the planet,
    not fly off to infinity. Check |r| < 150 after many frames."""
    cpu = _make_cpu(rom_bytes)
    cpu.run_for(600_000)
    px = _s32(cpu.read_u32(IWRAM_BASE + 0x00)) >> 16
    py = _s32(cpu.read_u32(IWRAM_BASE + 0x04)) >> 16
    dx = px - 120
    dy = py - 80
    r2 = dx * dx + dy * dy
    assert r2 < 150 * 150, f"player escaped: r^2={r2} (dx={dx}, dy={dy})"
