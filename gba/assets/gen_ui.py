"""HUD frames, target reticle, maneuver-node icon.

All sprites are indexed into specific palette banks.
"""
import numpy as np


def render_reticle() -> np.ndarray:
    """16x16 target reticle using BANK_RETICLE indices."""
    g = np.zeros((16, 16), dtype=np.uint8)
    art = [
        "................",
        "......1111......",
        ".....1....1.....",
        "....1......1....",
        "...1........1...",
        "...1........1...",
        "..1..........1..",
        "..1...88.....1..",
        "..1...88.....1..",
        "..1..........1..",
        "...1........1...",
        "...1........1...",
        "....1......1....",
        ".....1....1.....",
        "......1111......",
        "................",
    ]
    for y, row in enumerate(art):
        for x, c in enumerate(row):
            g[y, x] = 0 if c == '.' else int(c, 16)
    return g


def render_maneuver_node() -> np.ndarray:
    """16x16 maneuver-node icon using BANK_MANEUVER indices."""
    g = np.zeros((16, 16), dtype=np.uint8)
    art = [
        "................",
        "................",
        "......2222......",
        ".....233332.....",
        "....23344332....",
        "....23499432....",
        "....23944932....",
        "....239AA932....",
        "....23944932....",
        "....23499432....",
        "....23344332....",
        ".....233332.....",
        "......2222......",
        "................",
        "................",
        "................",
    ]
    for y, row in enumerate(art):
        for x, c in enumerate(row):
            g[y, x] = 0 if c == '.' else int(c, 16)
    return g


def render_hud_frame(width: int = 240, height: int = 32) -> np.ndarray:
    """Bottom HUD strip background frame (uses BANK_HUD indices)."""
    g = np.zeros((height, width), dtype=np.uint8)
    # Outer bevel
    g[0, :] = 3
    g[-1, :] = 3
    g[:, 0] = 3
    g[:, -1] = 3
    # Inner fill: very dark green
    g[1:-1, 1:-1] = 4
    # Divider lines (vertical) at 1/3 and 2/3
    g[1:-1, width // 3] = 2
    g[1:-1, 2 * width // 3] = 2
    return g


def render_velocity_marker() -> np.ndarray:
    """Small 8x8 prograde marker (BANK_RETICLE indices)."""
    g = np.zeros((8, 8), dtype=np.uint8)
    art = [
        "...11...",
        "..1881..",
        ".18..81.",
        "18....81",
        "18....81",
        ".18..81.",
        "..1881..",
        "...11...",
    ]
    for y, row in enumerate(art):
        for x, c in enumerate(row):
            g[y, x] = 0 if c == '.' else int(c, 16)
    return g
