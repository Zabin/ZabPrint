"""Procedural starfield tilemap.

The GBA tile engine wants 8x8 tiles referenced by index. We generate one
256x256 px region (32x32 tiles) of stars and a small nebula glow as a
single BG layer. Output indices use BANK_STARS.
"""
import numpy as np

from assets.noise import fbm_2d


def starfield_indices(width: int = 256, height: int = 256, *,
                      seed: int = 0xC0DE,
                      star_density: float = 0.012) -> np.ndarray:
    """Return a HxW array of palette indices for the starfield + nebula glow."""
    rng = np.random.default_rng(seed)

    # Soft nebula glow: fBm noise mapped to indices 1..5 (very dark blues).
    glow = fbm_2d(width, height, seed=seed + 1, octaves=4, base_cell=32)
    glow_idx = np.clip((glow * 6).astype(np.int32), 0, 5)
    out = glow_idx.astype(np.uint8)

    # Sprinkle stars.
    n_stars = int(width * height * star_density)
    xs = rng.integers(0, width, size=n_stars)
    ys = rng.integers(0, height, size=n_stars)
    brightness = rng.random(n_stars)
    for x, y, b in zip(xs, ys, brightness):
        # Dim star: idx 6, medium: idx 7-8, bright: idx 9
        if b < 0.7:
            out[y, x] = max(out[y, x], 6)
        elif b < 0.9:
            out[y, x] = 8
        else:
            out[y, x] = 9
            # Occasional cross-glint at brightest stars
            if y > 0:
                out[y - 1, x] = max(out[y - 1, x], 7)
            if y < height - 1:
                out[y + 1, x] = max(out[y + 1, x], 7)
            if x > 0:
                out[y, x - 1] = max(out[y, x - 1], 7)
            if x < width - 1:
                out[y, x + 1] = max(out[y, x + 1], 7)

    # A few colored stars: choose 6 positions, paint with bank colors 10-14.
    for color_idx in (10, 11, 12, 13, 14, 15):
        x = int(rng.integers(8, width - 8))
        y = int(rng.integers(8, height - 8))
        out[y, x] = color_idx
        out[y - 1, x] = color_idx
        out[y + 1, x] = color_idx
        out[y, x - 1] = color_idx
        out[y, x + 1] = color_idx

    return out
