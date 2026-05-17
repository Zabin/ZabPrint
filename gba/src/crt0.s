@ ============================================================================
@ crt0.s -- ROM entry + game frame loop (Mode 3 bitmap).
@
@ The cart packer reserves 0x000..0x0BF for the header; the entry-point branch
@ at 0x000 (hand-encoded in build.py) jumps here, so `_start` lives at ROM
@ offset 0x0C0 (== address 0x080000C0).
@
@ Mechanics:
@   * D-pad applies thrust in the cardinal direction.
@   * Velocity carries momentum -- semi-implicit Euler: v += a, p += v.
@   * Friction: v -= v >> 5  (about 3% per frame), so the ship drifts to
@     rest if you stop thrusting.
@   * A button fires a projectile inheriting the ship's velocity x4 plus a
@     fixed forward kick (so a stationary ship still shoots straight right).
@   * One projectile slot; it deactivates when it leaves the playfield.
@
@ Game state at IWRAM 0x03000000+:
@   +0x00  ship_x_q16   Q16.16 pixel position
@   +0x04  ship_y_q16
@   +0x08  ship_vx_q16  velocity (pixels per frame, Q16)
@   +0x0C  ship_vy_q16
@   +0x10  prev_keys    last frame's inverted KEYINPUT (for edge detect)
@   +0x14  proj_x_q16
@   +0x18  proj_y_q16
@   +0x1C  proj_vx_q16
@   +0x20  proj_vy_q16
@   +0x24  proj_active  0/1
@ ============================================================================

        .arm
        .align 2

        .equ DISPCNT,     0x04000000
        .equ VCOUNT,      0x04000006
        .equ KEYINPUT,    0x04000130
        .equ VRAM,        0x06000000

        .equ STATE,       0x03000000
        .equ S_SHIP_X,    0x00
        .equ S_SHIP_Y,    0x04
        .equ S_SHIP_VX,   0x08
        .equ S_SHIP_VY,   0x0C
        .equ S_PREV,      0x10
        .equ S_PROJ_X,    0x14
        .equ S_PROJ_Y,    0x18
        .equ S_PROJ_VX,   0x1C
        .equ S_PROJ_VY,   0x20
        .equ S_PROJ_ON,   0x24

        @ Tuning constants (Q16.16 values where applicable).
        .equ THRUST,      0x4000        @ 0.25 px/frame^2
        .equ SHIP_X0,     0x00780000    @ 120 << 16
        .equ SHIP_Y0,     0x00500000    @  80 << 16
        .equ PROJ_KICK,   0x00040000    @ 4.0 px/frame baseline shot speed

_start:
        ldr     sp, =0x03007F00
        ldr     r0, =DISPCNT
        ldr     r1, =0x0403
        str     r1, [r0]

        @ Zero the entire state block, then set initial position.
        ldr     r0, =STATE
        mov     r1, #0
        mov     r2, #10                 @ 10 words = 40 bytes covers state
init_z:
        str     r1, [r0]
        add     r0, r0, #4
        subs    r2, r2, #1
        bne     init_z

        ldr     r0, =STATE
        ldr     r1, =SHIP_X0
        str     r1, [r0, #S_SHIP_X]
        ldr     r1, =SHIP_Y0
        str     r1, [r0, #S_SHIP_Y]

frame_loop:
        @ -------- vsync: wait through current vblank, then for next one --
        ldr     r3, =VCOUNT
wait_end_vblank:
        ldrh    r2, [r3]
        cmp     r2, #160
        bge     wait_end_vblank
wait_start_vblank:
        ldrh    r2, [r3]
        cmp     r2, #160
        blt     wait_start_vblank

        @ -------- read input + edge-detect new presses ------------------
        ldr     r0, =KEYINPUT
        ldrh    r0, [r0]
        mvn     r0, r0                  @ bit set = pressed

        ldr     r12, =STATE
        ldr     r1, [r12, #S_PREV]
        str     r0, [r12, #S_PREV]
        bic     r1, r0, r1              @ r1 = newly pressed this frame

        @ -------- apply thrust to ship velocity -------------------------
        ldr     r4, [r12, #S_SHIP_VX]
        ldr     r5, [r12, #S_SHIP_VY]
        ldr     r6, =THRUST

        tst     r0, #0x10               @ Right -> +vx
        addne   r4, r4, r6
        tst     r0, #0x20               @ Left  -> -vx
        subne   r4, r4, r6
        tst     r0, #0x40               @ Up    -> -vy
        subne   r5, r5, r6
        tst     r0, #0x80               @ Down  -> +vy
        addne   r5, r5, r6

        @ Friction: v -= v >> 5  (about 3% drag per frame).
        sub     r4, r4, r4, asr #5
        sub     r5, r5, r5, asr #5

        str     r4, [r12, #S_SHIP_VX]
        str     r5, [r12, #S_SHIP_VY]

        @ -------- integrate position then clamp -------------------------
        ldr     r7, [r12, #S_SHIP_X]
        ldr     r8, [r12, #S_SHIP_Y]
        add     r7, r7, r4
        add     r8, r8, r5

        @ Clamp x in [2.0, 237.0] (Q16): 0x00020000..0x00ED0000
        mov     r9, #0x00020000
        cmp     r7, r9
        movlt   r7, r9
        mov     r9, #0x00ED0000
        cmp     r7, r9
        movgt   r7, r9
        mov     r9, #0x00020000
        cmp     r8, r9
        movlt   r8, r9
        mov     r9, #0x009D0000
        cmp     r8, r9
        movgt   r8, r9

        str     r7, [r12, #S_SHIP_X]
        str     r8, [r12, #S_SHIP_Y]

        @ -------- projectile: spawn on A-pressed edge -------------------
        ldr     r9, [r12, #S_PROJ_ON]
        cmp     r9, #0
        bne     proj_update             @ already flying; just update
        tst     r1, #0x01               @ A newly pressed?
        beq     proj_skip
        @ Spawn: copy ship position + velocity*4 + forward kick (+x).
        str     r7, [r12, #S_PROJ_X]
        str     r8, [r12, #S_PROJ_Y]
        mov     r2, r4, lsl #2          @ ship_vx * 4
        ldr     r3, =PROJ_KICK
        add     r2, r2, r3              @ + baseline shot speed
        str     r2, [r12, #S_PROJ_VX]
        mov     r2, r5, lsl #2          @ ship_vy * 4
        str     r2, [r12, #S_PROJ_VY]
        mov     r2, #1
        str     r2, [r12, #S_PROJ_ON]
        b       proj_skip

proj_update:
        @ Move projectile, deactivate if off-screen.
        ldr     r2, [r12, #S_PROJ_X]
        ldr     r3, [r12, #S_PROJ_Y]
        ldr     r9, [r12, #S_PROJ_VX]
        ldr     r10, [r12, #S_PROJ_VY]
        add     r2, r2, r9
        add     r3, r3, r10
        str     r2, [r12, #S_PROJ_X]
        str     r3, [r12, #S_PROJ_Y]
        @ Check integer position is within bounds.
        mov     r9, r2, asr #16
        mov     r10, r3, asr #16
        cmp     r9, #0
        blt     proj_off
        cmp     r9, #240
        bge     proj_off
        cmp     r10, #0
        blt     proj_off
        cmp     r10, #160
        bge     proj_off
        b       proj_skip
proj_off:
        mov     r2, #0
        str     r2, [r12, #S_PROJ_ON]
proj_skip:

        @ -------- clear VRAM with deep-space colour ---------------------
        ldr     r0, =VRAM
        ldr     r1, =0x0421
        orr     r1, r1, r1, lsl #16
        ldr     r2, =9600
clear_loop:
        str     r1, [r0]
        add     r0, r0, #4
        subs    r2, r2, #1
        bne     clear_loop

        @ -------- starfield (32 stars, fixed-seed LCG) ------------------
        ldr     r6, =0xACE17B0F
        ldr     r7, =1103515245
        ldr     r8, =12345
        ldr     r9, =VRAM
        ldr     r10, =0x7FFF
        mov     r11, #32
star_loop:
        mla     r6, r7, r6, r8
        mov     r0, r6, lsr #8
        and     r0, r0, #0xFF
        cmp     r0, #240
        bge     star_skip
        mov     r1, r6, lsr #20
        and     r1, r1, #0xFF
        cmp     r1, #160
        bge     star_skip
        mov     r12, #240
        mul     r2, r1, r12
        add     r2, r2, r0
        add     r2, r9, r2, lsl #1
        strh    r10, [r2]
star_skip:
        subs    r11, r11, #1
        bne     star_loop

        @ -------- planets ----------------------------------------------
        mov     r0, #60
        mov     r1, #50
        ldr     r2, =0x001F             @ red
        bl      draw_disc9
        mov     r0, #180
        mov     r1, #110
        ldr     r2, =0x7C00             @ blue
        bl      draw_disc9

        @ -------- projectile (if active): single bright pixel -----------
        ldr     r12, =STATE
        ldr     r3, [r12, #S_PROJ_ON]
        cmp     r3, #0
        beq     draw_ship
        ldr     r0, [r12, #S_PROJ_X]
        ldr     r1, [r12, #S_PROJ_Y]
        mov     r0, r0, asr #16
        mov     r1, r1, asr #16
        ldr     r9, =VRAM
        mov     r3, #240
        mul     r2, r1, r3
        add     r2, r2, r0
        add     r2, r9, r2, lsl #1
        ldr     r3, =0x03FF             @ yellow (BGR555)
        strh    r3, [r2]

draw_ship:
        @ -------- ship (5x5 white at integer ship_x/ship_y) -------------
        ldr     r12, =STATE
        ldr     r0, [r12, #S_SHIP_X]
        ldr     r1, [r12, #S_SHIP_Y]
        mov     r0, r0, asr #16
        mov     r1, r1, asr #16
        ldr     r2, =0x7FFF
        bl      draw_square5

        b       frame_loop

@ ----------------------------------------------------------------------------
@ draw_square5(cx, cy, color) -- 5x5 filled.
@ ----------------------------------------------------------------------------
draw_square5:
        push    {r4, r5, r6, r7, r8, lr}
        sub     r4, r1, #2
        sub     r5, r0, #2
        mov     r6, #5
        ldr     r7, =VRAM
sq5_row:
        mov     r8, r5
        mov     r0, #5
sq5_col:
        mov     r1, #240
        mul     r3, r4, r1
        add     r3, r3, r8
        add     r3, r7, r3, lsl #1
        strh    r2, [r3]
        add     r8, r8, #1
        subs    r0, r0, #1
        bne     sq5_col
        add     r4, r4, #1
        subs    r6, r6, #1
        bne     sq5_row
        pop     {r4, r5, r6, r7, r8, lr}
        bx      lr

@ ----------------------------------------------------------------------------
@ draw_disc9(cx, cy, color) -- radius-4 filled disc.
@ ----------------------------------------------------------------------------
draw_disc9:
        push    {r4, r5, r6, r7, r8, r9, r10, lr}
        mov     r3, r0
        mov     r4, r1
        mov     r5, r2
        ldr     r6, =VRAM
        mov     r7, #0
disc_y:
        sub     r8, r7, #4
        mul     r9, r8, r8
        mov     r10, #0
disc_x:
        sub     r0, r10, #4
        mul     r1, r0, r0
        add     r1, r1, r9
        cmp     r1, #16
        bgt     disc_skip
        add     r2, r3, r0
        add     r1, r4, r8
        mov     r0, #240
        mul     r0, r1, r0
        add     r0, r0, r2
        add     r0, r6, r0, lsl #1
        strh    r5, [r0]
disc_skip:
        add     r10, r10, #1
        cmp     r10, #9
        blt     disc_x
        add     r7, r7, #1
        cmp     r7, #9
        blt     disc_y
        pop     {r4, r5, r6, r7, r8, r9, r10, lr}
        bx      lr

        .ltorg
