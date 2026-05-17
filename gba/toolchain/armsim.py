"""ARMv4T (ARM mode only) interpreter for the instruction subset our codegen emits.

Scope: every instruction in `toolchain/encode_arm.py` plus the BIOS SWIs the
physics code calls (0x06 Div, 0x0D Sqrt, 0x09 ArcTan2). The interpreter is a
TDD oracle for `src/physics.s` — it is not a full GBA emulator.

Conventions:
  - r0..r12 = general, r13 = SP, r14 = LR, r15 = PC.
  - Internally `regs[15]` holds the address of the *current* instruction; ARM
    pipeline-bias (PC reads as +8) is applied on a per-read basis.
  - Flags are 4 ints (N, Z, C, V) in {0, 1}.
  - Memory is a single bytearray, addressable from `base_addr` (default 0).

The call convention used by tests: set r0..r3 to args, set LR to a sentinel
address, jump to the function's entry, and run until PC hits the sentinel.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


_SENTINEL_LR = 0xDEADBEEE   # even so BX's LSB-mask leaves it unchanged
INT32_MIN = -0x80000000
INT32_MAX = 0x7FFFFFFF


def _u32(x: int) -> int:
    return x & 0xFFFFFFFF


def _s32(x: int) -> int:
    x &= 0xFFFFFFFF
    return x - 0x100000000 if x & 0x80000000 else x


def _ror32(value: int, amount: int) -> int:
    amount &= 31
    if amount == 0:
        return _u32(value)
    return _u32((value >> amount) | (value << (32 - amount)))


class ArmCpu:
    def __init__(self, *, memory_size: int = 1 << 18, base_addr: int = 0):
        self.regs = [0] * 16
        self.n = self.z = self.c = self.v = 0
        self.memory = bytearray(memory_size)
        self.base_addr = base_addr
        self.cycles = 0
        self.halted = False

    # -- memory helpers --------------------------------------------------

    def _mem_index(self, addr: int) -> int:
        idx = (addr - self.base_addr) & 0xFFFFFFFF
        if idx + 4 > len(self.memory):
            raise MemoryError(f"address 0x{addr:08X} outside simulated memory")
        return idx

    def read_u32(self, addr: int) -> int:
        i = self._mem_index(addr)
        return self.memory[i] | (self.memory[i + 1] << 8) \
            | (self.memory[i + 2] << 16) | (self.memory[i + 3] << 24)

    def write_u32(self, addr: int, value: int) -> None:
        i = self._mem_index(addr)
        value = _u32(value)
        self.memory[i]     = value & 0xFF
        self.memory[i + 1] = (value >> 8) & 0xFF
        self.memory[i + 2] = (value >> 16) & 0xFF
        self.memory[i + 3] = (value >> 24) & 0xFF

    def read_u16(self, addr: int) -> int:
        i = self._mem_index(addr) if False else (addr - self.base_addr) & 0xFFFFFFFF
        if i + 2 > len(self.memory):
            raise MemoryError(addr)
        return self.memory[i] | (self.memory[i + 1] << 8)

    def write_u16(self, addr: int, value: int) -> None:
        i = (addr - self.base_addr) & 0xFFFFFFFF
        if i + 2 > len(self.memory):
            raise MemoryError(addr)
        self.memory[i]     = value & 0xFF
        self.memory[i + 1] = (value >> 8) & 0xFF

    def read_u8(self, addr: int) -> int:
        i = (addr - self.base_addr) & 0xFFFFFFFF
        return self.memory[i]

    def write_u8(self, addr: int, value: int) -> None:
        i = (addr - self.base_addr) & 0xFFFFFFFF
        self.memory[i] = value & 0xFF

    def load_code(self, blob: bytes, at: int) -> None:
        i = (at - self.base_addr) & 0xFFFFFFFF
        if i + len(blob) > len(self.memory):
            raise MemoryError("blob does not fit")
        self.memory[i:i + len(blob)] = blob

    # -- register helpers -----------------------------------------------

    def set_reg(self, n: int, v: int) -> None:
        self.regs[n] = _u32(v)

    def get_reg_u32(self, n: int) -> int:
        return _u32(self.regs[n])

    def get_reg_s32(self, n: int) -> int:
        return _s32(self.regs[n])

    # -- run loop --------------------------------------------------------

    def call(self, entry: int, *, max_cycles: int = 200000) -> None:
        """Invoke an ARM function at `entry`. Returns when LR's sentinel is hit
        or `max_cycles` is exceeded (raises in that case)."""
        self.regs[14] = _SENTINEL_LR
        self.regs[15] = entry
        for _ in range(max_cycles):
            if self.regs[15] == _SENTINEL_LR or self.halted:
                return
            self.step()
        raise RuntimeError(f"armsim exceeded {max_cycles} cycles at PC=0x{self.regs[15]:08X}")

    def step(self) -> None:
        pc = self.regs[15]
        instr = self.read_u32(pc)
        self.regs[15] = _u32(pc + 4)
        self._exec(instr, pc_at_instr=pc)
        self.cycles += 1

    # -- condition codes ------------------------------------------------

    def _check_cond(self, cond: int) -> bool:
        n, z, c, v = self.n, self.z, self.c, self.v
        if cond == 0x0: return z == 1
        if cond == 0x1: return z == 0
        if cond == 0x2: return c == 1
        if cond == 0x3: return c == 0
        if cond == 0x4: return n == 1
        if cond == 0x5: return n == 0
        if cond == 0x6: return v == 1
        if cond == 0x7: return v == 0
        if cond == 0x8: return (c == 1) and (z == 0)
        if cond == 0x9: return (c == 0) or (z == 1)
        if cond == 0xA: return n == v
        if cond == 0xB: return n != v
        if cond == 0xC: return (z == 0) and (n == v)
        if cond == 0xD: return (z == 1) or (n != v)
        if cond == 0xE: return True
        return True  # 0xF reserved -> treat as always

    # -- dispatch -------------------------------------------------------

    def _exec(self, instr: int, *, pc_at_instr: int) -> None:
        cond = (instr >> 28) & 0xF
        if not self._check_cond(cond):
            return

        # 1) SWI: bits 27..24 == 1111
        if (instr & 0x0F000000) == 0x0F000000:
            self._do_swi(instr & 0xFFFFFF)
            return

        # 2) Branch / branch+link: bits 27..25 == 101
        if (instr & 0x0E000000) == 0x0A000000:
            self._do_branch(instr, pc_at_instr=pc_at_instr)
            return

        # 3) Block transfer LDM/STM: bits 27..25 == 100
        if (instr & 0x0E000000) == 0x08000000:
            self._do_block(instr)
            return

        # 4) Load/Store immediate or register (single data transfer):
        #    bits 27..26 == 01
        if (instr & 0x0C000000) == 0x04000000:
            self._do_sdt(instr)
            return

        # 5) BX: pattern 0x012FFF1X
        if (instr & 0x0FFFFFF0) == 0x012FFF10:
            self._do_bx(instr)
            return

        # 6) MRS: bits 27..23 == 00010, bits 21..20 == 00, bits 19..16 == 1111
        if (instr & 0x0FBF0FFF) == 0x010F0000:
            self._do_mrs(instr)
            return

        # 7) MSR immediate: bits 27..23 == 00110, bits 21..20 == 10
        if (instr & 0x0FB0F000) == 0x0320F000:
            self._do_msr_imm(instr)
            return

        # 8) MUL / MLA: bits 27..22 == 000000, bits 7..4 == 1001
        if (instr & 0x0FC000F0) == 0x00000090:
            self._do_mul_mla(instr)
            return

        # 9) SMULL / UMULL: bits 27..23 == 00001, bits 7..4 == 1001
        if (instr & 0x0F8000F0) == 0x00800090:
            self._do_long_mul(instr)
            return

        # 10) Halfword load/store immediate: bits 27..25 == 000, bit 22 = 1,
        #     bit 7 = 1, bit 4 = 1, bits 6..5 = 01.
        if (instr & 0x0E4000F0) == 0x004000B0:
            self._do_halfword(instr)
            return

        # 11) Otherwise: data processing (immediate or register)
        #     bits 27..26 == 00.
        if (instr & 0x0C000000) == 0x00000000:
            self._do_dp(instr)
            return

        raise NotImplementedError(
            f"unsupported instruction 0x{instr:08X} at PC=0x{pc_at_instr:08X}")

    # -- data processing -------------------------------------------------

    def _do_dp(self, instr: int) -> None:
        op = (instr >> 21) & 0xF
        S = (instr >> 20) & 1
        Rn = (instr >> 16) & 0xF
        Rd = (instr >> 12) & 0xF
        I = (instr >> 25) & 1

        if I:
            rot = ((instr >> 8) & 0xF) * 2
            imm8 = instr & 0xFF
            op2 = _ror32(imm8, rot)
            shifter_carry = self.c
            if rot != 0:
                shifter_carry = (op2 >> 31) & 1
        else:
            Rm = instr & 0xF
            shift_amount = (instr >> 7) & 0x1F
            shift_type = (instr >> 5) & 0x3
            value = self.get_reg_u32(Rm)
            op2, shifter_carry = self._apply_shift(value, shift_type, shift_amount, S)

        rn_val = self.get_reg_u32(Rn)
        result, carry, overflow = self._dp_alu(op, rn_val, op2, shifter_carry)

        # TST, TEQ, CMP, CMN always update flags and write nowhere
        is_test = op in (0x8, 0x9, 0xA, 0xB)
        if not is_test:
            self.regs[Rd] = _u32(result)

        if S or is_test:
            self.n = (result >> 31) & 1
            self.z = 1 if (_u32(result) == 0) else 0
            self.c = carry
            self.v = overflow

    @staticmethod
    def _apply_shift(value: int, shift_type: int, amount: int, S: int):
        value = _u32(value)
        if shift_type == 0:  # LSL
            if amount == 0:
                return value, 0   # carry-out unchanged path is via shifter_carry
            res = _u32(value << amount)
            carry = (value >> (32 - amount)) & 1 if amount <= 32 else 0
            return res, carry
        if shift_type == 1:  # LSR
            if amount == 0:
                # LSR #0 means LSR #32
                return 0, (value >> 31) & 1
            return _u32(value >> amount), (value >> (amount - 1)) & 1
        if shift_type == 2:  # ASR
            sign = (value >> 31) & 1
            if amount == 0:
                # ASR #0 means ASR #32: result is sign-extended
                return (0xFFFFFFFF if sign else 0), sign
            sv = _s32(value)
            return _u32(sv >> amount), (value >> (amount - 1)) & 1
        # ROR
        if amount == 0:
            # RRX (rotate right with extend by 1)
            res = (value >> 1) | (0 << 31)  # incoming carry handled elsewhere; we approximate
            return _u32(res), value & 1
        return _ror32(value, amount), (value >> ((amount - 1) & 31)) & 1

    def _dp_alu(self, op: int, a: int, b: int, shifter_carry: int):
        a_u, b_u = _u32(a), _u32(b)
        a_s, b_s = _s32(a_u), _s32(b_u)
        carry_in = self.c
        if op == 0x0:   # AND
            r = a_u & b_u; return _u32(r), shifter_carry, self.v
        if op == 0x1:   # EOR
            r = a_u ^ b_u; return _u32(r), shifter_carry, self.v
        if op == 0x2:   # SUB
            r = (a_u - b_u) & 0x1FFFFFFFF
            carry = 1 if a_u >= b_u else 0
            ov = self._ov_sub(a_s, b_s, _s32(_u32(r)))
            return _u32(r), carry, ov
        if op == 0x3:   # RSB
            r = (b_u - a_u) & 0x1FFFFFFFF
            carry = 1 if b_u >= a_u else 0
            ov = self._ov_sub(b_s, a_s, _s32(_u32(r)))
            return _u32(r), carry, ov
        if op == 0x4:   # ADD
            r = a_u + b_u
            carry = 1 if r > 0xFFFFFFFF else 0
            ov = self._ov_add(a_s, b_s, _s32(_u32(r)))
            return _u32(r), carry, ov
        if op == 0x5:   # ADC
            r = a_u + b_u + carry_in
            carry = 1 if r > 0xFFFFFFFF else 0
            ov = self._ov_add(a_s, b_s, _s32(_u32(r)))
            return _u32(r), carry, ov
        if op == 0x6:   # SBC
            r = a_u - b_u - (1 - carry_in)
            carry = 1 if r >= 0 else 0
            r &= 0x1FFFFFFFF
            ov = self._ov_sub(a_s, b_s, _s32(_u32(r)))
            return _u32(r), carry, ov
        if op == 0x7:   # RSC
            r = b_u - a_u - (1 - carry_in)
            carry = 1 if r >= 0 else 0
            r &= 0x1FFFFFFFF
            ov = self._ov_sub(b_s, a_s, _s32(_u32(r)))
            return _u32(r), carry, ov
        if op == 0x8:   # TST -> like AND, no write
            r = a_u & b_u; return _u32(r), shifter_carry, self.v
        if op == 0x9:   # TEQ -> like EOR
            r = a_u ^ b_u; return _u32(r), shifter_carry, self.v
        if op == 0xA:   # CMP -> like SUB
            r = (a_u - b_u) & 0x1FFFFFFFF
            carry = 1 if a_u >= b_u else 0
            ov = self._ov_sub(a_s, b_s, _s32(_u32(r)))
            return _u32(r), carry, ov
        if op == 0xB:   # CMN -> like ADD
            r = a_u + b_u
            carry = 1 if r > 0xFFFFFFFF else 0
            ov = self._ov_add(a_s, b_s, _s32(_u32(r)))
            return _u32(r), carry, ov
        if op == 0xC:   # ORR
            r = a_u | b_u; return _u32(r), shifter_carry, self.v
        if op == 0xD:   # MOV
            return _u32(b_u), shifter_carry, self.v
        if op == 0xE:   # BIC
            r = a_u & (~b_u & 0xFFFFFFFF); return _u32(r), shifter_carry, self.v
        if op == 0xF:   # MVN
            return _u32(~b_u & 0xFFFFFFFF), shifter_carry, self.v
        raise NotImplementedError(f"DP op {op}")

    @staticmethod
    def _ov_add(a_s, b_s, r_s):
        return 1 if ((a_s ^ r_s) & (b_s ^ r_s)) >> 31 else 0

    @staticmethod
    def _ov_sub(a_s, b_s, r_s):
        return 1 if ((a_s ^ b_s) & (a_s ^ r_s)) >> 31 else 0

    # -- multiplication --------------------------------------------------

    def _do_mul_mla(self, instr: int) -> None:
        A = (instr >> 21) & 1
        S = (instr >> 20) & 1
        Rd = (instr >> 16) & 0xF
        Rn = (instr >> 12) & 0xF
        Rs = (instr >> 8) & 0xF
        Rm = instr & 0xF
        prod = (self.get_reg_u32(Rm) * self.get_reg_u32(Rs)) & 0xFFFFFFFF
        if A:
            prod = (prod + self.get_reg_u32(Rn)) & 0xFFFFFFFF
        self.regs[Rd] = prod
        if S:
            self.n = (prod >> 31) & 1
            self.z = 1 if prod == 0 else 0

    def _do_long_mul(self, instr: int) -> None:
        U = (instr >> 22) & 1   # 1 = signed (SMULL), 0 = unsigned (UMULL)
        S = (instr >> 20) & 1
        RdHi = (instr >> 16) & 0xF
        RdLo = (instr >> 12) & 0xF
        Rs = (instr >> 8) & 0xF
        Rm = instr & 0xF
        if U:
            a = _s32(self.get_reg_u32(Rm))
            b = _s32(self.get_reg_u32(Rs))
            prod = a * b
        else:
            prod = self.get_reg_u32(Rm) * self.get_reg_u32(Rs)
        prod_u = prod & 0xFFFFFFFFFFFFFFFF
        self.regs[RdLo] = prod_u & 0xFFFFFFFF
        self.regs[RdHi] = (prod_u >> 32) & 0xFFFFFFFF
        if S:
            self.n = (prod_u >> 63) & 1
            self.z = 1 if prod_u == 0 else 0

    # -- single data transfer (LDR/STR/LDRB/STRB immediate, pre-indexed) --

    def _do_sdt(self, instr: int) -> None:
        # P=1 pre, W=0 no writeback (matches our encoders)
        U = (instr >> 23) & 1
        B = (instr >> 22) & 1
        L = (instr >> 20) & 1
        Rn = (instr >> 16) & 0xF
        Rd = (instr >> 12) & 0xF
        offset = instr & 0xFFF
        base = self.get_reg_u32(Rn)
        if Rn == 15:
            base = _u32(base + 4)   # PC reads as +8; we already advanced +4
        addr = _u32(base + offset) if U else _u32(base - offset)
        if L:
            if B:
                self.regs[Rd] = self.read_u8(addr)
            else:
                # ARM allows unaligned LDR with rotation -- our codegen always
                # uses word-aligned bases, so we don't emulate rotation.
                self.regs[Rd] = self.read_u32(addr)
        else:
            if B:
                self.write_u8(addr, self.get_reg_u32(Rd))
            else:
                self.write_u32(addr, self.get_reg_u32(Rd))

    def _do_halfword(self, instr: int) -> None:
        U = (instr >> 23) & 1
        L = (instr >> 20) & 1
        Rn = (instr >> 16) & 0xF
        Rd = (instr >> 12) & 0xF
        offH = (instr >> 8) & 0xF
        offL = instr & 0xF
        offset = (offH << 4) | offL
        base = self.get_reg_u32(Rn)
        addr = _u32(base + offset) if U else _u32(base - offset)
        if L:
            self.regs[Rd] = self.read_u16(addr)
        else:
            self.write_u16(addr, self.get_reg_u32(Rd))

    # -- branch / bx -----------------------------------------------------

    def _do_branch(self, instr: int, *, pc_at_instr: int) -> None:
        L = (instr >> 24) & 1
        imm24 = instr & 0xFFFFFF
        # Sign-extend imm24, shift left 2.
        if imm24 & 0x800000:
            imm24 |= ~0xFFFFFF
        offset = imm24 << 2
        target = _u32(pc_at_instr + 8 + offset)
        if L:
            self.regs[14] = _u32(pc_at_instr + 4)
        self.regs[15] = target

    def _do_bx(self, instr: int) -> None:
        Rm = instr & 0xF
        target = self.get_reg_u32(Rm)
        # We don't model Thumb interwork here; just mask the low bit.
        self.regs[15] = target & ~1

    # -- block transfer --------------------------------------------------

    def _do_block(self, instr: int) -> None:
        P = (instr >> 24) & 1
        U = (instr >> 23) & 1
        W = (instr >> 21) & 1
        L = (instr >> 20) & 1
        Rn = (instr >> 16) & 0xF
        reglist = instr & 0xFFFF
        base = self.get_reg_u32(Rn)

        regs = [i for i in range(16) if (reglist >> i) & 1]
        n = len(regs)
        if U:
            addresses = [_u32(base + (i + (1 if P else 0)) * 4) for i in range(n)]
            new_base = _u32(base + n * 4)
        else:
            # Decrement: lowest reg goes at lowest address.
            start = _u32(base - n * 4 + (0 if P else 4))
            addresses = [_u32(start + i * 4) for i in range(n)]
            new_base = _u32(base - n * 4)

        if L:
            for r, a in zip(regs, addresses):
                self.regs[r] = self.read_u32(a)
        else:
            for r, a in zip(regs, addresses):
                self.write_u32(a, self.get_reg_u32(r))

        if W:
            self.regs[Rn] = new_base

    # -- MRS / MSR ------------------------------------------------------

    def _do_mrs(self, instr: int) -> None:
        Rd = (instr >> 12) & 0xF
        cpsr = (self.n << 31) | (self.z << 30) | (self.c << 29) | (self.v << 28)
        # USR mode bits (low 5) hard-coded: 0x10.
        self.regs[Rd] = _u32(cpsr | 0x10)

    def _do_msr_imm(self, instr: int) -> None:
        mask = (instr >> 16) & 0xF
        rot = ((instr >> 8) & 0xF) * 2
        imm8 = instr & 0xFF
        value = _ror32(imm8, rot)
        # Only flag field (bit 3 of mask) writes NZCV in our usage.
        if mask & 0x8:
            self.n = (value >> 31) & 1
            self.z = (value >> 30) & 1
            self.c = (value >> 29) & 1
            self.v = (value >> 28) & 1

    # -- SWI (BIOS) ------------------------------------------------------

    def _do_swi(self, num24: int) -> None:
        # BIOS numbers are encoded as `num << 16` on real hardware.
        bios = (num24 >> 16) & 0xFF
        if bios == 0x06:
            self._bios_div()
        elif bios == 0x0D:
            self._bios_sqrt()
        elif bios == 0x09:
            self._bios_atan2()
        else:
            raise NotImplementedError(f"BIOS SWI 0x{bios:02X} not implemented")

    def _bios_div(self) -> None:
        # r0 = numerator (signed), r1 = denominator (signed).
        # Returns: r0 = quotient (trunc toward 0), r1 = remainder, r3 = abs(quotient).
        num = self.get_reg_s32(0)
        den = self.get_reg_s32(1)
        if den == 0:
            q = INT32_MAX if num >= 0 else INT32_MIN
            r = num
        else:
            # Truncate toward zero.
            q = abs(num) // abs(den)
            if (num < 0) ^ (den < 0):
                q = -q
            r = num - q * den
        self.regs[0] = _u32(q)
        self.regs[1] = _u32(r)
        self.regs[3] = _u32(abs(q))

    def _bios_sqrt(self) -> None:
        x = self.get_reg_u32(0)
        self.regs[0] = _u32(math.isqrt(x))

    def _bios_atan2(self) -> None:
        # BIOS SWI 0x09 ArcTan2: r0=x, r1=y, returns r0 = 16-bit binary angle.
        x = self.get_reg_s32(0)
        y = self.get_reg_s32(1)
        if x == 0 and y == 0:
            self.regs[0] = 0
            return
        rad = math.atan2(y, x)
        if rad < 0:
            rad += 2 * math.pi
        brad = int(round(rad * (0x10000 / (2 * math.pi)))) & 0xFFFF
        self.regs[0] = _u32(brad)
