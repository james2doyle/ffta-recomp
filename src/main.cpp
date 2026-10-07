#include <cstdio>
#include <cstring>
#include <vector>

#include "runtime.h"
#include "runtime_arm.h"
#include "mod_function_hooks.h"
#include "mod_runtime.h"
#include "ffta_ram_dispatch.h"

#if defined(GBAGAME_RECOMP_UI)
#include "game_launcher_boot.h"
#endif

#if !defined(_WIN32)
#include <sys/resource.h>
// Generated guest code turns every guest BL into a host C call; FFTA's
// call chains plus the PPU renderer exceed the Linux 8 MiB default. The
// framework reserves 16 MiB on Windows via LINKER:--stack; on Linux the
// main-thread stack is governed by RLIMIT_STACK, so raise it here.
static void raise_stack_limit() {
    struct rlimit rl;
    if (getrlimit(RLIMIT_STACK, &rl) == 0) {
        if (rl.rlim_max == RLIM_INFINITY) {
            rl.rlim_cur = RLIM_INFINITY;
        } else if (rl.rlim_cur < rl.rlim_max) {
            rl.rlim_cur = rl.rlim_max;
        }
        setrlimit(RLIMIT_STACK, &rl);
    }
}
#endif

namespace {

void print_usage() {
    std::printf("FFTARecomp [--bios <path>] [--rom <path>] [game.toml]\n");
}

// ── LZSS decompressor guard (mod_function_hook, game.toml) ──────────────────
// The decoder at 0x0800543C reads its output length from the source header
// (big-endian at src+0, stream at src+4). The save-menu/summon divergence
// re-enters it with a corrupted source pointer; the decoded length then
// reads ~4G and the track-back copy loop (0x08005558) never ends. Check the
// header at the entry: an implausible call is skipped back to the caller
// (bounded degradation, logged) instead of hanging. BRINGUP § "Summon crash".
int ffta_lzss_entry_guard(uint32_t addr, int thumb, ArmCpuState* cpu) {
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

GBA_MOD_CONSTRUCTOR(register_ffta_lzss_guard) {
    gba_mod_register_function_entry_plugin("ffta.lzss-guard", 0x0800543Cu, 1,
                                           ffta_lzss_entry_guard);
}

}  // namespace

int main(int argc, char** argv) {
#if !defined(_WIN32)
    raise_stack_limit();
#endif
    for (int i = 1; i < argc; ++i) {
        if (std::strcmp(argv[i], "--help") == 0 ||
            std::strcmp(argv[i], "-h") == 0) {
            print_usage();
            return 0;
        }
    }

    gbarecomp::RunOptions opts;
    opts.builtin_game_name = "Final Fantasy Tactics Advance";
    opts.builtin_rom_sha1 = "4ac05441f4de70a4ec3dd932116346c61b8783d9";
    opts.launcher_region = "USA";
    opts.launcher_game_config = "game.toml";

    // FFTA relocates position-independent save/flash helpers into a moving
    // stack frame and calls them by computed address; canonicalize those
    // transient copies to their generated native bodies so a reused scratch
    // slot can never execute stale AOT code (see src/ffta_ram_dispatch.h,
    // BRINGUP § Phase 5 save-flow). Cleared by run_game() on every return path.
    g_runtime_ram_dispatch_hook = &ffta::ram_dispatch;

    // Enable the LZSS entry guard registered above (the activation plugin
    // re-enables it if the launcher's plugin lifecycle resets hooks).
    gba_mod_set_function_hook_enabled("ffta.lzss-guard", 1);

#if defined(GBAGAME_RECOMP_UI)
    std::vector<std::string> args(argv, argv + argc);
    if (game_launcher_preboot(args, opts)) return 0;
    std::vector<char*> av;
    av.reserve(args.size());
    for (auto& arg : args) av.push_back(arg.data());
    return gbarecomp::run_game(static_cast<int>(av.size()), av.data(), opts);
#else
    return gbarecomp::run_game(argc, argv, opts);
#endif
}
