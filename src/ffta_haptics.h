#pragma once
// FFTA battle-damage haptics policy (issue #30, Phase 4).
//
// The HP helper at 0x080A2210 is the single entry every HP delta passes
// through. Disasm: r0 = unit pointer, r1 = signed amount (the helper keeps the
// low 16 bits and sign-extends them), and it writes `hp = clamp(hp - amount,
// 0, max_hp)` at `strh r5,[r6,#0x18]` (0x080A2298). Max HP is the u16 at
// unit+0x1A (accessor 0x080C7EA4 arg 0x14 returns it directly).
//
// The hook is an observer: it returns 0 so the guest body still runs. It only
// reacts when the battle gate cell [0x0200F4A8] holds a plausible EWRAM
// pointer (installed at 0x08096C26, cleared at 0x08096CCC) and the delta is
// positive. The HP<->MP swap call site (0x080A337E, return LR 0x080A3382/3)
// passes `curHP-curMP` and is not damage, so it is excluded.
#include <cstdint>

namespace ffta {

inline constexpr std::uint32_t kBattleGateCell = 0x0200F4A8u;
// `bl 0x080A2210` at 0x080A337E; Thumb callers return with bit 0 set.
inline constexpr std::uint32_t kHpSwapReturn = 0x080A3382u;
inline constexpr std::uint32_t kHpSwapReturnThumb = 0x080A3383u;

inline constexpr std::uint32_t kHapticsPulseMs = 120u;
inline constexpr std::uint32_t kHapticsCoalesceMs = 120u;
// Popup-driven pulses: one per displayed damage number, rate-limited to the
// same 120 ms window (8 guest frames at 60 Hz). A multi-hit burst that draws
// several numbers in one frame still collapses to one pulse.
inline constexpr std::uint32_t kHapticsPopupPulseGapFrames = 8u;
// The popup path has no target max HP (the display element carries only the
// number), so it scales the displayed damage against this reference. 100 is
// the observed full-bar-ish hit; anything above caps at 1.0.
inline constexpr std::uint32_t kHapticsPopupReferenceDamage = 100u;
// The armed pulse is released when the game spawns the damage-number popup
// (the 0x080A8BF8 display-element initializer), so the buzz lands with the
// number for EVERY flow — the gap between the HP apply and the popup varies
// per animation (measured: fast melee ~22 frames; Air Render ~240; Totema
// summon >900, with the numbers landing after the old 900-frame deadline —
// BRINGUP 2026-10-22). If no popup arrives (unknown display path), the pulse
// still fires at the grace deadline — late, never lost. The deadline must
// exceed the longest animation, or a long summon fires early at the deadline
// and coalesces its remaining hits.
inline constexpr std::uint64_t kHapticsFireGraceFrames = 2400u;

// Battle state installs a battle object pointer into this EWRAM cell for the
// duration of a fight. The range is deliberately loose: any object in EWRAM is
// plausible; the gate only needs to reject the world map / menu values.
inline bool haptics_battle_gate(std::uint32_t value) {
    return value >= 0x02000000u && value < 0x02040000u;
}

// Fire only on real damage: positive signed delta, live battle, not the HP/MP
// swap pseudo-damage. Heals arrive negative and are filtered here.
inline bool haptics_should_fire(std::int32_t amount, std::uint32_t gate,
                                std::uint32_t lr) {
    return amount > 0 && haptics_battle_gate(gate) &&
           lr != kHpSwapReturn && lr != kHpSwapReturnThumb;
}

// Fixed impact profile: 0.35 floor + 0.65 * (damage / max HP), capped at 1.0.
// An implausible max HP (0, or outside the game's 1..999 sanity band) falls
// back to full strength rather than under-driving a real hit.
inline float haptic_damage_strength(std::uint32_t amount,
                                    std::uint32_t max_hp) {
    if (amount == 0) return 0.0f;
    float ratio = 1.0f;
    if (max_hp >= 1u && max_hp <= 999u) {
        ratio = static_cast<float>(amount) / static_cast<float>(max_hp);
        if (ratio > 1.0f) ratio = 1.0f;
    }
    return 0.35f + 0.65f * ratio;
}

// Strongest request wins when a later hit coalesces into an already-armed
// pulse. A multi-target summon applies one burst: keeping the first hit
// under-drove the Totema pulse (0.74) while later hits were 1.00.
inline float haptic_merge_strength(float pending, float incoming) {
    return incoming > pending ? incoming : pending;
}

// Strength for a popup-driven pulse. The displayed number is the only scale
// available at the popup, so use the 100-damage reference above. Same floor
// and span as haptic_damage_strength().
inline float haptic_popup_strength(std::uint32_t value) {
    if (value == 0) return 0.0f;
    float ratio = static_cast<float>(value) /
                  static_cast<float>(kHapticsPopupReferenceDamage);
    if (ratio > 1.0f) ratio = 1.0f;
    return 0.35f + 0.65f * ratio;
}

}  // namespace ffta
