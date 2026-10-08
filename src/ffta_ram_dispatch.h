#pragma once
// FFTA save/flash RAM-code canonicalizer.
//
// FFTA's save/flash driver relocates short POSITION-INDEPENDENT helpers into
// its own stack frame and calls them by computed address (live copies observed
// at 0x03007CA2..0x03007E86 across sessions — see BRINGUP.md § Phase 4/5
// save-flow entries and the game.toml [[code_copy]] batch-t block). The copy
// address moves with the stack, so the fixed dispatch table can resume a
// stale AOT body at the wrong offset (the load-hang: a fresh copy whose
// prologue sits at 0x03007D74 was entered at the old copy's loop body, the
// prologue was skipped and the byte-copy loop ran away).
//
// This hook byte-verifies the live RAM bytes against the routine's ROM source
// before every RAM-range dispatch and runs the canonical generated body
// instead. A reused scratch slot that no longer holds the routine falls
// through to the normal dispatcher. Pattern follows
// EmeraldRecomp src/emerald_ram_dispatch.h (same framework hook).
#include "runtime_arm.h"
#include <cstdio>

extern "C" void gf_tfunc_03007D64(void);  // byte-copy    <- ROM 0x08141AF0 (0x24)
extern "C" void gf_tfunc_03007CE4(void);  // byte-compare <- ROM 0x08141BB0 (0x2E)
extern "C" void gf_tfunc_03007D48(void);  // ldrb r0,[r0]; bx lr getter

namespace ffta {

inline bool ram_matches_rom(uint32_t ram_pc, uint32_t rom_pc, uint32_t size) {
    for (uint32_t offset = 0; offset < size; ++offset)
        if (bus_read_u8(ram_pc + offset) != bus_read_u8(rom_pc + offset))
            return false;
    return true;
}

// Defensive fixups for the corrupted-copy class (BRINGUP § "Summon crash" /
// "Save-flow divergence"). Two shapes observed:
//  * r2 == 0xFFFFFFFF (the routine's own loop sentinel) with a valid-ish
//    context: an interrupted copy RESUMED at its entry — the true remaining
//    count survives in r3; reconstruct it.
//  * any other implausible count (e.g. 0xFF00CE7F / 0xFF01010F): a garbage
//    descriptor from a stale frame — clamp to a bounded no-op.
// Legitimate counts observed are <= 0x1000. Both shapes would otherwise run
// a multi-gigabyte runaway and corrupt IWRAM.
inline void copy_entry_fixup(uint32_t pc) {
    uint32_t r2 = g_cpu.R[2];
    if (r2 <= 0x10000u) return;
    if (r2 == 0xFFFFFFFFu) {
        uint32_t count = g_cpu.R[3] + 1u;
        if (count <= 0x10000u) { g_cpu.R[2] = count; return; }
    }
    static uint32_t logged = 0;
    if (logged < 32) {
        std::fprintf(stderr,
                     "[ffta] copy-guard: clamped count=0x%08X r3=0x%08X r0=0x%08X r1=0x%08X pc=0x%08X\n",
                     r2, g_cpu.R[3], g_cpu.R[0], g_cpu.R[1], pc);
        ++logged;
    }
    g_cpu.R[2] = 0;
}

// Runs before the fixed dispatch table for every RAM-range (0x02-0x03) target.
// Returns non-zero after running a byte-verified canonical body.
inline int ram_dispatch(uint32_t pc, int thumb) {
    if (!thumb) return 0;
    // iwram_byte_copy — also covers the 2-byte-offset re-plant at 0x03007CA4
    // (its entry bytes are ROM 0x08141AF0 verbatim).
    if (ram_matches_rom(pc, 0x08141AF0u, 0x24u)) { copy_entry_fixup(pc); gf_tfunc_03007D64(); return 1; }
    // Observed corrupted re-entries dispatch two bytes BEFORE a fresh plant
    // (pc=0x03007D72, routine at 0x03007D74): treat as the copy too.
    //
    // GUARD: r2==0xFFFFFFFF means this dispatch is the setup fragment's own
    // mid-body fall-through (its `rsbs` already ran) — e.g. an entry at a
    // 0x03007D74 plant runs gf_tfunc_03007D64, which ends by dispatching
    // 0x03007D72 with r2==-1. Re-entering the setup there recursed
    // infinitely (8-byte stack leak per cycle, IRQ fired mid-march, save-load
    // abort 0x700200F2). Mid-run crossings must fall through to the fixed
    // table: 0x03007D72 = the loop-body unit, whose entry registers are
    // exactly the routine's loop state (r2=-1, r3=count-1, r4=src, r1=dst)
    // -> loop -> 0x03007D80 tail pops and returns to the driver.
    if (pc == 0x03007D72u && g_cpu.R[2] != 0xFFFFFFFFu &&
        ram_matches_rom(pc + 2u, 0x08141AF0u, 0x24u)) {
        copy_entry_fixup(pc); gf_tfunc_03007D64(); return 1;
    }
    // iwram_byte_compare.
    if (ram_matches_rom(pc, 0x08141BB0u, 0x2Eu)) { gf_tfunc_03007CE4(); return 1; }
    // iwram_{flash,save}_getter (00 78 70 47) — planted at 0x03007D48/7D9C/7E00/7E60.
    if (ram_matches_rom(pc, 0x08141AACu, 0x04u)) { gf_tfunc_03007D48(); return 1; }
    return 0;
}

}  // namespace ffta
