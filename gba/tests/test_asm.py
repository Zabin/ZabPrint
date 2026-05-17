"""Two-pass assembler driver tests.

The assembler accepts a string of assembly source and returns a flat bytes
object plus a symbol table. It supports:
  * `.arm` / `.thumb` mode switching (with implicit alignment to 4 or 2)
  * Labels with forward and backward references
  * `.equ NAME, expr` constants
  * `.word`, `.hword`, `.byte` data directives
  * `.incbin "path"` raw byte inclusion
  * `.align N` (power-of-two byte alignment)
  * `ldr Rd, =expr` -- literal-pool load, flushed at `.ltorg` or end of section
  * Numeric literals in dec, 0xhex, 0bbin
  * Comments with `;` or `@` or `//`

The driver lives in toolchain.asm; encoder calls are dispatched through the
ARM/Thumb modules verified in test_arm_encoding.py / test_thumb_encoding.py.
"""
from pathlib import Path
import pytest

from toolchain.asm import assemble


def asm(src: str, *, base_addr: int = 0x08000000):
    return assemble(src, base_addr=base_addr)


# ---------------------------------------------------------------------------
# Trivial single instructions
# ---------------------------------------------------------------------------

def test_arm_mov_immediate():
    r = asm(".arm\nmov r0, #0\n")
    # 0xE3A00000 little-endian
    assert r.bytes_ == bytes.fromhex("0000A0E3")

def test_arm_two_instructions_pack_little_endian():
    r = asm(".arm\nmov r0, #0\nmov r1, #1\n")
    # 0xE3A00000, 0xE3A01001
    assert r.bytes_ == bytes.fromhex("0000A0E3") + bytes.fromhex("0110A0E3")

def test_thumb_mov_imm8():
    r = asm(".thumb\nmov r0, #0\n")
    # 0x2000 little-endian
    assert r.bytes_ == bytes.fromhex("0020")


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------

def test_arm_branch_to_label_backward():
    src = """
    .arm
loop:
    mov r0, #0
    b loop
"""
    r = asm(src, base_addr=0)
    # loop is at offset 0; b at offset 4; pc+8 = 12; offset to loop = -12.
    # imm24 = -12/4 = -3 -> 0xFFFFFD
    # bytes: 0xEAFFFFFD little-endian = FD FF FF EA
    assert r.bytes_[4:8] == bytes.fromhex("FDFFFFEA")

def test_arm_branch_to_label_forward():
    src = """
    .arm
    b done
    mov r1, #1
done:
    mov r2, #2
"""
    r = asm(src, base_addr=0)
    # b at offset 0, pc+8=8. done at offset 8. offset = 0. imm24=0.
    assert r.bytes_[0:4] == bytes.fromhex("000000EA")

def test_label_offset_in_symbol_table():
    r = asm(".arm\nmov r0,#0\nfoo:\nmov r0,#0\n", base_addr=0x100)
    assert r.symbols["foo"] == 0x104


# ---------------------------------------------------------------------------
# .word / .hword / .byte directives
# ---------------------------------------------------------------------------

def test_word_directive():
    r = asm(".arm\n.word 0xDEADBEEF\n")
    assert r.bytes_ == bytes.fromhex("EFBEADDE")

def test_hword_directive():
    r = asm(".arm\n.hword 0xBEEF\n")
    assert r.bytes_ == bytes.fromhex("EFBE")

def test_byte_directive():
    r = asm(".arm\n.byte 0xAB, 0xCD, 0x12\n")
    assert r.bytes_ == bytes.fromhex("ABCD12")


# ---------------------------------------------------------------------------
# .equ constants
# ---------------------------------------------------------------------------

def test_equ_used_as_immediate():
    src = """
.equ MY_VAL, 0xAB
.arm
mov r0, #MY_VAL
"""
    r = asm(src)
    # mov r0, #0xAB -> 0xE3A000AB
    assert r.bytes_ == bytes.fromhex("AB00A0E3")


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------

def test_comment_semicolon_ignored():
    r = asm(".arm\nmov r0, #0  ; this is a comment\n")
    assert r.bytes_ == bytes.fromhex("0000A0E3")

def test_comment_at_sign_ignored():
    r = asm(".arm\nmov r0, #0  @ at-comment\n")
    assert r.bytes_ == bytes.fromhex("0000A0E3")

def test_comment_double_slash_ignored():
    r = asm(".arm\nmov r0, #0  // c++ style\n")
    assert r.bytes_ == bytes.fromhex("0000A0E3")


# ---------------------------------------------------------------------------
# Literal pool: ldr Rd, =value
# ---------------------------------------------------------------------------

def test_ldr_equals_immediate_pools_word():
    src = """
.arm
ldr r0, =0xDEADBEEF
.ltorg
"""
    r = asm(src)
    # ldr r0, [pc, #0] -- with PC bias +8 and pool right after the instruction
    # ldr at offset 0, pool word at offset 4. PC at execution = 0+8 = 8.
    # Offset needed: pool(4) - (pc+8 = 8) = -4. But that's negative, so we
    # arrange the pool AFTER -- meaning offset = pool(4) - 8 = -4 isn't right.
    # Convention: literal pool is placed immediately after .ltorg. ldr's
    # encoded offset = pool_addr - (instr_addr + 8). Instr at 0, pool at 4 ->
    # offset = -4 (U=0). encoded: E51F0004 (LDR r0, [pc, #-4])
    # We could instead place the pool 4 bytes earlier but standard practice is
    # to use a positive offset; with PC bias the literal pool is at PC+offset
    # where offset>=0. So the assembler should reorder: put a placeholder at
    # the instruction site and place the pool after, with offset positive
    # WHEN there's at least one instruction between LDR and .ltorg. With
    # NO instructions between, the offset is computed as (4 - 8) = -4 and
    # U=0 must be set. That's what the encoder does.
    assert r.bytes_[0:4] == bytes.fromhex("04001FE5")  # E51F0004
    assert r.bytes_[4:8] == bytes.fromhex("EFBEADDE")


def test_ldr_equals_label():
    src = """
.arm
ldr r0, =data_table
b skip
data_table:
.word 0x12345678
skip:
.ltorg
"""
    r = asm(src, base_addr=0x100)
    # Symbol data_table should resolve to base + 8
    assert r.symbols["data_table"] == 0x108


# ---------------------------------------------------------------------------
# Alignment
# ---------------------------------------------------------------------------

def test_align_4_inserts_padding():
    src = """
.arm
.byte 0xAA
.align 4
.word 0x11223344
"""
    r = asm(src)
    # 1 byte + 3 zero pad + 4-byte word
    assert r.bytes_ == bytes.fromhex("AA000000") + bytes.fromhex("44332211")


# ---------------------------------------------------------------------------
# .incbin
# ---------------------------------------------------------------------------

def test_incbin_includes_raw_bytes(tmp_path):
    blob = tmp_path / "blob.bin"
    blob.write_bytes(b"\xDE\xAD\xBE\xEF\x12\x34")
    src = f'.arm\n.incbin "{blob}"\n'
    r = asm(src)
    assert r.bytes_ == b"\xDE\xAD\xBE\xEF\x12\x34"


# ---------------------------------------------------------------------------
# Thumb interwork
# ---------------------------------------------------------------------------

def test_thumb_branch_to_label_backward():
    src = """
.thumb
loop:
    mov r0, #0
    b loop
"""
    r = asm(src, base_addr=0)
    # loop at offset 0. b at offset 2. PC bias +4 -> pc=6. offset needed = -6.
    # imm11 = -3, encoded low 11 bits = 0x7FD.
    # Word: 0b11100_11111111101 = 0xE7FD
    assert r.bytes_[2:4] == bytes.fromhex("FDE7")


# ---------------------------------------------------------------------------
# Bare-bones round-trip: assembled output is byte-exact
# ---------------------------------------------------------------------------

def test_complete_program_roundtrip():
    src = """
.arm
.equ REG_DISPCNT, 0x04000000
start:
    ldr r0, =REG_DISPCNT
    mov r1, #0
    str r1, [r0]
hang:
    b hang
.ltorg
"""
    r = asm(src, base_addr=0x08000000)
    # 4 instructions + 1 pool word = 20 bytes
    assert len(r.bytes_) == 20
    # last instruction = "b hang" -- branches to itself, offset=-8, imm24=-2=0xFFFFFE
    assert r.bytes_[12:16] == bytes.fromhex("FEFFFFEA")
