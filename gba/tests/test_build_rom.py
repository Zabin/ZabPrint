"""End-to-end ROM build smoke test.

Builds the cartridge image via `build.build_rom()` and asserts the structural
properties a real GBA expects: correct size, valid Nintendo logo, recomputed
header checksum, entry-point branch landing on the first byte of the payload.
"""
from __future__ import annotations

import build
from toolchain.cart import compute_header_checksum, DEFAULT_ROM_SIZE
from toolchain.nintendo_logo import NINTENDO_LOGO


def _decode_branch(word: int) -> int:
    """Return the byte offset a B instruction at PC=0 will jump to."""
    cond = (word >> 28) & 0xF
    op = (word >> 25) & 0x7
    assert cond == 0xE and op == 0b101, f"not a B/BL instruction: 0x{word:08X}"
    imm24 = word & 0xFFFFFF
    if imm24 & 0x800000:
        imm24 -= 0x1000000
    return 8 + (imm24 << 2)


def test_rom_is_2mib():
    rom = build.build_rom()
    assert len(rom) == DEFAULT_ROM_SIZE
    assert len(rom) == 2 * 1024 * 1024


def test_rom_nintendo_logo_intact():
    rom = build.build_rom()
    assert rom[0x04:0xA0] == NINTENDO_LOGO


def test_rom_header_fields():
    rom = build.build_rom()
    assert rom[0xA0:0xAC] == b"ZABSPACE\x00\x00\x00\x00"
    assert rom[0xAC:0xB0] == b"ZSPE"
    assert rom[0xB2] == 0x96            # BIOS-enforced fixed byte


def test_rom_header_checksum_matches():
    rom = build.build_rom()
    assert rom[0xBD] == compute_header_checksum(rom[0xA0:0xBD])


def test_entry_branch_targets_payload_start():
    rom = build.build_rom()
    word = int.from_bytes(rom[0:4], "little")
    target = _decode_branch(word)
    assert target == 0xC0, f"entry branch should land on payload start (0xC0), got 0x{target:X}"


def test_first_payload_instruction_is_real():
    """The byte at 0xC0 should be the first instruction of `_start`, not 0xFF
    fill. The exact encoding is `ldr sp, [pc, #+offset]` for the SP setup;
    we just assert it isn't filler."""
    rom = build.build_rom()
    word = int.from_bytes(rom[0xC0:0xC4], "little")
    assert word != 0xFFFFFFFF, "payload appears empty at 0xC0"
    # Top nibble == E means AL condition; sanity check.
    assert (word >> 28) == 0xE


def test_tail_padded_with_ff():
    """The packer fills unused ROM bytes with 0xFF (cart-bus pull-up)."""
    rom = build.build_rom()
    # Look near the end of the ROM, far past any code we'd emit.
    assert rom[-16:] == b"\xFF" * 16


def test_build_main_writes_file(tmp_path, monkeypatch):
    """`build.main()` writes a file to BUILD_DIR/game.gba."""
    monkeypatch.setattr(build, "BUILD_DIR", tmp_path)
    out = build.main()
    assert out.exists()
    assert out.stat().st_size == DEFAULT_ROM_SIZE
