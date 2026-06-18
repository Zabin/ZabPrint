"""Single-command build for the GBA ROM.

Concatenates every src/*.s into one assembly unit, hands it to the in-tree
two-pass assembler, prepends a hand-encoded entry-point branch, and runs the
result through the cartridge packer. Output is build/game.gba (2 MiB).

Run from the gba/ directory:

    python -m build           # or: python build.py
"""
from __future__ import annotations

from pathlib import Path

from toolchain.asm import assemble
from toolchain.cart import pack_rom


_ROOT = Path(__file__).resolve().parent
SRC_DIR = _ROOT / "src"
BUILD_DIR = _ROOT / "build"


# "B _start" from ROM offset 0 to the first byte of the payload (ROM offset
# 0xC0). With PC+8 = 0x08000008 and target = 0x080000C0, the imm24 field is
# (0xC0 - 8) / 4 = 0x2E.  cond=AL (0xE), 0b101 << 25, L=0 => 0xEA00002E.
ENTRY_BRANCH = (0xEA00002E).to_bytes(4, "little")

# The assembler is told the payload sits at this address so labels resolve
# correctly. The cart packer then places `payload[4:]` at ROM offset 0xC0,
# i.e. exactly the address we used during assembly.
PAYLOAD_BASE = 0x080000C0

# The order matters: crt0.s must come first so `_start` is at offset 0 of
# the assembled blob.
SOURCE_ORDER = ("crt0.s", "physics.s")


def build_payload() -> bytes:
    parts = []
    for name in SOURCE_ORDER:
        path = SRC_DIR / name
        parts.append(f"@ ===== {name} =====")
        parts.append(path.read_text())
    return assemble("\n".join(parts), base_addr=PAYLOAD_BASE).bytes_


def build_rom() -> bytes:
    main_code = build_payload()
    return pack_rom(ENTRY_BRANCH + main_code, title="ZABSPACE", code="ZSPE")


def main() -> Path:
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    out = BUILD_DIR / "game.gba"
    rom = build_rom()
    out.write_bytes(rom)
    print(f"Wrote {out} ({len(rom):,} bytes)")
    return out


if __name__ == "__main__":
    main()
