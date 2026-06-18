"""Golden-byte tests for the Thumb (16-bit) instruction encoders.

Thumb has 19 fixed formats in ARMv4T (ARM ARM A6). One test per format we
actually use in the game. Encoders return a 16-bit unsigned int.
"""
import pytest

from toolchain.encode_thumb import (
    TCOND_EQ, TCOND_NE, TCOND_AL_T,  # T's "always" is unused; B uses no cond
    enc_t_shift_imm,           # fmt 1: LSL/LSR/ASR imm
    enc_t_addsub_reg, enc_t_addsub_imm3,  # fmt 2
    enc_t_movcmpaddsub_imm8,   # fmt 3
    enc_t_alu,                  # fmt 4
    enc_t_hireg_op, enc_t_bx,  # fmt 5
    enc_t_ldr_pc_rel,          # fmt 6
    enc_t_ldst_reg,            # fmt 7
    enc_t_ldst_imm5,           # fmt 9
    enc_t_ldsth_imm5,          # fmt 10
    enc_t_ldst_sp,             # fmt 11
    enc_t_add_pc_sp,           # fmt 12
    enc_t_add_sp,              # fmt 13
    enc_t_push, enc_t_pop,     # fmt 14
    enc_t_ldmia, enc_t_stmia,  # fmt 15
    enc_t_b_cond,              # fmt 16
    enc_t_swi,                 # fmt 17
    enc_t_b,                   # fmt 18
    enc_t_bl_pair,             # fmt 19
    TALU_AND, TALU_EOR, TALU_LSL, TALU_LSR, TALU_ASR, TALU_ADC, TALU_SBC,
    TALU_ROR, TALU_TST, TALU_NEG, TALU_CMP, TALU_CMN, TALU_ORR, TALU_MUL,
    TALU_BIC, TALU_MVN,
    THI_ADD, THI_CMP, THI_MOV,
    TSHIFT_LSL, TSHIFT_LSR, TSHIFT_ASR,
)


# ---------------------------------------------------------------------------
# Format 1: move shifted register (LSL/LSR/ASR by imm5)
# ---------------------------------------------------------------------------

def test_lsl_r0_r1_imm0():
    # lsl r0, r1, #0 -> 0x0008
    assert enc_t_shift_imm(TSHIFT_LSL, imm5=0, Rs=1, Rd=0) == 0x0008

def test_lsl_r2_r3_imm4():
    # lsl r2, r3, #4 -> 0x011A
    # fmt: 000 op[2] imm5 Rs Rd
    # op=00, imm5=4, Rs=3, Rd=2
    # = 0000 0001 0001 1010 = 0x011A
    assert enc_t_shift_imm(TSHIFT_LSL, imm5=4, Rs=3, Rd=2) == 0x011A

def test_asr_r0_r0_imm31():
    # asr r0, r0, #31 -> 0x17C0
    assert enc_t_shift_imm(TSHIFT_ASR, imm5=31, Rs=0, Rd=0) == 0x17C0


# ---------------------------------------------------------------------------
# Format 2: add/sub register and imm3
# ---------------------------------------------------------------------------

def test_add_r0_r1_r2_register():
    # add r0, r1, r2 -> 0x1888
    assert enc_t_addsub_reg(is_sub=False, Rm=2, Rs=1, Rd=0) == 0x1888

def test_sub_r0_r1_r2_register():
    # sub r0, r1, r2 -> 0x1A88
    assert enc_t_addsub_reg(is_sub=True, Rm=2, Rs=1, Rd=0) == 0x1A88

def test_add_r0_r1_imm3_3():
    # add r0, r1, #3 -> 0x1CC8
    assert enc_t_addsub_imm3(is_sub=False, imm3=3, Rs=1, Rd=0) == 0x1CC8

def test_sub_r0_r1_imm3_1():
    # sub r0, r1, #1 -> 0x1E48
    assert enc_t_addsub_imm3(is_sub=True, imm3=1, Rs=1, Rd=0) == 0x1E48


# ---------------------------------------------------------------------------
# Format 3: mov/cmp/add/sub imm8 on low reg
# ---------------------------------------------------------------------------

def test_mov_r0_imm0():
    # mov r0, #0 -> 0x2000
    assert enc_t_movcmpaddsub_imm8(op=0, Rd=0, imm8=0) == 0x2000

def test_mov_r1_imm_ff():
    # mov r1, #0xFF -> 0x21FF
    assert enc_t_movcmpaddsub_imm8(op=0, Rd=1, imm8=0xFF) == 0x21FF

def test_cmp_r0_imm0():
    # cmp r0, #0 -> 0x2800
    assert enc_t_movcmpaddsub_imm8(op=1, Rd=0, imm8=0) == 0x2800

def test_add_r0_imm8_1():
    # add r0, #1 -> 0x3001
    assert enc_t_movcmpaddsub_imm8(op=2, Rd=0, imm8=1) == 0x3001

def test_sub_r0_imm8_1():
    # sub r0, #1 -> 0x3801
    assert enc_t_movcmpaddsub_imm8(op=3, Rd=0, imm8=1) == 0x3801


# ---------------------------------------------------------------------------
# Format 4: ALU operations
# ---------------------------------------------------------------------------

def test_and_r0_r1():
    # and r0, r1 -> 0x4008
    assert enc_t_alu(TALU_AND, Rs=1, Rd=0) == 0x4008

def test_orr_r0_r1():
    # orr r0, r1 -> 0x4308
    assert enc_t_alu(TALU_ORR, Rs=1, Rd=0) == 0x4308

def test_mul_r0_r1():
    # mul r0, r1 -> 0x4348
    assert enc_t_alu(TALU_MUL, Rs=1, Rd=0) == 0x4348

def test_neg_r0_r1():
    # neg r0, r1 -> 0x4248
    assert enc_t_alu(TALU_NEG, Rs=1, Rd=0) == 0x4248


# ---------------------------------------------------------------------------
# Format 5: Hi register operations / BX
# ---------------------------------------------------------------------------

def test_mov_r8_r0_hireg():
    # mov r8, r0  (low->high) -> 0x4680
    # H1=1 (Rd is high), H2=0 (Rs is low), op=MOV(10), Rd=0(low part), Rs=0
    assert enc_t_hireg_op(THI_MOV, H1=1, H2=0, Rd=0, Rs=0) == 0x4680

def test_mov_r0_r8_hireg():
    # mov r0, r8 -> 0x4640
    assert enc_t_hireg_op(THI_MOV, H1=0, H2=1, Rd=0, Rs=0) == 0x4640

def test_add_sp_imm_via_hi_register_not_used():
    # Just make sure ADD between hi/low works: add r0, r8 -> 0x4440
    assert enc_t_hireg_op(THI_ADD, H1=0, H2=1, Rd=0, Rs=0) == 0x4440

def test_bx_lr():
    # bx lr -> 0x4770 (H2=1 since lr is "high" in fmt5 encoding for BX)
    # bx Rm where Rm=14: H2=1, Rs=6 -> bits 7:6=10, 5:3=110, ... let me just verify by hand.
    # Format: 0100 0111 H2 Rs[2:0] 000
    # bx lr: Rm=14, so H2=1, Rs=14&7=6. = 0100 0111 0111 0000 = 0x4770
    assert enc_t_bx(Rm=14) == 0x4770

def test_bx_r0():
    # bx r0 -> 0x4700
    assert enc_t_bx(Rm=0) == 0x4700


# ---------------------------------------------------------------------------
# Format 6: PC-relative load
# ---------------------------------------------------------------------------

def test_ldr_r0_pc_imm0():
    # ldr r0, [pc, #0] -> 0x4800
    assert enc_t_ldr_pc_rel(Rd=0, imm8_words=0) == 0x4800

def test_ldr_r1_pc_imm8():
    # ldr r1, [pc, #8] -> imm8_words=2
    # 0x4902
    assert enc_t_ldr_pc_rel(Rd=1, imm8_words=2) == 0x4902


# ---------------------------------------------------------------------------
# Format 7/8: load/store with register offset
# ---------------------------------------------------------------------------

def test_str_r0_r1_r2():
    # str r0, [r1, r2] -> 0x5088
    # fmt: 0101 L 0 B 0 Rm[3] Rb[3] Rd[3]
    # L=0(store), B=0(word). op=0. Rm=2, Rb=1, Rd=0
    # = 0101 0000 1000 1000 = 0x5088
    assert enc_t_ldst_reg(L=0, B=0, Rm=2, Rb=1, Rd=0) == 0x5088

def test_ldr_r0_r1_r2():
    # ldr r0, [r1, r2] -> 0x5888
    assert enc_t_ldst_reg(L=1, B=0, Rm=2, Rb=1, Rd=0) == 0x5888


# ---------------------------------------------------------------------------
# Format 9: load/store with imm5 offset (scaled)
# ---------------------------------------------------------------------------

def test_str_r0_r1_imm0_word():
    # str r0, [r1, #0] -> 0x6008
    assert enc_t_ldst_imm5(L=0, B=0, imm5_scaled=0, Rb=1, Rd=0) == 0x6008

def test_str_r0_r1_imm4_word():
    # str r0, [r1, #4] -> 0x6048
    # imm5 = 4/4 = 1
    assert enc_t_ldst_imm5(L=0, B=0, imm5_scaled=1, Rb=1, Rd=0) == 0x6048

def test_ldr_r0_r1_imm0_word():
    # ldr r0, [r1] -> 0x6808
    assert enc_t_ldst_imm5(L=1, B=0, imm5_scaled=0, Rb=1, Rd=0) == 0x6808


# ---------------------------------------------------------------------------
# Format 10: load/store halfword
# ---------------------------------------------------------------------------

def test_strh_r0_r1_imm0():
    # strh r0, [r1] -> 0x8008
    assert enc_t_ldsth_imm5(L=0, imm5_scaled=0, Rb=1, Rd=0) == 0x8008

def test_ldrh_r0_r1_imm2():
    # ldrh r0, [r1, #2] -> 0x8848
    # imm5 scaled by 2: imm5 = 1
    assert enc_t_ldsth_imm5(L=1, imm5_scaled=1, Rb=1, Rd=0) == 0x8848


# ---------------------------------------------------------------------------
# Format 11: SP-relative load/store
# ---------------------------------------------------------------------------

def test_str_r0_sp_0():
    # str r0, [sp, #0] -> 0x9000
    assert enc_t_ldst_sp(L=0, Rd=0, imm8_words=0) == 0x9000

def test_ldr_r1_sp_4():
    # ldr r1, [sp, #4] -> imm8_words=1
    # = 0x9901
    assert enc_t_ldst_sp(L=1, Rd=1, imm8_words=1) == 0x9901


# ---------------------------------------------------------------------------
# Format 12: get relative address (ADD Rd, PC/SP, #imm8*4)
# ---------------------------------------------------------------------------

def test_add_r0_pc_4():
    # add r0, pc, #4 -> 0xA001
    assert enc_t_add_pc_sp(SP=False, Rd=0, imm8_words=1) == 0xA001

def test_add_r0_sp_0():
    # add r0, sp, #0 -> 0xA800
    assert enc_t_add_pc_sp(SP=True, Rd=0, imm8_words=0) == 0xA800


# ---------------------------------------------------------------------------
# Format 13: ADD/SUB SP by imm7*4
# ---------------------------------------------------------------------------

def test_add_sp_imm():
    # add sp, #16 -> 0xB004
    assert enc_t_add_sp(is_sub=False, imm7_words=4) == 0xB004

def test_sub_sp_imm():
    # sub sp, #16 -> 0xB084
    assert enc_t_add_sp(is_sub=True, imm7_words=4) == 0xB084


# ---------------------------------------------------------------------------
# Format 14: PUSH / POP
# ---------------------------------------------------------------------------

def test_push_r0():
    # push {r0} -> 0xB401
    assert enc_t_push(reglist=0x01, R_bit=False) == 0xB401

def test_push_r0_lr():
    # push {r0, lr} -> 0xB501
    assert enc_t_push(reglist=0x01, R_bit=True) == 0xB501

def test_pop_pc():
    # pop {pc} -> 0xBD00 (no Rs, R=1 means pc)
    assert enc_t_pop(reglist=0x00, R_bit=True) == 0xBD00


# ---------------------------------------------------------------------------
# Format 15: multiple load/store
# ---------------------------------------------------------------------------

def test_stmia_r0_r1_r2():
    # stmia r0!, {r1, r2} -> 0xC006
    assert enc_t_stmia(Rb=0, reglist=0x06) == 0xC006

def test_ldmia_r0_r1_r2():
    # ldmia r0!, {r1, r2} -> 0xC806
    assert enc_t_ldmia(Rb=0, reglist=0x06) == 0xC806


# ---------------------------------------------------------------------------
# Format 16: conditional branch
# ---------------------------------------------------------------------------

def test_beq_offset_0():
    # beq . + 4   (PC bias +4: target = current + 4 means offset 0)
    # cond=EQ
    assert enc_t_b_cond(TCOND_EQ, offset=0) == 0xD0FE - 0xD0FE + 0xD000  # 0xD000

def test_beq_offset_0_clean():
    assert enc_t_b_cond(TCOND_EQ, offset=0) == 0xD000

def test_bne_offset_minus_4():
    # bne .    (loop back to current addr: offset = -4 means target = pc+4-4 = pc)
    # imm8 = -2, low 8 = 0xFE
    # = 0xD1FE
    assert enc_t_b_cond(TCOND_NE, offset=-4) == 0xD1FE


# ---------------------------------------------------------------------------
# Format 17: SWI
# ---------------------------------------------------------------------------

def test_swi_imm():
    # swi #5 -> 0xDF05
    assert enc_t_swi(imm8=5) == 0xDF05


# ---------------------------------------------------------------------------
# Format 18: unconditional branch
# ---------------------------------------------------------------------------

def test_b_offset_0():
    # b .+4 (offset=0) -> 0xE000
    assert enc_t_b(offset=0) == 0xE000

def test_b_offset_minus_4():
    # b . (offset=-4) -> imm11 = -2 -> low 11 bits = 0x7FE -> 0xE7FE
    assert enc_t_b(offset=-4) == 0xE7FE


# ---------------------------------------------------------------------------
# Format 19: long branch with link (encodes as 2 halfwords)
# ---------------------------------------------------------------------------

def test_bl_offset_0():
    # bl .+4 means PC offset 0 (PC bias +4); produces (0xF000, 0xF800).
    hi, lo = enc_t_bl_pair(offset=0)
    assert (hi, lo) == (0xF000, 0xF800)

def test_bl_offset_4():
    # bl . + 8 -> offset=4 -> imm22 = 4>>1 = 2.  upper 11 bits = 0, lower 11 bits = 2
    # hi: 0xF000, lo: 0xF802
    hi, lo = enc_t_bl_pair(offset=4)
    assert (hi, lo) == (0xF000, 0xF802)
