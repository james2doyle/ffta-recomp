#pragma once
// Battle-damage haptics seams for FFTA (mod_function_hook "ffta.haptics").
// Extracted to a header so src/main.cpp registers exactly the reviewed
// callbacks and the pure policy in ffta_haptics.h stays testable without the
// runtime.
//
// Three observers, one pulse pipeline:
//   1. haptics_damage_hook @ 0x080A2210 — the HP delta helper (unit
//      hp@+0x18); delta arrives signed in r1.
//   2. haptics_hp_store_hook @ 0x080A3250 — the enemy-unit direct store
//      (hp@+0x1C, max@+0x1E); r1 = new hp, r2 = unit; delta = old - new.
//   3. haptics_popup_hook @ 0x080A8BF8 — the damage-number popup spawn
//      (display-element initializer); RELEASES the armed pulse so the buzz
//      lands with the number for every animation length (measured store->
//      number gaps: fast melee ~22 frames, Air Render ~240; BRINGUP
//      2026-10-20). A grace deadline releases late rather than never.
//
// All callbacks return 0 (decline), so the generated bodies execute
// normally; they only read arguments/state and ARM a delayed pulse. The
// pulse itself fires from the game's per-frame policy (called from
// ffta_ws_margin_policy's frame callback), one release per armed pulse.
// Savestate loads/restores fold into haptics_reset() via the mods reset
// callback.
#include "ffta_haptics.h"
#include "gba_ppu.h"  // complete type for the frame-count read
#include "host_clock.h"
#include "host_window.h"
#include "runtime_arm.h"
#include "runtime_bus_bridge.h"  // active_ppu(): the PPU frame counter is
                                 // the ExtendedViewFrameInfo::frame_count clock

#include <cstdio>

namespace ffta {
namespace haptics_detail {

// The armed pulse: guest frame the damage applied, the grace deadline, and
// whether the damage-number popup has spawned (the release trigger).
// Game-thread only (the hooks and the frame policy both run on the
// emulation thread).
struct PendingPulse {
    std::uint64_t arm_frame = 0;
    std::uint64_t grace_frame = 0;
    float strength = 0.0f;
    bool armed = false;
    bool reported = false;   // release-check line already emitted for this arm
    bool popup_seen = false; // display popup spawned since arming
};
inline PendingPulse& pending() {
    static PendingPulse value;
    return value;
}
// Guest frame of the most recent display-popup spawn (0.080A8BF8 hook).
inline std::uint64_t& last_popup_frame() {
    static std::uint64_t value = 0;
    return value;
}
// Guest frame of the most recent real damage apply. The popup path only
// fires when a positive HP delta authorized it within the grace window;
// heals, misses, and status popups never set it.
inline std::uint64_t& last_damage_frame() {
    static std::uint64_t value = 0;
    return value;
}
// Popup-driven pulse rate limit (guest frames).
inline std::uint64_t& last_popup_pulse_frame() {
    static std::uint64_t value = 0;
    return value;
}
inline bool& have_popup_pulse() {
    static bool value = false;
    return value;
}
// Coalescing window state (millisecond clock), as before.
inline std::uint32_t& last_ms() {
    static std::uint32_t value = 0;
    return value;
}
inline bool& have_last() {
    static bool value = false;
    return value;
}
// Diagnostic budget shared by both paths.
inline int& logged() {
    static int value = 0;
    return value;
}
// Entry-census budget (separate from `logged` so the census cannot eat the
// arm/release diagnostics): first N HP-helper entries during the process.
inline int& entry_logged() {
    static int value = 0;
    return value;
}
// Popup-census budget (separate): first N display-popup spawns.
inline int& popup_logged() {
    static int value = 0;
    return value;
}

}  // namespace haptics_detail

// The guest frame clock the frame policy consumes
// (ExtendedViewFrameInfo::frame_count == PPU frame_count). Null PPU (no
// runtime yet) reads as 0. Lives in ffta (not gbarecomp): game-side helper.
inline std::uint64_t runtime_guest_frame_count() {
    const gba::GbaPpu* ppu = gbarecomp::active_ppu();
    return ppu ? ppu->frame_count() : 0u;
}

// Clear pending pulse + coalesce window when the mods lifecycle resets
// game-owned state (also covers savestate restore within a battle).
inline void haptics_reset() {
    haptics_detail::pending() = haptics_detail::PendingPulse{};
    haptics_detail::have_last() = false;
    haptics_detail::last_ms() = 0;
    haptics_detail::last_popup_frame() = 0;
    haptics_detail::last_damage_frame() = 0;
    haptics_detail::last_popup_pulse_frame() = 0;
    haptics_detail::have_popup_pulse() = false;
}

// Per-frame service: called from the game's extended-view frame policy (the
// runtime's frame-start hook) with the guest's frame counter. Fires the armed
// pulse when the delay elapses. Late frames (pause, fast-forward frame gaps)
// still fire on the first frame past the target — a pulse never disappears,
// it only ever lands late.
inline void haptics_frame_service(std::uint64_t guest_frame) {
    auto& p = haptics_detail::pending();
    if (!p.armed) return;
    // Bounded release diagnostic (shares the hook's budget): proves the
    // frame policy path is live and shows the arm->release delta. Printed
    // once per arm — a per-frame line would eat the whole budget before the
    // PULSE fire line ever got its slot.
    if (!p.reported && haptics_detail::logged() < 64) {
        std::fprintf(stderr,
                     "[ffta] haptics: release-check f=%llu arm=%llu "
                     "grace=%llu popup=%llu\n",
                     static_cast<unsigned long long>(guest_frame),
                     static_cast<unsigned long long>(p.arm_frame),
                     static_cast<unsigned long long>(p.grace_frame),
                     static_cast<unsigned long long>(
                         haptics_detail::last_popup_frame()));
        p.reported = true;
        ++haptics_detail::logged();
    }
    const bool by_popup = p.popup_seen;
    const bool by_grace = guest_frame >= p.grace_frame;
    if (!by_popup && !by_grace) return;
    p.armed = false;
    // Sink-entry census line: fires for BOTH the pill and damage paths.
    // Distinguishes facade-reached (this line, from either caller) from
    // sink-reached (the android_haptics_pulse census inside the sink) —
    // a missing pill line means the facade never saw the call at all.
    if (haptics_detail::logged() < 64) {
        std::fprintf(stderr,
                     "[ffta] haptics: PULSE fire f=%llu strength=%.2f ms=%u%s\n",
                     static_cast<unsigned long long>(guest_frame),
                     static_cast<double>(p.strength),
                     static_cast<unsigned>(kHapticsPulseMs),
                     (!by_popup && by_grace) ? " (grace)" : "");
        ++haptics_detail::logged();
    }
    gbarecomp::host_primary_haptic(p.strength, kHapticsPulseMs);
}

// Shared arm path for both damage seams: strength profile, coalescing, and
// the armed pulse bookkeeping. Multi-hit attacks and AoE hits arrive in
// consecutive frames; one pulse per window keeps the phone from buzzing a
// dozen times per action. The subtraction is wrap-safe for the 32-bit
// millisecond clock. An already armed-but-not-yet-fired pulse also
// suppresses re-arming.
inline void haptics_arm(std::int32_t delta, std::uint32_t max_hp,
                        std::uint32_t gate) {
    const float strength = haptic_damage_strength(
        static_cast<std::uint32_t>(delta), max_hp);
    const std::uint32_t now = gbarecomp::real_host_clock().millis();
    const std::uint64_t now_frame = runtime_guest_frame_count();
    // Authorize the popup path for this damage burst. Every real HP apply
    // refreshes it, including coalesced ones: the Totema's numbers land
    // >1300 frames after the last apply, and every label must still fire.
    haptics_detail::last_damage_frame() = now_frame;
    const bool coalesced =
        haptics_detail::pending().armed ||
        (haptics_detail::have_last() &&
         static_cast<std::int32_t>(now - haptics_detail::last_ms()) <
             static_cast<std::int32_t>(kHapticsCoalesceMs));
    // Bounded first-eight diagnostic: same spirit as the lzss-guard / pad
    // census lines — enough to prove the seam live, never a log flood.
    if (haptics_detail::logged() < 64) {
        std::fprintf(stderr,
                     "[ffta] haptics: damage=%d max_hp=%u strength=%.2f "
                     "gate=0x%08X fire=popup(+%uf grace)%s\n",
                     static_cast<int>(delta), static_cast<unsigned>(max_hp),
                     static_cast<double>(strength), static_cast<unsigned>(gate),
                     static_cast<unsigned>(kHapticsFireGraceFrames),
                     coalesced ? " (coalesced)" : "");
        ++haptics_detail::logged();
    }
    // Same action: keep the strongest hit for the grace fallback. The popup
    // path fires per displayed number; the pending pulse is only the
    // no-popup safety net.
    if (coalesced) {
        auto& p = haptics_detail::pending();
        if (p.armed) p.strength = haptic_merge_strength(p.strength, strength);
        return;
    }
    haptics_detail::last_ms() = now;
    haptics_detail::have_last() = true;
    // Arm instead of firing: the frame policy releases the pulse when the
    // damage-number popup spawns (0x080A8BF8 display-element initializer) —
    // perfect sync for every animation length — or at the grace deadline if
    // no popup arrives. Frames come from the same counter the frame policy
    // consumes (ExtendedViewFrameInfo::frame_count = PPU frame_count).
    haptics_detail::pending().arm_frame = now_frame;
    haptics_detail::pending().grace_frame =
        now_frame + kHapticsFireGraceFrames;
    // A popup 0-2 frames BEFORE the apply (fast flows that hit and display
    // together) counts as this hit's popup. A "future" timestamp is stale
    // state surviving a savestate load (the mods reset callback does not run
    // on TCP loads — the epoch check in the frame policy also clears it).
    const std::uint64_t lp = haptics_detail::last_popup_frame();
    haptics_detail::pending().popup_seen =
        lp != 0 && lp <= now_frame && lp + 2 >= now_frame;
    haptics_detail::pending().strength = strength;
    haptics_detail::pending().armed = true;
    haptics_detail::pending().reported = false;
}

inline int haptics_damage_hook(std::uint32_t addr, int thumb,
                               ArmCpuState* cpu) {
    (void)addr;
    (void)thumb;
    // Match the helper's own interpretation: low 16 bits, sign-extended.
    const std::int16_t delta = static_cast<std::int16_t>(cpu->R[1] & 0xFFFFu);
    const std::uint32_t gate = bus_read_u32(kBattleGateCell);
    const bool fire = haptics_should_fire(delta, gate, cpu->R[14]);
    // Entry census (first 16 entries; own budget): proves the entry seam is
    // live and shows every decision's inputs, including filtered entries.
    if (haptics_detail::entry_logged() < 64) {
        ++haptics_detail::entry_logged();
        std::fprintf(stderr,
                     "[ffta] haptics: entry delta=%d gate=0x%08X lr=0x%08X "
                     "fire=%d\n",
                     static_cast<int>(delta), static_cast<unsigned>(gate),
                     static_cast<unsigned>(cpu->R[14]), fire ? 1 : 0);
    }
    if (!fire) return 0;

    const std::uint32_t max_hp = bus_read_u16(cpu->R[0] + 0x1Au);
    haptics_arm(delta, max_hp, gate);
    return 0;  // observer: never consume the guest call
}

// Second seam (2026-10-20, issue #30): the enemy-unit damage path writes the
// final HP directly instead of calling the 0x080A2210 delta helper. Proven
// by the abort-on-mem-write trace on a landed Air Render hit:
//   pc=0x080A3250 writes r1 (new hp) with r2 = unit;
//   block: ldrh r1,[r2,#0x1C]; subs r1, staged damage; clamp [0, max@0x1E];
//   strh r1,[r2,#0x1C].
// The helper (hp@+0x18 layout) is NOT executed for this flow — the hook at
// 0x080A2210 never fires, which is why enemy hits produced no haptics.
// Observer at the store's entry point: old hp still in memory, r1 = new hp,
// r2 = unit pointer. Delta = old - new (positive only; heals filtered).
inline int haptics_hp_store_hook(std::uint32_t addr, int thumb,
                                 ArmCpuState* cpu) {
    (void)addr;
    (void)thumb;
    const std::uint32_t unit = cpu->R[2];
    const std::uint32_t new_hp = cpu->R[1] & 0xFFFFu;
    const std::uint32_t old_hp = bus_read_u16(unit + 0x1Cu);
    const std::int32_t delta = static_cast<std::int32_t>(old_hp) -
                               static_cast<std::int32_t>(new_hp);
    const std::uint32_t gate = bus_read_u32(kBattleGateCell);
    const bool fire = delta > 0 && haptics_battle_gate(gate);
    // Entry census (shared 16-entry budget with the helper seam).
    if (haptics_detail::entry_logged() < 64) {
        ++haptics_detail::entry_logged();
        std::fprintf(stderr,
                     "[ffta] haptics: entry-store delta=%d gate=0x%08X "
                     "hp=%u->%u fire=%d\n",
                     static_cast<int>(delta), static_cast<unsigned>(gate),
                     static_cast<unsigned>(old_hp),
                     static_cast<unsigned>(new_hp), fire ? 1 : 0);
    }
    if (!fire) return 0;

    const std::uint32_t max_hp = bus_read_u16(unit + 0x1Eu);
    haptics_arm(delta, max_hp, gate);
    return 0;  // observer: never consume the guest call
}

// Release trigger (2026-10-20, issue #30): the display-element initializer
// at 0x080A8BF8 — the damage-number popup spawn (both parents tail-call /
// dispatch into this split root, so every popup init passes the guard).
// At entry: r2 = signed displayed value, r0 = abs(value) (stored to
// element+8), r8 = element kind, r5 = element.
//
// Per-label pulses (2026-10-22, user request): each damage number fires its
// own short pulse, rate-limited to kHapticsPopupPulseGapFrames so rapid
// multi-hits collapse. Kinds 0/1 are the player/enemy number elements and the
// sign is meaningful (positive damage, negative heal); kind 21 is the miss
// text. Authorization comes from the HP seams: a positive apply must have
// happened within the grace window, so heals, misses, and stray status
// numbers stay silent. The armed pending pulse remains the no-popup fallback.
inline int haptics_popup_hook(std::uint32_t addr, int thumb,
                              ArmCpuState* cpu) {
    (void)addr;
    (void)thumb;
    const std::uint64_t now_frame = runtime_guest_frame_count();
    haptics_detail::last_popup_frame() = now_frame;
    auto& p = haptics_detail::pending();
    const std::int16_t value =
        static_cast<std::int16_t>(cpu->R[2] & 0xFFFFu);
    const int kind = static_cast<int>(cpu->R[8] & 0xFFu);
    const bool damage_number = (kind == 0 || kind == 1) && value > 0;
    const std::uint64_t last_apply = haptics_detail::last_damage_frame();
    const bool authorized =
        damage_number && last_apply != 0 && now_frame >= last_apply &&
        now_frame - last_apply <= kHapticsFireGraceFrames;
    if (p.armed && authorized) p.popup_seen = true;

    bool fired = false;
    float fired_strength = 0.0f;
    if (authorized) {
        const bool rate_ok =
            !haptics_detail::have_popup_pulse() ||
            now_frame - haptics_detail::last_popup_pulse_frame() >=
                kHapticsPopupPulseGapFrames;
        if (rate_ok) {
            fired_strength =
                haptic_popup_strength(static_cast<std::uint32_t>(value));
            // This popup is the real release; do not also fire the armed
            // grace fallback for the same hit.
            p.armed = false;
            haptics_detail::last_popup_pulse_frame() = now_frame;
            haptics_detail::have_popup_pulse() = true;
            fired = true;
        }
    }

    // Bounded popup census (own budget): shows value/kind/armed/fire for the
    // first popups of the session — enough to verify the seam, never a
    // flood.
    if (haptics_detail::popup_logged() < 24) {
        ++haptics_detail::popup_logged();
        std::fprintf(stderr,
                     "[ffta] haptics: popup f=%llu value=%d kind=%d armed=%d "
                     "fire=%d\n",
                     static_cast<unsigned long long>(now_frame),
                     static_cast<int>(value), kind, p.armed ? 1 : 0,
                     fired ? 1 : 0);
    }
    if (fired) {
        if (haptics_detail::logged() < 64) {
            std::fprintf(stderr,
                         "[ffta] haptics: PULSE fire f=%llu strength=%.2f "
                         "ms=%u (popup)\n",
                         static_cast<unsigned long long>(now_frame),
                         static_cast<double>(fired_strength),
                         static_cast<unsigned>(kHapticsPulseMs));
            ++haptics_detail::logged();
        }
        gbarecomp::host_primary_haptic(fired_strength, kHapticsPulseMs);
    }
    return 0;  // observer: never consume the guest call
}

}  // namespace ffta
