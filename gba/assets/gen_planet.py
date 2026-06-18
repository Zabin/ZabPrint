"""Procedural planet sprites.

We render 6 planet variants (32x32 each) using the planet palette banks:
rocky, gas giant, ice. Each is a noise-shaded disc with simple terminator
lighting from the left, so the player gets visual cues about which side
of the planet is sun-facing.
"""
import numpy as np

from assets.noise import fbm_2d
from assets.gen_palette import (
    BANK_ROCKY, BANK_GAS, BANK_ICE,
)


# Variant table: (palette_bank_index, base_seed, light_dir_x, type_label)
PLANET_VARIANTS = [
    (2, 0x10001, -0.7, "rocky-a"),    # rocky, sun from left
    (2, 0x10002, +0.7, "rocky-b"),    # rocky, sun from right
    (3, 0x10003, -0.5, "gas-a"),      # gas giant
    (3, 0x10004, +0.5, "gas-b"),
    (4, 0x10005, -0.6, "ice-a"),
    (4, 0x10006, +0.6, "ice-b"),
]


def render_planet(size: int = 32, *, bank_idx: int, seed: int,
                  light_dir_x: float = -0.7) -> np.ndarray:
    """Return a size x size array of palette indices into the variant's bank.

    Index 0 is reserved as transparent / off-disc.
    """
    bank = [BANK_ROCKY, BANK_GAS, BANK_ICE][[2, 3, 4].index(bank_idx)]
    n_bank = len(bank)
    out = np.zeros((size, size), dtype=np.uint8)
    cx = cy = (size - 1) / 2.0
    radius = size / 2.0 - 1.0

    height = fbm_2d(size, size, seed=seed, octaves=4, base_cell=size // 2)

    # Simple Lambertian lighting: clamp the dot product of the surface
    # normal with a light direction.
    light_dir_y = -0.2
    yy, xx = np.indices((size, size), dtype=np.float32)
    dx = (xx - cx) / radius
    dy = (yy - cy) / radius
    r2 = dx * dx + dy * dy
    on_disc = r2 <= 1.0
    # Approximate z-normal at this disc point: nz = sqrt(1 - r2).
    nz = np.sqrt(np.clip(1.0 - r2, 0.0, 1.0))
    # Surface normal vector (dx, dy, nz). Dot with (light_dir_x, light_dir_y, 0.7).
    light_intensity = (
        dx * light_dir_x + dy * light_dir_y + nz * 0.7
    )
    light_intensity = np.clip(light_intensity, 0.0, 1.0)

    # Modulate brightness by noise so the surface has terrain.
    shading = 0.55 * light_intensity + 0.45 * (height / max(height.max(), 1e-6))
    shading = np.clip(shading, 0.0, 1.0)

    # Map to palette indices 1..(n_bank-1). Index 0 stays as transparent.
    indices = 1 + (shading * (n_bank - 2)).astype(np.uint8)
    indices = np.where(on_disc, indices, 0)

    # Bright limb highlight on the sun-facing edge.
    rim = on_disc & (r2 > 0.85) & (light_intensity > 0.6)
    indices[rim] = n_bank - 1  # highlight color

    out[:, :] = indices
    return out


def render_all_variants(size: int = 32) -> list[tuple[str, int, np.ndarray]]:
    """Return [(label, bank_idx, indices_array), ...] for every variant."""
    out = []
    for bank_idx, seed, lx, label in PLANET_VARIANTS:
        idx = render_planet(size, bank_idx=bank_idx, seed=seed, light_dir_x=lx)
        out.append((label, bank_idx, idx))
    return out
