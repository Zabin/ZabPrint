"""Canonical 156-byte Nintendo logo blob expected by the GBA BIOS at cart
offsets 0x04..0x9F.

The BIOS compares this region against its internal copy on boot. Any deviation
causes the cart to be rejected. Homebrew uses the exact same byte sequence;
this is what every GBA cart, official or otherwise, must contain.

Hex grouped 16 per row for readability; assembled into a single bytes object.
"""

_LOGO_HEX = """
24 FF AE 51 69 9A A2 21 3D 84 82 0A 84 E4 09 AD
11 24 8B 98 C0 81 7F 21 A3 52 BE 19 93 09 CE 20
10 46 4A 4A F8 27 31 EC 58 C7 E8 33 82 E3 CE BF
85 F4 DF 94 CE 4B 09 C1 94 56 8A C0 13 72 A7 FC
9F 84 4D 73 A3 CA 9A 61 58 97 A3 27 FC 03 98 76
23 1D C7 61 03 04 AE 56 BF 38 84 00 40 A7 0E FD
FF 52 FE 03 6F 95 30 F1 97 FB C0 85 60 D6 80 25
A9 63 BE 03 01 4E 38 E2 F9 A2 34 FF BB 3E 03 44
78 00 90 CB 88 11 3A 94 65 C0 7C 63 87 F0 3C AF
D6 25 E4 8B 38 0A AC 72 21 D4 F8 07
"""

NINTENDO_LOGO = bytes.fromhex(_LOGO_HEX.replace('\n', '').replace(' ', ''))

assert len(NINTENDO_LOGO) == 156, f"Nintendo logo wrong length: {len(NINTENDO_LOGO)}"
