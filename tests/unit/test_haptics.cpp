// Host unit tests for the issue-#30 battle-damage haptics policy
// (src/ffta_haptics.h + the arm/fire state machine in
// src/ffta_haptics_hook.h): battle-gate predicate, damage-filter rules, the
// damage->strength curve, and the frame-delay arming behavior. No
// ROM/BIOS/window needed — the arm/fire seams are pure given the frame
// number, so the animation-sync feature is locked here.
//
// The entry hook itself (bus reads, host routing) is covered by the live
// battle replay/device route, not by this pure suite.
#include "../../src/ffta_haptics.h"
#include "../../src/ffta_haptics_hook.h"

#include <cmath>
#include <cstdint>
#include <cstdio>

namespace {

int haptics_failures = 0;

#define HAPTIC_CHECK(cond)                                                  \
    do {                                                                    \
        if (!(cond)) {                                                      \
            std::printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);     \
            ++haptics_failures;                                             \
        }                                                                   \
    } while (0)

bool close_to(float a, float b) {
    return std::fabs(a - b) < 1e-5f;
}

}  // namespace

int run_haptics_tests() {
    using namespace ffta;  // haptics_detail, kHaptics*, haptics_* helpers
    using ffta::haptic_damage_strength;
    using ffta::haptics_should_fire;
    using ffta::haptics_battle_gate;
    using ffta::kHpSwapReturn;
    using ffta::kHpSwapReturnThumb;

    // ── battle gate: plausible EWRAM object pointers only ────────────────
    HAPTIC_CHECK(haptics_battle_gate(0x02000000u));
    HAPTIC_CHECK(haptics_battle_gate(0x0200F4E8u));  // state1 battle object
    HAPTIC_CHECK(haptics_battle_gate(0x0203FFFFu));
    HAPTIC_CHECK(!haptics_battle_gate(0x01FFFFFFu));
    HAPTIC_CHECK(!haptics_battle_gate(0x02040000u));
    HAPTIC_CHECK(!haptics_battle_gate(0x0u));

    // ── damage filter: positive, in battle, not the HP/MP swap ───────────
    constexpr std::uint32_t kGate = 0x0200F4E8u;
    HAPTIC_CHECK(haptics_should_fire(79, kGate, 0x080A3167u));
    HAPTIC_CHECK(haptics_should_fire(1, kGate, 0x080A3167u));
    HAPTIC_CHECK(!haptics_should_fire(0, kGate, 0x080A3167u));
    HAPTIC_CHECK(!haptics_should_fire(-1, kGate, 0x080A3167u));  // heal
    HAPTIC_CHECK(!haptics_should_fire(79, 0x01000000u, 0x080A3167u));
    HAPTIC_CHECK(!haptics_should_fire(79, kGate, kHpSwapReturn));
    HAPTIC_CHECK(!haptics_should_fire(79, kGate, kHpSwapReturnThumb));

    // ── strength: 0.35 floor + 0.65 * damage/maxHP, capped at 1.0 ────────
    HAPTIC_CHECK(haptic_damage_strength(0, 100) == 0.0f);
    HAPTIC_CHECK(close_to(haptic_damage_strength(1, 100), 0.3565f));
    HAPTIC_CHECK(close_to(haptic_damage_strength(50, 100), 0.675f));
    HAPTIC_CHECK(close_to(haptic_damage_strength(100, 100), 1.0f));
    HAPTIC_CHECK(close_to(haptic_damage_strength(200, 100), 1.0f));
    HAPTIC_CHECK(close_to(haptic_damage_strength(1, 1), 1.0f));
    // Implausible max HP falls back to full strength, never under-drives.
    HAPTIC_CHECK(close_to(haptic_damage_strength(1, 0), 1.0f));
    HAPTIC_CHECK(close_to(haptic_damage_strength(1, 1000), 1.0f));
    HAPTIC_CHECK(close_to(haptic_damage_strength(1, 999), 0.35065f));
    HAPTIC_CHECK(close_to(haptic_damage_strength(65535, 999), 1.0f));
    HAPTIC_CHECK(close_to(haptic_damage_strength(65535, 0), 1.0f));

    // ── popup-synced release: arm at hit, fire when the damage-number
    // popup spawns (or at the grace deadline) ────────────────────────────
    // (measured gaps: fast melee ~22 frames, Air Render ~240 — the display
    // hook makes the sync exact for every animation.)
    using ffta::haptics_frame_service;
    using ffta::haptics_reset;
    constexpr std::uint64_t kGrace = ffta::kHapticsFireGraceFrames;
    HAPTIC_CHECK(kGrace == 2400);

    haptics_reset();
    // Nothing armed: frame service is a no-op.
    haptics_frame_service(1'000'000);
    HAPTIC_CHECK(!haptics_detail::pending().armed);

    // Simulate a hit: arm directly (the guest hooks need a CPU/bus; the
    // arming contract is what we lock here).
    haptics_detail::pending().arm_frame = 1000;
    haptics_detail::pending().grace_frame = 1000 + kGrace;
    haptics_detail::pending().strength = 0.77f;
    haptics_detail::pending().armed = true;
    haptics_detail::pending().popup_seen = false;

    // No popup yet: armed, silent.
    haptics_frame_service(1000);
    haptics_frame_service(1100);
    HAPTIC_CHECK(haptics_detail::pending().armed);

    // Popup spawns: the next service tick releases and disarms.
    haptics_detail::pending().popup_seen = true;
    haptics_frame_service(1101);
    HAPTIC_CHECK(!haptics_detail::pending().armed);

    // Frames after: no re-fire (one pulse per hit).
    haptics_frame_service(1102);
    haptics_frame_service(1200);

    // No popup ever (unknown display path): the grace deadline releases.
    haptics_detail::pending().arm_frame = 2000;
    haptics_detail::pending().grace_frame = 2000 + kGrace;
    haptics_detail::pending().strength = 0.5f;
    haptics_detail::pending().armed = true;
    haptics_detail::pending().popup_seen = false;
    haptics_frame_service(2000 + kGrace - 1);
    HAPTIC_CHECK(haptics_detail::pending().armed);
    haptics_frame_service(2000 + kGrace);  // grace deadline
    HAPTIC_CHECK(!haptics_detail::pending().armed);

    // Long animation (Totema, 2026-10-22): the damage numbers can land well
    // past 900 frames. The pulse must stay armed through the old deadline and
    // release on the popup, not fire early at grace.
    haptics_detail::pending().arm_frame = 5000;
    haptics_detail::pending().grace_frame = 5000 + kGrace;
    haptics_detail::pending().strength = 0.74f;
    haptics_detail::pending().armed = true;
    haptics_detail::pending().popup_seen = false;
    haptics_frame_service(5000 + 1500);  // past the old 900-frame window
    HAPTIC_CHECK(haptics_detail::pending().armed);
    haptics_detail::pending().popup_seen = true;
    haptics_frame_service(5000 + 1501);
    HAPTIC_CHECK(!haptics_detail::pending().armed);

    // Coalesced hits keep the strongest request for the grace fallback: a
    // multi-target Totema first hit 72/121 (0.74), later hits 101/100 (1.00).
    HAPTIC_CHECK(haptic_merge_strength(0.74f, 1.0f) == 1.0f);
    HAPTIC_CHECK(haptic_merge_strength(0.74f, 0.50f) == 0.74f);
    HAPTIC_CHECK(haptic_merge_strength(0.74f, 0.74f) == 0.74f);

    // Per-label popup strength: the displayed number is the scale (100-ref).
    HAPTIC_CHECK(haptic_popup_strength(0) == 0.0f);
    HAPTIC_CHECK(close_to(haptic_popup_strength(50), 0.675f));
    HAPTIC_CHECK(close_to(haptic_popup_strength(84), 0.896f));
    HAPTIC_CHECK(close_to(haptic_popup_strength(100), 1.0f));
    HAPTIC_CHECK(close_to(haptic_popup_strength(200), 1.0f));

    // Late service (pause/frame gap): a frame past the grace still fires on
    // the first frame the policy sees — a pulse never disappears.
    haptics_detail::pending().arm_frame = 3000;
    haptics_detail::pending().grace_frame = 3000 + kGrace;
    haptics_detail::pending().strength = 0.5f;
    haptics_detail::pending().armed = true;
    haptics_frame_service(3000 + kGrace + 500);  // way late
    HAPTIC_CHECK(!haptics_detail::pending().armed);

    // Reset clears an armed pulse (savestate restore mid-window).
    haptics_detail::pending().arm_frame = 4000;
    haptics_detail::pending().grace_frame = 4000 + kGrace;
    haptics_detail::pending().armed = true;
    haptics_detail::last_damage_frame() = 4000;
    haptics_detail::have_popup_pulse() = true;
    haptics_reset();
    HAPTIC_CHECK(!haptics_detail::pending().armed);
    HAPTIC_CHECK(haptics_detail::last_damage_frame() == 0);
    HAPTIC_CHECK(!haptics_detail::have_popup_pulse());

    // Wrap-safety of the frame comparison is trivial (u64); but the
    // arm-time clock (PPU frame_count) is also u64 — no wrap in practice.

    return haptics_failures;
}
