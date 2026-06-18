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
    """16x16 body of the Grappler -- a bulky tug with a rear reel housing."""
    g = np.zeros((16, 16), dtype=np.uint8)
    art = [
        "................",
        ".....55555......",
        "....7555557.....",
        "....75BBB57.....",
        "...755555557....",
        "...75CCCCC57....",
        "..75555555557...",
        "..75588888557...",
        "..75899998557...",
        ".7589999999857..",
        ".7589999999857..",
        ".7558999998557..",
        "..7588888887....",
        "...88.999.88....",
        "....9..9..9.....",
        "................",
    ]
    for y, row in enumerate(art):
        for x, c in enumerate(row):
            g[y, x] = 0 if c == '.' else int(c, 16)
    return g


def _body_lancer() -> np.ndarray:
    """16x16 body of the Lancer -- a slim needle with a forward weapon prong."""
    g = np.zeros((16, 16), dtype=np.uint8)
    art = [
        "................",
        ".......8........",
        ".......7........",
        ".......7........",
        ".......7........",
        "......787.......",
        "......7B7.......",
        ".....77B77......",
        ".....75557......",
        ".....75557......",
        "....7555557.....",
        "....75CCC57.....",
        "....7555557.....",
        "....75888557....",
        ".....78887......",
        "......989.......",
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
