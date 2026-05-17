"""Ship sprites: Grappler and Lancer, plus thrust frames.

Each ship is 16x16, hand-pixel-coded as a 2D index grid. Idle / thrust-low /
thrust-high frames share the body and only differ in the engine plume.

Palette index convention (per ship's bank):
  0   transparent
  1-7 body steel ramp (dark -> light)
  8   colored glow (cyan for Grappler, red for Lancer)
  9   secondary glow (darker)
  10  shadow detail
  11  cockpit highlight (white)
  12  warm accent (vents)
  13  tertiary glow (brighter)
  14  shadow
  15  deep shadow

Thrust frame indices reference BANK_THRUST instead.
"""
import numpy as np


def _body_grappler() -> np.ndarray:
    """16x16 body of the Grappler -- a slim arrow with grappling arms."""
    g = np.zeros((16, 16), dtype=np.uint8)
    art = [
        "................",
        ".......77.......",
        "......7777......",
        "......7558......",
        ".....755558.....",
        ".....755558.....",
        "....75555558....",
        "....75588558....",
        "...7558558558...",
        "...7755555557...",
        "..755588885557..",
        "..755588885557..",
        ".7559..88..9557.",
        ".55....99....55.",
        ".5............5.",
        "................",
    ]
    for y, row in enumerate(art):
        for x, c in enumerate(row):
            g[y, x] = 0 if c == '.' else int(c, 16)
    return g


def _body_lancer() -> np.ndarray:
    """16x16 body of the Lancer -- a sharper dart with side fins."""
    g = np.zeros((16, 16), dtype=np.uint8)
    art = [
        "................",
        ".......B........",
        ".......77.......",
        "......7887......",
        "......7887......",
        "..3...77BB77..3.",
        "..73.7755557.37.",
        "..7757555555757.",
        "...775555555577.",
        "....75588885577.",
        ".....7588885577.",
        ".....75888885.7.",
        ".....758888857..",
        "......7888887...",
        ".......98889....",
        "........99......",
    ]
    for y, row in enumerate(art):
        for x, c in enumerate(row):
            g[y, x] = 0 if c == '.' else int(c, 16)
    return g


def _thrust_low() -> np.ndarray:
    """8x6 thrust frame, indices into BANK_THRUST."""
    g = np.zeros((6, 8), dtype=np.uint8)
    art = [
        "...11...",
        "..1221..",
        ".122321.",
        ".123431.",
        "..1331..",
        "...11...",
    ]
    for y, row in enumerate(art):
        for x, c in enumerate(row):
            g[y, x] = 0 if c == '.' else int(c)
    return g


def _thrust_high() -> np.ndarray:
    """8x10 thrust frame, indices into BANK_THRUST."""
    g = np.zeros((10, 8), dtype=np.uint8)
    art = [
        "...11...",
        "..1221..",
        ".122321.",
        ".123431.",
        ".134541.",
        ".134551.",
        "..1441..",
        "..1331..",
        "...22...",
        "....1...",
    ]
    for y, row in enumerate(art):
        for x, c in enumerate(row):
            g[y, x] = 0 if c == '.' else int(c)
    return g


def render_ships() -> dict[str, np.ndarray]:
    """Return all ship sprite frames."""
    return {
        'grappler_idle': _body_grappler(),
        'lancer_idle': _body_lancer(),
        'thrust_low': _thrust_low(),
        'thrust_high': _thrust_high(),
    }
