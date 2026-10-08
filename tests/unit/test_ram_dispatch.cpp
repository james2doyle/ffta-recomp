// Host unit tests for src/ffta_ram_dispatch.h — the FFTA save/flash RAM-code
// canonicalizer hook. No ROM/BIOS needed: the fake bus serves synthetic
// patterns (deliberately NOT ROM-derived bytes), and the generated bodies
// are stubbed.
//
// Run:  cmake --build build --target ffta_unit_tests && ./build/ffta_unit_tests
//   or: ctest --test-dir build --output-on-failure
#include "ffta_ram_dispatch.h"

#include <cstdio>
#include <cstring>

// ── stubs: CPU global, fake bus, generated bodies ───────────────────
extern "C" {
ArmCpuState g_cpu;
}

namespace {

uint8_t g_iwram[0x10000];  // guest 0x03000000..0x0300FFFF
uint8_t g_rom[0x400];      // guest 0x08141A00..0x08141DFF (source snippets)

int g_copy_calls = 0;
int g_compare_calls = 0;
int g_getter_calls = 0;
uint32_t g_copy_entry_r2 = 0;

constexpr uint32_t IWRAM_BASE = 0x03000000u;
constexpr uint32_t ROM_BASE = 0x08141A00u;

void pattern(uint8_t* p, size_t n, uint8_t seed) {
    for (size_t i = 0; i < n; ++i) p[i] = static_cast<uint8_t>(seed + i * 7u);
}

void bus_poke(uint32_t addr, const uint8_t* src, size_t len) {
    if (addr >= IWRAM_BASE && addr + len <= IWRAM_BASE + 0x10000u) {
        std::memcpy(g_iwram + (addr - IWRAM_BASE), src, len);
    } else if (addr >= ROM_BASE && addr + len <= ROM_BASE + 0x400u) {
        std::memcpy(g_rom + (addr - ROM_BASE), src, len);
    } else {
        std::fprintf(stderr, "bus_poke: bad range %08X+%zu\n", addr, len);
    }
}

// Plant the SAME synthetic "routine" at both the IWRAM address and the ROM
// source address the hook byte-verifies against.
void plant_pair(uint32_t ram_pc, uint32_t rom_pc, size_t len, uint8_t seed) {
    uint8_t buf[0x80];
    pattern(buf, len, seed);
    bus_poke(ram_pc, buf, len);
    bus_poke(rom_pc, buf, len);
}

void reset_state() {
    std::memset(&g_cpu, 0, sizeof(g_cpu));
    std::memset(g_iwram, 0, sizeof(g_iwram));
    std::memset(g_rom, 0, sizeof(g_rom));
    g_copy_calls = g_compare_calls = g_getter_calls = 0;
    g_copy_entry_r2 = 0;
}

int g_failures = 0;
#define CHECK(cond)                                                     \
    do {                                                                \
        if (!(cond)) {                                                  \
            std::printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond); \
            ++g_failures;                                               \
        }                                                               \
    } while (0)

}  // namespace

extern "C" uint8_t bus_read_u8(uint32_t addr) {
    if (addr >= IWRAM_BASE && addr < IWRAM_BASE + 0x10000u)
        return g_iwram[addr - IWRAM_BASE];
    if (addr >= ROM_BASE && addr < ROM_BASE + 0x400u)
        return g_rom[addr - ROM_BASE];
    return 0xFFu;
}

extern "C" void gf_tfunc_03007D64(void) {
    ++g_copy_calls;
    g_copy_entry_r2 = g_cpu.R[2];
    // Mimic the setup fragment's tail state: its `rsbs` has run, so a
    // subsequent dispatch of the split boundary carries r2 == -1.
    g_cpu.R[2] = 0xFFFFFFFFu;
}

extern "C" void gf_tfunc_03007CE4(void) { ++g_compare_calls; }
extern "C" void gf_tfunc_03007D48(void) { ++g_getter_calls; }

int main() {
    using ffta::copy_entry_fixup;
    using ffta::ram_dispatch;

    // ── copy_entry_fixup semantics ──────────────────────────────────
    reset_state();
    g_cpu.R[2] = 0x1000u;  // legitimate count: untouched
    copy_entry_fixup(0x03007D74u);
    CHECK(g_cpu.R[2] == 0x1000u);

    reset_state();
    g_cpu.R[2] = 0xFFFFFFFFu;  // the loop sentinel is not a count: clamp
    g_cpu.R[3] = 0x00000FFFu;
    copy_entry_fixup(0x03007D74u);
    CHECK(g_cpu.R[2] == 0x0u);

    reset_state();
    g_cpu.R[2] = 0xFFFFFFFFu;  // out of range reconstruction -> no-op
    g_cpu.R[3] = 0x00010000u;
    copy_entry_fixup(0x03007D74u);
    CHECK(g_cpu.R[2] == 0x0u);

    reset_state();
    g_cpu.R[2] = 0xFF00CE7Fu;  // garbage descriptor -> clamped no-op
    copy_entry_fixup(0x03007D74u);
    CHECK(g_cpu.R[2] == 0x0u);

    // ── copy: entry exactly at the plant (branch A) ─────────────────
    reset_state();
    plant_pair(0x03007D74u, 0x08141AF0u, 0x24u, 0x11);
    g_cpu.R[2] = 0x1000u;
    CHECK(ram_dispatch(0x03007D74u, 1) == 1);
    CHECK(g_copy_calls == 1);
    CHECK(g_copy_entry_r2 == 0x1000u);

    // ── REGRESSION (2026-10-08): the setup fragment's mid-body crossing ──
    // After gf_tfunc_03007D64 ran, the dispatch of the split boundary
    // 0x03007D72 carries r2 == -1. Re-entering the setup there recursed
    // infinitely (stack march -> IRQ-table tear -> save-load abort). The
    // hook must fall through to the fixed table instead.
    reset_state();
    plant_pair(0x03007D74u, 0x08141AF0u, 0x24u, 0x11);
    g_cpu.R[2] = 0xFFFFFFFFu;  // post-rsbs boundary state
    g_cpu.R[3] = 0x00000FFFu;
    CHECK(ram_dispatch(0x03007D72u, 1) == 0);
    CHECK(g_copy_calls == 0);

    // ── REGRESSION (route_G, 2026-10-08): a mid-copy resume can land ON the
    // fresh re-plant address — the driver re-plants the helper at its stack
    // pointer, so the resume PC byte-matches the routine start. The old hook
    // re-ran the canonical body from the top there (second push + setup
    // re-run), tearing the driver's frame by 8; its epilogue then popped the
    // staging-buffer pointer and branched into 0x02003CB0. A resume
    // (r2 == -1) must pass through from ANY address, even a byte-matching
    // plant: never a fresh call.
    reset_state();
    plant_pair(0x03007D74u, 0x08141AF0u, 0x24u, 0x11);
    g_cpu.R[2] = 0xFFFFFFFFu;  // live mid-copy state (r3/r1/r4 carried)
    g_cpu.R[3] = 0x00000D5Fu;
    CHECK(ram_dispatch(0x03007D74u, 1) == 0);
    CHECK(g_copy_calls == 0);

    // Chained form of the same scenario through the stub.
    reset_state();
    plant_pair(0x03007D74u, 0x08141AF0u, 0x24u, 0x11);
    g_cpu.R[2] = 0x1000u;
    CHECK(ram_dispatch(0x03007D74u, 1) == 1);   // entry at the plant
    CHECK(g_copy_calls == 1);
    CHECK(g_cpu.R[2] == 0xFFFFFFFFu);           // stub left the crossing state
    CHECK(ram_dispatch(0x03007D72u, 1) == 0);   // crossing: must not re-fire
    CHECK(g_copy_calls == 1);
    CHECK(ram_dispatch(0x03007D74u, 1) == 0);   // resume at the plant: passthrough
    CHECK(g_copy_calls == 1);

    // A fresh two-byte-early entry (real count) is still serviced.
    reset_state();
    plant_pair(0x03007D74u, 0x08141AF0u, 0x24u, 0x11);
    g_cpu.R[2] = 0x1000u;
    g_cpu.R[3] = 0x00000FFFu;
    CHECK(ram_dispatch(0x03007D72u, 1) == 1);
    CHECK(g_copy_calls == 1);
    CHECK(g_copy_entry_r2 == 0x1000u);

    // Unrelated address: no match. (Real ROM sources are never all-zero;
    // give the checkable source slots non-zero content so a zero-filled
    // RAM region cannot spuriously match the byte-verify, as it cannot
    // against real ROM bytes.)
    reset_state();
    {
        uint8_t buf[0x80];
        pattern(buf, 0x24u, 0x11); bus_poke(0x08141AF0u, buf, 0x24u);
        pattern(buf, 0x2Eu, 0x22); bus_poke(0x08141BB0u, buf, 0x2Eu);
        pattern(buf, 0x04u, 0x33); bus_poke(0x08141AACu, buf, 0x04u);
    }
    CHECK(ram_dispatch(0x03005000u, 1) == 0);

    // ARM mode is never serviced by this hook.
    reset_state();
    plant_pair(0x03007D74u, 0x08141AF0u, 0x24u, 0x11);
    CHECK(ram_dispatch(0x03007D74u, 0) == 0);

    // ── byte_compare ────────────────────────────────────────────────
    reset_state();
    plant_pair(0x03007CE4u, 0x08141BB0u, 0x2Eu, 0x22);
    CHECK(ram_dispatch(0x03007CE4u, 1) == 1);
    CHECK(g_compare_calls == 1);

    // ── flash/save getter ───────────────────────────────────────────
    reset_state();
    plant_pair(0x03007D48u, 0x08141AACu, 0x04u, 0x33);
    CHECK(ram_dispatch(0x03007D48u, 1) == 1);
    CHECK(g_getter_calls == 1);

    std::printf("%s (%d failure%s)\n", g_failures ? "FAIL" : "PASS",
                g_failures, g_failures == 1 ? "" : "s");
    return g_failures ? 1 : 0;
}
