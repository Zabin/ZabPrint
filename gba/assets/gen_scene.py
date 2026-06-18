"""Composite a mock in-game frame as a PNG preview.

Renders what the user would see on a GBA screen (240x160 px) by manually
compositing:
  BG1: starfield (BANK_STARS)
  BG2: planet sprite (BANK_GAS / BANK_ROCKY / BANK_ICE)
  OAM: ship sprite (BANK_GRAPPLER or BANK_LANCER) + reticle + maneuver node
  BG0: HUD strip at bottom (BANK_HUD) with text

This is software-rendered in Python; the actual ROM will produce the same
image via the hardware's tile/sprite engines.
"""
import numpy as np

from assets.preview import indexed_to_rgb, palette_to_rgb
from assets.gen_palette import (
    BANK_STARS, BANK_GRAPPLER, BANK_LANCER, BANK_HUD, BANK_RETICLE,
    BANK_MANEUVER, BANK_GAS, BANK_ROCKY, BANK_ICE, BANK_THRUST,
)
from assets.gen_stars import starfield_indices
from assets.gen_planet import render_planet
from assets.gen_ship import render_ships
from assets.gen_ui import (
    render_reticle, render_maneuver_node, render_hud_frame, render_velocity_marker,
)
from assets.gen_font import glyph_indices


SCREEN_W = 240
SCREEN_H = 160


def _paste_sprite_rgb(canvas: np.ndarray, sprite_indices: np.ndarray,
                      palette_rgb: list[tuple[int, int, int]],
                      x: int, y: int):
    """Paint a sprite onto an RGB canvas, treating index 0 as transparent."""
    H, W = sprite_indices.shape
    for sy in range(H):
        for sx in range(W):
            idx = int(sprite_indices[sy, sx])
            if idx == 0:
                continue
            cx, cy = x + sx, y + sy
            if 0 <= cx < canvas.shape[1] and 0 <= cy < canvas.shape[0]:
                canvas[cy, cx] = palette_rgb[idx]


def render_scene_title() -> np.ndarray:
    """Mock title screen."""
    canvas = np.zeros((SCREEN_H, SCREEN_W, 3), dtype=np.uint8)
    stars = starfield_indices(SCREEN_W, SCREEN_H, seed=0x71_71_71)
    return _render_title_inner(canvas, stars)


def _render_title_inner(canvas, stars):
    pal_stars = palette_to_rgb(BANK_STARS)
    canvas[:] = indexed_to_rgb(stars, BANK_STARS)
    pal_lancer = palette_to_rgb(BANK_LANCER)
    pal_grappler = palette_to_rgb(BANK_GRAPPLER)
    pal_hud = palette_to_rgb(BANK_HUD)

    # Title text "ZAB SPACE" centered
    title = "ZAB SPACE"
    char_w = 8
    total_w = len(title) * char_w
    start_x = (SCREEN_W - total_w) // 2
    for i, ch in enumerate(title):
        g = glyph_indices(ch, fg=1, bg=0)
        _paste_sprite_rgb(canvas, g, pal_hud, start_x + i * char_w, 40)
    subtitle = "PRESS START"
    sub_x = (SCREEN_W - len(subtitle) * char_w) // 2
    for i, ch in enumerate(subtitle):
        g = glyph_indices(ch, fg=5, bg=0)
        _paste_sprite_rgb(canvas, g, pal_hud, sub_x + i * char_w, 120)

    # Decorative ships flanking the title
    ships = render_ships()
    _paste_sprite_rgb(canvas, ships['grappler_idle'], pal_grappler,
                      start_x - 24, 36)
    _paste_sprite_rgb(canvas, ships['lancer_idle'], pal_lancer,
                      start_x + total_w + 8, 36)
    return canvas


def render_scene_flight() -> np.ndarray:
    """Mock in-flight gameplay frame."""
    canvas = np.zeros((SCREEN_H, SCREEN_W, 3), dtype=np.uint8)
    # BG1: starfield
    stars = starfield_indices(SCREEN_W, SCREEN_H, seed=0xF11)
    canvas[:] = indexed_to_rgb(stars, BANK_STARS)

    # BG2: a planet at the upper-left
    planet = render_planet(64, bank_idx=3, seed=0xF12, light_dir_x=-0.7)
    pal_gas = palette_to_rgb(BANK_GAS)
    _paste_sprite_rgb(canvas, planet, pal_gas, 8, 16)

    # OAM: ship near center, reticle to the right, maneuver node ahead
    ships = render_ships()
    pal_grappler = palette_to_rgb(BANK_GRAPPLER)
    _paste_sprite_rgb(canvas, ships['grappler_idle'], pal_grappler, 110, 70)

    # Thrust plume behind the ship
    thrust = ships['thrust_high']
    pal_thrust = palette_to_rgb(BANK_THRUST)
    _paste_sprite_rgb(canvas, thrust, pal_thrust, 114, 84)

    pal_ret = palette_to_rgb(BANK_RETICLE)
    _paste_sprite_rgb(canvas, render_reticle(), pal_ret, 180, 50)

    pal_man = palette_to_rgb(BANK_MANEUVER)
    _paste_sprite_rgb(canvas, render_maneuver_node(), pal_man, 150, 35)

    pal_vel = palette_to_rgb(BANK_RETICLE)
    _paste_sprite_rgb(canvas, render_velocity_marker(), pal_vel, 150, 75)

    # HUD strip at the bottom
    pal_hud = palette_to_rgb(BANK_HUD)
    hud = render_hud_frame(SCREEN_W, 28)
    hud_rgb = indexed_to_rgb(hud, BANK_HUD)
    canvas[SCREEN_H - 28:SCREEN_H, :] = hud_rgb

    # HUD text
    lines = [
        ("ALT 0204", 4, SCREEN_H - 24, 1),
        ("VEL 41.8", 86, SCREEN_H - 24, 1),
        ("TGT LOCK", 168, SCREEN_H - 24, 13),
        ("WARP 010X", 4, SCREEN_H - 12, 5),
        ("FUEL 87%", 86, SCREEN_H - 12, 1),
        ("MISN  2/4", 168, SCREEN_H - 12, 1),
    ]
    for text, x, y, fg in lines:
        for i, ch in enumerate(text):
            g = glyph_indices(ch, fg=fg, bg=0)
            _paste_sprite_rgb(canvas, g, pal_hud, x + i * 8, y)

    return canvas
