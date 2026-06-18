"""Shared 16-color palette banks.

The GBA exposes 256 BG palette entries and 256 sprite palette entries, each
addressable as either one bank of 256 colors or 16 banks of 16 colors. We use
16 banks of 16 throughout, with one bank dedicated to each visual element:

  Bank 0  HUD (greens, ambers, blacks)
  Bank 1  Starfield (deep space blue, white stars)
  Bank 2  Rocky planet
  Bank 3  Gas giant
  Bank 4  Ice planet
  Bank 5  Nebula
  Bank 6  Asteroid grey
  Bank 7  Ship Grappler (steel + cyan)
  Bank 8  Ship Lancer (steel + red)
  Bank 9  Thrust flame (yellow/orange/red)
  Bank 10 Reticle / lock-on (cyan/red)
  Bank 11 Maneuver-node accents (purple/violet)
  Bank 12 Tether/grapple line (steel + amber)
  Bank 13 DEW beam (cyan -> white core)
  Bank 14 Mission complete sting (green)
  Bank 15 Mission fail sting (red)

All entries are stored as 5-bit (0..31) per channel BGR555.
"""
from typing import Sequence

# Each bank is exactly 16 entries (r5, g5, b5). The first entry is always
# transparent / background black for the bank.
Bank = list[tuple[int, int, int]]


# ---------------------------------------------------------------------------
# Hand-tuned banks
# ---------------------------------------------------------------------------

def _ramp(c1: tuple[int, int, int], c2: tuple[int, int, int], n: int) -> list:
    """Linear ramp between two 5-bit colors, n steps inclusive."""
    out = []
    for i in range(n):
        t = i / (n - 1) if n > 1 else 0
        out.append(tuple(
            max(0, min(31, round(c1[k] + (c2[k] - c1[k]) * t)))
            for k in range(3)
        ))
    return out


BANK_HUD: Bank = [
    (0, 0, 0),
    (0, 31, 8),    # bright HUD green
    (0, 22, 6),
    (0, 14, 4),
    (0, 8, 2),
    (31, 24, 0),   # warning amber
    (31, 12, 0),   # alarm red-orange
    (31, 31, 28),  # off-white
    (24, 24, 28),  # cool grey
    (16, 16, 18),
    (8, 8, 10),
    (4, 4, 6),
    (0, 0, 4),
    (2, 16, 24),   # accent cyan
    (0, 24, 31),   # accent bright cyan
    (12, 0, 24),   # accent purple
]

BANK_STARS: Bank = [
    (0, 0, 0),
    (1, 1, 4),
    (2, 2, 6),
    (4, 4, 10),
    (6, 6, 14),
    (10, 10, 18),
    (16, 16, 22),
    (22, 22, 26),
    (28, 28, 30),
    (31, 31, 31),
    (8, 12, 28),    # blue star
    (16, 22, 31),
    (28, 26, 18),   # yellow star
    (31, 28, 12),
    (28, 10, 6),    # red star
    (24, 4, 16),    # magenta nebula tinge
]

BANK_ROCKY: Bank = [
    (0, 0, 0),
    *_ramp((6, 2, 0), (28, 18, 6), 8),
    (16, 8, 0),
    (8, 4, 0),
    (24, 14, 4),
    (31, 22, 10),
    (12, 6, 2),
    (4, 2, 0),
    (31, 28, 22),  # highlight
]

BANK_GAS: Bank = [
    (0, 0, 0),
    *_ramp((4, 6, 24), (16, 22, 31), 6),
    *_ramp((20, 14, 6), (28, 22, 14), 4),
    (28, 28, 30),
    (10, 8, 12),
    (4, 4, 8),
    (24, 18, 8),
    (16, 12, 6),
]

BANK_ICE: Bank = [
    (0, 0, 0),
    *_ramp((4, 6, 10), (24, 28, 31), 8),
    (12, 16, 22),
    (8, 12, 18),
    (28, 30, 31),
    (18, 22, 28),
    (10, 14, 22),
    (4, 6, 12),
    (31, 31, 31),
]

BANK_NEBULA: Bank = [
    (0, 0, 0),
    (8, 0, 16),
    (16, 4, 22),
    (22, 8, 28),
    (28, 14, 31),
    (12, 4, 18),
    (4, 0, 8),
    (0, 8, 22),
    (4, 14, 28),
    (10, 20, 31),
    (20, 28, 31),
    (28, 4, 12),
    (22, 0, 8),
    (16, 0, 4),
    (8, 0, 4),
    (2, 0, 2),
]

BANK_ASTEROID: Bank = [
    (0, 0, 0),
    *_ramp((4, 4, 4), (28, 28, 30), 12),
    (10, 8, 6),
    (6, 4, 2),
    (16, 14, 12),
]

BANK_GRAPPLER: Bank = [
    (0, 0, 0),
    *_ramp((4, 4, 8), (28, 28, 31), 7),       # steel body
    (0, 22, 31),   # cyan glow
    (0, 14, 22),
    (0, 8, 14),
    (31, 31, 31),  # cockpit highlight
    (12, 6, 4),    # warm contrast
    (0, 31, 24),   # tether mount glow
    (6, 12, 18),   # shadow
    (2, 4, 8),
]

BANK_LANCER: Bank = [
    (0, 0, 0),
    *_ramp((6, 4, 4), (30, 28, 28), 7),       # steel body warmed
    (31, 8, 6),    # red glow
    (24, 4, 2),
    (16, 0, 0),
    (31, 31, 31),  # cockpit
    (31, 22, 0),   # exhaust accent
    (16, 8, 4),
    (18, 12, 10),
    (4, 2, 2),
]

BANK_THRUST: Bank = [
    (0, 0, 0),
    (31, 31, 28),
    (31, 28, 14),
    (31, 22, 6),
    (31, 14, 0),
    (28, 6, 0),
    (22, 2, 0),
    (14, 0, 0),
    (6, 0, 0),
    (31, 31, 31),
    (31, 30, 22),
    (28, 18, 4),
    (16, 4, 0),
    (8, 0, 0),
    (2, 0, 0),
    (0, 0, 0),
]

BANK_RETICLE: Bank = [
    (0, 0, 0),
    (0, 31, 28),
    (0, 22, 22),
    (0, 14, 16),
    (0, 8, 10),
    (31, 8, 4),
    (22, 4, 2),
    (16, 0, 0),
    (31, 31, 31),
    (24, 24, 24),
    (16, 16, 16),
    (8, 8, 8),
    (31, 28, 8),
    (28, 18, 4),
    (16, 12, 2),
    (4, 4, 0),
]

BANK_MANEUVER: Bank = [
    (0, 0, 0),
    (16, 4, 28),
    (22, 10, 31),
    (28, 18, 31),
    (12, 0, 22),
    (6, 0, 14),
    (24, 24, 31),
    (10, 8, 16),
    (4, 4, 8),
    (31, 28, 30),
    (28, 18, 22),
    (22, 12, 16),
    (16, 8, 12),
    (8, 4, 8),
    (31, 31, 31),
    (4, 2, 6),
]

BANK_TETHER: Bank = [
    (0, 0, 0),
    (16, 12, 8),
    (24, 18, 10),
    (28, 24, 14),
    (31, 28, 18),
    (22, 16, 8),
    (16, 12, 6),
    (10, 8, 4),
    (6, 4, 2),
    (4, 2, 2),
    (8, 8, 12),
    (16, 16, 22),
    (24, 24, 28),
    (28, 28, 31),
    (31, 31, 31),
    (2, 2, 4),
]

BANK_DEW: Bank = [
    (0, 0, 0),
    (0, 8, 22),
    (0, 16, 28),
    (0, 22, 31),
    (8, 26, 31),
    (16, 28, 31),
    (24, 30, 31),
    (28, 31, 31),
    (31, 31, 31),
    (16, 16, 22),
    (8, 8, 12),
    (4, 4, 8),
    (2, 2, 6),
    (0, 0, 4),
    (24, 16, 31),
    (28, 8, 22),
]

BANK_OK: Bank = [
    (0, 0, 0),
    *_ramp((0, 12, 4), (10, 31, 14), 8),
    (0, 22, 8),
    (4, 16, 6),
    (8, 28, 12),
    (16, 31, 20),
    (24, 31, 26),
    (31, 31, 31),
    (0, 6, 2),
]

BANK_FAIL: Bank = [
    (0, 0, 0),
    *_ramp((12, 0, 0), (31, 8, 4), 8),
    (22, 4, 2),
    (16, 0, 0),
    (28, 12, 8),
    (31, 18, 14),
    (31, 24, 22),
    (31, 31, 31),
    (6, 0, 0),
]


# All banks in order.
ALL_BANKS: list[Bank] = [
    BANK_HUD, BANK_STARS, BANK_ROCKY, BANK_GAS, BANK_ICE, BANK_NEBULA,
    BANK_ASTEROID, BANK_GRAPPLER, BANK_LANCER, BANK_THRUST, BANK_RETICLE,
    BANK_MANEUVER, BANK_TETHER, BANK_DEW, BANK_OK, BANK_FAIL,
]

BANK_NAMES = [
    "HUD", "Stars", "Rocky", "Gas", "Ice", "Nebula", "Asteroid", "Grappler",
    "Lancer", "Thrust", "Reticle", "Maneuver", "Tether", "DEW", "OK", "Fail",
]


# ---------------------------------------------------------------------------
# Verification (every bank must be exactly 16 entries)
# ---------------------------------------------------------------------------

def _verify_banks():
    for name, bank in zip(BANK_NAMES, ALL_BANKS):
        if len(bank) != 16:
            raise AssertionError(f"bank {name} has {len(bank)} entries, expected 16")
        for r, g, b in bank:
            if not (0 <= r <= 31 and 0 <= g <= 31 and 0 <= b <= 31):
                raise AssertionError(f"bank {name} has out-of-range color: ({r},{g},{b})")


_verify_banks()
