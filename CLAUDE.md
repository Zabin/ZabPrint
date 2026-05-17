# CLAUDE.md — GBA Space Game project

## Repo layout

This repository has two unrelated codebases. **Stay inside `gba/` unless
explicitly told otherwise.** The other code is a thermal-printer project
that has nothing to do with this work and must not be modified.

```
gba/
  toolchain/        Pure-Python ARM/Thumb assembler, linker, cart packer,
                    asset packer, fixed-point reference, ARMv4 interpreter.
                    Stdlib only.
  assets/           Build-time procedural visual assets (numpy + Pillow OK).
  audio/            Build-time procedural music + sfx (stdlib only).
  src/              Hand-written ARM/Thumb assembly processed by toolchain/.
  tests/            pytest. `conftest.py` injects gba/ onto sys.path.
  build.py          Single-command build: src/*.s -> game.gba.
  build/            gitignored. game.gba + preview wavs/pngs land here.
```

## Branch

All development on this project lives on `claude/gba-space-game-Xwd0A`.
Never commit to other branches without explicit permission.

## Build + test commands

```bash
cd /home/user/ZabPrint/gba
python -m pytest tests/                 # full suite, must stay green
python build.py                         # write build/game.gba (2 MiB)
python -m audio.gen_all                 # rebuild audio bins + wav previews
python -m assets.gen_all                # rebuild asset bins + png previews
```

## Test discipline

Tests come first. Every code change has a covering test, written before
the implementation. Goldens are inline integer literals with the
derivation noted in a comment. Tolerances are absolute integer bounds
(no `pytest.approx` for fixed-point math). Current count is in `memory.md`.

## Assembler gotchas

The in-tree assembler (`toolchain/asm.py`) supports a deliberate subset.
Things that bit us in past sessions:

1. **Labels starting with `.`** look like directives. Use plain identifiers
   (`_sqrt_loop`, not `.Lsqrt_loop`).
2. **`.global`** is not implemented. Labels are already exported via the
   `symbols` dict returned by `assemble()`.
3. **`.space N`** is not implemented either. If you need padding, emit
   `.byte 0` or `.word 0` repeatedly via a generated source string.
4. **`mov rX, #imm`** requires `imm` to be encodable as an 8-bit value
   rotated right by an even amount. `mov r0, #-1` and `mov r0, #0xFFFFFFFF`
   both fail. Use `mvn r0, #0` (= -1) or `ldr r0, =VALUE` (literal pool).
5. **Cond + S suffix** (e.g. `subhs`) was previously mis-parsed as
   `sub` + `h` + `s`. The fix landed in `split_cond()`; if you add new
   mnemonics, keep the "cond first, then S" order.
6. **Shifted-register operands** like `mov r0, r1, lsl #4` come in as a
   third comma-split operand. `_tryparse_arm_dp` merges them back; if
   you add a new DP-style instruction, mirror that merge.
7. **`.ltorg`** must be reachable within ±4 KiB of every `ldr =VALUE` site.
   For long files, flush the pool more than once.

## ROM layout convention

`build.py` hand-encodes a 4-byte branch at ROM offset 0:

    0xEA00002E  ==  b 0x080000C0

so the GBA boot path jumps over the 192-byte header straight into our
payload. Source files are assembled with `base_addr=0x080000C0`; the
`pack_rom()` call layers the entry branch + Nintendo logo + header
+ checksum on top.

The first label in the first source file (`src/crt0.s`) **must** be
`_start`. The assembler order in `build.py` puts `crt0.s` first
deliberately for this reason.

## Game-state convention

Live game state is at IWRAM `0x03000000+`. The layout is documented in
the header of `src/crt0.s`. When you change the layout:

1. Update the equates in `crt0.s`.
2. Update the `init_z` loop count if the size grows.
3. Update offset constants in `tests/test_rom_execute.py`.

## What to ask before doing

* Anything touching the parent repo outside `gba/` — refuse unless
  explicitly approved.
* Anything destructive: `git reset --hard`, `git push --force`, force-push
  to a published branch, deleting files we generated as deliverables.
* Anything that bypasses test discipline (TDD-first). If a feature can't
  be tested, say so before writing it.

## Feedback cadence

The master plan in `/root/.claude/plans/generate-a-space-exploration-purrfect-chipmunk.md`
specifies feedback checkpoints at four milestones (A: visual assets;
B: audio; C: scene composition; D: first runnable ROM). At each, send
the relevant preview file via `SendUserFile` and use `AskUserQuestion`
to confirm direction before continuing. Milestone A, B, and D have
already happened; C is partial.
