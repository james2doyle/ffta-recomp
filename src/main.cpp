#include <cstdio>
#include <cstring>
#include <vector>

#include "runtime.h"
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
