@ ============================================================================
@ crt0.s -- ROM entry + orbital game frame loop (Mode 3 bitmap).
@
@ Mechanics:
@   * Single primary at the screen centre, mass parameter MU.
@   * Player + 3 targets orbit under Newtonian gravity (cowell_step in
@     physics.s, semi-implicit Euler, dt = 1 frame).
@   * D-pad applies single-impulse burns (in-track / radial) costed against a
@     finite delta-V tank. Element kernel converts state->{a,e,omega,nu} for
@     the HUD and mission-completion checks.
@   * Mission state machine cycles through five doctrinal objectives
@     (DENY, DGRD, DSRP, DSTR, DECV). DENY + DSRP have a 50-orbit fail timer.
@   * Two weapons: grapple (A) tows targets to a graveyard radius; DEW (B)
@     hitscan beam along the velocity vector. Destroy mission spawns persistent
@     debris that drains DV + score on contact.
@   * Two reference frames toggled by SELECT: ECI (planet centred) and RIC
@     (target centred, axes aligned to its radial / in-track frame).
@   * Time-warp at 1x / 10x / 100x via R; plane change via L (costs DV).
@   * Predicted orbit paths -- 64 substep forward integration cached per body,
@     drawn as dashed dim pixels. Recomputed only when state changes.
@
@ Art:
@   * Procedural starfield (32 LCG stars, stable seed) + banded planet.
@   * Bodies as 3x3 squares (player white; targets red / green / cyan).
@   * 4x6 pixel font for HUD labels (DV / a / e / Ta / Te / WRP / MIS /
@     VIEW / PLN / LAP / SCORE) + _draw_dec for numeric readouts.
@
@ State at IWRAM 0x03000000 (~600 words zero-initialised; see "STATE block"
@ section below for the full equate table). Keep memory.md in sync.
@ ============================================================================

        .arm
        .align 4

@ ---- MMIO -----------------------------------------------------------------
        .equ DISPCNT,     0x04000000
        .equ VCOUNT,      0x04000006
        .equ KEYINPUT,    0x04000130
        .equ VRAM,        0x06000000

@ ---- STATE block (IWRAM @ 0x03000000) -------------------------------------
        .equ STATE,       0x03000000
        .equ S_PLAYER,    0x00
        .equ S_PREV,      0x10
        .equ S_SCORE,     0x14
        .equ S_FRAME,     0x18
        .equ S_SHIP_DV,   0x1C
        .equ S_T0,        0x20
        .equ S_T1,        0x30
        .equ S_T2,        0x40
        .equ S_PLAYER_EL, 0x50          @ player elements  { a, e, omega, nu } Q16
        .equ S_TARGET_EL, 0x60          @ target 0 elements (cached for HUD)
        .equ S_WARP,      0x70          @ time-warp substep count (1, 10, 100)
        .equ S_VIEW_MODE, 0x74          @ 0 = ECI, 1 = RIC (centred on target 0)
        .equ S_RIC_TX,    0x78          @ target ECI x_q16 cached for transform
        .equ S_RIC_TY,    0x7C
        .equ S_RIC_RX,    0x80          @ R-hat x in primary-centred Q16
        .equ S_RIC_RY,    0x84
        .equ S_RIC_IX,    0x88          @ I-hat x
        .equ S_RIC_IY,    0x8C
        .equ S_MISSION_ID,        0x90  @ 0=Deny 1=Degrade 2=Disrupt 3=Destroy 4=Deceive
        .equ S_ORBIT_COUNT,       0x94  @ orbits since current mission started (reset on cycle)
        .equ S_MISSION_TARGET,    0x98  @ index into targets[3]
        .equ S_HOLD_TIMERS,       0x9C  @ 3 words: per-target hold-at-risk frame counters
        .equ S_DEW_COOLDOWN,      0xA8
        .equ S_T_HEALTH,          0xAC  @ 3 words: per-target health for DEW (3 -> 0)
        .equ S_PLAYER_PLANE,      0xB8
        .equ S_T_PLANE,           0xBC  @ 3 words: per-target plane flag (0 or 1)
        .equ S_GRAPPLE_TARGET,    0xC8  @ -1 = none, else target idx 0..2
        .equ S_GRAPPLE_TIMER,     0xCC  @ frames the current grapple has been held
        .equ GRAPPLE_RANGE_SQ,    4096  @ 64 px squared
        .equ GRAPPLE_FULL,        120   @ frames to complete tow-to-graveyard
        .equ S_DEBRIS,            0xD0  @ 4 slots * 8 words = 128 bytes
        .equ DEBRIS_SLOT_SZ,      32    @ bytes per slot: x,y,vx,vy,alive,age,pad,pad
        .equ DEBRIS_N,            4     @ number of slots
        .equ DEBRIS_MAX_AGE,      600   @ ~10 s at 60 fps (1x warp)
        .equ DEBRIS_HIT_SQ,       9     @ player collision radius squared (3 px)
        .equ S_SENSOR_DIR,        0x150 @ cached fx_atan2(vy, vx) for the cone
        .equ SENSOR_HALF_ANGLE,   0x2000 @ 45° in brad: ±45° = 90° total cone
        .equ S_PATH_DIRTY,        0x154 @ low 4 bits = per-body dirty flag
        .equ S_PREV_NU,           0x158 @ prev frame's player true-anomaly (Q16 brads) for orbit-wrap detect
        .equ S_PATH_PLAYER,       0x160 @ 256 points * 8 B = 2048 B (full-orbit dashed line)
        .equ S_PATH_T0,           0x960
        .equ S_PATH_T1,           0x1160
        .equ S_PATH_T2,           0x1960
        .equ PATH_N_POINTS,       256
        .equ PATH_BYTES,          2048 @ 256 * 8 -- enough substeps to close
                                       @ a full orbit at default radius (T ~ 240 frames).
        .equ PATH_DRAW_STRIDE,    8    @ visible-dot stride: 32 dots per orbit
                                       @ (256 / 8) keeps render cost flat vs old N=64.
        .equ PLANE_CHANGE_DV,     0x00190000   @ 25 (Q16) cost to flip planes
        .equ HOLD_DIST_SQ,        144   @ 12 px squared
        .equ HOLD_THRESH,         90    @ frames to trigger Deny completion
        .equ ORBIT_LIMIT,         50    @ DENY + DSRP missions fail at this many elapsed orbits
        .equ DEW_RANGE_SQ,        4900  @ 70 px squared
        .equ DEW_CD_FRAMES,       30
        .equ DEW_INIT_HEALTH,     3
        .equ DV_REFILL_Q16,       0x00190000   @ 25 (Q16) refill on mission complete
        .equ RIC_ZOOM_SHIFT, 14         @ Q16 ΔR/ΔI -> screen px:  >> (16-2) = ×4 zoom

        @ Tuning: planet at screen centre, MU sized for ~4-second orbits at
        @ radius 40 pixels. These match the defaults in physics.s.
        .equ PLANET_X,    120
        .equ PLANET_Y,    80
        .equ PLANET_X_Q16, 0x00780000
        .equ PLANET_Y_Q16, 0x00500000
        .equ MU_Q16,       0x001E0000

        .equ THRUST,      0x2000          @ legacy ΔV-free thrust (kept for now)
        .equ BURN_DV,     0x1000          @ 0.0625 in Q16 (1/16 px/frame); subtle nudges
        .equ DV_MAX,      0x00640000      @ 100 in Q16 -- starting ΔV tank
        .equ THRUST_COST, 0x00010000      @ 1 unit per impulse (Q16)
        .equ MIN_V_FOR_PROGRADE, 0x100    @ avoid div-by-near-zero when |v| ~ 0

_start:
        ldr     sp, =0x03007F00
        ldr     r0, =DISPCNT
        ldr     r1, =0x0403
        str     r1, [r0]

        @ Zero the control-state region (0..0x160, 88 words). The 8 KiB
        @ path-cache region above 0x160 deliberately is NOT pre-zeroed:
        @ dirty=0xF below causes _refresh_paths on frame 1 to overwrite
        @ every byte of it before _draw_path consumes the cache. Keeping
        @ this init short matters because every test in test_rom_execute.py
        @ runs the ROM for a budgeted number of cycles.
        ldr     r0, =STATE
        mov     r1, #0
        mov     r2, #100
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

        @ Initialise ship_dv = DV_MAX, warp = 1, target healths = DEW_INIT_HEALTH.
        ldr     r0, =STATE
        ldr     r1, =DV_MAX
        str     r1, [r0, #S_SHIP_DV]
        mov     r1, #1
        str     r1, [r0, #S_WARP]
        mov     r1, #DEW_INIT_HEALTH
        str     r1, [r0, #(S_T_HEALTH + 0)]
        str     r1, [r0, #(S_T_HEALTH + 4)]
        str     r1, [r0, #(S_T_HEALTH + 8)]
        @ Initial planes: t0 = 0, t1 = 1, t2 = 0  (a second plane to exercise the cost)
        mov     r1, #0
        str     r1, [r0, #(S_T_PLANE + 0)]
        mov     r1, #1
        str     r1, [r0, #(S_T_PLANE + 4)]
        mov     r1, #0
        str     r1, [r0, #(S_T_PLANE + 8)]
        @ Grapple slot starts disengaged (-1).
        mvn     r1, #0
        str     r1, [r0, #S_GRAPPLE_TARGET]
        @ Mark all 4 paths dirty so the first frame recomputes them.
        mov     r1, #0xF
        str     r1, [r0, #S_PATH_DIRTY]

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
        bic     r1, r0, r1                      @ r1 = newly pressed (current AND NOT prev)

        @ -------- D-pad orbital burns (edge-detected, ΔV-costed) -------
        @ Up    = prograde,   Down  = retrograde   (along  v unit vector)
        @ Right = radial-out, Left  = radial-in    (along  r unit vector)
        @ Each impulse adds BURN_DV * unit-vector to velocity and costs
        @ THRUST_COST from ship_dv. Skip everything if no D-pad press or
        @ DV exhausted.
        mov     r4, r1                          @ always cache newly-pressed (used by warp cycle too)
        tst     r4, #0xF0
        beq     burns_done
        ldr     r2, [r12, #S_SHIP_DV]
        cmp     r2, #0
        ble     burns_done

        @ Compute |v|.
        ldr     r0, [r12, #(S_PLAYER + 8)]
        mov     r1, r0
        bl      fx_mul_q16
        mov     r5, r0
        ldr     r12, =STATE
        ldr     r0, [r12, #(S_PLAYER + 12)]
        mov     r1, r0
        bl      fx_mul_q16
        add     r5, r5, r0
        mov     r0, r5
        bl      fx_sqrt_q16
        mov     r5, r0                          @ r5 = |v|

        @ Compute rx, ry, |r| (primary-centred).
        ldr     r12, =STATE
        ldr     r0, [r12, #S_PLAYER]
        ldr     r1, =PLANET_X_Q16
        sub     r6, r0, r1                      @ r6 = rx
        ldr     r0, [r12, #(S_PLAYER + 4)]
        ldr     r1, =PLANET_Y_Q16
        sub     r7, r0, r1                      @ r7 = ry
        mov     r0, r6
        mov     r1, r6
        bl      fx_mul_q16
        mov     r8, r0
        mov     r0, r7
        mov     r1, r7
        bl      fx_mul_q16
        add     r8, r8, r0
        mov     r0, r8
        bl      fx_sqrt_q16
        mov     r8, r0                          @ r8 = |r|

        @ Direction mapping (user-locked):
        @   Right (bit 4) = +in-track   (~prograde for near-circular orbits)
        @   Left  (bit 5) = -in-track   (~retrograde)
        @   Up    (bit 6) = +radial     (away from primary)
        @   Down  (bit 7) = -radial     (toward primary)

        @ ---- Right: +in-track  (impulse = +BURN_DV * (vx, vy)/|v|)
        tst     r4, #0x10
        beq     skip_right
        cmp     r5, #MIN_V_FOR_PROGRADE
        ble     skip_right
        ldr     r12, =STATE
        ldr     r0, [r12, #(S_PLAYER + 8)]
        mov     r1, r5
        bl      fx_div_q16                      @ vx/|v|
        ldr     r1, =BURN_DV
        bl      fx_mul_q16                      @ dvx
        mov     r9, r0
        ldr     r12, =STATE
        ldr     r0, [r12, #(S_PLAYER + 12)]
        mov     r1, r5
        bl      fx_div_q16
        ldr     r1, =BURN_DV
        bl      fx_mul_q16                      @ dvy
        mov     r1, r0
        mov     r0, r9
        bl      _apply_burn
skip_right:

        @ ---- Left: -in-track
        tst     r4, #0x20
        beq     skip_left
        cmp     r5, #MIN_V_FOR_PROGRADE
        ble     skip_left
        ldr     r12, =STATE
        ldr     r0, [r12, #(S_PLAYER + 8)]
        mov     r1, r5
        bl      fx_div_q16
        ldr     r1, =BURN_DV
        bl      fx_mul_q16
        rsb     r9, r0, #0                      @ -dvx
        ldr     r12, =STATE
        ldr     r0, [r12, #(S_PLAYER + 12)]
        mov     r1, r5
        bl      fx_div_q16
        ldr     r1, =BURN_DV
        bl      fx_mul_q16
        rsb     r1, r0, #0                      @ -dvy
        mov     r0, r9
        bl      _apply_burn
skip_left:

        @ ---- Up: +radial-out  (impulse = +BURN_DV * (rx, ry)/|r|)
        tst     r4, #0x40
        beq     skip_up
        mov     r0, r6
        mov     r1, r8
        bl      fx_div_q16
        ldr     r1, =BURN_DV
        bl      fx_mul_q16
        mov     r9, r0
        mov     r0, r7
        mov     r1, r8
        bl      fx_div_q16
        ldr     r1, =BURN_DV
        bl      fx_mul_q16
        mov     r1, r0
        mov     r0, r9
        bl      _apply_burn
skip_up:

        @ ---- Down: -radial (toward primary)
        tst     r4, #0x80
        beq     skip_down
        mov     r0, r6
        mov     r1, r8
        bl      fx_div_q16
        ldr     r1, =BURN_DV
        bl      fx_mul_q16
        rsb     r9, r0, #0
        mov     r0, r7
        mov     r1, r8
        bl      fx_div_q16
        ldr     r1, =BURN_DV
        bl      fx_mul_q16
        rsb     r1, r0, #0
        mov     r0, r9
        bl      _apply_burn
skip_down:

burns_done:

        @ -------- R / L: cycle time warp 1 / 10 / 100 -----------------
        tst     r4, #0x100                      @ R
        beq     no_warp_r
        ldr     r12, =STATE
        ldr     r5, [r12, #S_WARP]
        cmp     r5, #1
        moveq   r5, #10
        beq     warp_store_r
        cmp     r5, #10
        moveq   r5, #100
        beq     warp_store_r
        mov     r5, #1
warp_store_r:
        str     r5, [r12, #S_WARP]
no_warp_r:
        tst     r4, #0x200                      @ L
        beq     no_warp_l
        ldr     r12, =STATE
        ldr     r5, [r12, #S_WARP]
        cmp     r5, #100
        moveq   r5, #10
        beq     warp_store_l
        cmp     r5, #10
        moveq   r5, #1
        beq     warp_store_l
        mov     r5, #100
warp_store_l:
        str     r5, [r12, #S_WARP]
no_warp_l:

        @ -------- SELECT (bit 2): toggle ECI <-> RIC view -------------
        tst     r4, #0x04
        beq     no_view_toggle
        ldr     r12, =STATE
        ldr     r5, [r12, #S_VIEW_MODE]
        eor     r5, r5, #1
        str     r5, [r12, #S_VIEW_MODE]
no_view_toggle:

        @ -------- START (bit 3): plane change, costs PLANE_CHANGE_DV ----
        tst     r4, #0x08
        beq     no_plane_change
        ldr     r12, =STATE
        ldr     r5, [r12, #S_SHIP_DV]
        ldr     r6, =PLANE_CHANGE_DV
        cmp     r5, r6
        blt     no_plane_change
        sub     r5, r5, r6
        str     r5, [r12, #S_SHIP_DV]
        ldr     r5, [r12, #S_PLAYER_PLANE]
        eor     r5, r5, #1
        str     r5, [r12, #S_PLAYER_PLANE]
no_plane_change:

        @ -------- DEW (B button, edge-detected, cooldown-gated) -------
        @ Decrement cooldown first; even if B isn't pressed.
        ldr     r12, =STATE
        ldr     r5, [r12, #S_DEW_COOLDOWN]
        cmp     r5, #0
        ble     dew_cd_done
        sub     r5, r5, #1
        str     r5, [r12, #S_DEW_COOLDOWN]
dew_cd_done:
        @ Fire if B newly-pressed AND cooldown clear.
        tst     r4, #0x02
        beq     dew_done
        ldr     r5, [r12, #S_DEW_COOLDOWN]
        cmp     r5, #0
        bgt     dew_done

        @ Find nearest target within DEW_RANGE_SQ.
        ldr     r0, [r12, #S_PLAYER]
        ldr     r1, [r12, #(S_PLAYER + 4)]
        mov     r5, r0, asr #16                 @ player int x
        mov     r6, r1, asr #16                 @ player int y
        mvn     r0, #0                          @ best target idx (-1 = none)
        ldr     r1, =DEW_RANGE_SQ
        add     r1, r1, #1                      @ best dist² (just outside range)
        mov     r2, #0                          @ iter i
dew_scan_loop:
        @ Skip if target is on a different plane than player.
        add     r3, r12, r2, lsl #2
        ldr     r3, [r3, #S_T_PLANE]
        ldr     r7, [r12, #S_PLAYER_PLANE]
        cmp     r3, r7
        bne     dew_scan_next
        mov     r3, r2, lsl #4
        add     r3, r3, #S_T0
        add     r7, r12, r3
        ldr     r3, [r7]
        ldr     r8, [r7, #4]
        mov     r3, r3, asr #16
        mov     r8, r8, asr #16
        sub     r3, r3, r5                      @ dx
        sub     r8, r8, r6                      @ dy
        mul     r3, r3, r3
        mul     r8, r8, r8
        add     r3, r3, r8
        cmp     r3, r1
        bge     dew_scan_next
        mov     r0, r2                          @ best idx
        mov     r1, r3                          @ best dist²
dew_scan_next:
        add     r2, r2, #1
        cmp     r2, #3
        blt     dew_scan_loop

        cmp     r0, #0
        blt     dew_done                        @ no target in range

        @ Hit: health[idx] -= 1
        ldr     r12, =STATE
        add     r2, r12, r0, lsl #2             @ &health[idx]
        ldr     r3, [r2, #S_T_HEALTH]
        sub     r3, r3, #1
        str     r3, [r2, #S_T_HEALTH]
        @ Cooldown
        mov     r5, #DEW_CD_FRAMES
        str     r5, [r12, #S_DEW_COOLDOWN]

        @ If health hits 0, respawn target + maybe advance Degrade mission.
        cmp     r3, #0
        bgt     dew_done

        @ Respawn from init_orbits[1 + idx]
        mov     r2, r0                          @ stash idx
        add     r1, r2, #1                      @ body index (1, 2, 3)
        ldr     r0, =init_orbits
        add     r0, r0, r1, lsl #4
        mov     r1, r12
        add     r1, r1, r2, lsl #4
        add     r1, r1, #S_T0
        push    {r2, lr}
        bl      _copy_orbit_body
        pop     {r2, lr}
        @ Reset that target's health to DEW_INIT_HEALTH
        ldr     r12, =STATE
        add     r3, r12, r2, lsl #2
        mov     r5, #DEW_INIT_HEALTH
        str     r5, [r3, #S_T_HEALTH]
        @ Also clear that target's hold-timer
        mov     r5, #0
        str     r5, [r3, #S_HOLD_TIMERS]
        @ Mark that target's path dirty: bit (1 << (idx + 1)).
        cmp     r2, #0
        moveq   r5, #2
        cmp     r2, #1
        moveq   r5, #4
        cmp     r2, #2
        moveq   r5, #8
        ldr     r3, [r12, #S_PATH_DIRTY]
        orr     r3, r3, r5
        str     r3, [r12, #S_PATH_DIRTY]

        @ Mission Degrade completion if matched
        ldr     r0, [r12, #S_MISSION_ID]
        cmp     r0, #1                          @ Degrade
        bne     dew_done
        ldr     r0, [r12, #S_MISSION_TARGET]
        cmp     r0, r2
        bne     dew_done
        bl      _advance_mission
dew_done:

        @ -------- Grapple (A held; first-frame edge acquires, sustained drags)
        @ State machine on S_GRAPPLE_TARGET (-1 = idle, else target idx).
        @ r0 was clobbered by the DEW scan; current inverted-keys mask is
        @ still in S_PREV (we stored it there at input time).
        ldr     r12, =STATE
        ldr     r0, [r12, #S_PREV]
        tst     r0, #0x01                       @ A currently held?
        beq     grapple_release
        ldr     r5, [r12, #S_GRAPPLE_TARGET]
        cmp     r5, #0
        bge     grapple_drag                    @ already locked

        @ Acquire: scan same-plane targets within GRAPPLE_RANGE_SQ.
        ldr     r0, [r12, #S_PLAYER]
        ldr     r1, [r12, #(S_PLAYER + 4)]
        mov     r5, r0, asr #16                 @ player int x
        mov     r6, r1, asr #16                 @ player int y
        mvn     r0, #0                          @ best idx = -1
        ldr     r1, =GRAPPLE_RANGE_SQ
        add     r1, r1, #1                      @ best dist² (sentinel)
        mov     r2, #0
grapple_scan_loop:
        add     r3, r12, r2, lsl #2
        ldr     r3, [r3, #S_T_PLANE]
        ldr     r7, [r12, #S_PLAYER_PLANE]
        cmp     r3, r7
        bne     grapple_scan_next
        mov     r3, r2, lsl #4
        add     r3, r3, #S_T0
        add     r7, r12, r3
        ldr     r3, [r7]
        ldr     r8, [r7, #4]
        mov     r3, r3, asr #16
        mov     r8, r8, asr #16
        sub     r3, r3, r5
        sub     r8, r8, r6
        mul     r3, r3, r3
        mul     r8, r8, r8
        add     r3, r3, r8
        cmp     r3, r1
        bge     grapple_scan_next
        mov     r0, r2
        mov     r1, r3
grapple_scan_next:
        add     r2, r2, #1
        cmp     r2, #3
        blt     grapple_scan_loop

        cmp     r0, #0
        blt     grapple_done                    @ nothing in range
        str     r0, [r12, #S_GRAPPLE_TARGET]
        mov     r1, #0
        str     r1, [r12, #S_GRAPPLE_TIMER]
        b       grapple_done

grapple_drag:
        @ r5 = grapple_target idx. Drag target velocity toward player:
        @   vt += (vp - vt) >> 3
        @ Then grapple_timer++; if >= GRAPPLE_FULL, complete.
        mov     r6, r5, lsl #4
        add     r6, r6, #S_T0
        add     r6, r12, r6                     @ &target[idx]
        ldr     r0, [r12, #(S_PLAYER + 8)]
        ldr     r1, [r6, #8]
        sub     r2, r0, r1
        add     r1, r1, r2, asr #3
        str     r1, [r6, #8]
        ldr     r0, [r12, #(S_PLAYER + 12)]
        ldr     r1, [r6, #12]
        sub     r2, r0, r1
        add     r1, r1, r2, asr #3
        str     r1, [r6, #12]

        ldr     r0, [r12, #S_GRAPPLE_TIMER]
        add     r0, r0, #1
        str     r0, [r12, #S_GRAPPLE_TIMER]
        cmp     r0, #GRAPPLE_FULL
        blt     grapple_done

        @ Tow-to-graveyard complete: respawn target from init table, +3 score,
        @ Destroy mission advance if matched, debris will spawn via
        @ _spawn_debris (added in 8c.11).
        mov     r2, r5                          @ stash idx
        add     r1, r5, #1
        ldr     r0, =init_orbits
        add     r0, r0, r1, lsl #4
        mov     r1, r12
        add     r1, r1, r2, lsl #4
        add     r1, r1, #S_T0
        push    {r2, lr}
        bl      _copy_orbit_body
        pop     {r2, lr}
        ldr     r12, =STATE
        @ Reset target health + hold timer.
        add     r3, r12, r2, lsl #2
        mov     r1, #DEW_INIT_HEALTH
        str     r1, [r3, #S_T_HEALTH]
        mov     r1, #0
        str     r1, [r3, #S_HOLD_TIMERS]
        @ Mark that target's path dirty.
        cmp     r2, #0
        moveq   r1, #2
        cmp     r2, #1
        moveq   r1, #4
        cmp     r2, #2
        moveq   r1, #8
        ldr     r3, [r12, #S_PATH_DIRTY]
        orr     r3, r3, r1
        str     r3, [r12, #S_PATH_DIRTY]
        @ Score += 3.
        ldr     r1, [r12, #S_SCORE]
        add     r1, r1, #3
        str     r1, [r12, #S_SCORE]
        @ Destroy mission (3) on matched target -> hard-kill: spawn debris,
        @ advance the mission. Any other mission state -> soft kill, no debris.
        ldr     r0, [r12, #S_MISSION_ID]
        cmp     r0, #3
        bne     grapple_clear
        ldr     r0, [r12, #S_MISSION_TARGET]
        cmp     r0, r2
        bne     grapple_clear
        bl      _spawn_debris_at_player
        ldr     r12, =STATE
        bl      _advance_mission
        ldr     r12, =STATE
grapple_clear:
        mvn     r0, #0
        str     r0, [r12, #S_GRAPPLE_TARGET]
        mov     r0, #0
        str     r0, [r12, #S_GRAPPLE_TIMER]
        b       grapple_done

grapple_release:
        @ A not held -> drop any active grapple, reset timer.
        mvn     r1, #0
        str     r1, [r12, #S_GRAPPLE_TARGET]
        mov     r1, #0
        str     r1, [r12, #S_GRAPPLE_TIMER]
grapple_done:

        @ -------- Substep loop: cowell_step on each body, WARP times --
        ldr     r12, =STATE
        ldr     r5, [r12, #S_WARP]
warp_substep_loop:
        cmp     r5, #0
        ble     warp_substep_done
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
        sub     r5, r5, #1
        b       warp_substep_loop
warp_substep_done:

        @ -------- debris: cowell_step each alive slot + aging + collision ---
        bl      _debris_tick

        @ -------- orbital elements: cache for HUD ---------------------
        ldr     r12, =STATE
        mov     r0, r12                 @ &player == STATE
        add     r1, r12, #S_PLAYER_EL
        bl      _compute_elem_for_body
        ldr     r12, =STATE
        add     r0, r12, #S_T0
        add     r1, r12, #S_TARGET_EL
        bl      _compute_elem_for_body

        @ -------- orbit detection (true-anomaly wrap = periapsis pass) -
        @ cur_nu in S_PLAYER_EL+0x0C. Detect wrap from >=270° to <90° as
        @ a completed orbit. Always update S_PREV_NU. On wrap, increment
        @ S_ORBIT_COUNT and fail the mission if DENY/DSRP have hit the
        @ ORBIT_LIMIT countdown.
        ldr     r4, =STATE
        ldr     r0, [r4, #(S_PLAYER_EL + 12)]   @ cur_nu (Q16 brad)
        ldr     r1, [r4, #S_PREV_NU]            @ prev_nu
        str     r0, [r4, #S_PREV_NU]            @ update cache regardless
        ldr     r2, =0xC000                     @ 270° threshold
        cmp     r1, r2
        blt     _orbit_no_wrap
        ldr     r2, =0x4000                     @ 90° threshold
        cmp     r0, r2
        bge     _orbit_no_wrap
        @ Periapsis crossing detected.
        ldr     r0, [r4, #S_ORBIT_COUNT]
        add     r0, r0, #1
        str     r0, [r4, #S_ORBIT_COUNT]
        bl      _check_orbit_limit
_orbit_no_wrap:

        @ -------- holding-at-risk per target --------------------------
        @ For each target i:
        @   distance² (integer px) = (dx² + dy²) using truncated positions
        @   if d² <= HOLD_DIST_SQ: hold_timer[i]++ else hold_timer[i] = 0
        @   if hold_timer[i] >= HOLD_THRESH and mission_id == 0 (Deny) and
        @     mission_target == i: advance mission, refill ΔV, etc.
        ldr     r12, =STATE
        ldr     r0, [r12, #S_PLAYER]
        ldr     r1, [r12, #(S_PLAYER + 4)]
        mov     r4, r0, asr #16
        mov     r5, r1, asr #16
        mov     r6, #0
hold_check_loop:
        @ Skip cross-plane targets (no hold accumulates).
        add     r7, r12, r6, lsl #2
        ldr     r7, [r7, #S_T_PLANE]
        ldr     r0, [r12, #S_PLAYER_PLANE]
        cmp     r7, r0
        bne     hold_zero_skip
        mov     r7, r6, lsl #4
        add     r7, r7, #S_T0
        add     r8, r12, r7
        ldr     r0, [r8]
        ldr     r1, [r8, #4]
        mov     r0, r0, asr #16
        mov     r1, r1, asr #16
        sub     r0, r4, r0
        sub     r1, r5, r1
        mul     r0, r0, r0
        mul     r1, r1, r1
        add     r0, r0, r1

        @ Per-target hold-timer slot at S_HOLD_TIMERS + i*4
        add     r2, r12, r6, lsl #2
        ldr     r3, [r2, #S_HOLD_TIMERS]

        cmp     r0, #HOLD_DIST_SQ
        bgt     hold_reset
        add     r3, r3, #1
        b       hold_store
hold_reset:
        mov     r3, #0
hold_store:
        str     r3, [r2, #S_HOLD_TIMERS]

        @ Mission completion check (Deny only here).
        cmp     r3, #HOLD_THRESH
        blt     hold_skip_mission
        ldr     r1, [r12, #S_MISSION_ID]
        cmp     r1, #0
        bne     hold_skip_mission
        ldr     r1, [r12, #S_MISSION_TARGET]
        cmp     r1, r6
        bne     hold_skip_mission
        push    {r4, r5, r6, r12, lr}
        bl      _advance_mission
        pop     {r4, r5, r6, r12, lr}
hold_skip_mission:
        b       hold_advance
hold_zero_skip:
        @ Cross-plane: zero this target's hold timer.
        add     r0, r12, r6, lsl #2
        mov     r1, #0
        str     r1, [r0, #S_HOLD_TIMERS]
hold_advance:
        add     r6, r6, #1
        cmp     r6, #3
        blt     hold_check_loop

        @ -------- RIC frame params (always computed; cheap, ~150 cycles) -
        bl      _compute_ric_params

        @ -------- cache sensor_dir = atan2(player_vy, player_vx) -----
        ldr     r12, =STATE
        ldr     r0, [r12, #(S_PLAYER + 12)]
        ldr     r1, [r12, #(S_PLAYER + 8)]
        bl      fx_atan2
        ldr     r12, =STATE
        str     r0, [r12, #S_SENSOR_DIR]

        @ -------- clear VRAM ------------------------------------------
        @ Use stmia with 8 registers per iter (16 pixels per iter) so the
        @ clear fits inside VBlank (~83K cycles). The old single-str loop
        @ ran past VBlank into VDraw, causing the LCD beam to read a
        @ half-cleared framebuffer -> visible flicker.
        ldr     r0, =VRAM
        ldr     r1, =0x0421
        orr     r1, r1, r1, lsl #16
        mov     r2, r1
        mov     r3, r1
        mov     r4, r1
        mov     r5, r1
        mov     r6, r1
        mov     r7, r1
        mov     r8, r1
        ldr     r9, =2400                       @ 19200 words / 8 words-per-iter
clear_loop:
        stmia   r0!, {r1-r8}
        subs    r9, r9, #1
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

        @ -------- orbit-path prediction (recompute dirty, then draw all)
        bl      _refresh_paths
        ldr     r0, =(STATE + S_PATH_PLAYER)
        ldr     r1, =0x4310                     @ dim cyan
        bl      _draw_path
        ldr     r0, =(STATE + S_PATH_T0)
        ldr     r1, =0x0010                     @ dim red
        bl      _draw_path
        ldr     r0, =(STATE + S_PATH_T1)
        ldr     r1, =0x0200                     @ dim green
        bl      _draw_path
        ldr     r0, =(STATE + S_PATH_T2)
        ldr     r1, =0x4210                     @ dim cyan-grey
        bl      _draw_path

        @ -------- planet: three concentric bands -----------------------
        @ Transform the fixed primary position through the active view.
        ldr     r0, =PLANET_X_Q16
        ldr     r1, =PLANET_Y_Q16
        bl      _world_to_screen
        mov     r4, r0                          @ planet screen x
        mov     r5, r1                          @ planet screen y
        @ Outer rim (radius 14), light tan
        mov     r0, r4
        mov     r1, r5
        mov     r2, #14
        ldr     r3, =0x3AFB                     @ pale tan BGR555
        bl      draw_disc
        @ Mid band (radius 10), warmer
        mov     r0, r4
        mov     r1, r5
        mov     r2, #10
        ldr     r3, =0x126F                     @ rust orange
        bl      draw_disc
        @ Core (radius 5), deep
        mov     r0, r4
        mov     r1, r5
        mov     r2, #5
        ldr     r3, =0x08AC                     @ dark amber
        bl      draw_disc

        @ -------- targets (cone-filtered): full sprite if inside cone,
        @          single grey pixel ("last known position") if outside.
        mov     r0, #0
        ldr     r1, =0x001F
        bl      _draw_target
        mov     r0, #1
        ldr     r1, =0x03E0
        bl      _draw_target
        mov     r0, #2
        ldr     r1, =0x7FE0
        bl      _draw_target

        @ -------- debris (grey pixels) -------------------------------
        bl      _draw_debris

        @ -------- player ship core + heading nose ---------------------
        ldr     r12, =STATE
        ldr     r0, [r12, #S_PLAYER]
        ldr     r1, [r12, #(S_PLAYER + 4)]
        bl      _world_to_screen
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

        @ ============ Labeled HUD (Layer 8e) ============================
        @ Layout (y top -> bottom):
        @   y=2   DV   bar       value
        @   y=10  a    bar       value
        @   y=18  e    bar       value
        @   y=26  Ta   bar       value
        @   y=34  Te   bar       value
        @   y=44  WRP n  MIS xxx  VIEW xxx  PLN n
        @   y=145 SCORE nnnn
        @
        @ Label x=2..11 (DV is 9 px), bar x=20..120 (max len 100),
        @ value x=125..139 (3 digits * 5 px wide).
        @ ----------------------------------------------------------------

        @ --- Row 1: DV
        ldr     r0, =str_dv
        mov     r1, #2
        mov     r2, #2
        ldr     r3, =0x7FFF                     @ white label
        bl      _draw_str
        ldr     r12, =STATE
        ldr     r0, [r12, #S_SHIP_DV]
        cmp     r0, #0
        movlt   r0, #0
        ldr     r2, =DV_MAX
        cmp     r0, r2
        movgt   r0, r2
        mov     r0, r0, asr #16                 @ DV in integer 0..100
        @ Length proportional to DV/100 * 100 = DV directly (capped 0..100)
        mov     r2, r0
        push    {r0}
        mov     r0, #20
        mov     r1, #4
        ldr     r3, =0x7FE0                     @ cyan bar
        bl      _draw_hbar
        pop     {r0}
        @ Numeric value
        mov     r1, #125
        mov     r2, #2
        ldr     r3, =0x7FFF
        bl      _draw_dec

        @ --- Row 2: a (player)
        ldr     r0, =str_a
        mov     r1, #2
        mov     r2, #10
        ldr     r3, =0x7FFF
        bl      _draw_str
        ldr     r12, =STATE
        ldr     r0, [r12, #S_PLAYER_EL]
        bl      _hud_a_len_clamped
        mov     r2, r0
        push    {r0}
        mov     r0, #20
        mov     r1, #12
        ldr     r3, =0x7FE0                     @ cyan
        bl      _draw_hbar
        pop     {r0}
        @ Print integer a (Q16 >> 16)
        ldr     r12, =STATE
        ldr     r0, [r12, #S_PLAYER_EL]
        cmp     r0, #0
        movlt   r0, #0
        mov     r0, r0, asr #16
        cmp     r0, #0xFF
        movgt   r0, #0xFF
        mov     r1, #125
        mov     r2, #10
        ldr     r3, =0x7FFF
        bl      _draw_dec

        @ --- Row 3: e (player)
        ldr     r0, =str_e
        mov     r1, #2
        mov     r2, #18
        ldr     r3, =0x7FFF
        bl      _draw_str
        ldr     r12, =STATE
        ldr     r0, [r12, #(S_PLAYER_EL + 4)]
        bl      _hud_e_len_clamped
        mov     r2, r0
        mov     r0, #20
        mov     r1, #20
        ldr     r3, =0x03FF                     @ yellow
        bl      _draw_hbar
        @ Print e as 2-digit percent: (e_q16 * 100) >> 16
        ldr     r12, =STATE
        ldr     r0, [r12, #(S_PLAYER_EL + 4)]
        cmp     r0, #0
        movlt   r0, #0
        mov     r1, #100
        mul     r0, r0, r1
        mov     r0, r0, asr #16
        cmp     r0, #0xFF
        movgt   r0, #0xFF
        mov     r1, #125
        mov     r2, #18
        ldr     r3, =0x7FFF
        bl      _draw_dec

        @ --- Row 4: Ta (target a)
        ldr     r0, =str_ta
        mov     r1, #2
        mov     r2, #26
        ldr     r3, =0x4310                     @ dim cyan
        bl      _draw_str
        ldr     r12, =STATE
        ldr     r0, [r12, #S_TARGET_EL]
        bl      _hud_a_len_clamped
        mov     r2, r0
        mov     r0, #20
        mov     r1, #28
        ldr     r3, =0x4310
        bl      _draw_hbar
        ldr     r12, =STATE
        ldr     r0, [r12, #S_TARGET_EL]
        cmp     r0, #0
        movlt   r0, #0
        mvn     r2, #0x80000000                 @ INT32_MAX hyperbolic sentinel
        cmp     r0, r2
        moveq   r0, #0xFF
        bne     _ta_inrange
        b       _ta_print
_ta_inrange:
        mov     r0, r0, asr #16
        cmp     r0, #0xFF
        movgt   r0, #0xFF
_ta_print:
        mov     r1, #125
        mov     r2, #26
        ldr     r3, =0x4310
        bl      _draw_dec

        @ --- Row 5: Te (target e)
        ldr     r0, =str_te
        mov     r1, #2
        mov     r2, #34
        ldr     r3, =0x023F                     @ dim yellow
        bl      _draw_str
        ldr     r12, =STATE
        ldr     r0, [r12, #(S_TARGET_EL + 4)]
        bl      _hud_e_len_clamped
        mov     r2, r0
        mov     r0, #20
        mov     r1, #36
        ldr     r3, =0x023F
        bl      _draw_hbar
        ldr     r12, =STATE
        ldr     r0, [r12, #(S_TARGET_EL + 4)]
        cmp     r0, #0
        movlt   r0, #0
        mov     r1, #100
        mul     r0, r0, r1
        mov     r0, r0, asr #16
        cmp     r0, #0xFF
        movgt   r0, #0xFF
        mov     r1, #125
        mov     r2, #34
        ldr     r3, =0x023F
        bl      _draw_dec

        @ --- Row 6: WRP n  MIS xxx  VIEW xxx  PLN n
        ldr     r0, =str_wrp
        mov     r1, #2
        mov     r2, #44
        ldr     r3, =0x7FFF
        bl      _draw_str
        ldr     r12, =STATE
        ldr     r0, [r12, #S_WARP]
        mov     r1, #22
        mov     r2, #44
        ldr     r3, =0x03FF                     @ yellow
        bl      _draw_dec

        ldr     r0, =str_mis
        mov     r1, #50
        mov     r2, #44
        ldr     r3, =0x7FFF
        bl      _draw_str
        ldr     r12, =STATE
        ldr     r4, [r12, #S_MISSION_ID]
        cmp     r4, #5
        movge   r4, #0
        ldr     r0, =mission_names
        add     r0, r0, r4, lsl #2
        ldr     r0, [r0]
        ldr     r1, =mission_color_table
        add     r1, r1, r4, lsl #2
        ldr     r3, [r1]
        mov     r1, #70
        mov     r2, #44
        bl      _draw_str

        ldr     r0, =str_view
        mov     r1, #100
        mov     r2, #44
        ldr     r3, =0x7FFF
        bl      _draw_str
        ldr     r12, =STATE
        ldr     r4, [r12, #S_VIEW_MODE]
        cmp     r4, #0
        ldreq   r0, =str_eci
        ldrne   r0, =str_ric
        ldreq   r3, =0x7FFF
        ldrne   r3, =0x03FF
        mov     r1, #125
        mov     r2, #44
        bl      _draw_str

        ldr     r0, =str_pln
        mov     r1, #150
        mov     r2, #44
        ldr     r3, =0x7FFF
        bl      _draw_str
        ldr     r12, =STATE
        ldr     r0, [r12, #S_PLAYER_PLANE]
        mov     r1, #168
        mov     r2, #44
        ldr     r3, =0x7FFF
        bl      _draw_dec

        @ --- LAP nnn  (elapsed orbits since mission start; yellow if
        @ DENY/DSRP is in the last 10 of ORBIT_LIMIT)
        ldr     r0, =str_lap
        mov     r1, #187
        mov     r2, #44
        ldr     r3, =0x7FFF
        bl      _draw_str
        ldr     r12, =STATE
        ldr     r0, [r12, #S_ORBIT_COUNT]
        @ Default colour = white; switch to yellow on DENY/DSRP danger zone.
        ldr     r3, =0x7FFF
        ldr     r4, [r12, #S_MISSION_ID]
        cmp     r4, #0                          @ DENY?
        beq     _lap_chk
        cmp     r4, #2                          @ DSRP?
        bne     _lap_draw
_lap_chk:
        rsb     r4, r0, #ORBIT_LIMIT            @ remaining = ORBIT_LIMIT - count
        cmp     r4, #10
        ldrle   r3, =0x03FF                     @ yellow (R+G)
_lap_draw:
        mov     r1, #204
        mov     r2, #44
        bl      _draw_dec

        @ --- Bottom row: SCORE nnnn (y=145)
        ldr     r0, =str_score
        mov     r1, #2
        mov     r2, #145
        ldr     r3, =0x03E0                     @ bright green
        bl      _draw_str
        ldr     r12, =STATE
        ldr     r0, [r12, #S_SCORE]
        cmp     r0, #0x1000
        movgt   r0, #0x1000
        mov     r1, #32
        mov     r2, #145
        ldr     r3, =0x03E0
        bl      _draw_dec4

        b       frame_loop

        @ Flush the literal pool here so the frame-loop `ldr =VALUE`s land
        @ within +/- 4 KB. Without this, helpers at the end of the file
        @ can't reach the final .ltorg.
        .ltorg

@ ----------------------------------------------------------------------------
@ _world_to_screen(body_x_q16, body_y_q16) -- ECI Q16 -> integer screen px.
@   r0, r1 in: body position in ECI Q16
@   r0, r1 out: integer screen pixel x, y
@ Behaviour depends on S_VIEW_MODE:
@   0 = ECI: straight Q16 -> int (asr #16); planet at screen centre.
@   1 = RIC: subtract target ECI pos, decompose along R-hat / I-hat, scale
@           by ZOOM = 4 (asr #14), centre at (120, 80).
@ Clobbers r0-r3, r12 in ECI mode; pushes/pops r4-r6 in RIC mode.
@ ----------------------------------------------------------------------------
_world_to_screen:
        ldr     r12, =STATE
        ldr     r2, [r12, #S_VIEW_MODE]
        cmp     r2, #0
        beq     _w2s_eci

        push    {r4, r5, r6, lr}
        @ delta_x = body_x_eci - target_ECI_x
        ldr     r3, [r12, #S_RIC_TX]
        sub     r4, r0, r3              @ Δx (Q16)
        ldr     r3, [r12, #S_RIC_TY]
        sub     r5, r1, r3              @ Δy (Q16)

        @ ΔR = Δx * R̂x + Δy * R̂y
        mov     r0, r4
        ldr     r12, =STATE
        ldr     r1, [r12, #S_RIC_RX]
        bl      fx_mul_q16
        mov     r6, r0
        mov     r0, r5
        ldr     r12, =STATE
        ldr     r1, [r12, #S_RIC_RY]
        bl      fx_mul_q16
        add     r6, r6, r0              @ r6 = ΔR (Q16)

        @ ΔI = Δx * Îx + Δy * Îy
        mov     r0, r4
        ldr     r12, =STATE
        ldr     r1, [r12, #S_RIC_IX]
        bl      fx_mul_q16
        mov     r4, r0                  @ reuse r4 = ΔI low
        mov     r0, r5
        ldr     r12, =STATE
        ldr     r1, [r12, #S_RIC_IY]
        bl      fx_mul_q16
        add     r4, r4, r0              @ r4 = ΔI (Q16)

        @ screen_x = 120 + (ΔI >> 14)    (asr to keep sign)
        @ screen_y = 80  + (ΔR >> 14)
        mov     r0, r4, asr #RIC_ZOOM_SHIFT
        add     r0, r0, #120
        mov     r1, r6, asr #RIC_ZOOM_SHIFT
        add     r1, r1, #80
        pop     {r4, r5, r6, lr}
        bx      lr

_w2s_eci:
        mov     r0, r0, asr #16
        mov     r1, r1, asr #16
        bx      lr

@ ----------------------------------------------------------------------------
@ _compute_ric_params -- caches target ECI position + R̂ + Î for the active
@ RIC view (always target 0 in this phase; mission FSM will pick later).
@ Reads S_T0 in IWRAM; writes S_RIC_{TX,TY,RX,RY,IX,IY}.
@ ----------------------------------------------------------------------------
_compute_ric_params:
        push    {r4, r5, r6, r7, lr}
        ldr     r4, =STATE
        ldr     r0, [r4, #S_T0]
        str     r0, [r4, #S_RIC_TX]
        ldr     r0, [r4, #(S_T0 + 4)]
        str     r0, [r4, #S_RIC_TY]

        @ Primary-centred TPX, TPY.
        ldr     r0, [r4, #S_T0]
        ldr     r1, =PLANET_X_Q16
        sub     r5, r0, r1              @ TPX
        ldr     r0, [r4, #(S_T0 + 4)]
        ldr     r1, =PLANET_Y_Q16
        sub     r6, r0, r1              @ TPY

        @ |t| = sqrt(TPX^2 + TPY^2)
        mov     r0, r5
        mov     r1, r5
        bl      fx_mul_q16
        mov     r7, r0
        mov     r0, r6
        mov     r1, r6
        bl      fx_mul_q16
        add     r7, r7, r0
        mov     r0, r7
        bl      fx_sqrt_q16
        mov     r7, r0                  @ |t|

        @ Degenerate (target at primary): zero everything.
        cmp     r7, #0x100
        bgt     _ric_normal
        mov     r0, #0
        ldr     r4, =STATE
        str     r0, [r4, #S_RIC_RX]
        str     r0, [r4, #S_RIC_RY]
        str     r0, [r4, #S_RIC_IX]
        str     r0, [r4, #S_RIC_IY]
        pop     {r4, r5, r6, r7, lr}
        bx      lr

_ric_normal:
        @ R̂x = TPX / |t|
        mov     r0, r5
        mov     r1, r7
        bl      fx_div_q16
        ldr     r4, =STATE
        str     r0, [r4, #S_RIC_RX]
        @ R̂y = TPY / |t|
        mov     r0, r6
        mov     r1, r7
        bl      fx_div_q16
        ldr     r4, =STATE
        str     r0, [r4, #S_RIC_RY]

        @ Determine motion direction: cross = TPX*TVY - TPY*TVX.
        ldr     r4, =STATE
        ldr     r0, [r4, #(S_T0 + 12)]   @ TVY
        mov     r1, r5
        bl      fx_mul_q16              @ TPX*TVY
        mov     r5, r0                  @ stash
        ldr     r4, =STATE
        ldr     r0, [r4, #(S_T0 + 8)]
        mov     r1, r6
        bl      fx_mul_q16              @ TPY*TVX
        subs    r5, r5, r0              @ cross (signed); set flags

        @ Î = (-R̂y, R̂x) if cross > 0 (CCW), else (R̂y, -R̂x).
        ldr     r4, =STATE
        ldr     r0, [r4, #S_RIC_RX]
        ldr     r1, [r4, #S_RIC_RY]
        bge     _ric_ccw
        @ CW: Î = (R̂y, -R̂x)
        str     r1, [r4, #S_RIC_IX]
        rsb     r2, r0, #0
        str     r2, [r4, #S_RIC_IY]
        pop     {r4, r5, r6, r7, lr}
        bx      lr
_ric_ccw:
        @ CCW: Î = (-R̂y, R̂x)
        rsb     r2, r1, #0
        str     r2, [r4, #S_RIC_IX]
        str     r0, [r4, #S_RIC_IY]
        pop     {r4, r5, r6, r7, lr}
        bx      lr

@ ----------------------------------------------------------------------------
@ _advance_mission -- mission complete. Increments score by 5, refills ship_dv
@ by DV_REFILL_Q16 (capped at DV_MAX), cycles mission_id mod 5, picks a new
@ mission_target via frame_count mod 3, and clears all hold timers.
@ Clobbers r0-r4, r12.
@ ----------------------------------------------------------------------------
_advance_mission:
        push    {r4, lr}
        ldr     r4, =STATE
        @ score += 5
        ldr     r0, [r4, #S_SCORE]
        add     r0, r0, #5
        str     r0, [r4, #S_SCORE]
        @ ship_dv += DV_REFILL_Q16 (cap DV_MAX)
        ldr     r0, [r4, #S_SHIP_DV]
        ldr     r1, =DV_REFILL_Q16
        add     r0, r0, r1
        ldr     r1, =DV_MAX
        cmp     r0, r1
        movgt   r0, r1
        str     r0, [r4, #S_SHIP_DV]
        bl      _cycle_mission
        pop     {r4, lr}
        bx      lr

@ ----------------------------------------------------------------------------
@ _fail_mission -- like _advance_mission but on a TIMER-EXPIRY failure.
@ Penalty: score -= 2. No DV refill. Mission cycles to the next.
@ Clobbers r0-r4, r12.
@ ----------------------------------------------------------------------------
_fail_mission:
        push    {r4, lr}
        ldr     r4, =STATE
        @ score -= 2
        ldr     r0, [r4, #S_SCORE]
        sub     r0, r0, #2
        str     r0, [r4, #S_SCORE]
        bl      _cycle_mission
        pop     {r4, lr}
        bx      lr

@ ----------------------------------------------------------------------------
@ _cycle_mission -- shared mission-cycling code used by both
@ _advance_mission (win) and _fail_mission (timer expiry).
@   mission_id = (id + 1) mod 5
@   mission_target = (frame_count & 0x3F) mod 3
@   S_ORBIT_COUNT = 0
@   S_HOLD_TIMERS[0..2] = 0
@ Caller must have r4 = STATE pointer; we preserve r4.
@ ----------------------------------------------------------------------------
_cycle_mission:
        @ mission_id = (mission_id + 1) mod 5
        ldr     r0, [r4, #S_MISSION_ID]
        add     r0, r0, #1
        cmp     r0, #5
        movge   r0, #0
        str     r0, [r4, #S_MISSION_ID]
        @ mission_target = (frame_count & 0x3F) mod 3
        ldr     r0, [r4, #S_FRAME]
        and     r0, r0, #0x3F
_mod3_loop:
        cmp     r0, #3
        subge   r0, r0, #3
        bge     _mod3_loop
        str     r0, [r4, #S_MISSION_TARGET]
        @ Reset orbit count + hold timers
        mov     r0, #0
        str     r0, [r4, #S_ORBIT_COUNT]
        str     r0, [r4, #S_HOLD_TIMERS]
        str     r0, [r4, #(S_HOLD_TIMERS + 4)]
        str     r0, [r4, #(S_HOLD_TIMERS + 8)]
        bx      lr

@ ----------------------------------------------------------------------------
@ _check_orbit_limit -- called after every orbit increment. If the current
@ mission is DENY (0) or DSRP (2) and the orbit count has reached
@ ORBIT_LIMIT, trigger a mission failure.
@   r4 = STATE pointer (caller sets up)
@ Clobbers r0, r1.
@ ----------------------------------------------------------------------------
_check_orbit_limit:
        ldr     r0, [r4, #S_MISSION_ID]
        cmp     r0, #0                          @ DENY?
        beq     _col_check
        cmp     r0, #2                          @ DSRP?
        bxne    lr
_col_check:
        ldr     r0, [r4, #S_ORBIT_COUNT]
        cmp     r0, #ORBIT_LIMIT
        bxlt    lr
        @ Limit reached -- fail the mission.
        b       _fail_mission

@ ----------------------------------------------------------------------------
@ _spawn_debris_at_player -- spawn DEBRIS_N debris bodies at the player's
@ current position. Each slot's velocity = player velocity perturbed by a
@ small per-slot kick computed from S_FRAME (cheap deterministic PRNG).
@ Clobbers r0-r5, r12.
@ ----------------------------------------------------------------------------
_spawn_debris_at_player:
        push    {r4, r5, lr}
        ldr     r12, =STATE
        ldr     r4, [r12, #S_PLAYER]            @ player_x Q16
        ldr     r5, [r12, #(S_PLAYER + 4)]      @ player_y Q16
        @ Walk all 4 slots; overwrite each unconditionally with a fresh body.
        @ slot offsets: S_DEBRIS + i * 32
        mov     r0, #0                          @ i
_sdbr_loop:
        @ slot_addr = STATE + S_DEBRIS + i*32
        mov     r1, r0, lsl #5
        add     r1, r1, #S_DEBRIS
        add     r1, r12, r1
        str     r4, [r1, #0]                    @ x = player_x
        str     r5, [r1, #4]                    @ y = player_y
        @ Velocity = player velocity ± per-slot kick
        ldr     r2, [r12, #(S_PLAYER + 8)]      @ player_vx
        ldr     r3, [r12, #(S_PLAYER + 12)]     @ player_vy
        @ Per-slot kick: rotate (i + frame) bits to pick one of 4 directions
        @ approximating (+x, +y, -x, -y) at magnitude 0x8000 (0.5 Q16).
        @ idx 0: vx += 0x8000
        @ idx 1: vy += 0x8000
        @ idx 2: vx -= 0x8000
        @ idx 3: vy -= 0x8000
        cmp     r0, #0
        beq     _sdbr_kick_xp
        cmp     r0, #1
        beq     _sdbr_kick_yp
        cmp     r0, #2
        beq     _sdbr_kick_xn
        @ idx 3
        sub     r3, r3, #0x8000
        b       _sdbr_store
_sdbr_kick_xp:
        add     r2, r2, #0x8000
        b       _sdbr_store
_sdbr_kick_yp:
        add     r3, r3, #0x8000
        b       _sdbr_store
_sdbr_kick_xn:
        sub     r2, r2, #0x8000
_sdbr_store:
        str     r2, [r1, #8]
        str     r3, [r1, #12]
        mov     r2, #1
        str     r2, [r1, #16]                   @ alive = 1
        mov     r2, #0
        str     r2, [r1, #20]                   @ age = 0
        add     r0, r0, #1
        cmp     r0, #DEBRIS_N
        blt     _sdbr_loop
        pop     {r4, r5, lr}
        bx      lr

@ ----------------------------------------------------------------------------
@ _debris_tick -- per frame, advance every alive debris through cowell_step,
@ increment age, kill on age > DEBRIS_MAX_AGE or off-screen, and apply a
@ collision against the player: integer pixel distance² <= DEBRIS_HIT_SQ
@ subtracts 1 from score and kills the offending debris.
@ Clobbers r0-r3, r12; may call cowell_step (preserves r4-r11).
@ ----------------------------------------------------------------------------
_debris_tick:
        push    {r4-r10, lr}
        ldr     r4, =STATE
        ldr     r5, [r4, #S_PLAYER]
        ldr     r6, [r4, #(S_PLAYER + 4)]
        mov     r5, r5, asr #16                 @ player int x
        mov     r6, r6, asr #16
        mov     r7, #0                          @ i
_dtick_loop:
        mov     r0, r7, lsl #5
        add     r0, r0, #S_DEBRIS
        add     r8, r4, r0                      @ &slot
        ldr     r9, [r8, #16]                   @ alive
        cmp     r9, #0
        beq     _dtick_next

        @ Cowell step on this body.
        mov     r0, r8
        bl      cowell_step
        ldr     r4, =STATE
        mov     r0, r7, lsl #5
        add     r0, r0, #S_DEBRIS
        add     r8, r4, r0

        @ Age++
        ldr     r0, [r8, #20]
        add     r0, r0, #1
        str     r0, [r8, #20]
        cmp     r0, #DEBRIS_MAX_AGE
        bgt     _dtick_kill

        @ Off-screen kill: integer x,y outside [0, 240) x [0, 160)
        ldr     r0, [r8, #0]
        ldr     r1, [r8, #4]
        mov     r2, r0, asr #16
        mov     r3, r1, asr #16
        cmp     r2, #0
        blt     _dtick_kill
        cmp     r2, #240
        bge     _dtick_kill
        cmp     r3, #0
        blt     _dtick_kill
        cmp     r3, #160
        bge     _dtick_kill

        @ Player collision: |delta|² <= DEBRIS_HIT_SQ
        sub     r2, r2, r5
        sub     r3, r3, r6
        mul     r2, r2, r2
        mul     r3, r3, r3
        add     r2, r2, r3
        cmp     r2, #DEBRIS_HIT_SQ
        bgt     _dtick_next
        @ Hit: -1 score (clamp at 0), kill debris.
        ldr     r0, [r4, #S_SCORE]
        cmp     r0, #0
        subgt   r0, r0, #1
        str     r0, [r4, #S_SCORE]
_dtick_kill:
        mov     r0, #0
        str     r0, [r8, #16]
_dtick_next:
        add     r7, r7, #1
        cmp     r7, #DEBRIS_N
        blt     _dtick_loop
        pop     {r4-r10, lr}
        bx      lr

@ ----------------------------------------------------------------------------
@ _draw_target(idx, color) -- transformed body draw, cone-filtered.
@   r0 = target idx (0..2), r1 = BGR555 colour
@ Inside sensor cone: full 3x3 sprite (draw_square3).
@ Outside cone (or cross-plane): single dim-grey pixel at the projected
@ screen position -- the "last known location" fog-of-war affordance.
@ Cross-plane targets are also painted dim so the player still has
@ situational awareness without being able to engage them.
@ ----------------------------------------------------------------------------
_draw_target:
        push    {r4, r5, r6, r7, r8, lr}
        mov     r4, r0                          @ idx
        mov     r5, r1                          @ colour

        ldr     r12, =STATE
        mov     r6, r4, lsl #4
        add     r6, r6, #S_T0
        add     r6, r12, r6                     @ &target[idx]

        @ Screen coords via active view.
        ldr     r0, [r6, #0]
        ldr     r1, [r6, #4]
        bl      _world_to_screen
        mov     r7, r0                          @ screen x
        mov     r8, r1                          @ screen y

        @ Cross-plane gate first: cross-plane -> always dim.
        ldr     r12, =STATE
        add     r0, r12, r4, lsl #2
        ldr     r0, [r0, #S_T_PLANE]
        ldr     r1, [r12, #S_PLAYER_PLANE]
        cmp     r0, r1
        bne     _dt_dim

        @ Cone check: angle from sensor_dir to target.
        ldr     r2, [r6, #0]
        ldr     r3, [r6, #4]
        ldr     r0, [r12, #S_PLAYER]
        sub     r2, r2, r0
        ldr     r0, [r12, #(S_PLAYER + 4)]
        sub     r3, r3, r0
        mov     r0, r3                          @ y arg
        mov     r1, r2                          @ x arg
        bl      fx_atan2
        ldr     r12, =STATE
        ldr     r1, [r12, #S_SENSOR_DIR]
        sub     r0, r0, r1
        mov     r0, r0, lsl #16
        mov     r0, r0, asr #16
        cmp     r0, #0
        rsblt   r0, r0, #0
        cmp     r0, #SENSOR_HALF_ANGLE
        bgt     _dt_dim

        @ Inside cone: full sprite.
        mov     r0, r7
        mov     r1, r8
        mov     r2, r5
        bl      draw_square3
        b       _dt_done

_dt_dim:
        @ Single bright-grey pixel at the projected position.
        cmp     r7, #0
        blt     _dt_done
        cmp     r7, #240
        bge     _dt_done
        cmp     r8, #0
        blt     _dt_done
        cmp     r8, #160
        bge     _dt_done
        mov     r0, #240
        mul     r0, r8, r0
        add     r0, r0, r7
        ldr     r1, =VRAM
        add     r0, r1, r0, lsl #1
        ldr     r1, =0x4A52                     @ medium grey
        strh    r1, [r0]
_dt_done:
        pop     {r4, r5, r6, r7, r8, lr}
        bx      lr

@ ----------------------------------------------------------------------------
@ _draw_debris -- paint a single grey pixel for every alive debris body,
@ transformed through the active ECI/RIC view.
@ Clobbers r0-r3, r12 internally; push/pops r4-r6 and lr for safety.
@ ----------------------------------------------------------------------------
_draw_debris:
        push    {r4, r5, r6, lr}
        mov     r6, #0                          @ slot index
_ddr_loop:
        ldr     r4, =STATE
        mov     r0, r6, lsl #5
        add     r0, r0, #S_DEBRIS
        add     r5, r4, r0                      @ &slot
        ldr     r0, [r5, #16]
        cmp     r0, #0
        beq     _ddr_next
        ldr     r0, [r5, #0]
        ldr     r1, [r5, #4]
        bl      _world_to_screen
        cmp     r0, #0
        blt     _ddr_next
        cmp     r0, #240
        bge     _ddr_next
        cmp     r1, #0
        blt     _ddr_next
        cmp     r1, #160
        bge     _ddr_next
        mov     r2, #240
        mul     r2, r1, r2
        add     r2, r2, r0
        ldr     r3, =VRAM
        add     r2, r3, r2, lsl #1
        ldr     r3, =0x5294                     @ bright grey
        strh    r3, [r2]
_ddr_next:
        add     r6, r6, #1
        cmp     r6, #DEBRIS_N
        blt     _ddr_loop
        pop     {r4, r5, r6, lr}
        bx      lr

@ ----------------------------------------------------------------------------
@ _predict_path(body_ptr, out_ptr) -- forward-integrate PATH_N_POINTS
@ substeps of cowell_step on a scratch copy of the body's state, storing
@ (x_q16, y_q16) at each step into the out buffer (8 B per point).
@   r0 = body state ptr (4 Q16 words: x, y, vx, vy)
@   r1 = output cache ptr
@ Real body state is left untouched.
@ Clobbers r0..r3, r12; preserves r4-r11 via push/pop.
@ ----------------------------------------------------------------------------
_predict_path:
        push    {r4, r5, r6, r7, r8, r9, lr}
        @ Allocate 16 B of stack for scratch state copy.
        sub     sp, sp, #16
        mov     r4, sp                          @ scratch ptr
        mov     r5, r1                          @ out ptr
        @ Copy body state into scratch.
        ldr     r6, [r0, #0]
        str     r6, [r4, #0]
        ldr     r6, [r0, #4]
        str     r6, [r4, #4]
        ldr     r6, [r0, #8]
        str     r6, [r4, #8]
        ldr     r6, [r0, #12]
        str     r6, [r4, #12]
        mov     r6, #PATH_N_POINTS              @ loop counter
_pp_loop:
        @ Store current (x, y) into out cache.
        ldr     r7, [r4, #0]
        str     r7, [r5, #0]
        ldr     r7, [r4, #4]
        str     r7, [r5, #4]
        add     r5, r5, #8
        @ Step the scratch copy.
        mov     r0, r4
        bl      cowell_step
        subs    r6, r6, #1
        bne     _pp_loop
        add     sp, sp, #16
        pop     {r4, r5, r6, r7, r8, r9, lr}
        bx      lr

@ ----------------------------------------------------------------------------
@ _draw_path(cache_ptr, color) -- paint dashed pixels for a path.
@ Sub-samples every PATH_DRAW_STRIDE-th point so the per-frame draw cost
@ stays flat as PATH_N_POINTS grows. With N=256, STRIDE=8 -> 32 dots, which
@ visually closes a full orbit at the default radius.
@   r0 = path cache pointer (PATH_BYTES of Q16 (x,y) pairs)
@   r1 = colour (BGR555)
@ Clobbers r2..r12.
@ ----------------------------------------------------------------------------
_draw_path:
        push    {r4, r5, r6, r7, lr}
        mov     r4, r0                          @ ptr
        mov     r5, r1                          @ colour
        mov     r6, #0                          @ index (0..N-1, step PATH_DRAW_STRIDE)
_dp_loop:
        @ Load (x, y) of point[i]
        ldr     r0, [r4, #0]
        ldr     r1, [r4, #4]
        bl      _world_to_screen
        @ r0 = sx, r1 = sy. Bounds-check + paint.
        cmp     r0, #0
        blt     _dp_skip
        cmp     r0, #240
        bge     _dp_skip
        cmp     r1, #0
        blt     _dp_skip
        cmp     r1, #160
        bge     _dp_skip
        mov     r2, #240
        mul     r2, r1, r2
        add     r2, r2, r0
        ldr     r3, =VRAM
        add     r2, r3, r2, lsl #1
        strh    r5, [r2]
_dp_skip:
        add     r4, r4, #(PATH_DRAW_STRIDE * 8) @ advance by STRIDE points (8 B each)
        add     r6, r6, #PATH_DRAW_STRIDE
        cmp     r6, #PATH_N_POINTS
        blt     _dp_loop
        pop     {r4, r5, r6, r7, lr}
        bx      lr

@ ----------------------------------------------------------------------------
@ _refresh_paths -- recompute AT MOST ONE body's path per frame.
@
@ With PATH_N_POINTS=256 each predict_path is ~360K instructions (every
@ cowell_step substep does several Q16 fx_div calls, and udiv64 alone is
@ ~448 instructions). Refreshing all four at once on the boot frame
@ would burn ~1.5M instructions and visibly stutter (also break
@ test_rom_execute cycle budgets). Spreading the work across frames keeps
@ each frame's worst case to one body of refresh, which fits comfortably
@ in a normal frame budget; the cost the user pays is that at boot, the
@ three target paths trickle in over the next three frames after the
@ player path. After boot the dirty bits are rare (only set on burn or
@ respawn) so the cost is unnoticeable in steady state.
@
@ Clobbers r0..r3, r12.
@ ----------------------------------------------------------------------------
_refresh_paths:
        push    {r4, r5, lr}
        ldr     r4, =STATE
        ldr     r5, [r4, #S_PATH_DIRTY]
        @ Player (bit 0) -- highest priority since burns dirty only this bit.
        tst     r5, #1
        beq     _rp_t0
        mov     r0, r4
        ldr     r1, =(STATE + S_PATH_PLAYER)
        bl      _predict_path
        ldr     r4, =STATE
        ldr     r5, [r4, #S_PATH_DIRTY]
        bic     r5, r5, #1
        str     r5, [r4, #S_PATH_DIRTY]
        b       _rp_done
_rp_t0:
        tst     r5, #2
        beq     _rp_t1
        add     r0, r4, #S_T0
        ldr     r1, =(STATE + S_PATH_T0)
        bl      _predict_path
        ldr     r4, =STATE
        ldr     r5, [r4, #S_PATH_DIRTY]
        bic     r5, r5, #2
        str     r5, [r4, #S_PATH_DIRTY]
        b       _rp_done
_rp_t1:
        tst     r5, #4
        beq     _rp_t2
        add     r0, r4, #S_T1
        ldr     r1, =(STATE + S_PATH_T1)
        bl      _predict_path
        ldr     r4, =STATE
        ldr     r5, [r4, #S_PATH_DIRTY]
        bic     r5, r5, #4
        str     r5, [r4, #S_PATH_DIRTY]
        b       _rp_done
_rp_t2:
        tst     r5, #8
        beq     _rp_done
        add     r0, r4, #S_T2
        ldr     r1, =(STATE + S_PATH_T2)
        bl      _predict_path
        ldr     r4, =STATE
        ldr     r5, [r4, #S_PATH_DIRTY]
        bic     r5, r5, #8
        str     r5, [r4, #S_PATH_DIRTY]
_rp_done:
        pop     {r4, r5, lr}
        bx      lr

@ ----------------------------------------------------------------------------
@ _apply_burn(dvx, dvy) -- adds an impulse to the player's velocity and
@ decrements ship_dv by THRUST_COST. Caller must have already verified
@ ship_dv > 0; we floor at 0 here for safety against repeated calls in
@ the same frame.
@   r0 = dvx (Q16), r1 = dvy (Q16)
@ Clobbers: r2, r3, r12 (caller-saved).
@ ----------------------------------------------------------------------------
_apply_burn:
        ldr     r2, =STATE
        ldr     r3, [r2, #(S_PLAYER + 8)]
        add     r3, r3, r0
        str     r3, [r2, #(S_PLAYER + 8)]
        ldr     r3, [r2, #(S_PLAYER + 12)]
        add     r3, r3, r1
        str     r3, [r2, #(S_PLAYER + 12)]
        ldr     r3, [r2, #S_SHIP_DV]
        ldr     r12, =THRUST_COST
        sub     r3, r3, r12
        cmp     r3, #0
        movlt   r3, #0
        str     r3, [r2, #S_SHIP_DV]
        @ Player's path needs recomputation next frame.
        ldr     r3, [r2, #S_PATH_DIRTY]
        orr     r3, r3, #1
        str     r3, [r2, #S_PATH_DIRTY]
        bx      lr

@ ----------------------------------------------------------------------------
@ _compute_elem_for_body(body_ptr, out_ptr) -- wraps elements_from_state
@ by first subtracting PLANET position so the kernel sees primary at origin.
@   r0 = ECI state pointer (4 Q16 words: x, y, vx, vy in screen coords)
@   r1 = output pointer    (4 Q16 words: a, e, omega, nu)
@ Uses 16 bytes of stack as the primary-centred staging buffer.
@ ----------------------------------------------------------------------------
_compute_elem_for_body:
        push    {r4, lr}
        mov     r4, r1                  @ save out ptr across the kernel call
        sub     sp, sp, #16
        @ x_primary = x_eci - PLANET_X
        ldr     r2, =PLANET_X_Q16
        ldr     r3, [r0]
        sub     r3, r3, r2
        str     r3, [sp, #0]
        @ y_primary = y_eci - PLANET_Y
        ldr     r2, =PLANET_Y_Q16
        ldr     r3, [r0, #4]
        sub     r3, r3, r2
        str     r3, [sp, #4]
        @ vx, vy unchanged
        ldr     r3, [r0, #8]
        str     r3, [sp, #8]
        ldr     r3, [r0, #12]
        str     r3, [sp, #12]
        mov     r0, sp
        mov     r1, r4
        bl      elements_from_state
        add     sp, sp, #16
        pop     {r4, lr}
        bx      lr

@ ----------------------------------------------------------------------------
@ _hud_a_len_clamped(a_q16) -- map semi-major axis to a 0..100 bar length.
@ Special-cases the hyperbolic sentinel (INT32_MAX) -> 0 length.
@ ----------------------------------------------------------------------------
_hud_a_len_clamped:
        @ hyperbolic sentinel?
        mvn     r1, #0x80000000         @ r1 = 0x7FFFFFFF
        cmp     r0, r1
        moveq   r0, #0
        bxeq    lr
        mov     r0, r0, asr #16         @ a in pixels
        cmp     r0, #0
        movlt   r0, #0
        cmp     r0, #100
        movgt   r0, #100
        bx      lr

@ ----------------------------------------------------------------------------
@ _hud_e_len_clamped(e_q16) -- map eccentricity to a 0..40 bar length.
@ e is non-negative by construction; shift down so e=1 -> 32 px, cap at 40.
@ ----------------------------------------------------------------------------
_hud_e_len_clamped:
        mov     r0, r0, asr #11
        cmp     r0, #0
        movlt   r0, #0
        cmp     r0, #40
        movgt   r0, #40
        bx      lr

@ ----------------------------------------------------------------------------
@ _draw_hbar(x_start, y_row, length, color) -- horizontal pixel bar.
@   r0 = x_start (int pixels), r1 = y_row (int), r2 = length, r3 = color
@ No bounds checking; caller keeps inside [0, 240) x [0, 160).
@ ----------------------------------------------------------------------------
_draw_hbar:
        cmp     r2, #0
        bxle    lr
        push    {r4, r5, lr}
        mov     r4, #240
        mul     r4, r1, r4
        add     r4, r4, r0
        ldr     r5, =VRAM
        add     r4, r5, r4, lsl #1
hbar_loop:
        strh    r3, [r4]
        add     r4, r4, #2
        subs    r2, r2, #1
        bgt     hbar_loop
        pop     {r4, r5, lr}
        bx      lr

@ ----------------------------------------------------------------------------
@ _draw_glyph(idx, x, y, color) -- paint a single 4x6 pixel glyph.
@   r0 = glyph index, r1 = x, r2 = y, r3 = BGR555 colour
@ Walks 6 rows; for each row's 4 LSB bits, paints the corresponding pixel
@ if the bit is set. Per-pixel bounds-check against [0,240) x [0,160).
@ Clobbers r4..r11.
@ ----------------------------------------------------------------------------
_draw_glyph:
        push    {r4-r11, lr}
        mov     r4, r3                          @ colour preserved across writes
        @ glyph ptr = font_glyphs + idx*6
        ldr     r5, =font_glyphs
        mov     r6, r0, lsl #1
        add     r6, r6, r0, lsl #2
        add     r5, r5, r6                      @ r5 -> row bytes
        mov     r6, r1                          @ x0 (left col)
        mov     r7, r2                          @ y (current row)
        mov     r8, #0                          @ row counter
        ldr     r9, =VRAM
_dgl_row:
        add     r11, r5, r8
        ldrb    r10, [r11]                      @ row byte
        @ col 0 (bit 3)
        tst     r10, #8
        beq     _dgl_c1
        mov     r0, r6
        mov     r1, r7
        bl      _glyph_px
_dgl_c1:
        tst     r10, #4
        beq     _dgl_c2
        add     r0, r6, #1
        mov     r1, r7
        bl      _glyph_px
_dgl_c2:
        tst     r10, #2
        beq     _dgl_c3
        add     r0, r6, #2
        mov     r1, r7
        bl      _glyph_px
_dgl_c3:
        tst     r10, #1
        beq     _dgl_next
        add     r0, r6, #3
        mov     r1, r7
        bl      _glyph_px
_dgl_next:
        add     r7, r7, #1
        add     r8, r8, #1
        cmp     r8, #6
        blt     _dgl_row
        pop     {r4-r11, lr}
        bx      lr

@ Inner helper: paint pixel at (r0, r1) with colour in r4, using VRAM in r9.
@ Bounds-checked. Clobbers r2, r3, r11.
_glyph_px:
        cmp     r0, #0
        bxlt    lr
        cmp     r0, #240
        bxge    lr
        cmp     r1, #0
        bxlt    lr
        cmp     r1, #160
        bxge    lr
        mov     r2, #240
        mul     r2, r1, r2
        add     r2, r2, r0
        add     r11, r9, r2, lsl #1
        strh    r4, [r11]
        bx      lr

@ ----------------------------------------------------------------------------
@ _draw_str(ptr, x, y, color) -- paint a 0xFF-terminated glyph-index string.
@ Advances x by 5 px (4 px glyph + 1 px space) per character.
@ Clobbers r4..r8.
@ ----------------------------------------------------------------------------
_draw_str:
        push    {r4, r5, r6, r7, lr}
        mov     r4, r0                          @ ptr
        mov     r5, r1                          @ cur x
        mov     r6, r2                          @ y
        mov     r7, r3                          @ colour
_dstr_loop:
        ldrb    r0, [r4]
        cmp     r0, #0xFF
        beq     _dstr_done
        mov     r1, r5
        mov     r2, r6
        mov     r3, r7
        bl      _draw_glyph
        add     r4, r4, #1
        add     r5, r5, #5
        b       _dstr_loop
_dstr_done:
        pop     {r4, r5, r6, r7, lr}
        bx      lr

@ ----------------------------------------------------------------------------
@ _draw_dec(value, x_right, y, color) -- print 3-digit decimal at (x_right, y)
@ in BIG-ENDIAN reading order. Leading zeros are kept (e.g. 7 -> "007").
@   r0 = value (unsigned), r1 = x_right (top-left of leftmost digit),
@   r2 = y, r3 = colour
@ Always emits exactly 3 digits; caller picks the X for that field.
@ Uses BIOS SWI 0x06 for divmod by 10.
@ Clobbers r4..r8.
@ ----------------------------------------------------------------------------
_draw_dec:
        push    {r4, r5, r6, r7, lr}
        mov     r4, r0                          @ value
        @ rightmost digit at x = x_right + 10  (2 * 5)
        add     r5, r1, #10                     @ cur_x
        mov     r6, r2                          @ y
        mov     r7, r3                          @ colour
        mov     r8, #3                          @ digits remaining
_ddc_loop:
        mov     r0, r4
        mov     r1, #10
        swi     0x060000                        @ r0 = quot, r1 = rem
        mov     r4, r0
        add     r0, r1, #1                      @ glyph index ('0' is at 1)
        mov     r1, r5
        mov     r2, r6
        mov     r3, r7
        bl      _draw_glyph
        sub     r5, r5, #5
        subs    r8, r8, #1
        bne     _ddc_loop
        pop     {r4, r5, r6, r7, lr}
        bx      lr

@ Same as _draw_dec but 4 digits. Used for SCORE.
_draw_dec4:
        push    {r4, r5, r6, r7, lr}
        mov     r4, r0
        add     r5, r1, #15                     @ 3 * 5
        mov     r6, r2
        mov     r7, r3
        mov     r8, #4
_ddc4_loop:
        mov     r0, r4
        mov     r1, #10
        swi     0x060000
        mov     r4, r0
        add     r0, r1, #1
        mov     r1, r5
        mov     r2, r6
        mov     r3, r7
        bl      _draw_glyph
        sub     r5, r5, #5
        subs    r8, r8, #1
        bne     _ddc4_loop
        pop     {r4, r5, r6, r7, lr}
        bx      lr

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
        @ Bounds-check pixel (r8, r4) against [0,240) x [0,160).
        cmp     r8, #0
        blt     sq3_skip
        cmp     r8, #240
        bge     sq3_skip
        cmp     r4, #0
        blt     sq3_skip
        cmp     r4, #160
        bge     sq3_skip
        mov     r1, #240
        mul     r3, r4, r1
        add     r3, r3, r8
        add     r3, r7, r3, lsl #1
        strh    r2, [r3]
sq3_skip:
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
        @ Bounds-check before VRAM write.
        cmp     r0, #0
        blt     disc_skip2
        cmp     r0, #240
        bge     disc_skip2
        cmp     r1, #0
        blt     disc_skip2
        cmp     r1, #160
        bge     disc_skip2
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
        .align 4
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
        .align 4
nose_dx:
        .word  3,  2,  0, -2, -3, -2,  0,  2
nose_dy:
        .word  0,  2,  3,  2,  0, -2, -3, -2

@ Mission HUD palette (BGR555).
@   0 Deny      red
@   1 Degrade   green
@   2 Disrupt   blue
@   3 Destroy   cyan
@   4 Deceive   yellow
        .align 4
mission_color_table:
        .word   0x001F
        .word   0x03E0
        .word   0x7C00
        .word   0x7FE0
        .word   0x03FF

@ ----------------------------------------------------------------------------
@ Pixel font: 4-wide x 6-tall glyphs, one byte per row, low 4 bits are pixels
@ (bit 3 = leftmost). 30 glyphs * 6 = 180 bytes. Glyph indices:
@   0=space  1..10='0'..'9'
@   11='A' 12='C' 13='D' 14='E' 15='G' 16='I' 17='L' 18='M' 19='N' 20='O'
@   21='P' 22='R' 23='S' 24='T' 25='V' 26='W' 27='Y'
@   28='a' (lowercase)  29='e' (lowercase)
@ ----------------------------------------------------------------------------
        .align 4
font_glyphs:
        @ 0: space
        .byte 0x0, 0x0, 0x0, 0x0, 0x0, 0x0
        @ 1: '0'
        .byte 0x6, 0x9, 0x9, 0x9, 0x9, 0x6
        @ 2: '1'
        .byte 0x4, 0xC, 0x4, 0x4, 0x4, 0xE
        @ 3: '2'
        .byte 0xE, 0x1, 0x6, 0xC, 0x8, 0xF
        @ 4: '3'
        .byte 0xE, 0x1, 0x6, 0x1, 0x1, 0xE
        @ 5: '4'
        .byte 0x9, 0x9, 0xF, 0x1, 0x1, 0x1
        @ 6: '5'
        .byte 0xF, 0x8, 0xE, 0x1, 0x1, 0xE
        @ 7: '6'
        .byte 0x6, 0x8, 0xE, 0x9, 0x9, 0x6
        @ 8: '7'
        .byte 0xF, 0x1, 0x2, 0x4, 0x4, 0x4
        @ 9: '8'
        .byte 0x6, 0x9, 0x6, 0x9, 0x9, 0x6
        @ 10: '9'
        .byte 0x6, 0x9, 0x9, 0x7, 0x1, 0x6
        @ 11: 'A'
        .byte 0x6, 0x9, 0x9, 0xF, 0x9, 0x9
        @ 12: 'C'
        .byte 0x7, 0x8, 0x8, 0x8, 0x8, 0x7
        @ 13: 'D'
        .byte 0xE, 0x9, 0x9, 0x9, 0x9, 0xE
        @ 14: 'E'
        .byte 0xF, 0x8, 0xE, 0x8, 0x8, 0xF
        @ 15: 'G'
        .byte 0x7, 0x8, 0x8, 0xB, 0x9, 0x6
        @ 16: 'I'
        .byte 0xE, 0x4, 0x4, 0x4, 0x4, 0xE
        @ 17: 'L'
        .byte 0x8, 0x8, 0x8, 0x8, 0x8, 0xF
        @ 18: 'M'
        .byte 0x9, 0xF, 0xF, 0x9, 0x9, 0x9
        @ 19: 'N'
        .byte 0x9, 0xD, 0xF, 0xB, 0x9, 0x9
        @ 20: 'O'
        .byte 0x6, 0x9, 0x9, 0x9, 0x9, 0x6
        @ 21: 'P'
        .byte 0xE, 0x9, 0x9, 0xE, 0x8, 0x8
        @ 22: 'R'
        .byte 0xE, 0x9, 0x9, 0xE, 0xA, 0x9
        @ 23: 'S'
        .byte 0x7, 0x8, 0x6, 0x1, 0x1, 0xE
        @ 24: 'T'
        .byte 0xF, 0x4, 0x4, 0x4, 0x4, 0x4
        @ 25: 'V'
        .byte 0x9, 0x9, 0x9, 0x9, 0x6, 0x6
        @ 26: 'W'
        .byte 0x9, 0x9, 0x9, 0xF, 0xF, 0x9
        @ 27: 'Y'
        .byte 0x9, 0x9, 0x6, 0x4, 0x4, 0x4
        @ 28: 'a' (lowercase)
        .byte 0x0, 0x6, 0x3, 0x7, 0x9, 0x7
        @ 29: 'e' (lowercase)
        .byte 0x0, 0x6, 0x9, 0xE, 0x8, 0x7

@ Label strings: byte arrays of glyph indices, 0xFF-terminated.
        .align 4
str_dv:    .byte 13, 25, 0xFF                  @ "DV"
str_a:     .byte 28, 0xFF                      @ "a"
str_e:     .byte 29, 0xFF                      @ "e"
str_ta:    .byte 24, 28, 0xFF                  @ "Ta"
str_te:    .byte 24, 29, 0xFF                  @ "Te"
str_wrp:   .byte 26, 22, 21, 0xFF              @ "WRP"
str_mis:   .byte 18, 16, 23, 0xFF              @ "MIS"
str_view:  .byte 25, 16, 14, 26, 0xFF          @ "VIEW"
str_pln:   .byte 21, 17, 19, 0xFF              @ "PLN"
str_lap:   .byte 17, 11, 21, 0xFF              @ "LAP"
str_eci:   .byte 14, 12, 16, 0xFF              @ "ECI"
str_ric:   .byte 22, 16, 12, 0xFF              @ "RIC"
str_deny:  .byte 13, 14, 19, 27, 0xFF          @ "DENY"
str_dgrd:  .byte 13, 15, 22, 13, 0xFF          @ "DGRD"
str_dsrp:  .byte 13, 23, 22, 21, 0xFF          @ "DSRP"
str_dstr:  .byte 13, 23, 24, 22, 0xFF          @ "DSTR"
str_decv:  .byte 13, 14, 12, 25, 0xFF          @ "DECV"
str_score: .byte 23, 12, 20, 22, 14, 0xFF      @ "SCORE"

@ Mission name pointer table, indexed by mission_id.
        .align 4
mission_names:
        .word   str_deny
        .word   str_dgrd
        .word   str_dsrp
        .word   str_dstr
        .word   str_decv

        .ltorg
