"""Cartridge header + ROM packing tests.

Validates the static 192-byte GBA cartridge header structure (ARM ARM /
GBATEK), the embedded Nintendo logo blob (verified by SHA-256 against the
canonical value the BIOS expects), the entry-point branch, and the header
complement check byte at 0xBD.
"""
import hashlib
import pytest

from toolchain.cart import (
    NINTENDO_LOGO,
    CART_BASE,
    pack_rom,
    compute_header_checksum,
)


# ---------------------------------------------------------------------------
# Nintendo logo
# ---------------------------------------------------------------------------

NINTENDO_LOGO_SHA256 = (
    # SHA-256 of the canonical 156-byte Nintendo logo used by GBA BIOS to
    # validate that a cart is "official" enough to boot. (Homebrew uses the
    # same byte sequence; the BIOS just checksums it.) Frozen reference so a
    # silent corruption of nintendo_logo.py is caught.
    "08a0153cfd6b0ea54b938f7d209933fa849da0d56f5a34c481060c9ff2fad818"
)


def test_nintendo_logo_is_156_bytes():
    assert len(NINTENDO_LOGO) == 156


def test_nintendo_logo_sha256_canonical():
    actual = hashlib.sha256(NINTENDO_LOGO).hexdigest()
    assert actual == NINTENDO_LOGO_SHA256


# ---------------------------------------------------------------------------
# Header checksum (ARM ARM / GBATEK)
# ---------------------------------------------------------------------------

def test_checksum_function_basic():
    # All-zero header_bytes -> checksum = (-(0 + 0x19)) & 0xFF = 0xE7
    assert compute_header_checksum(bytes(29)) == 0xE7


def test_checksum_includes_full_29_bytes():
    # Each byte in the 29-byte slice contributes equally.
    data = b'\x01' + bytes(28)
    assert compute_header_checksum(data) == ((-1 - 0x19) & 0xFF)


# ---------------------------------------------------------------------------
# pack_rom -- end-to-end shape
# ---------------------------------------------------------------------------

def _stub_entry() -> bytes:
    # 4-byte ARM "B start" to a fixed offset (the linker can patch this).
    # The simplest valid entry: "b .+8" -- branch forward by 0 (PC bias +8).
    # 0xEA000000 in little-endian.
    return bytes.fromhex("000000EA")


def test_pack_rom_is_exactly_2mib_by_default():
    rom = pack_rom(_stub_entry(), title="ZABSPACE", code="ZSPE")
    assert len(rom) == 2 * 1024 * 1024


def test_pack_rom_entry_branch_at_offset_0():
    rom = pack_rom(_stub_entry(), title="ZABSPACE", code="ZSPE")
    assert rom[0:4] == bytes.fromhex("000000EA")


def test_pack_rom_logo_at_offset_4():
    rom = pack_rom(_stub_entry(), title="ZABSPACE", code="ZSPE")
    assert rom[0x04:0xA0] == NINTENDO_LOGO


def test_pack_rom_title_at_offset_a0():
    rom = pack_rom(_stub_entry(), title="ZABSPACE", code="ZSPE")
    # Title padded with NULs to 12 bytes
    assert rom[0xA0:0xAC] == b"ZABSPACE" + b"\x00" * 4


def test_pack_rom_code_at_offset_ac():
    rom = pack_rom(_stub_entry(), title="ZABSPACE", code="ZSPE")
    assert rom[0xAC:0xB0] == b"ZSPE"


def test_pack_rom_fixed_0x96_at_offset_b2():
    rom = pack_rom(_stub_entry(), title="ZABSPACE", code="ZSPE")
    assert rom[0xB2] == 0x96


def test_pack_rom_header_checksum_matches():
    rom = pack_rom(_stub_entry(), title="ZABSPACE", code="ZSPE")
    expected = compute_header_checksum(rom[0xA0:0xBD])
    assert rom[0xBD] == expected


def test_pack_rom_payload_follows_header():
    # If the entry block is 8 bytes (entry + one more instruction),
    # the second 4 bytes should appear at offset 0xC0 (right after 0xBF).
    payload = _stub_entry() + bytes.fromhex("DEADBEEF")
    rom = pack_rom(payload, title="ZABSPACE", code="ZSPE")
    # First 4 bytes are entry branch; remaining bytes go right after header.
    # Header is 0xC0 = 192 bytes, but the first 4 of those are the entry.
    # Convention: payload bytes 4+ go to offset 0xC0+.
    assert rom[0xC0:0xC4] == bytes.fromhex("DEADBEEF")


def test_pack_rom_padded_with_ff():
    rom = pack_rom(_stub_entry(), title="ZABSPACE", code="ZSPE")
    # After the header, the rest of ROM is 0xFF padding (cart-bus default).
    # Sample at the end.
    assert rom[-4:] == b"\xFF\xFF\xFF\xFF"


def test_pack_rom_custom_size():
    rom = pack_rom(_stub_entry(), title="ZABSPACE", code="ZSPE",
                   rom_size_bytes=256 * 1024)
    assert len(rom) == 256 * 1024


def test_pack_rom_title_truncated_to_12():
    rom = pack_rom(_stub_entry(), title="VERY_LONG_TITLE_EXCEEDS_12",
                   code="ZSPE")
    assert rom[0xA0:0xAC] == b"VERY_LONG_TI"


def test_cart_base_constant():
    # The GBA cartridge is mapped at 0x08000000 in the system memory map.
    assert CART_BASE == 0x08000000
