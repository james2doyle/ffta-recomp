// RED-first host unit tests for issue-22 no-laws toggle (task ndvo42zh).
// Expects src/ffta_cheats.h to exist with:
//   ffta::kNoLawsAddr == 0x02003C34, kNoLawsWrites == 4 (u16 stride-2, 8B)
//   ffta::cheats_set_no_laws(bool), cheats_no_laws_enabled(),
//   ffta::cheats_apply_no_laws(write_u16 fn) zeroing the battle-law cells.
// Plus menu-model wiring: a Toggle No Laws row via menu_add_row.
// This file MUST FAIL to build/run before the GREEN task (no header yet).
#include "../../src/ffta_cheats.h"
#include "../../gbarecompx/src/runtime/menu_model.h"

#include <cstdint>
#include <cstdio>

namespace {
int cheats_failures = 0;
#define CHEATS_CHECK(cond)                                                  \
    do {                                                                    \
        if (!(cond)) {                                                      \
            std::printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);   \
            ++cheats_failures;                                              \
        }                                                                   \
    } while (0)
uint16_t g_law_cells[4];
void fake_write_u16(uint32_t addr, uint16_t v) {
    uint32_t base = ffta::kNoLawsAddr;
    if (addr >= base && addr < base + 8 && ((addr - base) % 2) == 0)
        g_law_cells[(addr - base) / 2] = v;
}
}  // namespace
int run_cheats_tests() {
    CHEATS_CHECK(ffta::kNoLawsAddr == 0x02003C34u);
    CHEATS_CHECK(ffta::kNoLawsWrites == 4);
    g_law_cells[0] = 0x0014; g_law_cells[1] = 0x004Au;
    g_law_cells[2] = 0x0040; g_law_cells[3] = 0x004Bu;
    ffta::cheats_set_no_laws(true);
    CHEATS_CHECK(ffta::cheats_no_laws_enabled());
    ffta::cheats_apply_no_laws(fake_write_u16);
    CHEATS_CHECK(g_law_cells[0] == 0 && g_law_cells[1] == 0);
    CHEATS_CHECK(g_law_cells[2] == 0 && g_law_cells[3] == 0);
    ffta::cheats_set_no_laws(false);
    CHEATS_CHECK(!ffta::cheats_no_laws_enabled());
    gbarecomp::MenuModel m{};
    m.sections[0].title = "Cheats";
    m.section_count = 1;
    gbarecomp::MenuRow row{};
    row.kind = gbarecomp::MenuRowKind::Toggle;
    row.label = "No Laws";
    row.section = 0;
    row.int_value = 0;
    int idx = gbarecomp::menu_add_row(m, row);
    CHEATS_CHECK(idx == 0);
    CHEATS_CHECK(m.row_count == 1);
    CHEATS_CHECK(m.rows[0].kind == gbarecomp::MenuRowKind::Toggle);
    gbarecomp::menu_set_value_int(m, idx, 1);
    CHEATS_CHECK(gbarecomp::menu_value_int(m, idx) == 1);
    ffta::cheats_set_no_laws(gbarecomp::menu_value_int(m, idx) != 0);
    CHEATS_CHECK(ffta::cheats_no_laws_enabled());
    return cheats_failures;
}
