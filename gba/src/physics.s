@ ============================================================================
@ physics.s -- fixed-point math + (eventually) two-body integrator.
@
@ Validated bit-for-bit against `toolchain/fixedpoint.py` via
@ `tests/test_physics_asm.py`. The Python reference is the source of truth.
@
@ Calling convention:
@   * args in r0..r3, result in r0
@   * r4..r12 callee-saved
@   * lr holds the return address; functions end in `bx lr`
@ ============================================================================

        .arm
        .align 2

        @ Default planet + gravitational parameter. Consumers (crt0.s, tests)
        @ may re-`.equ` these later -- the assembler keeps the last value.
        .equ PLANET_X_Q16, 0x00780000      @ 120 << 16
        .equ PLANET_Y_Q16, 0x00500000      @  80 << 16
        .equ MU_Q16,       0x001E0000      @  30 << 16

@ ----------------------------------------------------------------------------
@ fx_mul_q16(a, b) -> (a * b) >> 16  (signed)
@ ----------------------------------------------------------------------------
fx_mul_q16:
        smull   r2, r3, r0, r1
        mov     r0, r2, lsr #16
        orr     r0, r0, r3, lsl #16
        bx      lr

@ ----------------------------------------------------------------------------
@ udiv64 -- unsigned 64-bit / 32-bit division by restoring subtraction.
@
@   Inputs:  r0 = num_lo, r1 = num_hi, r2 = divisor (assumed nonzero)
@   Outputs: r0 = quotient (low 32 bits), r1 = remainder
@   Clobbers: r3, r12
@
@ 64 iterations: shift the 96-bit register {r12:r1:r0} left by 1 each pass,
@ try subtracting the divisor from r12, set bit 0 of r0 on success.
@ ----------------------------------------------------------------------------
udiv64:
        mov     r12, #0                 @ running remainder
        mov     r3, #64                 @ loop counter
_ud_loop:
        movs    r0, r0, lsl #1          @ shift num low, C = old bit 31
        adcs    r1, r1, r1              @ shift num high, bring C in, C = old bit 31
        adc     r12, r12, r12           @ shift remainder, bring C in
        cmp     r12, r2
        subhs   r12, r12, r2            @ if r12 >= divisor: subtract
        orrhs   r0, r0, #1              @                    and set quotient bit
        subs    r3, r3, #1
        bne     _ud_loop
        mov     r1, r12                 @ return remainder in r1
        bx      lr

@ ----------------------------------------------------------------------------
@ fx_div_q16(a, b) -> (a << 16) / b, truncated toward zero.
@
@ Divide-by-zero sentinels match `fixedpoint.fx_div_q16`:
@   a >= 0, b == 0 -> 0x7FFFFFFF (INT32_MAX)
@   a  < 0, b == 0 -> 0x80000000 (INT32_MIN)
@ ----------------------------------------------------------------------------
fx_div_q16:
        cmp     r1, #0
        beq     _fx_div_by_zero

        push    {r4, lr}
        eor     r4, r0, r1              @ sign bit (bit 31 = result sign)
        @ Take absolute value of a (r0) and b (r1).
        cmp     r0, #0
        rsblt   r0, r0, #0
        cmp     r1, #0
        rsblt   r1, r1, #0
        @ Pack 48-bit numerator {hi:lo} = a << 16 into r1:r0, divisor into r2.
        mov     r2, r1                  @ divisor
        mov     r1, r0, lsr #16         @ num_hi
        mov     r0, r0, lsl #16         @ num_lo
        bl      udiv64                  @ r0 = quotient, r1 = remainder
        @ Apply sign.
        tst     r4, #0x80000000
        rsbne   r0, r0, #0
        pop     {r4, lr}
        bx      lr

_fx_div_by_zero:
        cmp     r0, #0
        mvnge   r0, #0x80000000         @ ge: r0 = ~0x80000000 = 0x7FFFFFFF
        movlt   r0, #0x80000000         @ lt: r0 = 0x80000000  (INT32_MIN)
        bx      lr

@ ----------------------------------------------------------------------------
@ fx_sqrt_q16(x) -> sqrt(x) in Q16.16
@
@ Returns 0 for x <= 0. For positive x, computes floor(sqrt(x << 16)) using
@ Newton's iteration:
@
@   target = x << 16              @ 48-bit unsigned in {r5:r4}
@   g = 1 << 24                   @ initial guess >= max possible sqrt
@   loop:
@     q = target / g              @ via udiv64
@     ng = (g + q) >> 1
@     if ng >= g: return g
@     g = ng
@
@ Floor convergence proof: when g > floor(sqrt(target)), the iteration is
@ strictly decreasing; equality with the previous step marks the floor.
@ ----------------------------------------------------------------------------
fx_sqrt_q16:
        cmp     r0, #0
        movle   r0, #0
        bxle    lr

        push    {r4, r5, r6, r7, lr}
        mov     r4, r0, lsl #16         @ target_lo
        mov     r5, r0, lsr #16         @ target_hi
        mov     r6, #0x01000000         @ g = 1 << 24
_sqrt_loop:
        @ q = target / g  via udiv64
        mov     r0, r4
        mov     r1, r5
        mov     r2, r6
        bl      udiv64                  @ r0 = quotient
        add     r7, r6, r0              @ ng_pre = g + q
        mov     r7, r7, lsr #1          @ ng = (g + q) >> 1
        cmp     r7, r6
        bge     _sqrt_done
        mov     r6, r7
        b       _sqrt_loop
_sqrt_done:
        mov     r0, r6
        pop     {r4, r5, r6, r7, pc}

@ ----------------------------------------------------------------------------
@ fx_atan2(y, x) -> 16-bit binary angle (matches BIOS SWI 0x09 ArcTan2)
@
@   Python ref: x == 0 and y == 0 -> 0; else 2*pi * atan2(y, x) / (2*pi).
@   The BIOS SWI takes r0 = x, r1 = y, returns angle in r0.
@   Our Python helper passes the Pythonic (y, x) order.
@ ----------------------------------------------------------------------------
fx_atan2:
        @ Caller passes r0 = y, r1 = x (Pythonic). BIOS expects r0 = x, r1 = y.
        @ Swap them in one EOR sequence.
        eor     r0, r0, r1
        eor     r1, r1, r0
        eor     r0, r0, r1
        @ Special-case the origin to match `fixedpoint.fx_atan2((0,0))=0`.
        orrs    r2, r0, r1
        moveq   r0, #0
        bxeq    lr
        swi     0x090000
        bx      lr

@ ----------------------------------------------------------------------------
@ cowell_step(state_ptr) -- semi-implicit Euler Newtonian gravity step.
@
@   state_ptr -> [ x_q16, y_q16, vx_q16, vy_q16 ]  (16 bytes)
@
@ Computes the acceleration from a single fixed primary at
@ (PLANET_X_Q16, PLANET_Y_Q16) with mass parameter MU_Q16 (linker-supplied
@ via .equ in the consuming source), then updates:
@
@   r_vec  = body - planet            (pointing FROM planet TO body)
@   r2     = |r_vec|^2
@   r      = sqrt(r2)
@   a_mag  = MU / r2                  (acceleration magnitude)
@   a_vec  = -a_mag * r_vec / r       (toward planet)
@   v     += a_vec                    (semi-implicit Euler: kick first)
@   p     += v                         (then drift)
@
@ We carry dx = planet - body (so the acceleration is +a_mag * (dx/r),
@ already pointing toward the planet). For r2 below 1.0 (Q16 0x10000) the
@ body is essentially on top of the primary; we skip the divide to avoid
@ numerical nonsense.
@
@ Caller-side: PLANET_X_Q16, PLANET_Y_Q16, MU_Q16 must be in the symbol
@ table when this file is assembled.
@ ----------------------------------------------------------------------------
cowell_step:
        push    {r4-r11, lr}
        mov     r4, r0                  @ state ptr
        ldr     r5, [r4, #0]            @ x
        ldr     r6, [r4, #4]            @ y
        ldr     r7, [r4, #8]            @ vx
        ldr     r8, [r4, #12]           @ vy

        ldr     r0, =PLANET_X_Q16
        sub     r9, r0, r5              @ dx = planet_x - x
        ldr     r0, =PLANET_Y_Q16
        sub     r10, r0, r6             @ dy = planet_y - y

        @ r2 = dx*dx + dy*dy
        mov     r0, r9
        mov     r1, r9
        bl      fx_mul_q16
        mov     r11, r0                 @ r11 = dx*dx
        mov     r0, r10
        mov     r1, r10
        bl      fx_mul_q16              @ r0 = dy*dy
        add     r11, r11, r0            @ r11 = r2 (Q16)

        @ Skip gravity if too close (avoids div-by-zero, also numerically nuts).
        cmp     r11, #0x10000           @ < 1.0 (Q16)?
        blt     _cs_skip_grav

        @ Keep r2 alive across calls; compute r = sqrt(r2).
        mov     r0, r11
        bl      fx_sqrt_q16
        push    {r0}                    @ stack: [r]

        @ a_mag = MU / r2
        ldr     r0, =MU_Q16
        mov     r1, r11
        bl      fx_div_q16
        push    {r0}                    @ stack: [a, r]

        @ ax = a * (dx / r)
        mov     r0, r9
        ldr     r1, [sp, #4]            @ r
        bl      fx_div_q16              @ ux = dx / r
        ldr     r1, [sp]                @ a
        bl      fx_mul_q16              @ ax
        add     r7, r7, r0              @ vx += ax

        @ ay = a * (dy / r)
        mov     r0, r10
        ldr     r1, [sp, #4]            @ r
        bl      fx_div_q16              @ uy = dy / r
        ldr     r1, [sp]                @ a
        bl      fx_mul_q16              @ ay
        add     r8, r8, r0              @ vy += ay

        add     sp, sp, #8              @ drop [a, r]

_cs_skip_grav:
        @ Drift: p += v
        add     r5, r5, r7
        add     r6, r6, r8

        str     r5, [r4, #0]
        str     r6, [r4, #4]
        str     r7, [r4, #8]
        str     r8, [r4, #12]

        pop     {r4-r11, lr}
        bx      lr
