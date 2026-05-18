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
        .equ S_MISSION_PROGRESS,  0x94  @ frame counter or proxy
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
        .equ PLANE_CHANGE_DV,     0x00190000   @ 25 (Q16) cost to flip planes
        .equ HOLD_DIST_SQ,        144   @ 12 px squared
        .equ HOLD_THRESH,         90    @ frames to trigger Deny completion
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

        @ Zero the state block (84 words: 52 prior + 128 B debris).
        ldr     r0, =STATE
        mov     r1, #0
        mov     r2, #84
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

        @ -------- targets (3x3 colored squares) -----------------------
        ldr     r12, =STATE
        ldr     r0, [r12, #S_T0]
        ldr     r1, [r12, #(S_T0 + 4)]
        bl      _world_to_screen
        ldr     r2, =0x001F                     @ red
        bl      draw_square3

        ldr     r12, =STATE
        ldr     r0, [r12, #S_T1]
        ldr     r1, [r12, #(S_T1 + 4)]
        bl      _world_to_screen
        ldr     r2, =0x03E0                     @ green
        bl      draw_square3

        ldr     r12, =STATE
        ldr     r0, [r12, #S_T2]
        ldr     r1, [r12, #(S_T2 + 4)]
        bl      _world_to_screen
        ldr     r2, =0x7FE0                     @ cyan-white
        bl      draw_square3

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

        @ -------- element HUD bars -----------------------------------
        @ Player a (cyan, y=3): length = a >> 16 (clamped 0..100)
        ldr     r12, =STATE
        ldr     r0, [r12, #S_PLAYER_EL]
        bl      _hud_a_len_clamped
        mov     r2, r0
        mov     r0, #2
        mov     r1, #3
        ldr     r3, =0x7FE0                     @ cyan
        bl      _draw_hbar
        @ Player e (yellow, y=5): length = e >> 11 (clamped 0..40)
        ldr     r12, =STATE
        ldr     r0, [r12, #(S_PLAYER_EL + 4)]
        bl      _hud_e_len_clamped
        mov     r2, r0
        mov     r0, #2
        mov     r1, #5
        ldr     r3, =0x03FF                     @ bright yellow
        bl      _draw_hbar
        @ Target 0 a (dim cyan, y=8)
        ldr     r12, =STATE
        ldr     r0, [r12, #S_TARGET_EL]
        bl      _hud_a_len_clamped
        mov     r2, r0
        mov     r0, #2
        mov     r1, #8
        ldr     r3, =0x4310                     @ dim cyan
        bl      _draw_hbar
        @ Target 0 e (dim yellow, y=10)
        ldr     r12, =STATE
        ldr     r0, [r12, #(S_TARGET_EL + 4)]
        bl      _hud_e_len_clamped
        mov     r2, r0
        mov     r0, #2
        mov     r1, #10
        ldr     r3, =0x023F                     @ dim yellow
        bl      _draw_hbar

        @ Warp HUD: yellow indicator at (115, 1), length = log10(warp)+1
        ldr     r12, =STATE
        ldr     r0, [r12, #S_WARP]
        mov     r2, #1
        cmp     r0, #10
        moveq   r2, #2
        cmp     r0, #100
        moveq   r2, #3
        mov     r0, #115
        mov     r1, #1
        ldr     r3, =0x03FF                     @ bright yellow
        bl      _draw_hbar

        @ Mission HUD: 5-pixel bar at (118, 4) colour-coded by mission_id.
        ldr     r12, =STATE
        ldr     r0, [r12, #S_MISSION_ID]
        cmp     r0, #5
        movge   r0, #0                          @ guard out-of-range
        ldr     r1, =mission_color_table
        add     r1, r1, r0, lsl #2
        ldr     r3, [r1]
        mov     r2, #5
        mov     r0, #118
        mov     r1, #4
        bl      _draw_hbar

        @ ECI / RIC mode indicator at (230, 1): 1 px white = ECI, 4 px = RIC
        ldr     r12, =STATE
        ldr     r0, [r12, #S_VIEW_MODE]
        mov     r2, #1
        cmp     r0, #0
        movne   r2, #4                          @ RIC -> 4 pixels
        ldr     r3, =0x7FFF                     @ white in ECI
        cmp     r0, #0
        ldrne   r3, =0x03FF                     @ yellow in RIC
        mov     r0, #230
        mov     r1, #1
        bl      _draw_hbar

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
        @ Reset progress + hold timers
        mov     r0, #0
        str     r0, [r4, #S_MISSION_PROGRESS]
        str     r0, [r4, #S_HOLD_TIMERS]
        str     r0, [r4, #(S_HOLD_TIMERS + 4)]
        str     r0, [r4, #(S_HOLD_TIMERS + 8)]
        pop     {r4, lr}
        bx      lr

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

@ Mission HUD palette (BGR555).
@   0 Deny      red
@   1 Degrade   green
@   2 Disrupt   blue
@   3 Destroy   cyan
@   4 Deceive   yellow
        .align 2
mission_color_table:
        .word   0x001F
        .word   0x03E0
        .word   0x7C00
        .word   0x7FE0
        .word   0x03FF

        .ltorg
