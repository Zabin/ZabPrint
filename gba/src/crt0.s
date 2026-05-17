@ ============================================================================
@ crt0.s -- ROM entry + orbital game frame loop (Mode 3 bitmap).
@
@ Mechanics:
@   * A single large primary at the screen centre. Mass parameter MU.
@   * Player ship + 3 targets all orbit the primary under Newtonian gravity
@     (Cowell step in physics.s, semi-implicit Euler, dt = 1 frame).
@   * D-pad applies small impulses to the player's velocity vector, letting
@     you raise / lower / re-shape your orbit.
@   * Touch a target (integer pixel distance <= 4) -> score++ and the target
@     respawns at its initial orbital state (kept in ROM as init_orbits).
@
@ Art:
@   * Procedural starfield (32 LCG stars, stable seed).
@   * Big banded planet -- three concentric discs at the centre.
@   * Targets: 3x3 squares in red/green/cyan.
@   * Player ship: 3x3 white core + a yellow nose pixel offset in the
@     direction of travel (8-way lookup from fx_atan2 output).
@   * Score bar: bright-green horizontal pixels at top-left.
@
@ State at IWRAM 0x03000000 (80 bytes / 20 words):
@   +0x00  player  { x_q16, y_q16, vx_q16, vy_q16 }
@   +0x10  prev_keys
@   +0x14  score
@   +0x18  frame_count
@   +0x1C  (pad)
@   +0x20  target 0 { x_q16, y_q16, vx_q16, vy_q16 }
@   +0x30  target 1 { ... }
@   +0x40  target 2 { ... }
@ ============================================================================

        .arm
        .align 2

        .equ DISPCNT,     0x04000000
        .equ VCOUNT,      0x04000006
        .equ KEYINPUT,    0x04000130
        .equ VRAM,        0x06000000

        .equ STATE,       0x03000000
        .equ S_PLAYER,    0x00
        .equ S_PREV,      0x10
        .equ S_SCORE,     0x14
        .equ S_FRAME,     0x18
        .equ S_T0,        0x20
        .equ S_T1,        0x30
        .equ S_T2,        0x40

        @ Tuning: planet at screen centre, MU sized for ~4-second orbits at
        @ radius 40 pixels. These match the defaults in physics.s.
        .equ PLANET_X,    120
        .equ PLANET_Y,    80
        .equ PLANET_X_Q16, 0x00780000
        .equ PLANET_Y_Q16, 0x00500000
        .equ MU_Q16,       0x001E0000

        .equ THRUST,      0x2000          @ 0.125 in Q16 -- subtle nudges

_start:
        ldr     sp, =0x03007F00
        ldr     r0, =DISPCNT
        ldr     r1, =0x0403
        str     r1, [r0]

        @ Zero the state block (20 words).
        ldr     r0, =STATE
        mov     r1, #0
        mov     r2, #20
init_z:
        str     r1, [r0]
        add     r0, r0, #4
        subs    r2, r2, #1
        bne     init_z

        @ Copy ROM-bound initial-orbit table into player + 3 targets.
        @ The table is 16 words (4 bodies * 4 words each); body 0 -> player,
        @ bodies 1..3 -> targets at S_T0, S_T1, S_T2.
        ldr     r0, =init_orbits
        ldr     r1, =STATE
        @ player (4 words)
        bl      _copy_orbit_body
        add     r1, r1, #(S_T0 - S_PLAYER - 16)   @ skip prev/score/frame/pad
        bl      _copy_orbit_body
        bl      _copy_orbit_body
        bl      _copy_orbit_body

frame_loop:
        @ -------- vsync -----------------------------------------------
        ldr     r3, =VCOUNT
wait_end_vblank:
        ldrh    r2, [r3]
        cmp     r2, #160
        bge     wait_end_vblank
wait_start_vblank:
        ldrh    r2, [r3]
        cmp     r2, #160
        blt     wait_start_vblank

        @ -------- frame_count++ ---------------------------------------
        ldr     r12, =STATE
        ldr     r1, [r12, #S_FRAME]
        add     r1, r1, #1
        str     r1, [r12, #S_FRAME]

        @ -------- input + edge detect ---------------------------------
        ldr     r0, =KEYINPUT
        ldrh    r0, [r0]
        mvn     r0, r0
        ldr     r1, [r12, #S_PREV]
        str     r0, [r12, #S_PREV]

        @ -------- D-pad thrust on player ------------------------------
        ldr     r4, [r12, #(S_PLAYER + 8)]      @ vx
        ldr     r5, [r12, #(S_PLAYER + 12)]     @ vy
        ldr     r6, =THRUST
        tst     r0, #0x10                       @ Right
        addne   r4, r4, r6
        tst     r0, #0x20                       @ Left
        subne   r4, r4, r6
        tst     r0, #0x40                       @ Up
        subne   r5, r5, r6
        tst     r0, #0x80                       @ Down
        addne   r5, r5, r6
        str     r4, [r12, #(S_PLAYER + 8)]
        str     r5, [r12, #(S_PLAYER + 12)]

        @ -------- Cowell step on each body ----------------------------
        ldr     r0, =STATE
        bl      cowell_step                     @ player
        ldr     r0, =STATE
        add     r0, r0, #S_T0
        bl      cowell_step
        ldr     r0, =STATE
        add     r0, r0, #S_T1
        bl      cowell_step
        ldr     r0, =STATE
        add     r0, r0, #S_T2
        bl      cowell_step

        @ -------- target collision: each target vs player -------------
        @ Player integer position
        ldr     r12, =STATE
        ldr     r0, [r12, #S_PLAYER]
        ldr     r1, [r12, #(S_PLAYER + 4)]
        mov     r4, r0, asr #16                 @ player int x
        mov     r5, r1, asr #16                 @ player int y

        mov     r6, #0                          @ target index 0..2
target_collide_loop:
        @ Compute byte offset of this target's state slot.
        @ S_T0 + i*0x10
        mov     r7, r6, lsl #4
        add     r7, r7, #S_T0
        add     r8, r12, r7                     @ &target[i]
        ldr     r0, [r8]
        ldr     r1, [r8, #4]
        mov     r0, r0, asr #16
        mov     r1, r1, asr #16
        sub     r0, r4, r0
        sub     r1, r5, r1
        mul     r0, r0, r0
        mul     r1, r1, r1
        add     r0, r0, r1
        cmp     r0, #16                         @ within 4 pixels?
        bgt     no_collect
        @ Collected! Respawn from init_orbits[1 + i] (body 1, 2, 3).
        ldr     r0, =init_orbits
        add     r9, r6, #1                      @ body index 1, 2, 3
        add     r0, r0, r9, lsl #4              @ + 16*body_idx
        mov     r1, r8                          @ dst = target slot
        push    {r6, r12, lr}
        bl      _copy_orbit_body
        pop     {r6, r12, lr}
        @ Score++
        ldr     r0, [r12, #S_SCORE]
        add     r0, r0, #1
        str     r0, [r12, #S_SCORE]
no_collect:
        add     r6, r6, #1
        cmp     r6, #3
        blt     target_collide_loop

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

        @ -------- planet: three concentric bands -----------------------
        @ Outer rim (radius 14), light tan
        mov     r0, #PLANET_X
        mov     r1, #PLANET_Y
        mov     r2, #14
        ldr     r3, =0x3AFB                     @ pale tan BGR555
        bl      draw_disc

        @ Mid band (radius 10), warmer
        mov     r0, #PLANET_X
        mov     r1, #PLANET_Y
        mov     r2, #10
        ldr     r3, =0x126F                     @ rust orange
        bl      draw_disc

        @ Core (radius 5), deep
        mov     r0, #PLANET_X
        mov     r1, #PLANET_Y
        mov     r2, #5
        ldr     r3, =0x08AC                     @ dark amber
        bl      draw_disc

        @ -------- targets (3x3 colored squares) -----------------------
        ldr     r12, =STATE

        ldr     r0, [r12, #S_T0]
        ldr     r1, [r12, #(S_T0 + 4)]
        mov     r0, r0, asr #16
        mov     r1, r1, asr #16
        ldr     r2, =0x001F                     @ red
        bl      draw_square3

        ldr     r12, =STATE
        ldr     r0, [r12, #S_T1]
        ldr     r1, [r12, #(S_T1 + 4)]
        mov     r0, r0, asr #16
        mov     r1, r1, asr #16
        ldr     r2, =0x03E0                     @ green
        bl      draw_square3

        ldr     r12, =STATE
        ldr     r0, [r12, #S_T2]
        ldr     r1, [r12, #(S_T2 + 4)]
        mov     r0, r0, asr #16
        mov     r1, r1, asr #16
        ldr     r2, =0x7FE0                     @ cyan-white
        bl      draw_square3

        @ -------- player ship core + heading nose ---------------------
        ldr     r12, =STATE
        ldr     r0, [r12, #S_PLAYER]
        ldr     r1, [r12, #(S_PLAYER + 4)]
        mov     r0, r0, asr #16                 @ int x
        mov     r1, r1, asr #16                 @ int y
        push    {r0, r1}                        @ save for nose
        ldr     r2, =0x7FFF                     @ white
        bl      draw_square3
        pop     {r4, r5}                        @ r4=cx, r5=cy

        @ Heading nose: atan2(vy, vx) -> 8-way bin -> offset table
        ldr     r12, =STATE
        ldr     r0, [r12, #(S_PLAYER + 12)]     @ vy first (Pythonic y arg)
        ldr     r1, [r12, #(S_PLAYER + 8)]      @ vx
        @ If both vx and vy are essentially zero, skip nose (no heading).
        orrs    r2, r0, r1
        beq     skip_nose
        bl      fx_atan2                        @ r0 = brad
        @ Round to nearest 8-bin: add 0x1000, shift right 13, mask 7
        ldr     r1, =0x1000
        add     r0, r0, r1
        mov     r0, r0, lsr #13
        and     r0, r0, #7
        @ dx = nose_dx[idx], dy = nose_dy[idx]
        ldr     r1, =nose_dx
        add     r1, r1, r0, lsl #2
        ldr     r6, [r1]
        ldr     r1, =nose_dy
        add     r1, r1, r0, lsl #2
        ldr     r7, [r1]
        @ Plot pixel at (cx + dx, cy + dy)
        add     r2, r4, r6                      @ px
        add     r3, r5, r7                      @ py
        @ Clamp into screen (cheap guard).
        cmp     r2, #0
        blt     skip_nose
        cmp     r2, #240
        bge     skip_nose
        cmp     r3, #0
        blt     skip_nose
        cmp     r3, #160
        bge     skip_nose
        mov     r0, #240
        mul     r0, r3, r0
        add     r0, r0, r2
        ldr     r1, =VRAM
        add     r0, r1, r0, lsl #1
        ldr     r1, =0x03FF                     @ yellow
        strh    r1, [r0]
skip_nose:

        @ -------- score bar (green pixels at top-left) -----------------
        ldr     r12, =STATE
        ldr     r0, [r12, #S_SCORE]
        cmp     r0, #0
        beq     skip_score
        cmp     r0, #50
        movgt   r0, #50
        ldr     r1, =(0x06000000 + 482)         @ VRAM + (2*240 + 1)*2
        ldr     r2, =0x03E0                     @ bright green
score_loop:
        strh    r2, [r1]
        add     r1, r1, #2
        subs    r0, r0, #1
        bne     score_loop
skip_score:

        b       frame_loop

@ ----------------------------------------------------------------------------
@ _copy_orbit_body -- copy 16 bytes (1 body's worth) from r0 -> r1, advancing
@ both pointers so callers can chain calls.
@ ----------------------------------------------------------------------------
_copy_orbit_body:
        ldr     r2, [r0]
        str     r2, [r1]
        ldr     r2, [r0, #4]
        str     r2, [r1, #4]
        ldr     r2, [r0, #8]
        str     r2, [r1, #8]
        ldr     r2, [r0, #12]
        str     r2, [r1, #12]
        add     r0, r0, #16
        add     r1, r1, #16
        bx      lr

@ ----------------------------------------------------------------------------
@ draw_square3(cx, cy, color) -- 3x3 filled.
@ ----------------------------------------------------------------------------
draw_square3:
        push    {r4, r5, r6, r7, r8, lr}
        sub     r4, r1, #1
        sub     r5, r0, #1
        mov     r6, #3
        ldr     r7, =VRAM
sq3_row:
        mov     r8, r5
        mov     r0, #3
sq3_col:
        mov     r1, #240
        mul     r3, r4, r1
        add     r3, r3, r8
        add     r3, r7, r3, lsl #1
        strh    r2, [r3]
        add     r8, r8, #1
        subs    r0, r0, #1
        bne     sq3_col
        add     r4, r4, #1
        subs    r6, r6, #1
        bne     sq3_row
        pop     {r4, r5, r6, r7, r8, lr}
        bx      lr

@ ----------------------------------------------------------------------------
@ draw_disc(cx, cy, r, color) -- filled disc.
@   Walks a (2r+1)^2 box, plots pixels where dx*dx + dy*dy <= r*r.
@   Caller must keep the disc on-screen (no clamping here).
@ ----------------------------------------------------------------------------
draw_disc:
        push    {r4, r5, r6, r7, r8, r9, r10, r11, lr}
        mov     r4, r0                          @ cx
        mov     r5, r1                          @ cy
        mov     r6, r2                          @ r
        mov     r7, r3                          @ color
        mul     r8, r6, r6                      @ r*r
        ldr     r11, =VRAM

        rsb     r9, r6, #0                      @ dy = -r
disc_y2:
        rsb     r10, r6, #0                     @ dx = -r
disc_x2:
        mul     r0, r9, r9
        mul     r1, r10, r10
        add     r1, r1, r0
        cmp     r1, r8
        bgt     disc_skip2
        add     r0, r4, r10                     @ px
        add     r1, r5, r9                      @ py
        mov     r2, #240
        mul     r2, r1, r2
        add     r2, r2, r0
        add     r2, r11, r2, lsl #1
        strh    r7, [r2]
disc_skip2:
        add     r10, r10, #1
        cmp     r10, r6
        ble     disc_x2
        add     r9, r9, #1
        cmp     r9, r6
        ble     disc_y2
        pop     {r4, r5, r6, r7, r8, r9, r10, r11, lr}
        bx      lr

@ ----------------------------------------------------------------------------
@ Initial-orbit table (4 bodies). Each entry is 4 words: x, y, vx, vy in Q16.
@ Computed from MU=30, planet at (120, 80):
@
@   body 0 (player): r=40 above   -> (120, 40) v=( v_circ_40, 0)
@   body 1 (target): r=50 right   -> (170, 80) v=( 0, +v_circ_50)
@   body 2 (target): r=30 below   -> (120,110) v=(-v_circ_30, 0)
@   body 3 (target): r=60 left    -> ( 60, 80) v=( 0, -v_circ_60)
@
@   v_circ_40 = sqrt(30/40) * Q16  = 56756
@   v_circ_50 = sqrt(30/50) * Q16  = 50774
@   v_circ_30 = sqrt(30/30) * Q16  = 65536
@   v_circ_60 = sqrt(30/60) * Q16  = 46341
@ ----------------------------------------------------------------------------
        .align 2
init_orbits:
        @ body 0 -- player at (120, 40), moving right
        .word 0x00780000        @ x = 120<<16
        .word 0x00280000        @ y =  40<<16
        .word 56756             @ vx = v_circ_40
        .word 0                 @ vy

        @ body 1 -- target at (170, 80), moving down
        .word 0x00AA0000
        .word 0x00500000
        .word 0
        .word 50774             @ +v_circ_50

        @ body 2 -- target at (120, 110), moving left
        .word 0x00780000
        .word 0x006E0000
        .word -65536            @ -v_circ_30
        .word 0

        @ body 3 -- target at (60, 80), moving up
        .word 0x003C0000
        .word 0x00500000
        .word 0
        .word -46341            @ -v_circ_60

@ ----------------------------------------------------------------------------
@ Heading-nose offset table: 8 directions, 3-px offset from ship centre.
@ Index by ((brad + 0x1000) >> 13) & 7. Direction 0 is +x (right); CCW in
@ screen coords means down (since +y is down on the GBA).
@   0 ->  +X     (right)
@   1 ->  +X +Y  (right-down)
@   2 ->  +Y     (down)
@   3 ->  -X +Y  (left-down)
@   4 ->  -X     (left)
@   5 ->  -X -Y  (left-up)
@   6 ->  -Y     (up)
@   7 ->  +X -Y  (right-up)
@ ----------------------------------------------------------------------------
        .align 2
nose_dx:
        .word  3,  2,  0, -2, -3, -2,  0,  2
nose_dy:
        .word  0,  2,  3,  2,  0, -2, -3, -2

        .ltorg
