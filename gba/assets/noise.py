"""Seeded value-noise primitives for procedural asset generation.

Deterministic given the seed -- every build produces byte-identical PNGs and
ROM blobs, which is essential for the asset-packer tests and for CI smoke
verification.
"""
import numpy as np


def value_noise_2d(width: int, height: int, *, seed: int, cell: int) -> np.ndarray:
    """Bilinearly-interpolated value noise on a `cell`x`cell` grid.

    Returns a HxW float32 array with values in [0, 1].
    """
    rng = np.random.default_rng(seed)
    gw = width // cell + 2
    gh = height // cell + 2
    grid = rng.random((gh, gw), dtype=np.float32)
    out = np.zeros((height, width), dtype=np.float32)
    for y in range(height):
        gy = y / cell
        y0 = int(gy)
        fy = gy - y0
        for x in range(width):
            gx = x / cell
            x0 = int(gx)
            fx = gx - x0
            a = grid[y0, x0]
            b = grid[y0, x0 + 1]
            c = grid[y0 + 1, x0]
            d = grid[y0 + 1, x0 + 1]
            top = a + (b - a) * fx
            bot = c + (d - c) * fx
            out[y, x] = top + (bot - top) * fy
    return out


def fbm_2d(width: int, height: int, *, seed: int, octaves: int = 4,
           base_cell: int = 16, gain: float = 0.5) -> np.ndarray:
    """Fractal Brownian Motion: sum several octaves of value noise."""
    out = np.zeros((height, width), dtype=np.float32)
    amp = 1.0
    total_amp = 0.0
    cell = base_cell
    for o in range(octaves):
        out += amp * value_noise_2d(width, height, seed=seed + o, cell=cell)
        total_amp += amp
        amp *= gain
        cell = max(2, cell // 2)
    return out / total_amp


def radial_mask(width: int, height: int, *, falloff: float = 1.0) -> np.ndarray:
    """1.0 at center, fading to 0 at the inscribed-circle boundary."""
    cx, cy = (width - 1) / 2.0, (height - 1) / 2.0
    rmax = min(cx, cy)
    yy, xx = np.indices((height, width), dtype=np.float32)
    dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    m = np.clip(1.0 - dist / rmax, 0.0, 1.0)
    return m ** falloff
