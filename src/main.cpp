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

// ── Widescreen (W2): authored margins (see reference/widescreen.md) ─────────
// FFTA's field BGs are 512-wide tilemap rings, so the columns the
// expanded-view compositor samples for margin pixels are the guest's own
// authored world (BRINGUP § W1b). Declare that (savestate loads keep the
// pillarbox policy off) and clip OBJ to the native viewport so parked
// sprites never leak into margins. Inert in faithful runs: only the
// expanded-view compositor reads these. Set from a mod constructor so they
// are live in whichever process runs the game.
extern "C" int g_ws_authored_margin_layers;
extern "C" int g_ws_obj_native_clip;
extern "C" int g_ws_pillarbox;
extern "C" int (*g_ws_bg_x_provider)(int, int, int, int*);
extern "C" unsigned g_ws_bg_x_provider_layers;
std::uint32_t g_ws_frame_left = 0;
std::uint32_t g_ws_frame_right = 0;
void ffta_ws_install_margin_hooks(std::uint32_t extra_left,
                                  std::uint32_t extra_right);
int ffta_ws_bg_x_provider(int bg, int x, int y, int* hw_x);
// ── Widescreen (W2): authored margins (see reference/widescreen.md) ─────────
// FFTA's field BGs are 512-wide tilemap rings, so the columns the
// expanded-view compositor samples for margin pixels are the guest's own
// authored world (BRINGUP § W1b). run_game() clears game-owned WS hooks on
// entry, so they are installed from the runner's extended_view_init callback
// (called once after the wide view is authorized — after that cleanup).
// Clipping OBJ to the native viewport keeps parked sprites out of margins.
// Inert in faithful runs: only the expanded-view compositor reads these.
void ffta_ws_install_margin_hooks(std::uint32_t extra_left,
                                  std::uint32_t extra_right) {
    (void)extra_left;
    (void)extra_right;
    g_ws_authored_margin_layers = 1;
    g_ws_obj_native_clip = 1;
    g_ws_bg_x_provider = ffta_ws_bg_x_provider;
    g_ws_bg_x_provider_layers = (1u << 2) | (1u << 3);  // BG2/BG3 (UI)
    std::fprintf(stderr, "[ffta] ws: margin hooks installed (extended_view_init)\n");
}

// ── Widescreen (W3): per-scene margin policy ───────────────────────────────
// The world map's field BGs are 256-px-wide tilemaps (size=2), so its margin
// samples land on the tilemap's wrapped edge — pillarbox those scenes.
// Field / battle / pub scenes keep their 512-wide rings (size=1) authored, so
// the margins stay real content. Runs at every emulated frame start, before
// scanline 0; inert at native width (only the wide compositor reads these).
void ffta_ws_margin_policy(const gbarecomp::ExtendedViewFrameInfo* frame) {
    if (!frame || !frame->io || frame->io_size < 0x10) return;
    g_ws_frame_left = frame->extra_left;
    g_ws_frame_right = frame->extra_right;
    if (frame->extra_left == 0 && frame->extra_right == 0) return;
    const std::uint8_t* io = frame->io;
    const unsigned bg0 = io[0x08] | (io[0x09] << 8);
    const unsigned bg1 = io[0x0A] | (io[0x0B] << 8);
    const bool world_map_tilemaps =
        ((bg0 >> 14) & 3u) == 2u && ((bg1 >> 14) & 3u) == 2u;
    g_ws_pillarbox = world_map_tilemaps ? 1 : 0;
}

// UI layers must not paint into margin columns: BG2/BG3 are 256-wide screens
// (menus, funds, dialogue panels) and would show wrapped edge fragments.
// Skip those layers wherever the output x is outside the native 240 span.
int ffta_ws_bg_x_provider(int bg, int x, int y, int* hw_x) {
    (void)y;
    (void)hw_x;
    if (bg >= 2) {
        const int left = static_cast<int>(g_ws_frame_left);
        if (x < left || x >= left + 240) return -1;  // handled: no pixel
    }
    return 0;
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
    // Widescreen (W2): validated capability — the mod (register_ffta_widescreen)
    // authors the field margins from the guest's 512-wide rings; users opt in
    // with --view-width up to 320 (or --resize-view). Default stays 240.
    opts.max_view_width = 320;
    opts.extended_view_init = ffta_ws_install_margin_hooks;
    opts.extended_view_frame = ffta_ws_margin_policy;
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
