"""ARM (32-bit) instruction encoders for ARMv4T.

Encoders return a 32-bit unsigned int representing the instruction word.
The caller (linker/cart packer) writes that word as 4 little-endian bytes.

Only the instructions actually emitted by the game are implemented. Each
encoder name documents the family; data-processing opcodes use shared
constants OP_*. Hand-verified golden bytes live in tests/test_arm_encoding.py
and the comments here describe the bit layout for the same instruction.
"""

# ---------------------------------------------------------------------------
# Condition codes (ARM ARM A3.2.1)
# ---------------------------------------------------------------------------
COND_EQ = 0x0
COND_NE = 0x1
COND_CS = 0x2
COND_CC = 0x3
COND_MI = 0x4
COND_PL = 0x5
COND_VS = 0x6
COND_VC = 0x7
COND_HI = 0x8
COND_LS = 0x9
COND_GE = 0xA
COND_LT = 0xB
COND_GT = 0xC
COND_LE = 0xD
COND_AL = 0xE  # always (default)

# ---------------------------------------------------------------------------
# Data-processing opcodes (ARM ARM A3.4)
# ---------------------------------------------------------------------------
OP_AND = 0x0
OP_EOR = 0x1
OP_SUB = 0x2
OP_RSB = 0x3
OP_ADD = 0x4
OP_ADC = 0x5
OP_SBC = 0x6
OP_RSC = 0x7
OP_TST = 0x8   # always S=1
OP_TEQ = 0x9   # always S=1
OP_CMP = 0xA   # always S=1
OP_CMN = 0xB   # always S=1
OP_ORR = 0xC
OP_MOV = 0xD
OP_BIC = 0xE
OP_MVN = 0xF

# Shift types (ARM ARM A5.1)
SHIFT_LSL = 0
SHIFT_LSR = 1
SHIFT_ASR = 2
SHIFT_ROR = 3


# ---------------------------------------------------------------------------
# Immediate encoding (12-bit field, 8-bit imm with 4-bit even rotate)
# ---------------------------------------------------------------------------

def encode_imm12(value: int) -> int:
    """Return imm12 field encoding `value`, or raise ValueError if it cannot be
    expressed as an 8-bit value rotated right by an even amount.

    Layout: [11:8] rotate/2, [7:0] imm8. effective = ROR(imm8, 2*rot).
    """
    value &= 0xFFFFFFFF
    if value == 0:
        return 0
    # Try every even rotate amount from 0 to 30.
    for rot in range(0, 16):
        # ROL(value, 2*rot) -- if this fits in 8 bits, we've found it.
        amount = (2 * rot) & 0x1F
        rotated = ((value << amount) | (value >> (32 - amount))) & 0xFFFFFFFF if amount else value
        if rotated <= 0xFF:
            return (rot << 8) | rotated
    raise ValueError(f"value 0x{value:08X} is not a valid ARM immediate")


# ---------------------------------------------------------------------------
# Data processing - immediate operand
# ---------------------------------------------------------------------------

def enc_dp_imm(op: int, cond: int, S: int, Rd: int, Rn: int, imm: int) -> int:
    """Data processing with 12-bit rotated immediate operand."""
    imm12 = encode_imm12(imm)
    return (
        (cond & 0xF) << 28
        | (0b00 << 26)
        | (1 << 25)             # I=1 immediate
        | (op & 0xF) << 21
        | (S & 1) << 20
        | (Rn & 0xF) << 16
        | (Rd & 0xF) << 12
        | (imm12 & 0xFFF)
    )


# ---------------------------------------------------------------------------
# Data processing - register operand (no shift)
# ---------------------------------------------------------------------------

def enc_dp_reg(op: int, cond: int, S: int, Rd: int, Rn: int, Rm: int) -> int:
    return enc_dp_reg_shift_imm(op, cond, S, Rd, Rn, Rm, SHIFT_LSL, 0)


def enc_dp_reg_shift_imm(op: int, cond: int, S: int, Rd: int, Rn: int,
                         Rm: int, shift: int, amount: int) -> int:
    """Data processing with register operand, shifted by an immediate amount."""
    assert 0 <= amount <= 31, f"shift amount {amount} out of range"
    op2 = (amount & 0x1F) << 7 | (shift & 0x3) << 5 | (Rm & 0xF)
    return (
        (cond & 0xF) << 28
        | (0b00 << 26)
        | (0 << 25)             # I=0 register
        | (op & 0xF) << 21
        | (S & 1) << 20
        | (Rn & 0xF) << 16
        | (Rd & 0xF) << 12
        | op2
    )


# ---------------------------------------------------------------------------
# Multiplication
# ---------------------------------------------------------------------------

def enc_mul(cond: int, S: int, Rd: int, Rm: int, Rs: int) -> int:
    """MUL Rd, Rm, Rs : Rd = Rm * Rs (low 32)."""
    return (
        (cond & 0xF) << 28
        | (0b000000 << 22)
        | (0 << 21)             # A=0 for MUL
        | (S & 1) << 20
        | (Rd & 0xF) << 16
        | (0 << 12)             # Rn unused
        | (Rs & 0xF) << 8
        | (0b1001 << 4)
        | (Rm & 0xF)
    )


def enc_mla(cond: int, S: int, Rd: int, Rm: int, Rs: int, Rn: int) -> int:
    """MLA Rd, Rm, Rs, Rn : Rd = Rm * Rs + Rn."""
    return (
        (cond & 0xF) << 28
        | (0b000000 << 22)
        | (1 << 21)             # A=1 for MLA
        | (S & 1) << 20
        | (Rd & 0xF) << 16
        | (Rn & 0xF) << 12
        | (Rs & 0xF) << 8
        | (0b1001 << 4)
        | (Rm & 0xF)
    )


def enc_smull(cond: int, S: int, RdLo: int, RdHi: int, Rm: int, Rs: int) -> int:
    """SMULL RdLo, RdHi, Rm, Rs : signed 64-bit result of Rm * Rs."""
    return _enc_long_mul(cond, S, RdLo, RdHi, Rm, Rs, U=1, A=0)


def enc_umull(cond: int, S: int, RdLo: int, RdHi: int, Rm: int, Rs: int) -> int:
    return _enc_long_mul(cond, S, RdLo, RdHi, Rm, Rs, U=0, A=0)


def _enc_long_mul(cond, S, RdLo, RdHi, Rm, Rs, U, A) -> int:
    return (
        (cond & 0xF) << 28
        | (0b00001 << 23)
        | (U & 1) << 22
        | (A & 1) << 21
        | (S & 1) << 20
        | (RdHi & 0xF) << 16
        | (RdLo & 0xF) << 12
        | (Rs & 0xF) << 8
        | (0b1001 << 4)
        | (Rm & 0xF)
    )


# ---------------------------------------------------------------------------
# Single data transfer (LDR/STR/LDRB/STRB) with immediate offset
# ---------------------------------------------------------------------------

def _enc_sdt_imm(cond, Rd, Rn, imm, *, L, B):
    """Internal helper. P=1 (pre-indexed), W=0 (no writeback)."""
    U = 1 if imm >= 0 else 0
    off = abs(imm)
    assert 0 <= off < 4096, f"sdt offset {imm} out of range"
    return (
        (cond & 0xF) << 28
        | (0b01 << 26)
        | (0 << 25)             # I=0 immediate
        | (1 << 24)             # P=1
        | (U & 1) << 23
        | (B & 1) << 22
        | (0 << 21)             # W=0
        | (L & 1) << 20
        | (Rn & 0xF) << 16
        | (Rd & 0xF) << 12
        | (off & 0xFFF)
    )


def enc_ldr_imm(cond, Rd, Rn, imm):
    return _enc_sdt_imm(cond, Rd, Rn, imm, L=1, B=0)


def enc_str_imm(cond, Rd, Rn, imm):
    return _enc_sdt_imm(cond, Rd, Rn, imm, L=0, B=0)


def enc_ldrb_imm(cond, Rd, Rn, imm):
    return _enc_sdt_imm(cond, Rd, Rn, imm, L=1, B=1)


def enc_strb_imm(cond, Rd, Rn, imm):
    return _enc_sdt_imm(cond, Rd, Rn, imm, L=0, B=1)


# ---------------------------------------------------------------------------
# Halfword load/store (ARM ARM A3.10)
# ---------------------------------------------------------------------------

def _enc_hw_imm(cond, Rd, Rn, imm, *, L, SH):
    U = 1 if imm >= 0 else 0
    off = abs(imm)
    assert 0 <= off < 256, f"halfword offset {imm} out of range"
    offH = (off >> 4) & 0xF
    offL = off & 0xF
    return (
        (cond & 0xF) << 28
        | (0b000 << 25)
        | (1 << 24)             # P=1
        | (U & 1) << 23
        | (1 << 22)             # I=1 immediate halfword form
        | (0 << 21)             # W=0
        | (L & 1) << 20
        | (Rn & 0xF) << 16
        | (Rd & 0xF) << 12
        | (offH & 0xF) << 8
        | (1 << 7)
        | (SH & 0x3) << 5
        | (1 << 4)
        | (offL & 0xF)
    )


def enc_ldrh_imm(cond, Rd, Rn, imm):
    return _enc_hw_imm(cond, Rd, Rn, imm, L=1, SH=0b01)


def enc_strh_imm(cond, Rd, Rn, imm):
    return _enc_hw_imm(cond, Rd, Rn, imm, L=0, SH=0b01)


# ---------------------------------------------------------------------------
# Branches
# ---------------------------------------------------------------------------

def _enc_branch_common(cond: int, L: int, offset: int) -> int:
    """offset is in bytes from the branch instruction (taking PC=PC+8 bias into
    account already). It must be word-aligned (multiple of 4) and fit in a
    signed 26-bit range (+/- 32 MiB)."""
    assert offset % 4 == 0, f"branch offset {offset} not word-aligned"
    imm24 = (offset >> 2) & 0xFFFFFF
    return (
        (cond & 0xF) << 28
        | (0b101 << 25)
        | (L & 1) << 24
        | imm24
    )


def enc_branch(cond: int, offset: int) -> int:
    return _enc_branch_common(cond, L=0, offset=offset)


def enc_branch_link(cond: int, offset: int) -> int:
    return _enc_branch_common(cond, L=1, offset=offset)


def enc_bx(cond: int, Rm: int) -> int:
    return (
        (cond & 0xF) << 28
        | 0x012FFF10
        | (Rm & 0xF)
    )


# ---------------------------------------------------------------------------
# Block transfer (LDM/STM)
# ---------------------------------------------------------------------------

def _enc_block(cond, Rn, reglist, *, L, pre, up, S=0, writeback):
    return (
        (cond & 0xF) << 28
        | (0b100 << 25)
        | (1 << 24 if pre else 0)
        | (1 << 23 if up else 0)
        | (S & 1) << 22
        | (1 << 21 if writeback else 0)
        | (L & 1) << 20
        | (Rn & 0xF) << 16
        | (reglist & 0xFFFF)
    )


def enc_stm(cond, Rn, reglist, *, pre, up, writeback, S=0):
    return _enc_block(cond, Rn, reglist, L=0, pre=pre, up=up, S=S, writeback=writeback)


def enc_ldm(cond, Rn, reglist, *, pre, up, writeback, S=0):
    return _enc_block(cond, Rn, reglist, L=1, pre=pre, up=up, S=S, writeback=writeback)


# ---------------------------------------------------------------------------
# Software interrupt (BIOS calls)
# ---------------------------------------------------------------------------

def enc_swi(cond: int, imm24: int) -> int:
    return (
        (cond & 0xF) << 28
        | (0b1111 << 24)
        | (imm24 & 0xFFFFFF)
    )


# ---------------------------------------------------------------------------
# PSR access
# ---------------------------------------------------------------------------

def enc_mrs(cond: int, Rd: int, spsr: bool) -> int:
    R = 1 if spsr else 0
    return (
        (cond & 0xF) << 28
        | (0b00010 << 23)
        | (R << 22)
        | (0b001111 << 16)
        | (Rd & 0xF) << 12
    )


def enc_msr_imm(cond: int, spsr: bool, mask: int, imm: int) -> int:
    """MSR <psr>_<fields>, #imm. mask bits: c=1, x=2, s=4, f=8."""
    R = 1 if spsr else 0
    imm12 = encode_imm12(imm)
    return (
        (cond & 0xF) << 28
        | (0b00110 << 23)
        | (R << 22)
        | (0b10 << 20)
        | (mask & 0xF) << 16
        | (0b1111 << 12)
        | (imm12 & 0xFFF)
    )
