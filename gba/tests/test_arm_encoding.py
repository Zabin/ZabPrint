"""Golden-byte tests for the ARM (32-bit) instruction encoders.

Each test pins one instruction to the exact 32-bit word it should produce,
with the bit breakdown derived from the ARM Architecture Reference Manual
(ARMv4T, the GBA's CPU). Format used in comments:

    Bits: [31:28]cond [27:25]type [24:21]op [20]S [19:16]Rn [15:12]Rd [11:0]op2

Tests assume a single 32-bit unsigned int return value. The assembler driver
later converts to 4-byte little-endian when writing to ROM; that's tested
separately.
"""
import pytest

from toolchain.encode_arm import (
    COND_EQ, COND_NE, COND_AL,
    OP_AND, OP_EOR, OP_SUB, OP_RSB, OP_ADD, OP_ADC, OP_SBC, OP_RSC,
    OP_TST, OP_TEQ, OP_CMP, OP_CMN, OP_ORR, OP_MOV, OP_BIC, OP_MVN,
    SHIFT_LSL, SHIFT_LSR, SHIFT_ASR, SHIFT_ROR,
    enc_dp_imm, enc_dp_reg, enc_dp_reg_shift_imm,
    enc_mul, enc_mla, enc_smull, enc_umull,
    enc_ldr_imm, enc_str_imm, enc_ldrb_imm, enc_strb_imm,
    enc_ldrh_imm, enc_strh_imm,
    enc_branch, enc_branch_link, enc_bx,
    enc_ldm, enc_stm,
    enc_swi, enc_mrs, enc_msr_imm,
    encode_imm12,
)


# ---------------------------------------------------------------------------
# Data processing - immediate
# ---------------------------------------------------------------------------

def test_mov_r0_imm0():
    # mov r0, #0
    # E 0 0  111 0 00 1 1101 0 0000 0000 000000000000
    # cond=AL(E), 00=dp, I=1, op=MOV(D), S=0, Rn=0, Rd=0, imm=000
    # = 0xE3A00000
    assert enc_dp_imm(OP_MOV, COND_AL, S=0, Rd=0, Rn=0, imm=0) == 0xE3A00000

def test_mov_r1_imm_ff():
    # mov r1, #0xFF -> 0xE3A010FF
    assert enc_dp_imm(OP_MOV, COND_AL, S=0, Rd=1, Rn=0, imm=0xFF) == 0xE3A010FF

def test_movs_r0_imm0_sets_flags():
    # movs r0, #0 -> 0xE3B00000 (S=1)
    assert enc_dp_imm(OP_MOV, COND_AL, S=1, Rd=0, Rn=0, imm=0) == 0xE3B00000

def test_add_r0_r1_imm1():
    # add r0, r1, #1 -> 0xE2810001
    # cond=E, 00, I=1, op=ADD(4), S=0, Rn=1, Rd=0, imm=1
    assert enc_dp_imm(OP_ADD, COND_AL, S=0, Rd=0, Rn=1, imm=1) == 0xE2810001

def test_sub_r2_r3_imm4():
    # sub r2, r3, #4 -> 0xE2432004
    assert enc_dp_imm(OP_SUB, COND_AL, S=0, Rd=2, Rn=3, imm=4) == 0xE2432004

def test_cmp_r0_imm0():
    # cmp r0, #0 -> 0xE3500000. CMP has S=1 implicit, Rd=0 by convention.
    assert enc_dp_imm(OP_CMP, COND_AL, S=1, Rd=0, Rn=0, imm=0) == 0xE3500000

def test_mvn_r0_imm0():
    # mvn r0, #0 -> 0xE3E00000 (r0 = ~0 = -1)
    assert enc_dp_imm(OP_MVN, COND_AL, S=0, Rd=0, Rn=0, imm=0) == 0xE3E00000

def test_orr_r0_r0_imm0x80000000_rotated():
    # orr r0, r0, #0x80000000 -- encoded as imm=0x02, rot=1 (rotate right by 2)
    # encode_imm12 must produce rot|imm = 0b 0001 0000 0010 = 0x102
    assert encode_imm12(0x80000000) == 0x102

def test_encode_imm12_zero():
    assert encode_imm12(0) == 0

def test_encode_imm12_simple():
    assert encode_imm12(0xFF) == 0xFF

def test_encode_imm12_rotated_high_byte():
    # 0xFF00 = 0xFF rotated right by 24 = ROR amount 24 -> imm8=0xFF, rot=12
    # encoded field: rot[11:8]=12, imm8[7:0]=0xFF -> 0xCFF
    assert encode_imm12(0xFF00) == 0xCFF

def test_encode_imm12_unrepresentable_raises():
    # 0x101 cannot be rotated to fit imm8
    with pytest.raises(ValueError):
        encode_imm12(0x101)


# ---------------------------------------------------------------------------
# Data processing - register
# ---------------------------------------------------------------------------

def test_mov_r0_r1():
    # mov r0, r1 -> 0xE1A00001
    assert enc_dp_reg(OP_MOV, COND_AL, S=0, Rd=0, Rn=0, Rm=1) == 0xE1A00001

def test_add_r0_r0_r1():
    # add r0, r0, r1 -> 0xE0800001
    assert enc_dp_reg(OP_ADD, COND_AL, S=0, Rd=0, Rn=0, Rm=1) == 0xE0800001

def test_mov_r0_r1_lsl_2():
    # mov r0, r1, lsl #2 -> 0xE1A00101
    assert enc_dp_reg_shift_imm(
        OP_MOV, COND_AL, S=0, Rd=0, Rn=0, Rm=1,
        shift=SHIFT_LSL, amount=2,
    ) == 0xE1A00101

def test_mov_r0_r1_lsr_16():
    # mov r0, r1, lsr #16 -> 0xE1A00821
    assert enc_dp_reg_shift_imm(
        OP_MOV, COND_AL, S=0, Rd=0, Rn=0, Rm=1,
        shift=SHIFT_LSR, amount=16,
    ) == 0xE1A00821

def test_mov_r0_r1_asr_31():
    # mov r0, r1, asr #31 -> 0xE1A00FC1
    assert enc_dp_reg_shift_imm(
        OP_MOV, COND_AL, S=0, Rd=0, Rn=0, Rm=1,
        shift=SHIFT_ASR, amount=31,
    ) == 0xE1A00FC1


# ---------------------------------------------------------------------------
# Multiplication
# ---------------------------------------------------------------------------

def test_mul_r0_r1_r2():
    # mul r0, r1, r2 -> 0xE0000291
    # cond=E, 0000000, S=0, Rd=0, _, Rs=2, 1001, Rm=1
    assert enc_mul(COND_AL, S=0, Rd=0, Rm=1, Rs=2) == 0xE0000291

def test_mla_r0_r1_r2_r3():
    # mla r0, r1, r2, r3 -> 0xE0203291 (accumulator r3, Rd=0)
    assert enc_mla(COND_AL, S=0, Rd=0, Rm=1, Rs=2, Rn=3) == 0xE0203291

def test_smull_r0_r1_r2_r3():
    # smull r0, r1, r2, r3  -> RdLo=0, RdHi=1, Rm=2, Rs=3
    # 0xE0C10392
    assert enc_smull(COND_AL, S=0, RdLo=0, RdHi=1, Rm=2, Rs=3) == 0xE0C10392

def test_umull_r0_r1_r2_r3():
    # umull r0, r1, r2, r3 -> 0xE0810392
    assert enc_umull(COND_AL, S=0, RdLo=0, RdHi=1, Rm=2, Rs=3) == 0xE0810392


# ---------------------------------------------------------------------------
# Single data transfer (LDR/STR with immediate offset)
# ---------------------------------------------------------------------------

def test_ldr_r0_r1_0():
    # ldr r0, [r1] -> 0xE5910000
    assert enc_ldr_imm(COND_AL, Rd=0, Rn=1, imm=0) == 0xE5910000

def test_ldr_r0_r1_4():
    # ldr r0, [r1, #4] -> 0xE5910004
    assert enc_ldr_imm(COND_AL, Rd=0, Rn=1, imm=4) == 0xE5910004

def test_ldr_r0_r1_neg4():
    # ldr r0, [r1, #-4] -> 0xE5110004
    assert enc_ldr_imm(COND_AL, Rd=0, Rn=1, imm=-4) == 0xE5110004

def test_str_r0_r1_8():
    # str r0, [r1, #8] -> 0xE5810008
    assert enc_str_imm(COND_AL, Rd=0, Rn=1, imm=8) == 0xE5810008

def test_ldrb_r0_r1_1():
    # ldrb r0, [r1, #1] -> 0xE5D10001
    assert enc_ldrb_imm(COND_AL, Rd=0, Rn=1, imm=1) == 0xE5D10001

def test_strb_r0_r1_1():
    # strb r0, [r1, #1] -> 0xE5C10001
    assert enc_strb_imm(COND_AL, Rd=0, Rn=1, imm=1) == 0xE5C10001


# ---------------------------------------------------------------------------
# Halfword load/store (LDRH/STRH)
# ---------------------------------------------------------------------------

def test_ldrh_r0_r1_0():
    # ldrh r0, [r1] -> 0xE1D100B0
    assert enc_ldrh_imm(COND_AL, Rd=0, Rn=1, imm=0) == 0xE1D100B0

def test_strh_r0_r1_2():
    # strh r0, [r1, #2] -> 0xE1C100B2
    assert enc_strh_imm(COND_AL, Rd=0, Rn=1, imm=2) == 0xE1C100B2


# ---------------------------------------------------------------------------
# Branches
# ---------------------------------------------------------------------------

def test_b_forward_2_instructions():
    # b .+8 (skip next instruction; PC bias is 8 so target = current+8 means
    # branch offset of 0, which the encoder also requires to be /4)
    # b target where (target - (current_pc + 8)) = 0 -> imm24=0
    assert enc_branch(COND_AL, offset=0) == 0xEA000000

def test_b_backward_to_self_minus_4():
    # b . -- branch to self.
    # target = current_pc, so (target - (current_pc + 8)) = -8, imm24 = -2.
    # imm24 two's complement of -2 = 0xFFFFFE.
    assert enc_branch(COND_AL, offset=-8) == 0xEAFFFFFE

def test_bl_offset_zero():
    # bl .+8 -> 0xEB000000
    assert enc_branch_link(COND_AL, offset=0) == 0xEB000000

def test_bne_offset_zero():
    # bne .+8 -> 0x1A000000
    assert enc_branch(COND_NE, offset=0) == 0x1A000000

def test_bx_lr():
    # bx lr -> 0xE12FFF1E
    assert enc_bx(COND_AL, Rm=14) == 0xE12FFF1E


# ---------------------------------------------------------------------------
# Block transfer (LDM/STM)
# ---------------------------------------------------------------------------

def test_push_lr_via_stm():
    # stmfd sp!, {lr} -> 0xE92D4000 (Pre-dec, Writeback)
    # Equivalent to "push {lr}" pseudo
    assert enc_stm(COND_AL, Rn=13, reglist=(1 << 14), pre=True, up=False, writeback=True) == 0xE92D4000

def test_pop_pc_via_ldm():
    # ldmfd sp!, {pc} -> 0xE8BD8000 (Post-inc, Writeback)
    assert enc_ldm(COND_AL, Rn=13, reglist=(1 << 15), pre=False, up=True, writeback=True) == 0xE8BD8000


# ---------------------------------------------------------------------------
# SWI (BIOS calls)
# ---------------------------------------------------------------------------

def test_swi_05_vblank_wait():
    # swi #5 -> 0xEF050000  (NB: GBA SWIs encode the number in the upper byte
    # of imm24, multiplied by 0x10000)
    assert enc_swi(COND_AL, imm24=0x050000) == 0xEF050000

def test_swi_0d_sqrt():
    assert enc_swi(COND_AL, imm24=0x0D0000) == 0xEF0D0000


# ---------------------------------------------------------------------------
# Status register access (MRS / MSR)
# ---------------------------------------------------------------------------

def test_mrs_r0_cpsr():
    # mrs r0, cpsr -> 0xE10F0000
    assert enc_mrs(COND_AL, Rd=0, spsr=False) == 0xE10F0000

def test_msr_cpsr_imm():
    # msr cpsr_c, #0x1F  -- switch to System mode
    # = 0xE321F01F (mask=0x1 for control byte only)
    assert enc_msr_imm(COND_AL, spsr=False, mask=0x1, imm=0x1F) == 0xE321F01F
