#pragma once
// ffta_cheats.h — issue #22 first cheat: no-laws runtime poke.
// Covers CB raw 42003C34 0000 / 00000003 0002: zero EWRAM 0x02003C34
// (gBattleLaws, 3B) as 4x u16 stride-2 (8B) for the x4 multi-write shape.
// Header-only pure logic so the host unit suite links without SDL/ROM
// (same pattern as ffta_speed_boost.h / ffta_haptics.h).
#include <cstdint>
namespace ffta {
inline constexpr uint32_t kNoLawsAddr = 0x02003C34u;
inline constexpr int kNoLawsWrites = 4;
inline bool& cheats_no_laws_flag() {
    static bool on = false;
    return on;
}
inline void cheats_set_no_laws(bool on) { cheats_no_laws_flag() = on; }
inline bool cheats_no_laws_enabled() { return cheats_no_laws_flag(); }
inline void cheats_reset() { cheats_no_laws_flag() = false; }
template <typename WriteU16>
inline void cheats_apply_no_laws(WriteU16 write_u16) {
    if (!cheats_no_laws_enabled()) return;
    for (int i = 0; i < kNoLawsWrites; ++i)
        write_u16(kNoLawsAddr + static_cast<uint32_t>(i * 2), 0u);
}
}  // namespace ffta
