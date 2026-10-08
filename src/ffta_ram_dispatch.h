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
// through to the normal dispatcher. Pattern follows EmeraldRecomp
// src/emerald_ram_dispatch.h (same framework hook; github.com/mstan/
// EmeraldRecomp — PolyForm Noncommercial 1.0.0; pattern only, no code
// copied — see THIRD_PARTY_ATTRIBUTION.md).
#include "runtime_arm.h"
#include <cstdio>
#include <cstdlib>

extern "C" void gf_tfunc_03007D64(void);  // byte-copy    <- ROM 0x08141AF0 (0x24)
extern "C" void gf_tfunc_03007CE4(void);  // byte-compare <- ROM 0x08141BB0 (0x2E)
extern "C" void gf_tfunc_03007D48(void);  // ldrb r0,[r0]; bx lr getter
extern "C" void gf_afunc_03002B70(void);  // ARM IRQ buffer rotate <- ROM 0x08005088 (0x40)

namespace ffta {

// TEMP instrumentation (FFTA_DISPATCH_LOG=1): log copy-family hook decisions.
inline void dispatch_log(const char* what, uint32_t pc) {
    static const bool on = std::getenv("FFTA_DISPATCH_LOG") != nullptr;
    if (!on || pc < 0x03002000u || pc > 0x03008000u) return;
    std::fprintf(stderr, "[dl] %-14s pc=%08X r2=%08X r3=%08X r0=%08X r1=%08X sp=%08X lr=%08X\n",
                 what, pc, g_cpu.R[2], g_cpu.R[3], g_cpu.R[0], g_cpu.R[1],
                 g_cpu.R[13], g_cpu.R[14]);
}

inline bool ram_matches_rom(uint32_t ram_pc, uint32_t rom_pc, uint32_t size) {
    for (uint32_t offset = 0; offset < size; ++offset)
        if (bus_read_u8(ram_pc + offset) != bus_read_u8(rom_pc + offset))
            return false;
    return true;
}

// Defensive fixup for the corrupted-copy class (BRINGUP § "Summon crash" /
// "Save-flow divergence"): an implausible count (e.g. 0xFF00CE7F /
// 0xFF01010F, or the sentinel 0xFFFFFFFF arriving as a "count") is a
// garbage descriptor from a stale frame — clamp to a bounded no-op, else
// the loop runs a multi-gigabyte runaway and corrupts IWRAM. Legitimate
// counts observed are <= 0x1000. Note: r2 == 0xFFFFFFFF never reaches here
// from ram_dispatch — resume-passthru handles it first (it is a loop-state
// sentinel, never a count).
inline void copy_entry_fixup(uint32_t pc) {
    uint32_t r2 = g_cpu.R[2];
    if (r2 <= 0x10000u) return;
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
    dispatch_log("enter", pc);
    if (!thumb) {
        // ARM-planted IRQ-critical helper (batch ah, link-feature session):
        // IE-off 8-word rotate at [0x030028A0]+0x40, ROM 0x08005088 (0x40
        // bytes). The hook previously handled thumb only; canonicalize the
        // live copy so any plant address resumes the generated body.
        if (ram_matches_rom(pc, 0x08005088u, 0x40u)) {
            dispatch_log("arm-rotate", pc);
            gf_afunc_03002B70(); return 1;
        }
        return 0;
    }
    // Mid-copy resumes (r2 == the loop sentinel 0xFFFFFFFF) must NEVER run the
    // canonical body from the top: the copy is already in progress (prologue
    // pushed, loop registers live in r1/r3/r4). Re-running the body pushes a
    // second frame and re-runs the setup (r4 <- r0), tearing the caller's
    // stack by 8 — observed as the driver epilogue popping the scan-buffer
    // pointer and branching into 0x02003CB0 (route_G strict abort, 2026-10-08;
    // the driver re-plants helpers at its stack pointer, so a resumed loop PC
    // can coincide with a fresh plant and byte-match the routine start).
    // Falling through to the fixed table continues correctly: 0x03007D72..
    // 0x03007D7E are the loop unit's resume labels, whose entry registers are
    // exactly the live loop state (r3=count-1, r4=src, r1=dst) -> loop ->
    // 0x03007D80 tail pops the ORIGINAL prologue's frame and returns to the
    // driver. A "fresh call" never carries r2==-1 (counts are <= 0x1000).
    if (g_cpu.R[2] == 0xFFFFFFFFu) {
        dispatch_log("resume-passthru", pc);
        return 0;
    }
    // iwram_byte_copy — also covers the 2-byte-offset re-plant at 0x03007CA4
    // (its entry bytes are ROM 0x08141AF0 verbatim).
    if (ram_matches_rom(pc, 0x08141AF0u, 0x24u)) {
        dispatch_log("case1-copy", pc);
        copy_entry_fixup(pc); gf_tfunc_03007D64(); return 1;
    }
    // Observed corrupted re-entries dispatch two bytes BEFORE a fresh plant
    // (pc=0x03007D72, routine at 0x03007D74): treat as the copy too. Only
    // fresh calls reach here — mid-copy (r2==-1) resumes fell through above.
    if (pc == 0x03007D72u &&
        ram_matches_rom(pc + 2u, 0x08141AF0u, 0x24u)) {
        dispatch_log("case2-2early", pc);
        copy_entry_fixup(pc); gf_tfunc_03007D64(); return 1;
    }
    // iwram_byte_compare.
    if (ram_matches_rom(pc, 0x08141BB0u, 0x2Eu)) {
        dispatch_log("compare", pc);
        gf_tfunc_03007CE4(); return 1;
    }
    // iwram_{flash,save}_getter (00 78 70 47) — planted at 0x03007D48/7D9C/7E00/7E60.
    if (ram_matches_rom(pc, 0x08141AACu, 0x04u)) {
        dispatch_log("getter", pc);
        gf_tfunc_03007D48(); return 1;
    }
    dispatch_log("fall", pc);
    return 0;
}

}  // namespace ffta
