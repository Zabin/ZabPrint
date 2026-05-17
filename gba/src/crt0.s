@ ============================================================================
@ crt0.s -- ROM entry point.
@
@ The cart packer reserves 0x000..0x0BF for the cartridge header. The entry-
@ point branch at 0x000 is hand-encoded in build.py to jump here. So this
@ file's first label `_start` is at ROM offset 0x0C0 (= 0x080000C0 absolute).
@
@ For this milestone the boot routine is intentionally minimal: switch to
@ Mode 3, paint a striped splash into VRAM so the user gets visual proof in
@ mGBA that the ROM boots, then idle. Real gameplay (input, physics, OAM
@ build) will be added on top in subsequent layers.
@ ============================================================================

        .arm
        .align 2

_start:
        @ User-mode stack at the canonical top of IWRAM. The BIOS leaves SP
        @ uninitialised for our mode on entry; we set it here before any
        @ push/pop happens elsewhere in the codebase.
        ldr     sp, =0x03007F00

        @ REG_DISPCNT = 0x0403  -> mode 3 (240x160 16bpp) + BG2 enable
        ldr     r0, =0x04000000
        ldr     r1, =0x0403
        str     r1, [r0]

        @ Paint VRAM with horizontal stripes so the boot is visually obvious.
        @ Row count in r3, pixel-in-row counter in r4, base pointer in r0,
        @ active colour in r1. Two BGR555 colours alternate every 16 rows.
        ldr     r0, =0x06000000         @ VRAM
        mov     r3, #0                  @ row index

row_loop:
        @ Pick colour based on bit 4 of the row index.
        tst     r3, #16
        ldreq   r1, =0x4210             @ slate
        ldrne   r1, =0x6B5A             @ pale blue

        mov     r4, #240                @ pixels per row
pix_loop:
        strh    r1, [r0]
        add     r0, r0, #2
        subs    r4, r4, #1
        bne     pix_loop

        add     r3, r3, #1
        cmp     r3, #160
        blt     row_loop

idle:
        b       idle

        .ltorg
