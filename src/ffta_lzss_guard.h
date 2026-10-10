#pragma once
// FFTA LZSS decompressor entry guard (mod_function_hook "ffta.lzss-guard").
//
// The decoder at 0x0800543C reads its output length from the source header
// (big-endian at src+0, stream at src+4). The save-menu/summon divergence
// re-enters it with a corrupted source pointer; the decoded length then
// reads ~4G and the track-back copy loop (0x08005558) never ends. Check the
// header at the entry: an implausible call is skipped back to the caller
// (bounded degradation, logged) instead of hanging. BRINGUP § "Summon crash".
//
// Registered from src/main.cpp (GBA_MOD_CONSTRUCTOR) at 0x0800543C, thumb;
// re-armed by the mods reset callback and once more at startup (paths that
// skip the activation pass). Extracted to a header so the host unit suite
// can exercise it directly (tests/unit/test_ram_dispatch.cpp) — the
// anonymous-namespace original was not linkable from the test binary.
#include "runtime_arm.h"

#include <cstdio>

namespace ffta {

inline int lzss_entry_guard(uint32_t addr, int thumb, ArmCpuState* cpu) {
    (void)addr;
    (void)thumb;
    const uint32_t src = cpu->R[1];
    const uint32_t len = (uint32_t(bus_read_u8(src)) << 24) |
                         (uint32_t(bus_read_u8(src + 1)) << 16) |
                         (uint32_t(bus_read_u8(src + 2)) << 8) |
                         uint32_t(bus_read_u8(src + 3));
    if (len > 0x100000u) {
        static uint32_t logged = 0;
        if (logged < 32) {
            std::fprintf(stderr,
                         "[ffta] lzss-guard: implausible length=0x%08X src=0x%08X "
                         "dst=0x%08X; skipping decompress\n",
                         len, src, cpu->R[0]);
            ++logged;
        }
        cpu->R[15] = cpu->R[14] & ~1u;  // return to the guest caller
        return 1;                       // handled: skip the original body
    }
    return 0;  // plausible call: decline (CPU writes discarded, body runs)
}

}  // namespace ffta