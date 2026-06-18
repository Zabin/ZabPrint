"""Tests for the ARMv4T interpreter `toolchain/armsim.py`.

Strategy: assemble small ARM functions via `toolchain.asm.assemble`, load them
into the simulator, set up r0..r3 as inputs, run until PC returns to a
sentinel LR, then read r0 back. This validates the full chain
(encoder -> assembler -> interpreter) for every instruction the codegen emits.
"""
from __future__ import annotations

import pytest

from toolchain.armsim import ArmCpu, _SENTINEL_LR
from toolchain.asm import assemble


def _run(src: str, *args: int, base: int = 0x100, max_cycles: int = 50000) -> ArmCpu:
    blob = assemble(src, base_addr=base).bytes_
    cpu = ArmCpu()
    cpu.load_code(blob, at=base)
    for i, v in enumerate(args):
        cpu.set_reg(i, v & 0xFFFFFFFF)
    cpu.call(base, max_cycles=max_cycles)
    return cpu


def _r0_s(src: str, *args: int) -> int:
    return _run(src, *args).get_reg_s32(0)


def _r0_u(src: str, *args: int) -> int:
    return _run(src, *args).get_reg_u32(0)


# --- mov / data-processing immediate ------------------------------------

def test_mov_immediate_then_return():
    assert _r0_s(".arm\nmov r0, #5\nbx lr\n") == 5


def test_mov_immediate_rotated_value():
    # 0xFF000000 = imm 0xFF rotated right by 8 bits.
    assert _r0_u(".arm\nmov r0, #0xFF000000\nbx lr\n") == 0xFF000000


def test_mvn_immediate():
    # MVN r0, #0  ->  r0 = ~0 = 0xFFFFFFFF (-1 signed)
    assert _r0_s(".arm\nmvn r0, #0\nbx lr\n") == -1


# --- arithmetic ---------------------------------------------------------

def test_add_register():
    assert _r0_s(".arm\nadd r0, r0, r1\nbx lr\n", 7, 35) == 42


def test_sub_register_negative_result():
    assert _r0_s(".arm\nsub r0, r0, r1\nbx lr\n", 3, 10) == -7


def test_rsb_register():
    assert _r0_s(".arm\nrsb r0, r0, r1\nbx lr\n", 3, 10) == 7   # r0 = r1 - r0


def test_and_or_eor():
    assert _r0_u(".arm\nand r0, r0, r1\nbx lr\n", 0xF0F0, 0xFF00) == 0xF000
    assert _r0_u(".arm\norr r0, r0, r1\nbx lr\n", 0x0F00, 0x00F0) == 0x0FF0
    assert _r0_u(".arm\neor r0, r0, r1\nbx lr\n", 0xFF00, 0xF0F0) == 0x0FF0


# --- shifts in the barrel shifter ----------------------------------------

def test_lsl_in_dp_reg():
    # r0 = r1 << 4
    assert _r0_u(".arm\nmov r0, r1, lsl #4\nbx lr\n", 0, 0x12) == 0x120


def test_lsr_high_bits():
    assert _r0_u(".arm\nmov r0, r1, lsr #16\nbx lr\n", 0, 0xABCD1234) == 0xABCD


def test_asr_preserves_sign():
    # 0xFFFF0000 (-65536 signed) asr 16 -> 0xFFFFFFFF (-1)
    out = _r0_s(".arm\nmov r0, r1, asr #16\nbx lr\n", 0, 0xFFFF0000)
    assert out == -1


def test_smull_low_then_high_combo():
    # Classic Q16.16 multiply: smull lo,hi,a,b ; mov r0,lo,lsr#16 ; orr r0,r0,hi,lsl#16
    src = """
    .arm
    smull r2, r3, r0, r1
    mov r0, r2, lsr #16
    orr r0, r0, r3, lsl #16
    bx lr
    """
    # 0.5 * 0.5 in Q16.16 = 0x8000 * 0x8000 = 0x40000000 -> result Q16 = 0x4000
    assert _r0_u(src, 0x00008000, 0x00008000) == 0x00004000
    # 1.0 * 1.0 = 0x10000 in Q16
    assert _r0_u(src, 0x00010000, 0x00010000) == 0x00010000
    # negative * positive
    # -0.5 * 0.5 = -0.25 in Q16 = -0x4000 -> 0xFFFFC000 unsigned
    assert _r0_u(src, 0xFFFF8000, 0x00008000) == 0xFFFFC000


def test_mul_low_only():
    assert _r0_s(".arm\nmul r0, r0, r1\nbx lr\n", 7, 6) == 42


def test_mla():
    # r0 = r1 * r2 + r3
    assert _r0_s(".arm\nmla r0, r1, r2, r3\nbx lr\n", 0, 4, 5, 7) == 27


# --- conditionals ------------------------------------------------------

def test_conditional_movne():
    # cmp r0, #0 ; movne r0, #99
    assert _r0_s(".arm\ncmp r0, #0\nmovne r0, #99\nbx lr\n", 5) == 99
    assert _r0_s(".arm\ncmp r0, #0\nmovne r0, #99\nbx lr\n", 0) == 0


def test_conditional_branch_taken_for_negative():
    src = """
    .arm
    cmp r0, #0
    bmi negative
    mov r0, #1
    bx lr
negative:
    mvn r0, #0
    bx lr
    """
    assert _r0_s(src, 5) == 1
    assert _r0_s(src, -3) == -1


def test_loop_counts_down():
    # Sum from r0 down to 1.
    src = """
    .arm
    mov r1, #0
loop:
    add r1, r1, r0
    subs r0, r0, #1
    bne loop
    mov r0, r1
    bx lr
    """
    assert _r0_s(src, 5) == 15
    assert _r0_s(src, 10) == 55


# --- load / store ------------------------------------------------------

def test_str_then_ldr_word():
    src = """
    .arm
    str r0, [r1]
    ldr r0, [r1]
    bx lr
    """
    # write 0xCAFEBABE to address 0x200, read it back.
    cpu_in_value = 0xCAFEBABE
    cpu = _run(src, cpu_in_value, 0x200)
    assert cpu.get_reg_u32(0) == cpu_in_value


def test_ldr_byte_and_halfword():
    blob = bytes([0x12, 0x34, 0x56, 0x78])
    cpu = ArmCpu()
    cpu.load_code(blob, at=0x300)
    src = """
    .arm
    ldrb r2, [r0]
    ldrh r3, [r0, #2]
    add r0, r2, r3
    bx lr
    """
    code = assemble(src, base_addr=0x400).bytes_
    cpu.load_code(code, at=0x400)
    cpu.set_reg(0, 0x300)
    cpu.call(0x400)
    # r2 = byte at 0x300 = 0x12; r3 = halfword at 0x302 = 0x7856
    assert cpu.get_reg_u32(0) == 0x12 + 0x7856


# --- push / pop ---------------------------------------------------------

def test_push_pop_round_trip():
    src = """
    .arm
    push {r4, r5, lr}
    mov r4, #10
    mov r5, #20
    pop {r4, r5, lr}
    add r0, r4, r5
    bx lr
    """
    cpu = ArmCpu()
    blob = assemble(src, base_addr=0x100).bytes_
    cpu.load_code(blob, at=0x100)
    cpu.set_reg(4, 333)
    cpu.set_reg(5, 444)
    cpu.set_reg(13, 0x10000)   # SP somewhere safe
    cpu.call(0x100)
    assert cpu.get_reg_s32(0) == 333 + 444


# --- BIOS SWIs ----------------------------------------------------------

def test_swi_div():
    src = """
    .arm
    swi 0x060000
    bx lr
    """
    # 100 / 7  -> q=14, r=2; r0=14, r1=2, r3=14
    cpu = _run(src, 100, 7)
    assert cpu.get_reg_s32(0) == 14
    assert cpu.get_reg_s32(1) == 2
    assert cpu.get_reg_s32(3) == 14


def test_swi_div_negative_truncates_toward_zero():
    src = ".arm\nswi 0x060000\nbx lr\n"
    cpu = _run(src, -7, 2)
    # ARM/C semantics: -7 / 2 = -3, remainder -1.
    assert cpu.get_reg_s32(0) == -3
    assert cpu.get_reg_s32(1) == -1


def test_swi_sqrt():
    src = ".arm\nswi 0x0D0000\nbx lr\n"
    assert _run(src, 144).get_reg_u32(0) == 12
    assert _run(src, 1024).get_reg_u32(0) == 32
    assert _run(src, 0).get_reg_u32(0) == 0


def test_swi_atan2_cardinal_directions():
    # BIOS convention: r0=x, r1=y.
    src = ".arm\nswi 0x090000\nbx lr\n"
    # (x=1, y=0)  ->  0 brad
    assert _run(src, 1, 0).get_reg_u32(0) == 0
    # (x=0, y=1)  -> pi/2 = 0x4000 brad
    assert _run(src, 0, 1).get_reg_u32(0) == 0x4000
    # (x=-1, y=0) -> pi  = 0x8000 brad
    assert _run(src, -1, 0).get_reg_u32(0) == 0x8000
    # (x=0, y=-1) -> 3pi/2 = 0xC000 brad
    assert _run(src, 0, -1).get_reg_u32(0) == 0xC000


# --- sanity guards -----------------------------------------------------

def test_runaway_loop_raises():
    src = ".arm\nloop:\nb loop\n"
    blob = assemble(src, base_addr=0x100).bytes_
    cpu = ArmCpu()
    cpu.load_code(blob, at=0x100)
    with pytest.raises(RuntimeError, match="exceeded"):
        cpu.call(0x100, max_cycles=100)
