"""Thumb (16-bit) instruction encoders for ARMv4T.

ARM ARM A6: Thumb has 19 instruction formats. We implement the ones the game
emits. Each encoder returns a 16-bit unsigned int; the BL "long branch with
link" format is unique in returning a (hi, lo) pair (two 16-bit halfwords).

The bit layout for each format is documented in-line above its encoder.
"""

# ---------------------------------------------------------------------------
# Condition codes (same encoding as ARM, but used for fmt 16 only)
# ---------------------------------------------------------------------------
TCOND_EQ = 0x0
TCOND_NE = 0x1
TCOND_CS = 0x2
TCOND_CC = 0x3
TCOND_MI = 0x4
TCOND_PL = 0x5
TCOND_VS = 0x6
TCOND_VC = 0x7
TCOND_HI = 0x8
TCOND_LS = 0x9
TCOND_GE = 0xA
TCOND_LT = 0xB
TCOND_GT = 0xC
TCOND_LE = 0xD
TCOND_AL_T = 0xE  # not used: would conflict with format 17 SWI

# Shift types for format 1
TSHIFT_LSL = 0
TSHIFT_LSR = 1
TSHIFT_ASR = 2

# Format 4 ALU op codes
TALU_AND = 0x0
TALU_EOR = 0x1
TALU_LSL = 0x2
TALU_LSR = 0x3
TALU_ASR = 0x4
TALU_ADC = 0x5
TALU_SBC = 0x6
TALU_ROR = 0x7
TALU_TST = 0x8
TALU_NEG = 0x9
TALU_CMP = 0xA
TALU_CMN = 0xB
TALU_ORR = 0xC
TALU_MUL = 0xD
TALU_BIC = 0xE
TALU_MVN = 0xF

# Format 5 hi-register op codes
THI_ADD = 0x0
THI_CMP = 0x1
THI_MOV = 0x2
# THI_BX uses op=3 implicitly through enc_t_bx


# ---------------------------------------------------------------------------
# Format 1: 000 op[2] imm5 Rs[3] Rd[3] -- shift by immediate
# ---------------------------------------------------------------------------

def enc_t_shift_imm(shift_op: int, imm5: int, Rs: int, Rd: int) -> int:
    assert 0 <= imm5 <= 31
    return (
        (0b000 << 13)
        | (shift_op & 0x3) << 11
        | (imm5 & 0x1F) << 6
        | (Rs & 0x7) << 3
        | (Rd & 0x7)
    )


# ---------------------------------------------------------------------------
# Format 2: 00011 I op Rn[3] Rs[3] Rd[3] -- add/sub register or imm3
# ---------------------------------------------------------------------------

def enc_t_addsub_reg(is_sub: bool, Rm: int, Rs: int, Rd: int) -> int:
    op = 1 if is_sub else 0
    return (
        (0b00011 << 11)
        | (0 << 10)             # I=0 (register)
        | (op & 1) << 9
        | (Rm & 0x7) << 6
        | (Rs & 0x7) << 3
        | (Rd & 0x7)
    )


def enc_t_addsub_imm3(is_sub: bool, imm3: int, Rs: int, Rd: int) -> int:
    assert 0 <= imm3 <= 7
    op = 1 if is_sub else 0
    return (
        (0b00011 << 11)
        | (1 << 10)             # I=1 (immediate)
        | (op & 1) << 9
        | (imm3 & 0x7) << 6
        | (Rs & 0x7) << 3
        | (Rd & 0x7)
    )


# ---------------------------------------------------------------------------
# Format 3: 001 op[2] Rd[3] imm8 -- mov/cmp/add/sub imm8
# ---------------------------------------------------------------------------

def enc_t_movcmpaddsub_imm8(op: int, Rd: int, imm8: int) -> int:
    assert 0 <= imm8 <= 255
    return (
        (0b001 << 13)
        | (op & 0x3) << 11
        | (Rd & 0x7) << 8
        | (imm8 & 0xFF)
    )


# ---------------------------------------------------------------------------
# Format 4: 010000 op[4] Rs[3] Rd[3] -- ALU operation
# ---------------------------------------------------------------------------

def enc_t_alu(op: int, Rs: int, Rd: int) -> int:
    return (
        (0b010000 << 10)
        | (op & 0xF) << 6
        | (Rs & 0x7) << 3
        | (Rd & 0x7)
    )


# ---------------------------------------------------------------------------
# Format 5: 010001 op[2] H1 H2 Rs[3] Rd[3] -- hi register + BX
# ---------------------------------------------------------------------------

def enc_t_hireg_op(op: int, H1: int, H2: int, Rs: int, Rd: int) -> int:
    return (
        (0b010001 << 10)
        | (op & 0x3) << 8
        | (H1 & 1) << 7
        | (H2 & 1) << 6
        | (Rs & 0x7) << 3
        | (Rd & 0x7)
    )


def enc_t_bx(Rm: int) -> int:
    """BX <reg>. Rm encodes the full 0..15 register number (H2 supplies the
    high bit). H1 must be 0; Rd field must be 000."""
    H2 = 1 if Rm >= 8 else 0
    return (
        (0b010001 << 10)
        | (0b11 << 8)           # op = 11 (BX)
        | (0 << 7)              # H1 = 0
        | (H2 << 6)
        | (Rm & 0x7) << 3
        # Rd bits = 000
    )


# ---------------------------------------------------------------------------
# Format 6: 01001 Rd[3] imm8 -- PC-relative load
# ---------------------------------------------------------------------------

def enc_t_ldr_pc_rel(Rd: int, imm8_words: int) -> int:
    """LDR Rd, [PC, #(imm8_words * 4)]. Effective address rounds PC down to
    a word boundary then adds the offset."""
    assert 0 <= imm8_words <= 255
    return (
        (0b01001 << 11)
        | (Rd & 0x7) << 8
        | (imm8_words & 0xFF)
    )


# ---------------------------------------------------------------------------
# Format 7/8: 0101 L B 0 Rm[3] Rb[3] Rd[3] -- load/store with register offset
# ---------------------------------------------------------------------------

def enc_t_ldst_reg(L: int, B: int, Rm: int, Rb: int, Rd: int) -> int:
    return (
        (0b0101 << 12)
        | (L & 1) << 11
        | (B & 1) << 10
        | (0 << 9)
        | (Rm & 0x7) << 6
        | (Rb & 0x7) << 3
        | (Rd & 0x7)
    )


# ---------------------------------------------------------------------------
# Format 9: 011 B L imm5 Rb[3] Rd[3] -- load/store imm5 offset
#   Word access (B=0): real offset = imm5 << 2
#   Byte access (B=1): real offset = imm5
# ---------------------------------------------------------------------------

def enc_t_ldst_imm5(L: int, B: int, imm5_scaled: int, Rb: int, Rd: int) -> int:
    assert 0 <= imm5_scaled <= 31
    return (
        (0b011 << 13)
        | (B & 1) << 12
        | (L & 1) << 11
        | (imm5_scaled & 0x1F) << 6
        | (Rb & 0x7) << 3
        | (Rd & 0x7)
    )


# ---------------------------------------------------------------------------
# Format 10: 1000 L imm5 Rb[3] Rd[3] -- halfword load/store
#   real offset = imm5 << 1
# ---------------------------------------------------------------------------

def enc_t_ldsth_imm5(L: int, imm5_scaled: int, Rb: int, Rd: int) -> int:
    assert 0 <= imm5_scaled <= 31
    return (
        (0b1000 << 12)
        | (L & 1) << 11
        | (imm5_scaled & 0x1F) << 6
        | (Rb & 0x7) << 3
        | (Rd & 0x7)
    )


# ---------------------------------------------------------------------------
# Format 11: 1001 L Rd[3] imm8 -- SP-relative load/store
#   real offset = imm8 << 2
# ---------------------------------------------------------------------------

def enc_t_ldst_sp(L: int, Rd: int, imm8_words: int) -> int:
    assert 0 <= imm8_words <= 255
    return (
        (0b1001 << 12)
        | (L & 1) << 11
        | (Rd & 0x7) << 8
        | (imm8_words & 0xFF)
    )


# ---------------------------------------------------------------------------
# Format 12: 1010 SP Rd[3] imm8 -- get relative address (ADD Rd, PC/SP, #)
# ---------------------------------------------------------------------------

def enc_t_add_pc_sp(SP: bool, Rd: int, imm8_words: int) -> int:
    assert 0 <= imm8_words <= 255
    return (
        (0b1010 << 12)
        | (1 << 11 if SP else 0)
        | (Rd & 0x7) << 8
        | (imm8_words & 0xFF)
    )


# ---------------------------------------------------------------------------
# Format 13: 10110000 S imm7 -- add/sub SP by imm7*4
# ---------------------------------------------------------------------------

def enc_t_add_sp(is_sub: bool, imm7_words: int) -> int:
    assert 0 <= imm7_words <= 127
    return (
        (0b10110000 << 8)
        | (1 << 7 if is_sub else 0)
        | (imm7_words & 0x7F)
    )


# ---------------------------------------------------------------------------
# Format 14: 1011 L 10 R reglist[8] -- PUSH / POP
#   For PUSH: L=0, R=1 includes LR
#   For POP : L=1, R=1 includes PC
# ---------------------------------------------------------------------------

def enc_t_push(reglist: int, R_bit: bool) -> int:
    return (
        (0b1011 << 12)
        | (0 << 11)             # L=0 push
        | (0b10 << 9)
        | (1 << 8 if R_bit else 0)
        | (reglist & 0xFF)
    )


def enc_t_pop(reglist: int, R_bit: bool) -> int:
    return (
        (0b1011 << 12)
        | (1 << 11)             # L=1 pop
        | (0b10 << 9)
        | (1 << 8 if R_bit else 0)
        | (reglist & 0xFF)
    )


# ---------------------------------------------------------------------------
# Format 15: 1100 L Rb[3] reglist[8] -- multiple load/store
# ---------------------------------------------------------------------------

def enc_t_stmia(Rb: int, reglist: int) -> int:
    return (
        (0b1100 << 12)
        | (0 << 11)
        | (Rb & 0x7) << 8
        | (reglist & 0xFF)
    )


def enc_t_ldmia(Rb: int, reglist: int) -> int:
    return (
        (0b1100 << 12)
        | (1 << 11)
        | (Rb & 0x7) << 8
        | (reglist & 0xFF)
    )


# ---------------------------------------------------------------------------
# Format 16: 1101 cond imm8 -- conditional branch
#   real offset = imm8_signed << 1, taking PC bias +4 into account
# ---------------------------------------------------------------------------

def enc_t_b_cond(cond: int, offset: int) -> int:
    """offset is in bytes from the current PC (already accounts for PC bias +4)."""
    assert offset % 2 == 0
    imm8 = (offset >> 1) & 0xFF
    assert -0x80 <= (offset >> 1) <= 0x7F, f"conditional branch offset {offset} out of range"
    return (
        (0b1101 << 12)
        | (cond & 0xF) << 8
        | imm8
    )


# ---------------------------------------------------------------------------
# Format 17: 11011111 imm8 -- SWI
# ---------------------------------------------------------------------------

def enc_t_swi(imm8: int) -> int:
    assert 0 <= imm8 <= 255
    return (0b11011111 << 8) | imm8


# ---------------------------------------------------------------------------
# Format 18: 11100 imm11 -- unconditional branch
# ---------------------------------------------------------------------------

def enc_t_b(offset: int) -> int:
    assert offset % 2 == 0
    half = offset >> 1
    assert -0x400 <= half <= 0x3FF, f"unconditional branch offset {offset} out of range"
    return (0b11100 << 11) | (half & 0x7FF)


# ---------------------------------------------------------------------------
# Format 19: 1111 0 imm11_hi  /  1111 1 imm11_lo -- long branch with link
#   Returns (hi, lo). Offset is signed 23-bit (in bytes, even), taking PC bias
#   +4 into account.
# ---------------------------------------------------------------------------

def enc_t_bl_pair(offset: int) -> tuple[int, int]:
    assert offset % 2 == 0
    imm22 = offset >> 1
    # Mask to 22-bit two's-complement
    imm22 &= (1 << 22) - 1
    hi = (0b11110 << 11) | ((imm22 >> 11) & 0x7FF)
    lo = (0b11111 << 11) | (imm22 & 0x7FF)
    return hi, lo
