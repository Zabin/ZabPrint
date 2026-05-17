"""Two-pass ARM/Thumb assembler driver.

Accepts a string of source and returns an AssemblyResult: the flat byte
output (little-endian) plus a symbol table.

Pass 1 walks the source line by line and builds a list of `Item`s. Each Item
records its byte offset, byte size, and a callback that produces its final
bytes once symbols are resolved.

Pass 2 calls each Item's emit() with a symbol-resolving expression evaluator
and concatenates the result.

Supported directives:
    .arm, .thumb        instruction-set mode (implicit align to 4 or 2)
    .equ NAME, expr     compile-time constant
    .word/.hword/.byte  data emission
    .incbin "path"      raw byte inclusion
    .align N            pad to N-byte boundary (N must be power of two)
    .ltorg              flush pending `ldr Rd, =expr` literal pool

Comments may start with `;`, `@`, or `//`.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from toolchain import encode_arm as ea
from toolchain import encode_thumb as et


# ===========================================================================
# Public API
# ===========================================================================

@dataclass
class AssemblyResult:
    bytes_: bytes
    symbols: dict[str, int]


def assemble(source: str, *, base_addr: int = 0x08000000) -> AssemblyResult:
    asm = Assembler(base_addr=base_addr)
    asm.feed(source)
    return asm.finalize()


# ===========================================================================
# Tokenization
# ===========================================================================

def _strip_comment(line: str) -> str:
    out = []
    i = 0
    while i < len(line):
        c = line[i]
        if c in ';@':
            break
        if c == '/' and i + 1 < len(line) and line[i + 1] == '/':
            break
        out.append(c)
        i += 1
    return ''.join(out)


def _split_top_level_commas(s: str) -> list[str]:
    """Split on commas not inside brackets or braces."""
    parts, buf, depth = [], [], 0
    for c in s:
        if c in '[{(':
            depth += 1
            buf.append(c)
        elif c in ']})':
            depth -= 1
            buf.append(c)
        elif c == ',' and depth == 0:
            parts.append(''.join(buf).strip())
            buf = []
        else:
            buf.append(c)
    if buf:
        parts.append(''.join(buf).strip())
    return parts


# ===========================================================================
# Expression evaluator (used in pass 2 once symbols are known)
# ===========================================================================

class ExprError(Exception):
    pass


class ExprEvaluator:
    """Tiny recursive-descent for + - * ( ) with identifiers and numbers."""

    def __init__(self, symbols: dict[str, int]):
        self.symbols = symbols

    def eval(self, text: str) -> int:
        self.tokens = self._tokenize(text)
        self.pos = 0
        v = self._add()
        if self.pos != len(self.tokens):
            raise ExprError(f"trailing tokens in expression: {text!r}")
        return v

    def _tokenize(self, text: str) -> list[str]:
        out = []
        i = 0
        while i < len(text):
            c = text[i]
            if c.isspace():
                i += 1
            elif c in '+-*()':
                out.append(c)
                i += 1
            elif c.isdigit() or (c == '0' and i + 1 < len(text) and text[i + 1] in 'xXbB'):
                j = i
                # hex / bin / dec
                if c == '0' and i + 1 < len(text) and text[i + 1] in 'xX':
                    j += 2
                    while j < len(text) and text[j] in '0123456789abcdefABCDEF_':
                        j += 1
                elif c == '0' and i + 1 < len(text) and text[i + 1] in 'bB':
                    j += 2
                    while j < len(text) and text[j] in '01_':
                        j += 1
                else:
                    while j < len(text) and (text[j].isdigit() or text[j] == '_'):
                        j += 1
                out.append(text[i:j])
                i = j
            elif c.isalpha() or c == '_' or c == '.':
                j = i + 1
                while j < len(text) and (text[j].isalnum() or text[j] in '_.'):
                    j += 1
                out.append(text[i:j])
                i = j
            else:
                raise ExprError(f"unexpected character {c!r} in expression")
        return out

    def _peek(self) -> str | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def _eat(self) -> str:
        t = self.tokens[self.pos]
        self.pos += 1
        return t

    def _add(self) -> int:
        v = self._mul()
        while self._peek() in ('+', '-'):
            op = self._eat()
            rhs = self._mul()
            v = v + rhs if op == '+' else v - rhs
        return v

    def _mul(self) -> int:
        v = self._unary()
        while self._peek() == '*':
            self._eat()
            v *= self._unary()
        return v

    def _unary(self) -> int:
        if self._peek() == '-':
            self._eat()
            return -self._unary()
        if self._peek() == '+':
            self._eat()
            return self._unary()
        return self._atom()

    def _atom(self) -> int:
        t = self._eat()
        if t == '(':
            v = self._add()
            if self._eat() != ')':
                raise ExprError("missing ')'")
            return v
        if t.startswith('0x') or t.startswith('0X'):
            return int(t.replace('_', ''), 16)
        if t.startswith('0b') or t.startswith('0B'):
            return int(t.replace('_', '')[2:], 2)
        if t[0].isdigit():
            return int(t.replace('_', ''))
        if t in self.symbols:
            return self.symbols[t]
        raise ExprError(f"undefined symbol: {t}")


# ===========================================================================
# IR
# ===========================================================================

@dataclass
class Item:
    offset: int
    size: int
    emit: Callable[[ExprEvaluator], bytes]


# ===========================================================================
# Operand helpers
# ===========================================================================

_REG_ALIASES = {'sp': 13, 'lr': 14, 'pc': 15}


def parse_reg(tok: str) -> int:
    t = tok.lower().strip()
    if t in _REG_ALIASES:
        return _REG_ALIASES[t]
    if t.startswith('r') and t[1:].isdigit():
        n = int(t[1:])
        if 0 <= n <= 15:
            return n
    raise SyntaxError(f"bad register: {tok!r}")


def parse_reglist(text: str) -> int:
    """Parse '{r0, r1-r3, lr}' into a 16-bit bitmask."""
    text = text.strip()
    if not (text.startswith('{') and text.endswith('}')):
        raise SyntaxError(f"register list must be in braces: {text!r}")
    body = text[1:-1]
    mask = 0
    for part in body.split(','):
        part = part.strip()
        if '-' in part:
            a, b = [parse_reg(x.strip()) for x in part.split('-')]
            for r in range(min(a, b), max(a, b) + 1):
                mask |= 1 << r
        elif part:
            mask |= 1 << parse_reg(part)
    return mask


def parse_imm(tok: str) -> str:
    """Strip '#' from an immediate operand, return the bare expression."""
    t = tok.strip()
    if t.startswith('#'):
        return t[1:].strip()
    return t


# Condition-suffix mapping for ARM/Thumb mnemonics
_COND_SUFFIXES = {
    'eq': ea.COND_EQ, 'ne': ea.COND_NE, 'cs': ea.COND_CS, 'hs': ea.COND_CS,
    'cc': ea.COND_CC, 'lo': ea.COND_CC, 'mi': ea.COND_MI, 'pl': ea.COND_PL,
    'vs': ea.COND_VS, 'vc': ea.COND_VC, 'hi': ea.COND_HI, 'ls': ea.COND_LS,
    'ge': ea.COND_GE, 'lt': ea.COND_LT, 'gt': ea.COND_GT, 'le': ea.COND_LE,
    'al': ea.COND_AL,
}


def split_cond(mnemonic: str, base: str) -> tuple[str, int, bool]:
    """Given e.g. 'movnes', return (base, cond, set_flags). 'mov' -> ('mov', AL, False)."""
    m = mnemonic.lower()
    if not m.startswith(base):
        raise ValueError
    suffix = m[len(base):]
    s_flag = False
    cond = ea.COND_AL
    if suffix.endswith('s'):
        s_flag = True
        suffix = suffix[:-1]
    if suffix:
        if suffix not in _COND_SUFFIXES:
            raise ValueError(f"unknown condition {suffix!r} on {mnemonic}")
        cond = _COND_SUFFIXES[suffix]
    return base, cond, s_flag


# Pending literal-pool entry: a single (value_expr, [ldr_instruction_offsets])
@dataclass
class PoolEntry:
    expr: str
    refs: list[tuple[int, int]] = field(default_factory=list)
    # refs: list of (ldr_offset, Rd) -- where the LDR lives so its offset
    # bytes can be patched in pass 2.


# ===========================================================================
# The assembler
# ===========================================================================

class Assembler:
    def __init__(self, *, base_addr: int):
        self.base_addr = base_addr
        self.offset = 0
        self.mode = 'arm'
        self.items: list[Item] = []
        self.labels: dict[str, int] = {}
        self.equates: dict[str, str] = {}
        # pending literal pool, per .ltorg flush
        self.pool: list[PoolEntry] = []
        # back-patch the LDR offsets when a pool flushes
        self.ldr_patches: list[tuple[int, int, int]] = []
        # (ldr_offset, Rd, pool_word_offset)

    # ---------------------- ingest ----------------------

    def feed(self, source: str):
        for raw_line in source.splitlines():
            line = _strip_comment(raw_line).strip()
            if not line:
                continue
            self._process_line(line)

    def _process_line(self, line: str):
        # Label?
        if ':' in line:
            label, rest = line.split(':', 1)
            label = label.strip()
            if label and self._is_ident(label):
                self.labels[label] = self.base_addr + self.offset
                line = rest.strip()
                if not line:
                    return
        # Directive?
        if line.startswith('.'):
            self._process_directive(line)
            return
        # Instruction
        self._process_instruction(line)

    @staticmethod
    def _is_ident(s: str) -> bool:
        return bool(s) and (s[0].isalpha() or s[0] == '_') and all(
            c.isalnum() or c == '_' for c in s[1:]
        )

    # ---------------------- directives ----------------------

    def _process_directive(self, line: str):
        head, _, args = line.partition(' ')
        head = head.lower()
        args = args.strip()
        if head == '.arm':
            self._align_to(4)
            self.mode = 'arm'
        elif head == '.thumb':
            self._align_to(2)
            self.mode = 'thumb'
        elif head == '.equ':
            name, value = [s.strip() for s in args.split(',', 1)]
            self.equates[name] = value
        elif head == '.word':
            self._emit_data(args, width=4)
        elif head == '.hword':
            self._emit_data(args, width=2)
        elif head == '.byte':
            self._emit_data(args, width=1)
        elif head == '.align':
            n = int(args)
            self._align_to(n)
        elif head == '.incbin':
            path = args.strip().strip('"').strip("'")
            data = Path(path).read_bytes()
            self._add_raw(data)
        elif head == '.ltorg':
            self._flush_pool()
        else:
            raise SyntaxError(f"unknown directive: {head}")

    def _emit_data(self, args: str, *, width: int):
        for expr in _split_top_level_commas(args):
            expr_local = expr
            off_local = self.offset
            def emit(resolver: ExprEvaluator, e=expr_local, w=width):
                v = resolver.eval(e) & ((1 << (8 * w)) - 1)
                return v.to_bytes(w, 'little')
            self.items.append(Item(off_local, width, emit))
            self.offset += width

    def _add_raw(self, data: bytes):
        off_local = self.offset
        self.items.append(Item(off_local, len(data), lambda r, d=data: d))
        self.offset += len(data)

    def _align_to(self, n: int):
        assert n & (n - 1) == 0, "alignment must be power of two"
        pad = (-self.offset) & (n - 1)
        if pad:
            self._add_raw(b'\x00' * pad)

    # ---------------------- literal pool ----------------------

    def _request_pool_word(self, expr: str, ldr_offset: int, Rd: int):
        # Coalesce identical expressions.
        for entry in self.pool:
            if entry.expr == expr:
                entry.refs.append((ldr_offset, Rd))
                return
        self.pool.append(PoolEntry(expr=expr, refs=[(ldr_offset, Rd)]))

    def _flush_pool(self):
        if not self.pool:
            return
        # Words must be 4-aligned.
        self._align_to(4)
        for entry in self.pool:
            pool_off = self.offset
            expr = entry.expr
            def emit(resolver: ExprEvaluator, e=expr):
                v = resolver.eval(e) & 0xFFFFFFFF
                return v.to_bytes(4, 'little')
            self.items.append(Item(pool_off, 4, emit))
            self.offset += 4
            for ldr_off, Rd in entry.refs:
                self.ldr_patches.append((ldr_off, Rd, pool_off))
        self.pool = []

    # ---------------------- instruction dispatch ----------------------

    def _process_instruction(self, line: str):
        # Split mnemonic and operands
        head, _, rest = line.partition(' ')
        mnemonic = head.lower()
        operands = [s for s in _split_top_level_commas(rest) if s] if rest else []
        if self.mode == 'arm':
            self._encode_arm(mnemonic, operands)
        else:
            self._encode_thumb(mnemonic, operands)

    # ====================== ARM instruction encoding ======================

    _ARM_DATA_OPS = {
        'and': ea.OP_AND, 'eor': ea.OP_EOR, 'sub': ea.OP_SUB, 'rsb': ea.OP_RSB,
        'add': ea.OP_ADD, 'adc': ea.OP_ADC, 'sbc': ea.OP_SBC, 'rsc': ea.OP_RSC,
        'orr': ea.OP_ORR, 'mov': ea.OP_MOV, 'bic': ea.OP_BIC, 'mvn': ea.OP_MVN,
    }
    _ARM_DATA_TEST_OPS = {
        'tst': ea.OP_TST, 'teq': ea.OP_TEQ, 'cmp': ea.OP_CMP, 'cmn': ea.OP_CMN,
    }

    def _encode_arm(self, mnemonic: str, operands: list[str]):
        # Data ops
        for base in self._ARM_DATA_OPS:
            if mnemonic.startswith(base) and self._tryparse_arm_dp(base, mnemonic, operands, set_flags_default=False):
                return
        for base in self._ARM_DATA_TEST_OPS:
            if mnemonic.startswith(base) and self._tryparse_arm_test(base, mnemonic, operands):
                return
        # Multiplication
        if mnemonic.startswith('mul'):
            if self._tryparse_arm_mul('mul', mnemonic, operands):
                return
        if mnemonic.startswith('mla'):
            if self._tryparse_arm_mla('mla', mnemonic, operands):
                return
        if mnemonic.startswith('smull'):
            if self._tryparse_arm_long_mul('smull', mnemonic, operands, signed=True):
                return
        if mnemonic.startswith('umull'):
            if self._tryparse_arm_long_mul('umull', mnemonic, operands, signed=False):
                return
        # Memory
        if mnemonic.startswith('ldrb'):
            if self._tryparse_arm_ldst('ldrb', mnemonic, operands, L=1, B=1):
                return
        if mnemonic.startswith('strb'):
            if self._tryparse_arm_ldst('strb', mnemonic, operands, L=0, B=1):
                return
        if mnemonic.startswith('ldrh'):
            if self._tryparse_arm_ldsth('ldrh', mnemonic, operands, L=1):
                return
        if mnemonic.startswith('strh'):
            if self._tryparse_arm_ldsth('strh', mnemonic, operands, L=0):
                return
        if mnemonic.startswith('ldr'):
            if self._tryparse_arm_ldr_equals(mnemonic, operands):
                return
            if self._tryparse_arm_ldst('ldr', mnemonic, operands, L=1, B=0):
                return
        if mnemonic.startswith('str'):
            if self._tryparse_arm_ldst('str', mnemonic, operands, L=0, B=0):
                return
        # Branches
        if mnemonic.startswith('bl') and not mnemonic.startswith('bls') and not mnemonic.startswith('bllo'):
            if self._tryparse_arm_branch('bl', mnemonic, operands, link=True):
                return
        if mnemonic == 'bx' or mnemonic.startswith('bx'):
            if self._tryparse_arm_bx(mnemonic, operands):
                return
        if mnemonic.startswith('b'):
            if self._tryparse_arm_branch('b', mnemonic, operands, link=False):
                return
        # Block transfer pseudo / explicit
        if mnemonic.startswith('push'):
            if self._tryparse_arm_push(mnemonic, operands):
                return
        if mnemonic.startswith('pop'):
            if self._tryparse_arm_pop(mnemonic, operands):
                return
        if mnemonic.startswith('stm'):
            if self._tryparse_arm_block('stm', mnemonic, operands, L=0):
                return
        if mnemonic.startswith('ldm'):
            if self._tryparse_arm_block('ldm', mnemonic, operands, L=1):
                return
        # SWI
        if mnemonic.startswith('swi') or mnemonic.startswith('svc'):
            if self._tryparse_arm_swi(mnemonic, operands):
                return
        # PSR access
        if mnemonic.startswith('mrs'):
            if self._tryparse_arm_mrs(mnemonic, operands):
                return
        if mnemonic.startswith('msr'):
            if self._tryparse_arm_msr(mnemonic, operands):
                return
        raise SyntaxError(f"ARM: unsupported instruction {mnemonic!r} {operands}")

    # ---- ARM data processing (3-operand and 2-operand MOV/MVN) ----

    def _tryparse_arm_dp(self, base: str, mnemonic: str, operands: list[str], *, set_flags_default: bool) -> bool:
        try:
            _, cond, s_flag = split_cond(mnemonic, base)
        except ValueError:
            return False
        if base in ('mov', 'mvn'):
            if len(operands) != 2:
                return False
            Rd = parse_reg(operands[0])
            Rn = 0
            op2 = operands[1]
        else:
            if len(operands) != 3:
                return False
            Rd = parse_reg(operands[0])
            Rn = parse_reg(operands[1])
            op2 = operands[2]
        op = self._ARM_DATA_OPS[base]
        S = 1 if s_flag else (1 if set_flags_default else 0)
        self._emit_arm_dp_word(cond, op, S, Rd, Rn, op2)
        return True

    def _emit_arm_dp_word(self, cond, op, S, Rd, Rn, op2_text):
        off_local = self.offset
        op2_text = op2_text.strip()
        if op2_text.startswith('#'):
            expr = op2_text[1:].strip()
            def emit(r, e=expr):
                v = r.eval(e)
                return ea.enc_dp_imm(op, cond, S, Rd, Rn, v).to_bytes(4, 'little')
        else:
            # Register form, optionally with shift: "r1, lsl #N"
            Rm_text, shift_text = (op2_text.split(',', 1) + [''])[:2]
            Rm = parse_reg(Rm_text)
            shift = ea.SHIFT_LSL
            amount = 0
            shift_text = shift_text.strip()
            if shift_text:
                shift_op, _, amt_text = shift_text.partition(' ')
                shift_op = shift_op.lower().strip()
                shift = {
                    'lsl': ea.SHIFT_LSL, 'lsr': ea.SHIFT_LSR,
                    'asr': ea.SHIFT_ASR, 'ror': ea.SHIFT_ROR,
                }[shift_op]
                amount_expr = amt_text.strip().lstrip('#').strip()
                def emit(r, ae=amount_expr, sh=shift):
                    a = r.eval(ae)
                    return ea.enc_dp_reg_shift_imm(op, cond, S, Rd, Rn, Rm, sh, a).to_bytes(4, 'little')
                self.items.append(Item(off_local, 4, emit))
                self.offset += 4
                return
            def emit(r, sh=shift, a=amount):
                return ea.enc_dp_reg_shift_imm(op, cond, S, Rd, Rn, Rm, sh, a).to_bytes(4, 'little')
        self.items.append(Item(off_local, 4, emit))
        self.offset += 4

    def _tryparse_arm_test(self, base: str, mnemonic: str, operands: list[str]) -> bool:
        try:
            _, cond, _ = split_cond(mnemonic, base)
        except ValueError:
            return False
        if len(operands) != 2:
            return False
        Rn = parse_reg(operands[0])
        op2 = operands[1].strip()
        op = self._ARM_DATA_TEST_OPS[base]
        off_local = self.offset
        if op2.startswith('#'):
            expr = op2[1:].strip()
            def emit(r, e=expr):
                v = r.eval(e)
                return ea.enc_dp_imm(op, cond, 1, 0, Rn, v).to_bytes(4, 'little')
        else:
            Rm = parse_reg(op2)
            def emit(r):
                return ea.enc_dp_reg(op, cond, 1, 0, Rn, Rm).to_bytes(4, 'little')
        self.items.append(Item(off_local, 4, emit))
        self.offset += 4
        return True

    # ---- multiplications ----

    def _tryparse_arm_mul(self, base, mnemonic, operands) -> bool:
        try:
            _, cond, s_flag = split_cond(mnemonic, base)
        except ValueError:
            return False
        if len(operands) != 3:
            return False
        Rd, Rm, Rs = (parse_reg(o) for o in operands)
        S = 1 if s_flag else 0
        off_local = self.offset
        self.items.append(Item(
            off_local, 4,
            lambda r: ea.enc_mul(cond, S, Rd, Rm, Rs).to_bytes(4, 'little'),
        ))
        self.offset += 4
        return True

    def _tryparse_arm_mla(self, base, mnemonic, operands) -> bool:
        try:
            _, cond, s_flag = split_cond(mnemonic, base)
        except ValueError:
            return False
        if len(operands) != 4:
            return False
        Rd, Rm, Rs, Rn = (parse_reg(o) for o in operands)
        S = 1 if s_flag else 0
        off_local = self.offset
        self.items.append(Item(
            off_local, 4,
            lambda r: ea.enc_mla(cond, S, Rd, Rm, Rs, Rn).to_bytes(4, 'little'),
        ))
        self.offset += 4
        return True

    def _tryparse_arm_long_mul(self, base, mnemonic, operands, *, signed) -> bool:
        try:
            _, cond, s_flag = split_cond(mnemonic, base)
        except ValueError:
            return False
        if len(operands) != 4:
            return False
        RdLo, RdHi, Rm, Rs = (parse_reg(o) for o in operands)
        S = 1 if s_flag else 0
        off_local = self.offset
        enc = ea.enc_smull if signed else ea.enc_umull
        self.items.append(Item(
            off_local, 4,
            lambda r: enc(cond, S, RdLo, RdHi, Rm, Rs).to_bytes(4, 'little'),
        ))
        self.offset += 4
        return True

    # ---- load/store ----

    def _parse_memref(self, text: str) -> tuple[int, str]:
        """Parse [Rn] or [Rn, #imm] or [Rn, #imm]!. Returns (Rn, imm_expr).

        For simplicity we only support pre-indexed immediate offset (P=1, W=0).
        """
        t = text.strip()
        if not (t.startswith('[') and ']' in t):
            raise SyntaxError(f"bad memory ref: {text!r}")
        body, _, _ = t[1:].partition(']')
        parts = [p.strip() for p in body.split(',')]
        Rn = parse_reg(parts[0])
        imm_expr = '0'
        if len(parts) > 1:
            imm_expr = parts[1].lstrip('#').strip()
        return Rn, imm_expr

    def _tryparse_arm_ldst(self, base, mnemonic, operands, *, L, B) -> bool:
        try:
            _, cond, _ = split_cond(mnemonic, base)
        except ValueError:
            return False
        if len(operands) != 2:
            return False
        Rd = parse_reg(operands[0])
        Rn, imm_expr = self._parse_memref(operands[1])
        off_local = self.offset
        if L == 1 and B == 0:
            enc_fn = ea.enc_ldr_imm
        elif L == 0 and B == 0:
            enc_fn = ea.enc_str_imm
        elif L == 1 and B == 1:
            enc_fn = ea.enc_ldrb_imm
        else:
            enc_fn = ea.enc_strb_imm
        def emit(r, e=imm_expr):
            v = r.eval(e)
            return enc_fn(cond, Rd, Rn, v).to_bytes(4, 'little')
        self.items.append(Item(off_local, 4, emit))
        self.offset += 4
        return True

    def _tryparse_arm_ldsth(self, base, mnemonic, operands, *, L) -> bool:
        try:
            _, cond, _ = split_cond(mnemonic, base)
        except ValueError:
            return False
        if len(operands) != 2:
            return False
        Rd = parse_reg(operands[0])
        Rn, imm_expr = self._parse_memref(operands[1])
        off_local = self.offset
        enc_fn = ea.enc_ldrh_imm if L else ea.enc_strh_imm
        def emit(r, e=imm_expr):
            v = r.eval(e)
            return enc_fn(cond, Rd, Rn, v).to_bytes(4, 'little')
        self.items.append(Item(off_local, 4, emit))
        self.offset += 4
        return True

    def _tryparse_arm_ldr_equals(self, mnemonic, operands) -> bool:
        try:
            _, cond, _ = split_cond(mnemonic, 'ldr')
        except ValueError:
            return False
        if len(operands) != 2:
            return False
        if not operands[1].lstrip().startswith('='):
            return False
        Rd = parse_reg(operands[0])
        expr = operands[1].lstrip()[1:].strip()
        ldr_off = self.offset
        self._request_pool_word(expr, ldr_off, Rd)
        # Placeholder LDR -- offset patched in pass 2 via ldr_patches table.
        def emit(r):
            # Find the patch for this offset.
            for off, RdP, pool_off in self.ldr_patches:
                if off == ldr_off and RdP == Rd:
                    # ARM PC bias = +8. Offset = pool_off - (ldr_off + 8).
                    delta = pool_off - (ldr_off + 8)
                    return ea.enc_ldr_imm(cond, Rd, 15, delta).to_bytes(4, 'little')
            raise AssertionError(f"unresolved literal pool ref at {ldr_off:#x}")
        self.items.append(Item(ldr_off, 4, emit))
        self.offset += 4
        return True

    # ---- branches ----

    def _tryparse_arm_branch(self, base, mnemonic, operands, *, link) -> bool:
        try:
            _, cond, _ = split_cond(mnemonic, base)
        except ValueError:
            return False
        if len(operands) != 1:
            return False
        target_expr = operands[0]
        off_local = self.offset
        def emit(r, e=target_expr):
            target = r.eval(e)
            offset = target - (self.base_addr + off_local + 8)
            enc = ea.enc_branch_link if link else ea.enc_branch
            return enc(cond, offset).to_bytes(4, 'little')
        self.items.append(Item(off_local, 4, emit))
        self.offset += 4
        return True

    def _tryparse_arm_bx(self, mnemonic, operands) -> bool:
        try:
            _, cond, _ = split_cond(mnemonic, 'bx')
        except ValueError:
            return False
        if len(operands) != 1:
            return False
        Rm = parse_reg(operands[0])
        off_local = self.offset
        self.items.append(Item(
            off_local, 4,
            lambda r: ea.enc_bx(cond, Rm).to_bytes(4, 'little'),
        ))
        self.offset += 4
        return True

    # ---- block transfer / push / pop ----

    def _tryparse_arm_push(self, mnemonic, operands) -> bool:
        try:
            _, cond, _ = split_cond(mnemonic, 'push')
        except ValueError:
            return False
        if len(operands) != 1:
            return False
        reglist = parse_reglist(operands[0])
        off_local = self.offset
        self.items.append(Item(
            off_local, 4,
            lambda r: ea.enc_stm(cond, 13, reglist, pre=True, up=False, writeback=True).to_bytes(4, 'little'),
        ))
        self.offset += 4
        return True

    def _tryparse_arm_pop(self, mnemonic, operands) -> bool:
        try:
            _, cond, _ = split_cond(mnemonic, 'pop')
        except ValueError:
            return False
        if len(operands) != 1:
            return False
        reglist = parse_reglist(operands[0])
        off_local = self.offset
        self.items.append(Item(
            off_local, 4,
            lambda r: ea.enc_ldm(cond, 13, reglist, pre=False, up=True, writeback=True).to_bytes(4, 'little'),
        ))
        self.offset += 4
        return True

    _BLOCK_SUFFIXES = {
        'ia': dict(pre=False, up=True),
        'ib': dict(pre=True, up=True),
        'da': dict(pre=False, up=False),
        'db': dict(pre=True, up=False),
        'fd': dict(pre=False, up=True),     # FD load = IA load
        'ed': dict(pre=True, up=True),
        'fa': dict(pre=False, up=False),
        'ea': dict(pre=True, up=False),
    }

    def _tryparse_arm_block(self, base, mnemonic, operands, *, L) -> bool:
        # mnemonic = stmXX[cond] or ldmXX[cond]
        for suffix, kw in self._BLOCK_SUFFIXES.items():
            try:
                _, cond, _ = split_cond(mnemonic, base + suffix)
                break
            except ValueError:
                continue
        else:
            return False
        # For STMFD/STMEA, FD load = IA load and FD store = DB store. We must
        # flip pre/up for STM vs LDM in the F/E codes.
        # The simple table above gives "load" semantics; STM needs swap.
        if L == 0 and suffix in ('fd', 'ed', 'fa', 'ea'):
            kw = {'fd': dict(pre=True, up=False),
                  'ed': dict(pre=False, up=False),
                  'fa': dict(pre=True, up=True),
                  'ea': dict(pre=False, up=True)}[suffix]
        if len(operands) != 2:
            return False
        Rn_text, _, wb = operands[0].partition('!')
        Rn = parse_reg(Rn_text)
        writeback = wb == '' and operands[0].endswith('!')
        # Actually parse '!' marker more reliably:
        writeback = operands[0].rstrip().endswith('!')
        reglist = parse_reglist(operands[1])
        off_local = self.offset
        enc_fn = ea.enc_ldm if L else ea.enc_stm
        pre = kw['pre']
        up = kw['up']
        self.items.append(Item(
            off_local, 4,
            lambda r: enc_fn(cond, Rn, reglist, pre=pre, up=up, writeback=writeback).to_bytes(4, 'little'),
        ))
        self.offset += 4
        return True

    # ---- swi / mrs / msr ----

    def _tryparse_arm_swi(self, mnemonic, operands) -> bool:
        for base in ('swi', 'svc'):
            try:
                _, cond, _ = split_cond(mnemonic, base)
                break
            except ValueError:
                continue
        else:
            return False
        if len(operands) != 1:
            return False
        expr = operands[0].lstrip('#').strip()
        off_local = self.offset
        def emit(r, e=expr):
            v = r.eval(e)
            return ea.enc_swi(cond, v & 0xFFFFFF).to_bytes(4, 'little')
        self.items.append(Item(off_local, 4, emit))
        self.offset += 4
        return True

    def _tryparse_arm_mrs(self, mnemonic, operands) -> bool:
        try:
            _, cond, _ = split_cond(mnemonic, 'mrs')
        except ValueError:
            return False
        if len(operands) != 2:
            return False
        Rd = parse_reg(operands[0])
        psr = operands[1].strip().lower()
        spsr = psr == 'spsr'
        off_local = self.offset
        self.items.append(Item(
            off_local, 4,
            lambda r: ea.enc_mrs(cond, Rd, spsr).to_bytes(4, 'little'),
        ))
        self.offset += 4
        return True

    def _tryparse_arm_msr(self, mnemonic, operands) -> bool:
        try:
            _, cond, _ = split_cond(mnemonic, 'msr')
        except ValueError:
            return False
        if len(operands) != 2:
            return False
        psr_field = operands[0].strip().lower()
        # parse psr_field: "cpsr_c" / "spsr_cf" / "cpsr"
        psr_name, _, fields = psr_field.partition('_')
        spsr = psr_name == 'spsr'
        mask = 0
        if not fields:
            mask = 0xF
        else:
            for c in fields:
                mask |= {'c': 1, 'x': 2, 's': 4, 'f': 8}[c]
        src = operands[1].strip()
        off_local = self.offset
        if src.startswith('#'):
            expr = src[1:].strip()
            def emit(r, e=expr):
                v = r.eval(e)
                return ea.enc_msr_imm(cond, spsr, mask, v).to_bytes(4, 'little')
            self.items.append(Item(off_local, 4, emit))
            self.offset += 4
            return True
        return False

    # ====================== Thumb instruction encoding ======================

    def _encode_thumb(self, mnemonic: str, operands: list[str]):
        # We only need a small subset for the smoke test.
        if mnemonic == 'mov':
            return self._enc_t_mov(operands)
        if mnemonic == 'b':
            return self._enc_t_b(operands, cond=None)
        for c, code in _COND_SUFFIXES.items():
            if mnemonic == 'b' + c:
                return self._enc_t_b(operands, cond=code)
        if mnemonic == 'bl':
            return self._enc_t_bl(operands)
        raise SyntaxError(f"Thumb: unsupported instruction {mnemonic!r} {operands}")

    def _enc_t_mov(self, operands):
        if len(operands) != 2:
            raise SyntaxError("thumb mov: 2 operands")
        Rd = parse_reg(operands[0])
        src = operands[1].strip()
        off_local = self.offset
        if src.startswith('#'):
            expr = src[1:].strip()
            def emit(r, e=expr):
                v = r.eval(e) & 0xFF
                return et.enc_t_movcmpaddsub_imm8(op=0, Rd=Rd, imm8=v).to_bytes(2, 'little')
        else:
            Rs = parse_reg(src)
            H1 = 1 if Rd >= 8 else 0
            H2 = 1 if Rs >= 8 else 0
            def emit(r):
                return et.enc_t_hireg_op(et.THI_MOV, H1, H2, Rs & 7, Rd & 7).to_bytes(2, 'little')
        self.items.append(Item(off_local, 2, emit))
        self.offset += 2

    def _enc_t_b(self, operands, *, cond):
        if len(operands) != 1:
            raise SyntaxError("thumb b: 1 operand")
        target_expr = operands[0]
        off_local = self.offset
        def emit(r, e=target_expr):
            target = r.eval(e)
            offset = target - (self.base_addr + off_local + 4)  # PC bias +4
            if cond is None:
                return et.enc_t_b(offset).to_bytes(2, 'little')
            return et.enc_t_b_cond(cond, offset).to_bytes(2, 'little')
        self.items.append(Item(off_local, 2, emit))
        self.offset += 2

    def _enc_t_bl(self, operands):
        if len(operands) != 1:
            raise SyntaxError("thumb bl: 1 operand")
        target_expr = operands[0]
        off_local = self.offset
        def emit(r, e=target_expr):
            target = r.eval(e)
            offset = target - (self.base_addr + off_local + 4)
            hi, lo = et.enc_t_bl_pair(offset)
            return hi.to_bytes(2, 'little') + lo.to_bytes(2, 'little')
        self.items.append(Item(off_local, 4, emit))
        self.offset += 4

    # ---------------------- finalize ----------------------

    def finalize(self) -> AssemblyResult:
        # Implicit ltorg flush at end-of-source.
        self._flush_pool()
        # Build the symbol table including equates.
        symbols = dict(self.labels)
        # Equates may forward-reference labels, so evaluate them.
        evaluator_syms = dict(symbols)
        # Iteratively resolve equates (handles equ depending on other equ)
        changed = True
        while changed:
            changed = False
            for name, expr in self.equates.items():
                if name in evaluator_syms:
                    continue
                try:
                    v = ExprEvaluator(evaluator_syms).eval(expr)
                except ExprError:
                    continue
                evaluator_syms[name] = v
                changed = True
        symbols = evaluator_syms
        evaluator = ExprEvaluator(symbols)
        # Pass 2: emit
        out = bytearray()
        for item in self.items:
            assert len(out) == item.offset, f"item offset mismatch at {item.offset} (have {len(out)})"
            chunk = item.emit(evaluator)
            assert len(chunk) == item.size, f"item size mismatch at {item.offset}"
            out.extend(chunk)
        return AssemblyResult(bytes_=bytes(out), symbols=symbols)
