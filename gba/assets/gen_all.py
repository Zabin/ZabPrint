"""Drive every asset generator and dump PNG previews + raw ROM blobs.

Usage:
  python3 -m assets.gen_all

Outputs (under gba/build/):
  preview/palette_banks.png    All 16-color banks as labeled swatches.
  preview/font.png             Full ASCII glyph sheet.
  preview/stars.png            256x256 starfield region.
  preview/planets.png          All planet variants as a contact sheet.
  preview/ships.png            Grappler + Lancer + thrust frames.
  preview/ui.png               HUD + reticle + maneuver-node icon.
  preview/scene_title.png      Mock title screen.
  preview/scene_flight.png     Mock flight gameplay frame.
"""
from pathlib import Path
import numpy as np

from assets.preview import (
    save_png, indexed_to_rgb, palette_to_rgb,
    stack_horizontal, stack_vertical,
)
from assets.gen_palette import ALL_BANKS, BANK_NAMES
from assets.gen_font import font_sheet_indices
from assets.gen_stars import starfield_indices
from assets.gen_planet import render_all_variants, PLANET_VARIANTS
from assets.gen_ship import render_ships
from assets.gen_ui import (
    render_reticle, render_maneuver_node, render_hud_frame, render_velocity_marker,
)
from assets.gen_scene import render_scene_title, render_scene_flight


BUILD_DIR = Path(__file__).resolve().parent.parent / "build" / "preview"


def _swatch(rgb: tuple[int, int, int], size: int) -> np.ndarray:
    out = np.zeros((size, size, 3), dtype=np.uint8)
    out[:] = rgb
    return out


def render_palette_banks_png(swatch_size: int = 16) -> np.ndarray:
    """A grid of 16 banks (rows) x 16 colors (cols), each cell `swatch_size` px."""
    rows = []
    for bank in ALL_BANKS:
        rgb = palette_to_rgb(bank)
        row = np.concatenate([_swatch(c, swatch_size) for c in rgb], axis=1)
        rows.append(row)
    grid = np.concatenate(rows, axis=0)
    return grid


def main():
    BUILD_DIR.mkdir(parents=True, exist_ok=True)

    # --- Palette banks ---
    pal_img = render_palette_banks_png(swatch_size=16)
    save_png(pal_img, BUILD_DIR / "palette_banks.png", scale=2)

    # --- Font sheet ---
    font_idx = font_sheet_indices()
    # Use HUD bank for display: idx 0 -> black, idx 1 -> bright green
    font_palette = [(0, 0, 0), (0, 31, 8)] + [(0, 0, 0)] * 14
    font_rgb = indexed_to_rgb(font_idx, font_palette)
    save_png(font_rgb, BUILD_DIR / "font.png", scale=2)

    # --- Stars ---
    from assets.gen_palette import BANK_STARS
    stars_idx = starfield_indices(256, 256, seed=0xC0DE)
    stars_rgb = indexed_to_rgb(stars_idx, BANK_STARS)
    save_png(stars_rgb, BUILD_DIR / "stars.png", scale=1)

    # --- Planets contact sheet ---
    from assets.gen_palette import BANK_ROCKY, BANK_GAS, BANK_ICE
    bank_for_idx = {2: BANK_ROCKY, 3: BANK_GAS, 4: BANK_ICE}
    variants = render_all_variants(64)
    planet_rgbs = []
    for label, bank_idx, idx_arr in variants:
        rgb = indexed_to_rgb(idx_arr, bank_for_idx[bank_idx])
        planet_rgbs.append(rgb)
    planets_img = stack_horizontal(planet_rgbs, gap=8, gap_color=(0, 0, 0))
    save_png(planets_img, BUILD_DIR / "planets.png", scale=3)

    # --- Ships ---
    from assets.gen_palette import BANK_GRAPPLER, BANK_LANCER, BANK_THRUST
    ships = render_ships()
    grappler_rgb = indexed_to_rgb(ships['grappler_idle'], BANK_GRAPPLER)
    lancer_rgb = indexed_to_rgb(ships['lancer_idle'], BANK_LANCER)
    thrust_low_rgb = indexed_to_rgb(ships['thrust_low'], BANK_THRUST)
    thrust_high_rgb = indexed_to_rgb(ships['thrust_high'], BANK_THRUST)
    ships_img = stack_horizontal(
        [grappler_rgb, lancer_rgb, thrust_low_rgb, thrust_high_rgb],
        gap=8, gap_color=(0, 0, 0),
    )
    save_png(ships_img, BUILD_DIR / "ships.png", scale=6)

    # --- UI ---
    from assets.gen_palette import BANK_RETICLE, BANK_MANEUVER, BANK_HUD
    reticle_rgb = indexed_to_rgb(render_reticle(), BANK_RETICLE)
    maneuver_rgb = indexed_to_rgb(render_maneuver_node(), BANK_MANEUVER)
    vel_rgb = indexed_to_rgb(render_velocity_marker(), BANK_RETICLE)
    hud_rgb = indexed_to_rgb(render_hud_frame(240, 32), BANK_HUD)
    icons = stack_horizontal([reticle_rgb, maneuver_rgb, vel_rgb],
                             gap=8, gap_color=(0, 0, 0))
    ui_img = stack_vertical([icons, hud_rgb], gap=8, gap_color=(0, 0, 0))
    save_png(ui_img, BUILD_DIR / "ui.png", scale=3)

    # --- Composited scene previews ---
    save_png(render_scene_title(), BUILD_DIR / "scene_title.png", scale=2)
    save_png(render_scene_flight(), BUILD_DIR / "scene_flight.png", scale=2)

    print(f"Previews written to {BUILD_DIR}")


if __name__ == "__main__":
    main()
