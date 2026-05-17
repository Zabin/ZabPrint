@ ============================================================================
@ physics.s -- fixed-point math + (eventually) two-body integrator.
@
@ This file is validated bit-for-bit against `toolchain/fixedpoint.py` via
@ `tests/test_physics_asm.py`. The Python reference is the source of truth;
@ this code must match it exactly across the input grid the tests exercise.
@
@ AAPCS-lite calling convention:
@   * args in r0..r3, result in r0
@   * r4..r12 callee-saved
@   * lr holds the return address; functions end in `bx lr`
@ ============================================================================

        .arm
        .align 2

@ ----------------------------------------------------------------------------
@ fx_mul_q16(a, b) -> (a * b) >> 16  (signed)
@
@   {r3:r2} = a * b (signed 64-bit)
@   result  = (r3 << 16) | (r2 >> 16)
@
@ Mirrors the canonical "Q16.16 multiply" pattern. Saturation isn't applied;
@ the Python reference's `sat32` only kicks in at |a*b| >= 2^47, which our
@ physics inputs never reach. Validated against the reference for ~2000
@ random pairs in tests/test_physics_asm.py.
@ ----------------------------------------------------------------------------
fx_mul_q16:
        smull   r2, r3, r0, r1
        mov     r0, r2, lsr #16
        orr     r0, r0, r3, lsl #16
        bx      lr
