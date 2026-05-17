@ ============================================================================
@ crt0.s -- ROM entry + game frame loop (Mode 3 bitmap).
@
@ Mechanics:
@   * D-pad applies thrust; velocity has friction so the ship drifts.
@   * A button (edge-detected) fires a projectile (one slot, inherits ship
@     velocity x4 + forward kick).
@   * Two planets sit in the world. Hit one with a projectile -> score++,
@     planet dies. When both planets are dead, the game respawns them at
@     LCG-randomised positions seeded from the frame counter.
@   * Score is shown as a horizontal bar of bright green pixels in the
@     top-left.
@
@ State at IWRAM 0x03000000:
@   +0x00  ship_x_q16        Q16.16 position
@   +0x04  ship_y_q16
@   +0x08  ship_vx_q16       Q16.16 velocity
@   +0x0C  ship_vy_q16
@   +0x10  prev_keys
@   +0x14  proj_x_q16
@   +0x18  proj_y_q16
@   +0x1C  proj_vx_q16
@   +0x20  proj_vy_q16
@   +0x24  proj_active
@   +0x28  p1_x  (integer)
@   +0x2C  p1_y
@   +0x30  p1_alive
@   +0x34  p2_x
@   +0x38  p2_y
@   +0x3C  p2_alive
@   +0x40  frame_count       LCG seed source for respawns
@   +0x44  score             number of planets killed
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
        .equ S_P1_X,      0x28
        .equ S_P1_Y,      0x2C
        .equ S_P1_ALIVE,  0x30
        .equ S_P2_X,      0x34
        .equ S_P2_Y,      0x38
        .equ S_P2_ALIVE,  0x3C
        .equ S_FRAME,     0x40
        .equ S_SCORE,     0x44

        .equ THRUST,      0x4000        @ 0.25 in Q16
        .equ SHIP_X0,     0x00780000    @ 120 << 16
        .equ SHIP_Y0,     0x00500000    @  80 << 16
        .equ PROJ_KICK,   0x00040000    @ 4 px/frame forward

_start:
        ldr     sp, =0x03007F00
        ldr     r0, =DISPCNT
        ldr     r1, =0x0403
        str     r1, [r0]

        @ Zero the state block (20 words = 80 bytes covers everything).
        ldr     r0, =STATE
        mov     r1, #0
        mov     r2, #20
init_z:
        str     r1, [r0]
        add     r0, r0, #4
        subs    r2, r2, #1
        bne     init_z

        @ Seed initial values that aren't zero.
        ldr     r0, =STATE
        ldr     r1, =SHIP_X0
        str     r1, [r0, #S_SHIP_X]
        ldr     r1, =SHIP_Y0
        str     r1, [r0, #S_SHIP_Y]
        mov     r1, #60
        str     r1, [r0, #S_P1_X]
        mov     r1, #50
        str     r1, [r0, #S_P1_Y]
        mov     r1, #1
        str     r1, [r0, #S_P1_ALIVE]
        mov     r1, #180
        str     r1, [r0, #S_P2_X]
        mov     r1, #110
        str     r1, [r0, #S_P2_Y]
        mov     r1, #1
        str     r1, [r0, #S_P2_ALIVE]

frame_loop:
        @ -------- vsync ------------------------------------------------
        ldr     r3, =VCOUNT
wait_end_vblank:
        ldrh    r2, [r3]
        cmp     r2, #160
        bge     wait_end_vblank
wait_start_vblank:
        ldrh    r2, [r3]
        cmp     r2, #160
        blt     wait_start_vblank

        @ -------- frame_count++ (drives respawn LCG) -------------------
        ldr     r12, =STATE
        ldr     r1, [r12, #S_FRAME]
        add     r1, r1, #1
        str     r1, [r12, #S_FRAME]

        @ -------- input read + edge detect -----------------------------
        ldr     r0, =KEYINPUT
        ldrh    r0, [r0]
        mvn     r0, r0

        ldr     r1, [r12, #S_PREV]
        str     r0, [r12, #S_PREV]
        bic     r1, r0, r1              @ newly pressed

        @ -------- thrust + friction ------------------------------------
        ldr     r4, [r12, #S_SHIP_VX]
        ldr     r5, [r12, #S_SHIP_VY]
        ldr     r6, =THRUST
        tst     r0, #0x10
        addne   r4, r4, r6
        tst     r0, #0x20
        subne   r4, r4, r6
        tst     r0, #0x40
        subne   r5, r5, r6
        tst     r0, #0x80
        addne   r5, r5, r6
        sub     r4, r4, r4, asr #5
        sub     r5, r5, r5, asr #5
        str     r4, [r12, #S_SHIP_VX]
        str     r5, [r12, #S_SHIP_VY]

        @ -------- integrate position + clamp ---------------------------
        ldr     r7, [r12, #S_SHIP_X]
        ldr     r8, [r12, #S_SHIP_Y]
        add     r7, r7, r4
        add     r8, r8, r5
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

        @ -------- projectile: spawn or update --------------------------
        ldr     r9, [r12, #S_PROJ_ON]
        cmp     r9, #0
        bne     proj_update
        tst     r1, #0x01
        beq     proj_done
        @ spawn
        str     r7, [r12, #S_PROJ_X]
        str     r8, [r12, #S_PROJ_Y]
        mov     r2, r4, lsl #2
        ldr     r3, =PROJ_KICK
        add     r2, r2, r3
        str     r2, [r12, #S_PROJ_VX]
        mov     r2, r5, lsl #2
        str     r2, [r12, #S_PROJ_VY]
        mov     r2, #1
        str     r2, [r12, #S_PROJ_ON]
        b       proj_done

proj_update:
        ldr     r2, [r12, #S_PROJ_X]
        ldr     r3, [r12, #S_PROJ_Y]
        ldr     r9, [r12, #S_PROJ_VX]
        ldr     r10, [r12, #S_PROJ_VY]
        add     r2, r2, r9
        add     r3, r3, r10
        str     r2, [r12, #S_PROJ_X]
        str     r3, [r12, #S_PROJ_Y]
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

        @ Projectile is on screen -- test against planets.
        @ Planet 1
        ldr     r11, [r12, #S_P1_ALIVE]
        cmp     r11, #0
        beq     test_p2
        ldr     r0, [r12, #S_P1_X]
        ldr     r1, [r12, #S_P1_Y]
        sub     r0, r9, r0
        sub     r1, r10, r1
        mul     r0, r0, r0
        mul     r1, r1, r1
        add     r0, r0, r1
        cmp     r0, #25
        bgt     test_p2
        @ HIT p1
        mov     r11, #0
        str     r11, [r12, #S_P1_ALIVE]
        str     r11, [r12, #S_PROJ_ON]
        ldr     r0, [r12, #S_SCORE]
        add     r0, r0, #1
        str     r0, [r12, #S_SCORE]
        b       proj_done

test_p2:
        ldr     r11, [r12, #S_P2_ALIVE]
        cmp     r11, #0
        beq     proj_done
        ldr     r0, [r12, #S_P2_X]
        ldr     r1, [r12, #S_P2_Y]
        sub     r0, r9, r0
        sub     r1, r10, r1
        mul     r0, r0, r0
        mul     r1, r1, r1
        add     r0, r0, r1
        cmp     r0, #25
        bgt     proj_done
        @ HIT p2
        mov     r11, #0
        str     r11, [r12, #S_P2_ALIVE]
        str     r11, [r12, #S_PROJ_ON]
        ldr     r0, [r12, #S_SCORE]
        add     r0, r0, #1
        str     r0, [r12, #S_SCORE]
        b       proj_done

proj_off:
        mov     r2, #0
        str     r2, [r12, #S_PROJ_ON]

proj_done:
        @ -------- respawn if both planets dead -------------------------
        ldr     r0, [r12, #S_P1_ALIVE]
        ldr     r1, [r12, #S_P2_ALIVE]
        orr     r0, r0, r1
        cmp     r0, #0
        bne     respawn_done

        @ LCG step from frame counter -> two new positions.
        ldr     r6, [r12, #S_FRAME]
        ldr     r7, =1103515245
        ldr     r8, =12345
        mla     r6, r7, r6, r8
        mov     r0, r6, lsr #8
        and     r0, r0, #0xFF
        cmp     r0, #200
        movgt   r0, #200
        cmp     r0, #20
        movlt   r0, #20
        mov     r1, r6, lsr #20
        and     r1, r1, #0xFF
        cmp     r1, #140
        movgt   r1, #140
        cmp     r1, #20
        movlt   r1, #20
        str     r0, [r12, #S_P1_X]
        str     r1, [r12, #S_P1_Y]
        mov     r9, #1
        str     r9, [r12, #S_P1_ALIVE]

        mla     r6, r7, r6, r8
        mov     r0, r6, lsr #8
        and     r0, r0, #0xFF
        cmp     r0, #200
        movgt   r0, #200
        cmp     r0, #20
        movlt   r0, #20
        mov     r1, r6, lsr #20
        and     r1, r1, #0xFF
        cmp     r1, #140
        movgt   r1, #140
        cmp     r1, #20
        movlt   r1, #20
        str     r0, [r12, #S_P2_X]
        str     r1, [r12, #S_P2_Y]
        mov     r9, #1
        str     r9, [r12, #S_P2_ALIVE]

respawn_done:

        @ -------- clear VRAM ------------------------------------------
        ldr     r0, =VRAM
        ldr     r1, =0x0421
        orr     r1, r1, r1, lsl #16
        ldr     r2, =9600
clear_loop:
        str     r1, [r0]
        add     r0, r0, #4
        subs    r2, r2, #1
        bne     clear_loop

        @ -------- starfield -------------------------------------------
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
        ldr     r12, =STATE
        ldr     r4, [r12, #S_P1_ALIVE]
        cmp     r4, #0
        beq     skip_p1_draw
        ldr     r0, [r12, #S_P1_X]
        ldr     r1, [r12, #S_P1_Y]
        ldr     r2, =0x001F
        bl      draw_disc9
skip_p1_draw:
        ldr     r12, =STATE
        ldr     r4, [r12, #S_P2_ALIVE]
        cmp     r4, #0
        beq     skip_p2_draw
        ldr     r0, [r12, #S_P2_X]
        ldr     r1, [r12, #S_P2_Y]
        ldr     r2, =0x7C00
        bl      draw_disc9
skip_p2_draw:

        @ -------- projectile (if active) -------------------------------
        ldr     r12, =STATE
        ldr     r3, [r12, #S_PROJ_ON]
        cmp     r3, #0
        beq     skip_proj_draw
        ldr     r0, [r12, #S_PROJ_X]
        ldr     r1, [r12, #S_PROJ_Y]
        mov     r0, r0, asr #16
        mov     r1, r1, asr #16
        ldr     r9, =VRAM
        mov     r3, #240
        mul     r2, r1, r3
        add     r2, r2, r0
        add     r2, r9, r2, lsl #1
        ldr     r3, =0x03FF
        strh    r3, [r2]
skip_proj_draw:

        @ -------- score bar (green pixels at top-left) -----------------
        ldr     r12, =STATE
        ldr     r0, [r12, #S_SCORE]
        cmp     r0, #0
        beq     skip_score
        cmp     r0, #50
        movgt   r0, #50
        ldr     r1, =(0x06000000 + 482)  @ VRAM + (2*240 + 1)*2
        ldr     r2, =0x03E0              @ bright green
score_loop:
        strh    r2, [r1]
        add     r1, r1, #2
        subs    r0, r0, #1
        bne     score_loop
skip_score:

        @ -------- ship -------------------------------------------------
        ldr     r12, =STATE
        ldr     r0, [r12, #S_SHIP_X]
        ldr     r1, [r12, #S_SHIP_Y]
        mov     r0, r0, asr #16
        mov     r1, r1, asr #16
        ldr     r2, =0x7FFF
        bl      draw_square5

        b       frame_loop

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
