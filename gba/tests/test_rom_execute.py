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
    cpu.run_for(5000)
    assert cpu.read_u32(IWRAM_BASE + 0x00) == 120 << 16, "player_x should be 120 (Q16)"
    assert cpu.read_u32(IWRAM_BASE + 0x04) ==  40 << 16, "player_y should be 40 (Q16)"
    assert cpu.read_u32(IWRAM_BASE + 0x08) == 56756, "player_vx should be v_circ_40"
    assert cpu.read_u32(IWRAM_BASE + 0x0C) == 0, "player_vy should be 0"


def test_rom_targets_initial_orbits(rom_bytes):
    """All three targets boot at their seeded orbital states."""
    cpu = _make_cpu(rom_bytes)
    cpu.run_for(5000)
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
    cpu.run_for(5000)
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


def test_rom_bottom_half_vram_cleared(rom_bytes):
    """Layer 8f regression: the clear loop must wipe the WHOLE framebuffer,
    not just the top half. Pre-paint a known colour at a bottom-half pixel
    away from any sprite and verify the clear erases it within a frame."""
    cpu = _make_cpu(rom_bytes)
    addr = VRAM_BASE + ((130 * 240 + 200) * 2)
    cpu.write_u16(addr, 0x7C1F)                   # magenta sentinel
    seen_bg = False
    for _ in range(40):
        cpu.run_for(100_000)
        if cpu.read_u16(addr) == 0x0421:
            seen_bg = True
            break
    assert seen_bg, "pixel (200, 130) was never overwritten by the clear -- bottom half not being wiped"


def test_rom_path_first_point_matches_state(rom_bytes):
    """After the first frame's _refresh_paths runs, S_PATH_PLAYER[0]
    holds the player's position at the moment the path was computed,
    which is near (but not exactly) the boot value because one
    cowell_step has run first."""
    cpu = _make_cpu(rom_bytes)
    cpu.run_for(400_000)   # multiple frames; player path definitely populated
    px_q16 = _s32(cpu.read_u32(IWRAM_BASE + 0x160))      # S_PATH_PLAYER + 0
    py_q16 = _s32(cpu.read_u32(IWRAM_BASE + 0x164))      # S_PATH_PLAYER + 4
    # Reasonable bounds: player still orbits near (120, 40) +/- ~10 px in
    # the first few frames.
    px = px_q16 >> 16
    py = py_q16 >> 16
    assert 110 <= px <= 130, f"path[0].x = {px} should be near 120"
    assert 30 <= py <= 50, f"path[0].y = {py} should be near 40"


def test_rom_path_closes_on_circular_orbit(rom_bytes):
    """Layer 8k: with per-body period-aware dt, the 256-point path covers
    one full period, so path[0] and path[255] should be very close together
    for a circular orbit. Pre-fix (dt=1) only ~88% of an r=40 orbit was
    sampled, so path[255] sat well away from path[0]."""
    cpu = _make_cpu(rom_bytes)
    cpu.run_for(400_000)
    # Park player at (160, 80) on a clean circular orbit (r=40, CW).
    cpu.write_u32(IWRAM_BASE + 0x00, 160 << 16)
    cpu.write_u32(IWRAM_BASE + 0x04,  80 << 16)
    cpu.write_u32(IWRAM_BASE + 0x08, 0)
    cpu.write_u32(IWRAM_BASE + 0x0C, 56756)
    # Re-dirty the player path so _refresh_paths recomputes from new state.
    cpu.write_u32(IWRAM_BASE + 0x154, 0xF)
    cpu.run_for(2_000_000)              # several frames -> all 4 paths refresh
    p0_x = _s32(cpu.read_u32(IWRAM_BASE + 0x160)) >> 16
    p0_y = _s32(cpu.read_u32(IWRAM_BASE + 0x164)) >> 16
    # path[255] is at the LAST 8-byte slot: 0x160 + 255 * 8 = 0x958
    p_last_x = _s32(cpu.read_u32(IWRAM_BASE + 0x958)) >> 16
    p_last_y = _s32(cpu.read_u32(IWRAM_BASE + 0x95C)) >> 16
    # On a closed orbit, path[0] and path[255] sit at the start/end of
    # one full revolution -- within a few pixels of each other.
    dist_sq = (p_last_x - p0_x) ** 2 + (p_last_y - p0_y) ** 2
    assert dist_sq <= 25, \
        f"path[0]=({p0_x},{p0_y}) and path[255]=({p_last_x},{p_last_y}) " \
        f"expected to close on a circular orbit; d²={dist_sq}"


def _reset_player_to_phase_zero(cpu):
    """Place player at position-phase 0 (planet-relative +x axis at radius
    40) with tangential CW circular velocity, so the next frame's phase
    is just past 0x0000."""
    cpu.write_u32(IWRAM_BASE + 0x00, 160 << 16)    # planet_x + 40
    cpu.write_u32(IWRAM_BASE + 0x04,  80 << 16)    # planet_y
    cpu.write_u32(IWRAM_BASE + 0x08, 0)             # vx = 0
    cpu.write_u32(IWRAM_BASE + 0x0C, 56756)         # vy = +v_circ_40 (CW)


def test_rom_lap_cum_phase_tips_over_threshold(rom_bytes):
    """Layer 8m: with cumulative-delta orbit detection, seeding
    S_CUM_PHASE = 0xFFFF and running for one frame must increment the
    lap counter -- any positive Δphase pushes cum past 0x10000 and
    fires a lap."""
    cpu = _make_cpu(rom_bytes)
    cpu.run_for(400_000)
    _reset_player_to_phase_zero(cpu)
    cpu.write_u32(IWRAM_BASE + 0x94, 0)             # clear lap count
    cpu.write_u32(IWRAM_BASE + 0x158, 0)            # prev_phase = 0 (matches parked phase)
    cpu.write_u32(IWRAM_BASE + 0x15C, 0xFFFF)       # cum_phase one tick from wrap
    cpu.run_for(2_000_000)
    after = cpu.read_u32(IWRAM_BASE + 0x94)
    assert after >= 1, f"cum past 0x10000 should fire lap; got {after}"


def test_rom_lap_increments_on_real_circular_orbit(rom_bytes):
    """Pre-8i regression: a pure circular orbit (e≈0) never wraps because
    ν = atan2(y,x) - ω jitters with ω. Post-8i this passes because we
    detect wraps on position phase, not true anomaly. Run ~1.5 orbits at
    warp=10 (period ≈ 29 warp-frames at r=40) and assert at least one
    lap is registered."""
    cpu = _make_cpu(rom_bytes)
    cpu.run_for(400_000)
    _reset_player_to_phase_zero(cpu)
    cpu.write_u32(IWRAM_BASE + 0x94, 0)             # orbit_count = 0
    cpu.write_u32(IWRAM_BASE + 0x158, 0)            # clear prev_phase
    cpu.write_u32(IWRAM_BASE + 0x15C, 0)            # clear cum_phase
    cpu.write_u32(IWRAM_BASE + 0x70, 10)            # warp = 10
    cpu.run_for(20_000_000)                         # ~30 frames of motion at warp=10 = ≥1 period
    after = cpu.read_u32(IWRAM_BASE + 0x94)
    assert after >= 1, f"circular orbit should wrap at least once; got {after}"


def test_rom_orbit_count_resets_on_mission_advance(rom_bytes):
    """Force a DGRD mission to complete and verify S_ORBIT_COUNT resets."""
    cpu = _make_cpu(rom_bytes)
    cpu.run_for(400_000)
    cpu.write_u32(IWRAM_BASE + 0x94, 7)             # orbit count = 7
    cpu.write_u32(IWRAM_BASE + 0x90, 1)             # DGRD
    cpu.write_u32(IWRAM_BASE + 0x98, 0)             # mission_target = 0
    score_before = _s32(cpu.read_u32(IWRAM_BASE + 0x14))
    cpu.write_u32(IWRAM_BASE + 0xAC, 1)             # T_HEALTH[0] = 1
    cpu.write_u32(IWRAM_BASE + 0x00, 168 << 16)
    cpu.write_u32(IWRAM_BASE + 0x04, 80 << 16)
    cpu.write_u32(IWRAM_BASE + 0x08, 0)
    cpu.write_u32(IWRAM_BASE + 0x0C, 0)
    cpu.write_u16(IO_BASE + 0x130, 0xFFFF & ~0x02)   # B held
    cpu.run_for(2_000_000)
    score_after = _s32(cpu.read_u32(IWRAM_BASE + 0x14))
    orbit_after = cpu.read_u32(IWRAM_BASE + 0x94)
    assert score_after > score_before, "mission did not advance (no +5 reward)"
    assert orbit_after == 0, f"orbit count must reset on advance; got {orbit_after}"


def test_rom_deny_mission_fails_at_orbit_limit(rom_bytes):
    """DENY (mission_id=0) at orbit count 49 + one ν-wrap must cycle to
    DGRD (id 1), subtract 2 from score, and not refill DV."""
    cpu = _make_cpu(rom_bytes)
    cpu.run_for(400_000)
    _reset_player_to_phase_zero(cpu)
    cpu.write_u32(IWRAM_BASE + 0x90, 0)             # DENY
    cpu.write_u32(IWRAM_BASE + 0x94, 49)
    cpu.write_u32(IWRAM_BASE + 0x158, 0)            # prev_phase = 0
    cpu.write_u32(IWRAM_BASE + 0x15C, 0xFFFF)       # cum_phase one tick from wrap
    score_before = _s32(cpu.read_u32(IWRAM_BASE + 0x14))
    dv_before = cpu.read_u32(IWRAM_BASE + 0x1C)
    cpu.run_for(2_000_000)
    mission_after = cpu.read_u32(IWRAM_BASE + 0x90)
    score_after = _s32(cpu.read_u32(IWRAM_BASE + 0x14))
    dv_after = cpu.read_u32(IWRAM_BASE + 0x1C)
    assert mission_after == 1, f"DENY should cycle to DGRD; got id={mission_after}"
    assert score_after == score_before - 2, \
        f"fail penalty -2; before={score_before}, after={score_after}"
    assert dv_after <= dv_before, "fail should not refill DV"


def test_rom_dsrp_mission_fails_at_orbit_limit(rom_bytes):
    """DSRP (mission_id=2) at orbit count 49 + ν-wrap must cycle to
    DSTR (id 3)."""
    cpu = _make_cpu(rom_bytes)
    cpu.run_for(400_000)
    _reset_player_to_phase_zero(cpu)
    cpu.write_u32(IWRAM_BASE + 0x90, 2)             # DSRP
    cpu.write_u32(IWRAM_BASE + 0x94, 49)
    cpu.write_u32(IWRAM_BASE + 0x158, 0)            # prev_phase = 0
    cpu.write_u32(IWRAM_BASE + 0x15C, 0xFFFF)       # cum_phase one tick from wrap
    score_before = _s32(cpu.read_u32(IWRAM_BASE + 0x14))
    cpu.run_for(2_000_000)
    mission_after = cpu.read_u32(IWRAM_BASE + 0x90)
    score_after = _s32(cpu.read_u32(IWRAM_BASE + 0x14))
    assert mission_after == 3, f"DSRP should cycle to DSTR; got id={mission_after}"
    assert score_after == score_before - 2


def test_rom_word_data_tables_are_word_aligned():
    """Regression: `.align 2` in this assembler means 2-BYTE alignment
    (unlike GAS, which is 2^N). Tables that hold .word entries must use
    `.align 4`, otherwise ldr on real ARM7TDMI returns rotated data."""
    from toolchain.asm import assemble
    src = (open('/home/user/ZabPrint/gba/src/crt0.s').read()
           + open('/home/user/ZabPrint/gba/src/physics.s').read())
    r = assemble(src, base_addr=0x080000C0)
    for name in ['mission_names', 'mission_color_table',
                 'init_orbits', 'nose_dx', 'nose_dy']:
        addr = r.symbols[name]
        assert (addr & 3) == 0, (
            f"{name} @ 0x{addr:08X} is not word-aligned -- ldr will rotate "
            "the loaded word on real hardware"
        )


def test_rom_hud_dv_label_drawn(rom_bytes):
    """The 'D' glyph of the 'DV' label is painted at (2, 2). Its first row
    bitmap is 0b1110 -> pixels at (2,2), (3,2), (4,2) get the white label
    colour (0x7FFF). Poll for a post-render frame."""
    cpu = _make_cpu(rom_bytes)
    addr = VRAM_BASE + ((2 * 240 + 2) * 2)
    seen = False
    for _ in range(40):
        cpu.run_for(100_000)
        if cpu.read_u16(addr) == 0x7FFF:
            seen = True
            break
    assert seen, "DV label's leftmost pixel never observed white"


def test_rom_hud_view_label_eci_vs_ric(rom_bytes):
    """In ECI (default), the VIEW value paints 'ECI' starting at x=125, y=44
    in white. The 'E' glyph row 0 = 0b1111 -> pixel (125, 44) is white."""
    cpu = _make_cpu(rom_bytes)
    addr = VRAM_BASE + ((44 * 240 + 125) * 2)
    seen_white = False
    for _ in range(40):
        cpu.run_for(100_000)
        if cpu.read_u16(addr) == 0x7FFF:
            seen_white = True
            break
    assert seen_white, "ECI 'E' glyph never observed white at (125, 44)"


def test_rom_hud_score_label_renders(rom_bytes):
    """The 'S' glyph at (2, 145) is the leftmost of the SCORE label. S row 0
    = 0b0111 -> pixels (3,145), (4,145), (5,145) are green (0x03E0)."""
    cpu = _make_cpu(rom_bytes)
    addr = VRAM_BASE + ((145 * 240 + 3) * 2)
    seen = False
    for _ in range(40):
        cpu.run_for(100_000)
        if cpu.read_u16(addr) == 0x03E0:
            seen = True
            break
    assert seen, "SCORE label's S glyph never observed green"


def test_rom_hud_a_bar_drawn(rom_bytes):
    """The labeled HUD (Layer 8e) puts the player a bar at y=12 starting
    at x=20. With boot orbit r=40, the bar paints ~40 cyan pixels. Poll
    across sample windows because the clear loop dominates each frame."""
    cpu = _make_cpu(rom_bytes)
    pixel_addr = VRAM_BASE + ((12 * 240 + 20) * 2)
    seen_cyan = False
    for _ in range(40):
        cpu.run_for(100_000)
        if cpu.read_u16(pixel_addr) == 0x7FE0:
            seen_cyan = True
            break
    assert seen_cyan, "HUD a-bar pixel at (20, 12) never observed cyan"


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


def test_rom_player_plane_inits_zero(rom_bytes):
    cpu = _make_cpu(rom_bytes)
    cpu.run_for(5000)
    assert cpu.read_u32(IWRAM_BASE + 0xB8) == 0   # player_plane


def test_rom_start_toggles_plane_costs_dv(rom_bytes):
    """Pressing START with sufficient ΔV flips player_plane and subtracts
    PLANE_CHANGE_DV (25 << 16)."""
    cpu = _make_cpu(rom_bytes, keyinput=0xFFFF & ~0x08)
    cpu.run_for(200_000)
    plane = cpu.read_u32(IWRAM_BASE + 0xB8)
    dv = cpu.read_u32(IWRAM_BASE + 0x1C)
    assert plane == 1, f"plane should flip to 1; got {plane}"
    assert dv == 0x00640000 - 0x00190000, \
        f"plane change should cost 25 ΔV; ship_dv now 0x{dv:08X}"


def test_rom_sensor_dir_cached_each_frame(rom_bytes):
    """After at least one frame, S_SENSOR_DIR at IWRAM 0x150 holds
    atan2(player_vy, player_vx). Boot velocity is (+v_circ, 0) so the
    heading is 0 brad (positive-x axis)."""
    cpu = _make_cpu(rom_bytes)
    cpu.run_for(200_000)
    sensor_dir = cpu.read_u32(IWRAM_BASE + 0x150) & 0xFFFF
    # After a frame or two, gravity has nudged vy slightly positive (the body
    # falls toward the primary), so heading drifts a few hundred brad off
    # zero. Allow ±0x800 (≈ 11°) of slack.
    in_range = sensor_dir <= 0x800 or sensor_dir >= (0x10000 - 0x800)
    assert in_range, f"sensor_dir should be near 0 at boot; got 0x{sensor_dir:04X}"


def test_rom_grapple_target_inits_to_minus_one(rom_bytes):
    """S_GRAPPLE_TARGET at IWRAM 0xC8 boots to -1 (no active grapple)."""
    cpu = _make_cpu(rom_bytes)
    cpu.run_for(5000)
    assert _s32(cpu.read_u32(IWRAM_BASE + 0xC8)) == -1


def test_rom_grapple_acquires_nearest_same_plane_target(rom_bytes):
    """Holding A acquires the nearest in-range same-plane target. Boot
    distances don't put any target in range, so stage the player at (168, 80)
    with zero velocity beside target 0 (170, 80), then hold A and let a few
    frames run so the new keyinput is observed."""
    cpu = _make_cpu(rom_bytes)
    cpu.run_for(100_000)   # past init copy + first vsync wait
    cpu.write_u32(IWRAM_BASE + 0x00, 168 << 16)
    cpu.write_u32(IWRAM_BASE + 0x04, 80 << 16)
    cpu.write_u32(IWRAM_BASE + 0x08, 0)
    cpu.write_u32(IWRAM_BASE + 0x0C, 0)
    cpu.write_u16(IO_BASE + 0x130, 0xFFFF & ~0x01)
    cpu.run_for(2_000_000)
    g = _s32(cpu.read_u32(IWRAM_BASE + 0xC8))
    assert g == 0, f"grapple should lock target 0; got {g}"


def test_rom_grapple_releases_when_a_not_held(rom_bytes):
    """A not held -> S_GRAPPLE_TARGET reset to -1 every frame."""
    cpu = _make_cpu(rom_bytes)
    cpu.run_for(200_000)
    assert _s32(cpu.read_u32(IWRAM_BASE + 0xC8)) == -1


def test_rom_debris_slots_init_dead(rom_bytes):
    """All 4 debris alive flags are 0 at boot."""
    cpu = _make_cpu(rom_bytes)
    cpu.run_for(5000)
    for i in range(4):
        slot = IWRAM_BASE + 0xD0 + i * 32
        assert cpu.read_u32(slot + 16) == 0, f"debris {i} should boot dead"


def test_rom_dew_fires_on_b_press(rom_bytes):
    """Holding B for the first frame triggers a DEW shot at the nearest in-
    range target. Boot positions: player (120, 40), target 0 (170, 80) ->
    d^2 = 4100, target 1 (120, 110) -> d^2 = 4900, target 2 (60, 80) -> 5200.
    DEW_RANGE_SQ = 4900, so targets 0 and 1 are in range but target 0 is
    closer. After the shot dew_cooldown sets to 30; target 0's health
    drops from 3 to 2; targets 1+2 are untouched."""
    cpu = _make_cpu(rom_bytes, keyinput=0xFFFF & ~0x02)
    cpu.run_for(200_000)
    cd = cpu.read_u32(IWRAM_BASE + 0xA8)
    assert cd >= 28, f"DEW should have fired (cooldown >= 28); got {cd}"
    health0 = cpu.read_u32(IWRAM_BASE + 0xAC + 0)
    assert health0 == 2, f"target 0 health should be 2 after one DEW hit; got {health0}"
    health1 = cpu.read_u32(IWRAM_BASE + 0xAC + 4)
    assert health1 == 3, f"target 1 untouched, should remain 3; got {health1}"


def test_rom_dew_inits_healths_to_three(rom_bytes):
    """All three targets start at DEW_INIT_HEALTH = 3."""
    cpu = _make_cpu(rom_bytes)
    cpu.run_for(5000)
    assert cpu.read_u32(IWRAM_BASE + 0xAC + 0) == 3
    assert cpu.read_u32(IWRAM_BASE + 0xAC + 4) == 3
    assert cpu.read_u32(IWRAM_BASE + 0xAC + 8) == 3


def test_rom_mission_state_initialised(rom_bytes):
    """mission_id (0=Deny), mission_target (0), hold_timers all zero at boot."""
    cpu = _make_cpu(rom_bytes)
    cpu.run_for(5000)
    assert cpu.read_u32(IWRAM_BASE + 0x90) == 0   # mission_id
    assert cpu.read_u32(IWRAM_BASE + 0x98) == 0   # mission_target
    assert cpu.read_u32(IWRAM_BASE + 0x9C) == 0   # hold_timer[0]
    assert cpu.read_u32(IWRAM_BASE + 0xA0) == 0   # hold_timer[1]
    assert cpu.read_u32(IWRAM_BASE + 0xA4) == 0   # hold_timer[2]


def test_rom_view_mode_defaults_to_eci(rom_bytes):
    cpu = _make_cpu(rom_bytes)
    cpu.run_for(5000)
    assert cpu.read_u32(IWRAM_BASE + 0x74) == 0


def test_rom_select_toggles_view_mode(rom_bytes):
    """Pressing SELECT (bit 2) once -> view_mode flips to 1 (RIC)."""
    cpu = _make_cpu(rom_bytes, keyinput=0xFFFF & ~0x04)
    cpu.run_for(200_000)
    assert cpu.read_u32(IWRAM_BASE + 0x74) == 1


def test_rom_dew_kill_respawns_target_in_place(rom_bytes):
    """Layer 8j: DEW kill should restore HP without teleporting the target.
    Pre-stage target 0 at (140, 60), far from its init orbit at (170, 80).
    Fire DEW (player nearby). After respawn, target 0 must still be near
    (140, 60), not at the init position."""
    cpu = _make_cpu(rom_bytes)                            # boot without B
    cpu.run_for(400_000)
    # Park target 0 at (140, 60) with no velocity; set HP=1 so one DEW kills.
    cpu.write_u32(IWRAM_BASE + 0x20, 140 << 16)
    cpu.write_u32(IWRAM_BASE + 0x24,  60 << 16)
    cpu.write_u32(IWRAM_BASE + 0x28, 0)
    cpu.write_u32(IWRAM_BASE + 0x2C, 0)
    cpu.write_u32(IWRAM_BASE + 0xAC, 1)                   # T0 HP = 1
    cpu.write_u32(IWRAM_BASE + 0xA8, 0)                   # DEW cooldown clear
    # Park player near target 0 so DEW is in range.
    cpu.write_u32(IWRAM_BASE + 0x00, 145 << 16)
    cpu.write_u32(IWRAM_BASE + 0x04,  60 << 16)
    cpu.write_u32(IWRAM_BASE + 0x08, 0)
    cpu.write_u32(IWRAM_BASE + 0x0C, 0)
    # Press B (edge transition from released to held) to fire DEW.
    cpu.write_u16(IO_BASE + 0x130, 0xFFFF & ~0x02)
    cpu.run_for(1_500_000)                                # let DEW fire + respawn
    health = cpu.read_u32(IWRAM_BASE + 0xAC)
    assert health == 3, f"T0 should respawn at full HP; got {health}"
    x = _s32(cpu.read_u32(IWRAM_BASE + 0x20)) >> 16
    y = _s32(cpu.read_u32(IWRAM_BASE + 0x24)) >> 16
    # Allow some orbital drift but assert we're NOT at init (170, 80).
    assert abs(x - 140) < 20 and abs(y - 60) < 20, \
        f"T0 should respawn in place near (140, 60); got ({x}, {y})"
    assert not (abs(x - 170) < 5 and abs(y - 80) < 5), \
        f"T0 should NOT teleport to init (170, 80); got ({x}, {y})"


def test_rom_mission_advance_rerolls_mission_target_orbit(rom_bytes):
    """Layer 8j: completing a mission rerolls the new mission target's
    orbit. Force a DGRD completion and assert the new mission_target's
    position differs from its init-orbit position (it was randomised)."""
    cpu = _make_cpu(rom_bytes)                            # boot without B
    cpu.run_for(400_000)
    cpu.write_u32(IWRAM_BASE + 0x90, 1)                   # mission = DGRD
    cpu.write_u32(IWRAM_BASE + 0x98, 0)                   # mission_target = 0
    cpu.write_u32(IWRAM_BASE + 0xAC, 1)                   # T0 HP = 1
    cpu.write_u32(IWRAM_BASE + 0xA8, 0)                   # DEW cooldown clear
    cpu.write_u32(IWRAM_BASE + 0x00, 168 << 16)
    cpu.write_u32(IWRAM_BASE + 0x04,  80 << 16)
    cpu.write_u32(IWRAM_BASE + 0x08, 0)
    cpu.write_u32(IWRAM_BASE + 0x0C, 0)
    cpu.write_u16(IO_BASE + 0x130, 0xFFFF & ~0x02)        # press B (edge)
    cpu.run_for(2_000_000)
    new_mt = cpu.read_u32(IWRAM_BASE + 0x98)
    assert new_mt in (0, 1, 2), f"mission_target should be in [0,2]; got {new_mt}"
    # Read the new mission target's (x, y)
    base = 0x20 + (new_mt << 4)
    x = _s32(cpu.read_u32(IWRAM_BASE + base)) >> 16
    y = _s32(cpu.read_u32(IWRAM_BASE + base + 4)) >> 16
    # The init positions are: T0=(170,80), T1=(120,110), T2=(60,80).
    init_positions = {0: (170, 80), 1: (120, 110), 2: (60, 80)}
    ix, iy = init_positions[new_mt]
    # Must be sufficiently far from the init position to count as rerolled.
    distance_sq = (x - ix) ** 2 + (y - iy) ** 2
    assert distance_sq > 100, \
        f"new mission_target {new_mt} expected rerolled away from init " \
        f"({ix}, {iy}); got ({x}, {y}) d²={distance_sq}"


def test_rom_ric_origin_follows_mission_target(rom_bytes):
    """Layer 8j: S_RIC_TX/TY should track S_MISSION_TARGET, not always T0.
    Set mission_target = 2, place target 2 at a distinct position, run one
    frame, assert S_RIC_TX/TY equals target 2's (x, y)."""
    cpu = _make_cpu(rom_bytes)
    cpu.run_for(400_000)
    cpu.write_u32(IWRAM_BASE + 0x98, 2)                   # mission_target = 2
    cpu.write_u32(IWRAM_BASE + 0x40,  50 << 16)           # T2 x
    cpu.write_u32(IWRAM_BASE + 0x44, 110 << 16)           # T2 y
    cpu.write_u32(IWRAM_BASE + 0x48, 0)
    cpu.write_u32(IWRAM_BASE + 0x4C, 0)
    cpu.run_for(1_500_000)                                # several frames so RIC params catch up
    ric_tx = cpu.read_u32(IWRAM_BASE + 0x78)
    ric_ty = cpu.read_u32(IWRAM_BASE + 0x7C)
    t2_x = cpu.read_u32(IWRAM_BASE + 0x40)
    t2_y = cpu.read_u32(IWRAM_BASE + 0x44)
    assert ric_tx == t2_x, \
        f"RIC origin x should track mission target 2 ({t2_x:#x}); got {ric_tx:#x}"
    assert ric_ty == t2_y, \
        f"RIC origin y should track mission target 2 ({t2_y:#x}); got {ric_ty:#x}"


def test_rom_ric_paints_target_at_screen_centre(rom_bytes):
    """In RIC mode, target 0 (the reference) must paint its 3x3 sprite at
    the screen centre (120, 80). Poll over several windows to catch a
    post-render state (clear loop fills most of each frame)."""
    cpu = _make_cpu(rom_bytes, keyinput=0xFFFF & ~0x04)
    pixel_addr = VRAM_BASE + ((80 * 240 + 120) * 2)
    seen_red = False
    for _ in range(40):
        cpu.run_for(100_000)
        if cpu.read_u16(pixel_addr) == 0x001F:
            seen_red = True
            break
    assert seen_red, "target 0 red sprite never observed at screen centre in RIC mode"


def test_rom_warp_inits_to_one(rom_bytes):
    """S_WARP at IWRAM 0x70 boots to 1 (real time)."""
    cpu = _make_cpu(rom_bytes)
    cpu.run_for(5000)
    assert cpu.read_u32(IWRAM_BASE + 0x70) == 1


def test_rom_r_cycles_warp_up(rom_bytes):
    """Pressing R once advances 1 -> 10."""
    cpu = _make_cpu(rom_bytes, keyinput=0xFFFF & ~0x100)
    cpu.run_for(200_000)
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
    cpu.run_for(5000)
    assert cpu.read_u32(IWRAM_BASE + 0x1C) == 0x00640000


def test_rom_in_track_burn_drains_dv(rom_bytes):
    """Holding Right triggers exactly one edge-detected in-track (prograde-
    like) burn on the first frame; ship_dv decrements by one THRUST_COST."""
    cpu = _make_cpu(rom_bytes, keyinput=0xFFFF & ~0x10)
    cpu.run_for(400_000)
    dv = cpu.read_u32(IWRAM_BASE + 0x1C)
    assert dv == 0x00640000 - 0x00010000, \
        f"one burn should drop ship_dv by THRUST_COST; got 0x{dv:08X}"


def test_rom_in_track_burn_grows_speed(rom_bytes):
    """Right (in-track) adds +BURN_DV * v̂ to velocity. Boot v = (v_circ, 0),
    so vx grows by +BURN_DV. Orbital motion then evolves but vx stays above
    the boot circular value for the first frame after the burn."""
    cpu = _make_cpu(rom_bytes, keyinput=0xFFFF & ~0x10)
    cpu.run_for(200_000)
    vx = _s32(cpu.read_u32(IWRAM_BASE + 0x08))
    assert vx > 56756, f"in-track burn should grow vx; got 0x{vx:08X}"


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


def test_rom_idle_smoke_long_run(rom_bytes):
    """3M-cycle idle smoke. No input, warp=1 throughout. Assertions:
      * No bodies escape (player + all targets within 200 px of primary)
      * No negative ship_dv (it should not drain at all without input)
      * Mission FSM state stays inside [0, 4]
      * All target healths in [0, DEW_INIT_HEALTH]
      * hold_timers in non-negative range
    """
    cpu = _make_cpu(rom_bytes)
    cpu.run_for(3_000_000)

    # Player + targets within 200 px of (120, 80).
    for off in (0x00, 0x20, 0x30, 0x40):
        x = _s32(cpu.read_u32(IWRAM_BASE + off)) >> 16
        y = _s32(cpu.read_u32(IWRAM_BASE + off + 4)) >> 16
        dx = x - 120
        dy = y - 80
        r2 = dx * dx + dy * dy
        assert r2 < 200 * 200, f"body at offset 0x{off:02X} escaped: r^2={r2}"

    # No DV drain (no input)
    dv = cpu.read_u32(IWRAM_BASE + 0x1C)
    assert 0 <= dv <= 0x00640000, f"ship_dv out of range: 0x{dv:08X}"

    # Mission id in 0..4
    mid = cpu.read_u32(IWRAM_BASE + 0x90)
    assert 0 <= mid <= 4, f"mission_id out of range: {mid}"

    # Target healths in [0, 3]
    for i in range(3):
        h = cpu.read_u32(IWRAM_BASE + 0xAC + i * 4)
        assert 0 <= h <= 3, f"target {i} health out of range: {h}"

    # Hold timers non-negative
    for i in range(3):
        t = cpu.read_u32(IWRAM_BASE + 0x9C + i * 4)
        assert 0 <= t <= 1000, f"hold_timer {i} out of range: {t}"


def test_rom_lap_does_not_increment_in_quarter_orbit_from_boot(rom_bytes):
    """Layer 8m regression: with the old threshold-band detector, the
    very first wrap of phase past 0xFFFF -> 0 fired the lap counter, and
    from boot phase 0xC000 (270°) that happened after ~10 frames at
    warp=10 (~1/3 of an orbit). Post-fix (cumulative phase delta), the
    lap only fires after a full 2π of cumulative arc. Empirically at
    warp=10 one orbit takes ~30 visible frames ≈ 11M cycles; run only
    3M cycles (~10 frames, well under one orbit) and assert no lap."""
    cpu = _make_cpu(rom_bytes)
    cpu.run_for(400_000)                  # boot complete
    assert cpu.read_u32(IWRAM_BASE + 0x94) == 0, "boot orbit count should be 0"
    cpu.write_u32(IWRAM_BASE + 0x70, 10)  # warp = 10
    cpu.run_for(3_500_000)                # ~10 frames at warp=10; pre-fix ticked here
    after = cpu.read_u32(IWRAM_BASE + 0x94)
    assert after == 0, \
        f"lap must not fire within the first ~1/3 orbit from boot; got {after}"


def test_rom_lap_fires_once_per_full_orbit_from_boot(rom_bytes):
    """Sanity-check companion to the quarter-orbit test: after just past
    one full revolution at warp=10, the lap counter must have ticked
    exactly once. Empirically lap=1 fires at ≈14.5M cycles past boot
    and lap=2 at ≈24M. Run 18M cycles -- safely in the [lap=1] band."""
    cpu = _make_cpu(rom_bytes)
    cpu.run_for(400_000)
    cpu.write_u32(IWRAM_BASE + 0x70, 10)
    cpu.run_for(18_000_000)
    after = cpu.read_u32(IWRAM_BASE + 0x94)
    assert after == 1, \
        f"exactly 1 lap should fire after one full orbit from boot; got {after}"


def test_rom_path_closes_on_eccentric_orbit(rom_bytes):
    """Layer 8m: _compute_path_dt must use semi-major axis a, not
    instantaneous radius r. On an eccentric orbit started at apoapsis,
    r >> a → the old r-based dt undersampled the period and the predicted
    path didn't close. After the fix the 256-point path covers one full
    period whether r=a (circular) or r≠a (elliptical)."""
    cpu = _make_cpu(rom_bytes)
    cpu.run_for(400_000)
    # Park player at (180, 80): r=60 along +x. Tangential vy = 30000 (Q16)
    # well below v_circ_60 (46341) -> elliptical, start is apoapsis.
    # eps = v²/2 - μ/r = (30000/65536)²/2 - 30/60 ≈ 0.1047 - 0.5 = -0.395
    # a = -μ/(2*eps) ≈ 38 px (so r=60 sits at apoapsis with r/a ≈ 1.58).
    cpu.write_u32(IWRAM_BASE + 0x00, 180 << 16)
    cpu.write_u32(IWRAM_BASE + 0x04,  80 << 16)
    cpu.write_u32(IWRAM_BASE + 0x08, 0)
    cpu.write_u32(IWRAM_BASE + 0x0C, 30000)
    cpu.write_u32(IWRAM_BASE + 0x154, 0xF)         # dirty all paths
    cpu.run_for(2_000_000)                         # let player path refresh
    p0_x = _s32(cpu.read_u32(IWRAM_BASE + 0x160)) >> 16
    p0_y = _s32(cpu.read_u32(IWRAM_BASE + 0x164)) >> 16
    p_last_x = _s32(cpu.read_u32(IWRAM_BASE + 0x958)) >> 16
    p_last_y = _s32(cpu.read_u32(IWRAM_BASE + 0x95C)) >> 16
    dist_sq = (p_last_x - p0_x) ** 2 + (p_last_y - p0_y) ** 2
    # Pre-fix: dist_sq ~> 1500 px² (path covers only ~63% of period).
    # Post-fix: within ~8 px after one full revolution (semi-implicit Euler
    # accumulates some precession on eccentric orbits but stays bounded).
    assert dist_sq <= 100, \
        f"path[0]=({p0_x},{p0_y}) and path[255]=({p_last_x},{p_last_y}) " \
        f"expected to close on an elliptical orbit; d²={dist_sq}"


def test_rom_grapple_releases_when_target_out_of_range(rom_bytes):
    """Layer 8m: once acquired, grapple_drag continued to tug the target's
    velocity each frame regardless of how far the player drifted away.
    Post-fix, grapple_drag re-checks distance every frame and releases when
    the target is outside GRAPPLE_RANGE_SQ (64 px). Setup: pre-lock onto
    target 0, park player far from it, hold A, run a frame -> grapple
    must drop to -1."""
    cpu = _make_cpu(rom_bytes)
    cpu.run_for(400_000)
    # Pre-acquire: lock grapple to target 0.
    cpu.write_u32(IWRAM_BASE + 0xC8, 0)
    cpu.write_u32(IWRAM_BASE + 0xCC, 5)            # mid-tow
    # Park player at (10, 10), target 0 at (200, 150) -> distance ≈ 268 px,
    # well outside GRAPPLE_RANGE = 64 px.
    cpu.write_u32(IWRAM_BASE + 0x00,  10 << 16)
    cpu.write_u32(IWRAM_BASE + 0x04,  10 << 16)
    cpu.write_u32(IWRAM_BASE + 0x08, 0)
    cpu.write_u32(IWRAM_BASE + 0x0C, 0)
    cpu.write_u32(IWRAM_BASE + 0x20, 200 << 16)
    cpu.write_u32(IWRAM_BASE + 0x24, 150 << 16)
    cpu.write_u32(IWRAM_BASE + 0x28, 0)
    cpu.write_u32(IWRAM_BASE + 0x2C, 0)
    cpu.write_u16(IO_BASE + 0x130, 0xFFFF & ~0x01)  # A held
    cpu.run_for(2_000_000)
    g = _s32(cpu.read_u32(IWRAM_BASE + 0xC8))
    assert g == -1, \
        f"grapple should release when target is out of range; got idx={g}"


def test_rom_grapple_does_not_perturb_distant_target_velocity(rom_bytes):
    """Companion to the release test: even though grapple_target was
    pre-set, the distant target's velocity must NOT have been pulled toward
    the player. (Pre-fix, the drag dropped vy by ~12.5% per frame at d=∞.)
    """
    cpu = _make_cpu(rom_bytes)
    cpu.run_for(400_000)
    cpu.write_u32(IWRAM_BASE + 0xC8, 0)
    cpu.write_u32(IWRAM_BASE + 0xCC, 5)
    cpu.write_u32(IWRAM_BASE + 0x00,  10 << 16)
    cpu.write_u32(IWRAM_BASE + 0x04,  10 << 16)
    cpu.write_u32(IWRAM_BASE + 0x08, 0)
    cpu.write_u32(IWRAM_BASE + 0x0C, 0)
    cpu.write_u32(IWRAM_BASE + 0x20, 200 << 16)
    cpu.write_u32(IWRAM_BASE + 0x24, 150 << 16)
    cpu.write_u32(IWRAM_BASE + 0x28, 0)            # T0 vx = 0
    cpu.write_u32(IWRAM_BASE + 0x2C, 40000)        # T0 vy = 40000
    cpu.write_u16(IO_BASE + 0x130, 0xFFFF & ~0x01)
    cpu.run_for(700_000)                            # one frame
    vy_after = _s32(cpu.read_u32(IWRAM_BASE + 0x2C))
    # Without the grapple-drag, vy only drifts via orbital gravity (small).
    # Allow 5% slack for the cowell substep.
    assert 38_000 <= vy_after <= 42_000, \
        f"distant target's vy should not be perturbed by an out-of-range " \
        f"grapple; got vy={vy_after} (expected ~40000)"

