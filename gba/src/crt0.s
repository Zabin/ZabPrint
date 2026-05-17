@ ============================================================================
@ crt0.s -- ROM entry + frame loop.
@
@ The cart packer reserves 0x000..0x0BF for the header. The entry-point branch
@ at offset 0x000 (hand-encoded in build.py) jumps here; this file's first
@ label `_start` therefore sits at ROM offset 0x0C0 == address 0x080000C0.
@
@ Layer 9 game loop (Mode 3 bitmap):
@   * vsync via VCOUNT polling -- one render per scan-frame
@   * read KEYINPUT, move ship sprite with the D-pad
@   * paint: deep-space clear -> 32-star LCG starfield ->
@            2 fixed planets -> 5x5 ship at (ship_x, ship_y)
@
@ Game state lives in IWRAM at 0x03000000+. The 1024-entry sin LUT and the
@ Cowell physics integrator are wired up as follow-ups -- the math primitives
@ are already in physics.s and validated by tests/test_physics_asm.py.
@ ============================================================================

        .arm
        .align 2

        .equ DISPCNT,   0x04000000
        .equ VCOUNT,    0x04000006
        .equ KEYINPUT,  0x04000130
        .equ VRAM,      0x06000000

        .equ SHIP_X,    0x03000000
        .equ SHIP_Y,    0x03000004

_start:
        @ User-mode stack at the canonical top of IWRAM.
        ldr     sp, =0x03007F00

        @ DISPCNT = mode 3 + BG2 on  -> 0x0403.
        ldr     r0, =DISPCNT
        ldr     r1, =0x0403
        str     r1, [r0]

        @ Initial ship position (centred-ish).
        ldr     r0, =SHIP_X
        mov     r1, #120
        str     r1, [r0]
        mov     r1, #80
        str     r1, [r0, #4]

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

        @ -------- input + ship update -----------------------------------
        ldr     r0, =KEYINPUT
        ldrh    r0, [r0]
        mvn     r0, r0                  @ active-low -> bit set = pressed

        ldr     r3, =SHIP_X
        ldr     r4, [r3]                @ ship_x
        ldr     r5, [r3, #4]            @ ship_y

        tst     r0, #0x10               @ Right (bit 4)
        addne   r4, r4, #2
        tst     r0, #0x20               @ Left  (bit 5)
        subne   r4, r4, #2
        tst     r0, #0x40               @ Up    (bit 6)
        subne   r5, r5, #2
        tst     r0, #0x80               @ Down  (bit 7)
        addne   r5, r5, #2

        @ Clamp ship into the visible playfield (leaving room for the 5x5).
        cmp     r4, #2
        movlt   r4, #2
        cmp     r4, #237
        movgt   r4, #237
        cmp     r5, #2
        movlt   r5, #2
        cmp     r5, #157
        movgt   r5, #157

        str     r4, [r3]
        str     r5, [r3, #4]

        @ -------- clear VRAM with deep-space ----------------------------
        @ 240 * 160 = 38400 halfwords = 9600 words; write two pixels per str.
        ldr     r0, =VRAM
        ldr     r1, =0x0421             @ deep blue/black BGR555
        orr     r1, r1, r1, lsl #16     @ packed pair
        ldr     r2, =9600
clear_loop:
        str     r1, [r0]
        add     r0, r0, #4
        subs    r2, r2, #1
        bne     clear_loop

        @ -------- starfield: 32 stars from a fixed LCG ------------------
        ldr     r6, =0xACE17B0F         @ seed (same every frame -> stable stars)
        ldr     r7, =1103515245
        ldr     r8, =12345
        ldr     r9, =VRAM
        ldr     r10, =0x7FFF            @ white
        mov     r11, #32
star_loop:
        mla     r6, r7, r6, r8          @ r6 = r7*r6 + r8 (LCG step)
        mov     r0, r6, lsr #8
        and     r0, r0, #0xFF           @ x in [0,255]; reject if >=240
        cmp     r0, #240
        bge     star_skip
        mov     r1, r6, lsr #20
        and     r1, r1, #0xFF
        cmp     r1, #160
        bge     star_skip
        mov     r12, #240
        mul     r2, r1, r12             @ y*240
        add     r2, r2, r0              @ + x
        add     r2, r9, r2, lsl #1
        strh    r10, [r2]
star_skip:
        subs    r11, r11, #1
        bne     star_loop

        @ -------- planet 1 at (60, 50), red -----------------------------
        mov     r0, #60
        mov     r1, #50
        ldr     r2, =0x001F
        bl      draw_disc9

        @ -------- planet 2 at (180, 110), blue --------------------------
        mov     r0, #180
        mov     r1, #110
        ldr     r2, =0x7C00
        bl      draw_disc9

        @ -------- ship: 5x5 white square at (ship_x, ship_y) ------------
        ldr     r3, =SHIP_X
        ldr     r0, [r3]
        ldr     r1, [r3, #4]
        ldr     r2, =0x7FFF
        bl      draw_square5

        b       frame_loop

@ ----------------------------------------------------------------------------
@ draw_square5(cx, cy, color)
@   r0 = cx, r1 = cy, r2 = color
@   Plots a 5x5 filled square centred at (cx, cy). Caller guarantees the
@   centre is at least 2 away from each edge (the ship clamp handles this).
@ ----------------------------------------------------------------------------
draw_square5:
        push    {r4, r5, r6, r7, r8, lr}
        sub     r4, r1, #2              @ y = cy - 2
        sub     r5, r0, #2              @ x_start = cx - 2
        mov     r6, #5                  @ rows remaining
        ldr     r7, =VRAM
sq5_row:
        mov     r8, r5                  @ x = x_start
        mov     r0, #5                  @ pixels in row
sq5_col:
        mov     r1, #240
        mul     r3, r4, r1              @ y * 240
        add     r3, r3, r8              @ + x
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
@ draw_disc9(cx, cy, color)
@   r0 = cx, r1 = cy, r2 = color
@   Filled disc of radius 4 (diameter 9). Brute force: walk a 9x9 box and
@   test dx*dx + dy*dy <= 16. Caller must pick a centre with margin >= 4.
@ ----------------------------------------------------------------------------
draw_disc9:
        push    {r4, r5, r6, r7, r8, r9, r10, lr}
        mov     r3, r0                  @ save cx
        mov     r4, r1                  @ save cy
        mov     r5, r2                  @ save color
        ldr     r6, =VRAM
        mov     r7, #0                  @ dy_idx 0..8 (dy = idx - 4)
disc_y:
        sub     r8, r7, #4              @ dy
        mul     r9, r8, r8              @ dy*dy
        mov     r10, #0                 @ dx_idx 0..8
disc_x:
        sub     r0, r10, #4             @ dx
        mul     r1, r0, r0              @ dx*dx
        add     r1, r1, r9              @ dx*dx + dy*dy
        cmp     r1, #16
        bgt     disc_skip
        @ plot at (cx + dx, cy + dy)
        add     r2, r3, r0              @ px = cx + dx
        add     r1, r4, r8              @ py = cy + dy
        mov     r0, #240
        mul     r0, r1, r0              @ py * 240
        add     r0, r0, r2              @ + px
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
