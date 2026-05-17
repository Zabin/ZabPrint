"""Cartridge packer for the GBA.

Builds the 192-byte header described in GBATEK and pads the ROM to a power-of-
two size (default 2 MiB). The caller hands us a "payload" -- the assembled
output starting with the 4-byte entry-point branch -- and we splice in the
header at the right offsets:

  0x00   4    entry-point branch (caller-supplied)
  0x04   156  Nintendo logo (BIOS-checked)
  0xA0   12   ASCII title, NUL-padded
  0xAC   4    game code
  0xB0   2    maker code
  0xB2   1    fixed 0x96 (BIOS-checked)
  0xB3   1    main unit code (0x00)
  0xB4   1    device type (0x00)
  0xB5   7    reserved (0x00)
  0xBC   1    software version
  0xBD   1    header checksum (complement of sum of 0xA0..0xBC + 0x19)
  0xBE   2    reserved (0x00)
  0xC0   N    payload bytes 4..N+4 (the rest of the assembled code)
"""
from toolchain.nintendo_logo import NINTENDO_LOGO


# Cartridge ROM is mapped at 0x08000000 in the GBA memory map (WAITSTATE 0).
CART_BASE = 0x08000000

HEADER_SIZE = 0xC0  # 192 bytes
DEFAULT_ROM_SIZE = 2 * 1024 * 1024


def compute_header_checksum(header_bytes_a0_bc: bytes) -> int:
    """Header checksum byte at 0xBD.

    Formula (GBATEK): chk = -(sum(0xA0..0xBC) + 0x19), low byte only.
    Input is exactly 29 bytes covering offsets 0xA0..0xBC inclusive.
    """
    assert len(header_bytes_a0_bc) == 29, "checksum input must be 29 bytes (0xA0..0xBC)"
    s = sum(header_bytes_a0_bc) + 0x19
    return (-s) & 0xFF


def _pad_or_trunc(s: str, n: int) -> bytes:
    b = s.encode('ascii', errors='replace')
    if len(b) >= n:
        return b[:n]
    return b + b'\x00' * (n - len(b))


def pack_rom(payload: bytes, *,
             title: str,
             code: str,
             maker_code: str = "00",
             software_version: int = 0,
             rom_size_bytes: int = DEFAULT_ROM_SIZE) -> bytes:
    """Build a complete cartridge ROM image.

    payload[0:4] is treated as the entry-point branch and placed at offset 0
    of the ROM. payload[4:] is placed starting at offset 0xC0 (immediately
    after the header). The remainder of the ROM is filled with 0xFF, which is
    the natural cart-bus pull-up value -- the BIOS will read 0xFF for any
    unused bytes regardless of what we write here.
    """
    assert len(payload) >= 4, "payload must contain at least the entry branch"
    rom = bytearray(b'\xFF' * rom_size_bytes)
    # 0x00..0x03: entry branch
    rom[0x00:0x04] = payload[0:4]
    # 0x04..0x9F: Nintendo logo
    rom[0x04:0xA0] = NINTENDO_LOGO
    # 0xA0..0xAB: title
    rom[0xA0:0xAC] = _pad_or_trunc(title, 12)
    # 0xAC..0xAF: game code
    rom[0xAC:0xB0] = _pad_or_trunc(code, 4)
    # 0xB0..0xB1: maker code
    rom[0xB0:0xB2] = _pad_or_trunc(maker_code, 2)
    # 0xB2: fixed 0x96
    rom[0xB2] = 0x96
    # 0xB3: main unit code (0x00)
    rom[0xB3] = 0x00
    # 0xB4: device type (0x00)
    rom[0xB4] = 0x00
    # 0xB5..0xBB: reserved (already 0xFF -> set to 0x00)
    for i in range(0xB5, 0xBC):
        rom[i] = 0x00
    # 0xBC: software version
    rom[0xBC] = software_version & 0xFF
    # 0xBD: header checksum
    rom[0xBD] = compute_header_checksum(bytes(rom[0xA0:0xBD]))
    # 0xBE..0xBF: reserved
    rom[0xBE] = 0x00
    rom[0xBF] = 0x00
    # 0xC0..: rest of payload
    rest = payload[4:]
    if rest:
        assert HEADER_SIZE + len(rest) <= rom_size_bytes, "payload too large for ROM"
        rom[HEADER_SIZE:HEADER_SIZE + len(rest)] = rest
    return bytes(rom)
