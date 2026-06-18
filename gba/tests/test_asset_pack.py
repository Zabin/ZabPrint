"""Asset packer tests.

The packer converts RGBA pixel data and arrays of (r,g,b) palette entries
into the GBA's native formats:
  * 4bpp tiles: 8x8 pixels packed as 32 bytes, two pixels per byte, low
    nibble holds the LEFT pixel of each pair. Order in VRAM is row-major
    across the tile.
  * BGR555 palette entries: 16-bit little-endian, 0bbbbbggg ggrrrrr (with a
    high zero), 5 bits per component.
"""
import pytest

from toolchain.asset_pack import (
    pack_bgr555,
    unpack_bgr555,
    pack_palette,
    rgba_to_4bpp_tile,
    rgba_to_4bpp_tileset,
    quantize_rgb_to_bgr555,
)


# ---------------------------------------------------------------------------
# BGR555 palette entry conversion
# ---------------------------------------------------------------------------

def test_pack_bgr555_black():
    assert pack_bgr555(0, 0, 0) == 0x0000

def test_pack_bgr555_white():
    # All 5-bit channels max -> 11111 11111 11111 = 0x7FFF
    assert pack_bgr555(31, 31, 31) == 0x7FFF

def test_pack_bgr555_pure_red():
    # r=31, g=0, b=0 -> 00000 00000 11111 = 0x001F
    assert pack_bgr555(31, 0, 0) == 0x001F

def test_pack_bgr555_pure_green():
    # g=31 -> 00000 11111 00000 = 0x03E0
    assert pack_bgr555(0, 31, 0) == 0x03E0

def test_pack_bgr555_pure_blue():
    # b=31 -> 11111 00000 00000 = 0x7C00
    assert pack_bgr555(0, 0, 31) == 0x7C00

def test_unpack_bgr555_round_trip():
    for r in (0, 7, 15, 23, 31):
        for g in (0, 12, 31):
            for b in (0, 5, 31):
                w = pack_bgr555(r, g, b)
                assert unpack_bgr555(w) == (r, g, b)


def test_quantize_rgb_to_bgr555_drops_low_bits():
    # 8-bit 255 -> 5-bit 31
    assert quantize_rgb_to_bgr555(255, 0, 0) == 0x001F
    # 8-bit 128 -> 5-bit 16 (128 >> 3 = 16)
    assert quantize_rgb_to_bgr555(128, 128, 128) == ((16 << 10) | (16 << 5) | 16)


# ---------------------------------------------------------------------------
# Palette packing (list of (r,g,b) -> bytes)
# ---------------------------------------------------------------------------

def test_pack_palette_16_colors():
    palette = [(0, 0, 0)] * 16  # all black
    data = pack_palette(palette)
    assert len(data) == 32
    assert data == b'\x00' * 32

def test_pack_palette_first_color_red():
    palette = [(31, 0, 0)] + [(0, 0, 0)] * 15
    data = pack_palette(palette)
    assert data[0:2] == b'\x1F\x00'  # little-endian 0x001F

def test_pack_palette_pads_to_16_entries():
    palette = [(31, 0, 0), (0, 31, 0)]
    data = pack_palette(palette, pad_to=16)
    assert len(data) == 32
    assert data[0:2] == b'\x1F\x00'
    assert data[2:4] == b'\xE0\x03'
    assert data[4:] == b'\x00' * 28


# ---------------------------------------------------------------------------
# 4bpp tile packing (8x8 pixels, 32 bytes per tile)
# ---------------------------------------------------------------------------

def test_rgba_to_4bpp_tile_all_zeros():
    # 8x8 of palette index 0 -> 32 zero bytes
    pixels = [[0] * 8 for _ in range(8)]
    data = rgba_to_4bpp_tile(pixels)
    assert data == b'\x00' * 32

def test_rgba_to_4bpp_tile_left_pixel_in_low_nibble():
    # Row 0: indices [1, 2, 0, 0, 0, 0, 0, 0] -- LEFT pixel of pair goes in
    # low nibble. So first byte holds (1 in lo, 2 in hi) = 0x21.
    pixels = [[0] * 8 for _ in range(8)]
    pixels[0][0] = 1
    pixels[0][1] = 2
    data = rgba_to_4bpp_tile(pixels)
    assert data[0] == 0x21

def test_rgba_to_4bpp_tile_full_row():
    # First row of 8 indices = [1, 2, 3, 4, 5, 6, 7, 8]
    # Packed: bytes = 0x21, 0x43, 0x65, 0x87 (low=left, high=right)
    pixels = [[1, 2, 3, 4, 5, 6, 7, 8]] + [[0] * 8] * 7
    data = rgba_to_4bpp_tile(pixels)
    assert data[0:4] == bytes([0x21, 0x43, 0x65, 0x87])

def test_rgba_to_4bpp_tile_rejects_index_over_15():
    pixels = [[16] + [0] * 7] + [[0] * 8] * 7
    with pytest.raises(ValueError):
        rgba_to_4bpp_tile(pixels)


# ---------------------------------------------------------------------------
# Tileset: arbitrary WxH image -> sequence of 8x8 tiles, row-major across tiles
# ---------------------------------------------------------------------------

def test_rgba_to_4bpp_tileset_16x8():
    # 16x8 image -> 2 tiles. Tile 0 left half all 1, tile 1 right half all 2.
    pixels = [[1] * 8 + [2] * 8 for _ in range(8)]
    data = rgba_to_4bpp_tileset(pixels)
    # Each tile is 32 bytes; we expect 64 bytes total.
    assert len(data) == 64
    # First tile: every byte is 0x11 (both nibbles index 1).
    assert data[:32] == b'\x11' * 32
    # Second tile: every byte is 0x22.
    assert data[32:64] == b'\x22' * 32

def test_rgba_to_4bpp_tileset_rejects_misaligned_size():
    # 9x8 -- width not multiple of 8.
    pixels = [[0] * 9 for _ in range(8)]
    with pytest.raises(ValueError):
        rgba_to_4bpp_tileset(pixels)
