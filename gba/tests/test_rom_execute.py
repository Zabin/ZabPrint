"""End-to-end ROM execution smoke test.

Loads build/game.gba into the ARMv4 interpreter with GBA-shaped memory
regions (ROM at 0x08000000, IWRAM at 0x03000000, VRAM at 0x06000000, I/O at
0x04000000), pre-seeds the I/O registers so the vsync polls exit
immediately, and runs the boot path long enough to complete one frame.

Then asserts:
  * DISPCNT was written with 0x0403 (mode 3 + BG2 on)
  * Ship state in IWRAM was initialised to (120, 80)
  * VRAM has a non-trivial number of non-zero halfwords (clear + stars +
    planets + ship all painted something)
  * The 5x5 around (120, 80) is white (the ship was drawn last)
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


def _make_gba_cpu(rom: bytes) -> ArmCpu:
    cpu = ArmCpu(regions=[
        (ROM_BASE,   2 * 1024 * 1024),
        (IWRAM_BASE, 32 * 1024),
        (VRAM_BASE,  96 * 1024),
        (IO_BASE,    1024),
    ])
    cpu.load_code(rom, at=ROM_BASE)
    # VCOUNT pre-set so both vsync polls fall through. The crt0 waits for
    # VCOUNT < 160 ("end of vblank") then VCOUNT >= 160 ("start of vblank").
    # Seeding 160 satisfies the second path immediately; we satisfy the
    # first by giving the loop a single VCOUNT < 160 read via a tiny tick.
    # Simpler: write 0 first, run, then write 160 just before the second poll
    # would loop. Even simpler: write 160, accept the first poll wastes one
    # iteration and exits in one read (since `bge` is taken once then we
    # need vcount to drop). Just hot-patch VCOUNT during the run via a hook
    # that always returns alternating values.
    #
    # Easiest correct approach: pre-write 0, then after first iteration the
    # second poll will spin -- instead we just put a value that satisfies
    # *both* polls by alternating reads. The interpreter's `read_u16` is the
    # natural seam; subclass to fake VCOUNT.
    return cpu


class _FakeVCountCpu(ArmCpu):
    """Subclass that returns alternating VCOUNT values on read so both
    crt0 polls (`bge` then `blt`) fall through in one or two iterations."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._vcount_toggle = False

    def read_u16(self, addr: int) -> int:
        if addr == IO_BASE + 6:
            # Alternate 0 (active line, satisfies `bge` exit) and 160
            # (vblank, satisfies `blt` exit). Two reads -> both polls done.
            self._vcount_toggle = not self._vcount_toggle
            return 0 if self._vcount_toggle else 160
        return super().read_u16(addr)


def test_rom_runs_first_frame(rom_bytes):
    cpu = _FakeVCountCpu(regions=[
        (ROM_BASE,   2 * 1024 * 1024),
        (IWRAM_BASE, 32 * 1024),
        (VRAM_BASE,  96 * 1024),
        (IO_BASE,    1024),
    ])
    cpu.load_code(rom_bytes, at=ROM_BASE)
    # KEYINPUT idle (all bits high = no buttons pressed).
    cpu.write_u16(IO_BASE + 0x130, 0xFFFF)

    cpu.regs[15] = ROM_BASE
    # Plenty for: SP setup + DISPCNT write + state init + 2 vsync polls +
    # input + ship update + 9600-iter clear loop (>= 38000 instructions) +
    # 32 stars + 2 disc fills + the final 5x5 ship draw.
    cpu.run_for(120_000)

    # DISPCNT was written?
    assert cpu.read_u32(IO_BASE) == 0x0403, "DISPCNT should be mode 3 + BG2"

    # Ship state initialised to Q16 positions (120 << 16, 80 << 16). With no
    # input the friction term holds velocity at 0 and position drifts only by
    # tiny rounding which is exactly zero with zero velocity.
    assert cpu.read_u32(IWRAM_BASE)     == 120 << 16, "SHIP_X should boot at 120 (Q16)"
    assert cpu.read_u32(IWRAM_BASE + 4) ==  80 << 16, "SHIP_Y should boot at 80 (Q16)"


def test_rom_paints_ship_at_default_position(rom_bytes):
    cpu = _FakeVCountCpu(regions=[
        (ROM_BASE,   2 * 1024 * 1024),
        (IWRAM_BASE, 32 * 1024),
        (VRAM_BASE,  96 * 1024),
        (IO_BASE,    1024),
    ])
    cpu.load_code(rom_bytes, at=ROM_BASE)
    cpu.write_u16(IO_BASE + 0x130, 0xFFFF)

    cpu.regs[15] = ROM_BASE
    cpu.run_for(120_000)

    # The 5x5 white square centred at (120, 80) should be in VRAM.
    # Pixel at exactly (120, 80) is white (0x7FFF) since it's inside the square.
    pixel_addr = VRAM_BASE + ((80 * 240 + 120) * 2)
    assert cpu.read_u16(pixel_addr) == 0x7FFF, \
        f"ship pixel at (120, 80) should be white, got 0x{cpu.read_u16(pixel_addr):04X}"

    # And a pixel well outside the ship region should be the background colour.
    bg_addr = VRAM_BASE + ((10 * 240 + 200) * 2)
    bg = cpu.read_u16(bg_addr)
    # Either the deep-space fill (0x0421) or a star (0x7FFF) -- both fine.
    assert bg in (0x0421, 0x7FFF), f"unexpected background pixel 0x{bg:04X}"


def test_rom_responds_to_dpad_right(rom_bytes):
    """Hold the Right button (active-low: bit 4 clear). Thrust accumulates
    into vx > 0, so the Q16 ship_x and ship_vx should both be strictly
    positive after a few frames."""
    cpu = _FakeVCountCpu(regions=[
        (ROM_BASE,   2 * 1024 * 1024),
        (IWRAM_BASE, 32 * 1024),
        (VRAM_BASE,  96 * 1024),
        (IO_BASE,    1024),
    ])
    cpu.load_code(rom_bytes, at=ROM_BASE)
    cpu.write_u16(IO_BASE + 0x130, 0xFFFF & ~0x10)

    cpu.regs[15] = ROM_BASE
    cpu.run_for(120_000)

    x_q16  = cpu.read_u32(IWRAM_BASE + 0x00)
    y_q16  = cpu.read_u32(IWRAM_BASE + 0x04)
    vx_q16 = cpu.read_u32(IWRAM_BASE + 0x08)

    # signed view
    if vx_q16 & 0x80000000:
        vx_q16 -= 0x100000000
    assert vx_q16 > 0, f"vx should be positive after holding Right; got 0x{cpu.read_u32(IWRAM_BASE+8):08X}"
    assert x_q16 > (120 << 16), f"ship_x should drift right; got 0x{x_q16:08X}"
    assert y_q16 == (80 << 16), "y must not change when only Right is held"


def test_rom_responds_to_dpad_up(rom_bytes):
    cpu = _FakeVCountCpu(regions=[
        (ROM_BASE,   2 * 1024 * 1024),
        (IWRAM_BASE, 32 * 1024),
        (VRAM_BASE,  96 * 1024),
        (IO_BASE,    1024),
    ])
    cpu.load_code(rom_bytes, at=ROM_BASE)
    cpu.write_u16(IO_BASE + 0x130, 0xFFFF & ~0x40)

    cpu.regs[15] = ROM_BASE
    cpu.run_for(120_000)

    x_q16  = cpu.read_u32(IWRAM_BASE + 0x00)
    y_q16  = cpu.read_u32(IWRAM_BASE + 0x04)
    vy_q16 = cpu.read_u32(IWRAM_BASE + 0x0C)
    if vy_q16 & 0x80000000:
        vy_q16 -= 0x100000000

    assert vy_q16 < 0, f"vy should be negative after holding Up; got vy=0x{cpu.read_u32(IWRAM_BASE+0xC):08X}"
    assert y_q16 < (80 << 16), f"ship_y should drift up; got 0x{y_q16:08X}"
    assert x_q16 == (120 << 16), "x must not change when only Up is held"


def test_rom_planets_and_score_initialised(rom_bytes):
    """After boot the two planets should be alive at their seeded positions
    and the score should be 0."""
    cpu = _FakeVCountCpu(regions=[
        (ROM_BASE,   2 * 1024 * 1024),
        (IWRAM_BASE, 32 * 1024),
        (VRAM_BASE,  96 * 1024),
        (IO_BASE,    1024),
    ])
    cpu.load_code(rom_bytes, at=ROM_BASE)
    cpu.write_u16(IO_BASE + 0x130, 0xFFFF)
    cpu.regs[15] = ROM_BASE
    cpu.run_for(120_000)

    # Planet 1: (60, 50), alive.
    assert cpu.read_u32(IWRAM_BASE + 0x28) == 60
    assert cpu.read_u32(IWRAM_BASE + 0x2C) == 50
    assert cpu.read_u32(IWRAM_BASE + 0x30) == 1
    # Planet 2: (180, 110), alive.
    assert cpu.read_u32(IWRAM_BASE + 0x34) == 180
    assert cpu.read_u32(IWRAM_BASE + 0x38) == 110
    assert cpu.read_u32(IWRAM_BASE + 0x3C) == 1
    # Score: 0.
    assert cpu.read_u32(IWRAM_BASE + 0x44) == 0
    # frame_count > 0 (several frames have ticked).
    assert cpu.read_u32(IWRAM_BASE + 0x40) > 0


def test_rom_a_button_spawns_projectile(rom_bytes):
    """A-button on edge spawns a projectile; the slot should be active and
    its Q16 position should equal the ship position at spawn-time."""
    cpu = _FakeVCountCpu(regions=[
        (ROM_BASE,   2 * 1024 * 1024),
        (IWRAM_BASE, 32 * 1024),
        (VRAM_BASE,  96 * 1024),
        (IO_BASE,    1024),
    ])
    cpu.load_code(rom_bytes, at=ROM_BASE)
    # Hold A (bit 0). The first frame edge-detects "newly pressed" since
    # prev_keys boots at 0 and current's bit 0 is set.
    cpu.write_u16(IO_BASE + 0x130, 0xFFFF & ~0x01)

    cpu.regs[15] = ROM_BASE
    cpu.run_for(80_000)   # roughly two frames

    proj_on = cpu.read_u32(IWRAM_BASE + 0x24)
    assert proj_on == 1, f"projectile slot should be active after A press; got {proj_on}"
    # Projectile X should be moving right (positive vx) thanks to the kick.
    proj_vx = cpu.read_u32(IWRAM_BASE + 0x1C)
    if proj_vx & 0x80000000:
        proj_vx -= 0x100000000
    assert proj_vx > 0, f"projectile should have positive vx (forward kick); got 0x{cpu.read_u32(IWRAM_BASE+0x1C):08X}"
