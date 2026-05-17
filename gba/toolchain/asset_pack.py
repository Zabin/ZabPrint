"""Convert RGBA pixel data and palettes into the GBA's native VRAM formats.

Two formats are produced:

  * 4bpp tile data. Each tile is 8x8 pixels packed as 32 bytes, two pixels per
    byte, with the LEFT pixel of each pair in the low nibble and the RIGHT
    pixel in the high nibble. Tiles in a tileset appear row-major across the
    image (left-to-right, then top-to-bottom).

  * BGR555 palette entries. Each entry is a 16-bit little-endian word with
    the layout `0bbbbbggg ggrrrrr` (5 bits per channel, top bit ignored).
"""
from typing import Iterable, Sequence


# ---------------------------------------------------------------------------
# BGR555 single-entry conversion
# ---------------------------------------------------------------------------

def pack_bgr555(r5: int, g5: int, b5: int) -> int:
    """Pack 5-bit (0-31) channels into a 16-bit BGR555 word."""
    assert 0 <= r5 <= 31 and 0 <= g5 <= 31 and 0 <= b5 <= 31
    return (b5 << 10) | (g5 << 5) | r5


def unpack_bgr555(word: int) -> tuple[int, int, int]:
    """Reverse of pack_bgr555. Returns (r5, g5, b5)."""
    return (word & 0x1F, (word >> 5) & 0x1F, (word >> 10) & 0x1F)


def quantize_rgb_to_bgr555(r: int, g: int, b: int) -> int:
    """Quantize 8-bit-per-channel RGB to BGR555 (simple drop of low 3 bits)."""
    return pack_bgr555(r >> 3, g >> 3, b >> 3)


# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------

def pack_palette(palette: Sequence[tuple[int, int, int]], *,
                 pad_to: int = 16,
                 already_5bit: bool = True) -> bytes:
    """Pack a list of (r, g, b) entries into a little-endian byte blob.

    Each color entry produces 2 bytes. If `already_5bit` is True the inputs
    are assumed to be 0..31; otherwise they are quantized from 0..255.
    Output is padded to `pad_to` entries with black.
    """
    out = bytearray()
    for entry in palette:
        if already_5bit:
            w = pack_bgr555(*entry)
        else:
            w = quantize_rgb_to_bgr555(*entry)
        out.extend(w.to_bytes(2, 'little'))
    while len(out) < 2 * pad_to:
        out.extend(b'\x00\x00')
    return bytes(out)


# ---------------------------------------------------------------------------
# 4bpp tile packing
# ---------------------------------------------------------------------------

def rgba_to_4bpp_tile(pixels: Sequence[Sequence[int]]) -> bytes:
    """Pack an 8x8 grid of palette indices (0..15) into 32 bytes."""
    if len(pixels) != 8 or any(len(row) != 8 for row in pixels):
        raise ValueError("tile must be 8x8")
    out = bytearray(32)
    for y in range(8):
        row = pixels[y]
        for x in range(0, 8, 2):
            left = row[x]
            right = row[x + 1]
            if not (0 <= left <= 15) or not (0 <= right <= 15):
                raise ValueError(f"palette index out of 4bpp range: {left}, {right}")
            out[y * 4 + (x >> 1)] = (right << 4) | left
    return bytes(out)


def rgba_to_4bpp_tileset(pixels: Sequence[Sequence[int]]) -> bytes:
    """Pack a WxH image (W and H multiples of 8) into a tileset blob.

    Tiles are emitted row-major across the source image.
    """
    H = len(pixels)
    W = len(pixels[0]) if H else 0
    if W % 8 != 0 or H % 8 != 0:
        raise ValueError(f"tileset dimensions must be multiple of 8: got {W}x{H}")
    out = bytearray()
    for ty in range(H // 8):
        for tx in range(W // 8):
            tile = [
                [pixels[ty * 8 + y][tx * 8 + x] for x in range(8)]
                for y in range(8)
            ]
            out.extend(rgba_to_4bpp_tile(tile))
    return bytes(out)
