#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

#include "runtime.h"
#include "runtime_arm.h"
#include "mod_function_hooks.h"
#include "mod_runtime.h"
#include "ffta_ram_dispatch.h"
#include "ffta_lzss_guard.h"
#include "mobile_platform.h"

#if defined(__ANDROID__)
#include <SDL_system.h>  // SDL_AndroidGetExternalStoragePath (user-visible saves)
#include <filesystem>
#include <system_error>
#endif

#if defined(GBAGAME_RECOMP_UI)
#include "game_launcher_boot.h"
#endif

#if !defined(_WIN32) && !defined(__ANDROID__)
#include <sys/resource.h>
// Generated guest code turns every guest BL into a host C call; FFTA's
// call chains plus the PPU renderer exceed the Linux 8 MiB default. The
// framework reserves 16 MiB on Windows via LINKER:--stack; on Linux the
// main-thread stack is governed by RLIMIT_STACK, so raise it here. On
// Android the game runs on a 256 MiB pthread (mobile_platform.h), so this
// is desktop-only.
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
// Definition: src/ffta_lzss_guard.h (ffta::lzss_entry_guard). The save-menu/
// summon divergence re-enters the 0x0800543C decoder with a corrupted source
// pointer; the header-guard implausibility check skips back to the caller
// (bounded degradation, logged) instead of hanging. Registered below via
// GBA_MOD_CONSTRUCTOR; extracted to the header so the unit suite links it.

// ── Trusted plugins: mods lifecycle (see reference/widescreen.md) ──────────
// Game-owned hooks install through the trusted-plugin activation pass
// (mods/preloaded catalog, feature "widescreen", default-enabled). The pass
// resets game-owned state — including a disable-all of entry hooks — then
// runs reset callbacks, then the committed plugins, so ordering against
// run_game()'s own WS cleanup is structural, not incidental.

// ── Widescreen (W2): authored margins (see reference/widescreen.md) ─────────
// FFTA's field BGs are 512-wide tilemap rings, so the columns the
// expanded-view compositor samples for margin pixels are the guest's own
// authored world (BRINGUP § W1b). Clipping OBJ to the native viewport keeps
// parked sprites out of margins. Inert in faithful runs: only the
// expanded-view compositor reads these.
extern "C" int g_ws_authored_margin_layers;
extern "C" int g_ws_obj_native_clip;
extern "C" int g_ws_pillarbox;
extern "C" int (*g_ws_bg_x_provider)(int, int, int, int*);
extern "C" unsigned g_ws_bg_x_provider_layers;
std::uint32_t g_ws_frame_left = 0;
std::uint32_t g_ws_frame_right = 0;
int ffta_ws_bg_x_provider(int bg, int x, int y, int* hw_x);
// Reset callback: fires in every activation pass (after the engine's
// disable-all of entry hooks), so it re-arms the correctness guard and
// clears our presentation state; the activation plugin opts back in below.
static void ffta_mod_reset() {
    g_ws_authored_margin_layers = 0;
    g_ws_obj_native_clip = 0;
    g_ws_bg_x_provider = nullptr;
    g_ws_bg_x_provider_layers = 0;
    g_ws_pillarbox = 0;
    g_ws_frame_left = 0;
    g_ws_frame_right = 0;
    gba_mod_set_function_hook_enabled("ffta.lzss-guard", 1);
}

// Activation plugin "ffta.widescreen" (manifest:
// mods/preloaded/packages/ffta.enhancement.widescreen). Installs the
// authored-margin hooks after the runner's game-owned cleanup; a disabled
// feature simply leaves the engine-default margin policy in place.
static void ffta_ws_activate() {
    g_ws_authored_margin_layers = 1;
    g_ws_obj_native_clip = 1;
    g_ws_bg_x_provider = ffta_ws_bg_x_provider;
    g_ws_bg_x_provider_layers = (1u << 2) | (1u << 3);  // BG2/BG3 (UI)
    std::fprintf(stderr, "[ffta] ws: margin hooks installed (ffta.widescreen)\n");
}

GBA_MOD_CONSTRUCTOR(register_ffta_mod_plugins) {
    gba_mod_register_function_entry_plugin("ffta.lzss-guard", 0x0800543Cu, 1,
                                           ffta::lzss_entry_guard);
    gba_mod_register_reset_callback(ffta_mod_reset);
    gba_mod_register_activation_plugin("ffta.widescreen", ffta_ws_activate);
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

#if defined(__ANDROID__)
// Issue #6: battery saves and save states live in the user-visible external
// app directory (.../Android/data/org.gbarecomp.fftarecomp/files/) so players
// can back them up or import them over USB/MTP — the app-private files/ tree
// needs run-as and is invisible to file managers. Internal files/ stays the
// fallback when external storage is unavailable, and the staged game TOML
// still points there. Filenames mirror android/app/build.gradle (romFile)
// and android/game_android.toml ([save].path); tools/android_static_check.py
// pins all three together.
// One-time migration: internal files move outward (copy + size-verify +
// remove original) only when the external copy is absent, so a
// player-imported file is never overwritten. The .suspend.pending marker is
// deliberately NOT migrated — a stale resume marker must never survive an
// update.
namespace {

void ffta_migrate_file(const std::filesystem::path& from,
                       const std::filesystem::path& to) {
    std::error_code ec;
    if (!std::filesystem::is_regular_file(from, ec)) return;
    if (std::filesystem::is_regular_file(to, ec)) return;  // player import wins
    std::filesystem::create_directories(to.parent_path(), ec);
    if (ec) {
        std::fprintf(stderr, "[ffta] saves: cannot create %s (%s)\n",
                     to.parent_path().c_str(), ec.message().c_str());
        return;
    }
    std::filesystem::copy_file(from, to, ec);
    if (ec) {
        std::fprintf(stderr, "[ffta] saves: cannot migrate %s (%s)\n",
                     from.c_str(), ec.message().c_str());
        return;
    }
    const auto src_size = std::filesystem::file_size(from, ec);
    const auto dst_size = std::filesystem::file_size(to, ec);
    if (!ec && src_size == dst_size) {
        std::filesystem::remove(from, ec);
        std::fprintf(stderr, "[ffta] saves: migrated %s -> %s\n",
                     from.c_str(), to.c_str());
    }
}

// Appends --save-path/--state-dir (CLI wins over the staged TOML). No-op
// when external storage is unavailable: the TOML's internal paths stand.
void ffta_redirect_player_data(std::vector<std::string>& args) {
    const char* ext = SDL_AndroidGetExternalStoragePath();
    if (!ext || !*ext) {
        std::fprintf(stderr, "[ffta] saves: external storage unavailable, "
                             "keeping app-private files/\n");
        return;
    }
    const std::filesystem::path saves = std::filesystem::path(ext) / "saves";
    const std::filesystem::path states = std::filesystem::path(ext) / "states";
    ffta_migrate_file("saves/ffta_us.sav", saves / "ffta_us.sav");
    for (int slot = 1; slot <= 9; ++slot)
        ffta_migrate_file("roms/ffta_usa.state" + std::to_string(slot),
                          states / ("ffta_usa.state" + std::to_string(slot)));
    ffta_migrate_file("roms/ffta_usa.suspend.state",
                      states / "ffta_usa.suspend.state");
    std::error_code ec;
    std::filesystem::create_directories(saves, ec);
    std::filesystem::create_directories(states, ec);
    args.emplace_back("--save-path");
    args.emplace_back((saves / "ffta_us.sav").string());
    args.emplace_back("--state-dir");
    args.emplace_back(states.string());
    std::fprintf(stderr, "[ffta] saves: external saves=%s states=%s\n",
                 saves.c_str(), states.c_str());
}

}  // namespace
#endif

}  // namespace

int ffta_main(int argc, char** argv) {
#if !defined(_WIN32) && !defined(__ANDROID__)
    raise_stack_limit();
#endif
    for (int i = 1; i < argc; ++i) {
        if (std::strcmp(argv[i], "--help") == 0 ||
            std::strcmp(argv[i], "-h") == 0) {
            print_usage();
            return 0;
        }
    }

    std::vector<std::string> args(argv, argv + argc);
    // Android: private-storage layout, log file, staged game.toml, no
    // pre-boot launcher. No-op on desktop (args left untouched).
    gbarecomp::MobileProcessOptions mobile;
    mobile.game_config = GBARECOMP_DEFAULT_GAME_CONFIG;
    mobile.program_name = "./FFTARecomp";
    const bool on_mobile = gbarecomp::mobile_prepare_process(args, mobile);

    gbarecomp::RunOptions opts;
    opts.builtin_game_name = "Final Fantasy Tactics Advance";
    // Widescreen (W2/W3): validated capability — the trusted plugin
    // "ffta.widescreen" (mods/preloaded catalog, default-enabled) authors the
    // field margins from the guest's 512-wide rings; users opt in with
    // --view-width up to 448 (matrix validated by tools/ws_check.py) or
    // --resize-view (window-aspect driven, same ceiling). Default stays 240.
    opts.mod_game_id = "ffta-us";
    opts.max_view_width = 448;
    opts.resize_driven_view = true;
    opts.max_resize_view_width = 448;
    opts.extended_view_frame = ffta_ws_margin_policy;
    opts.builtin_rom_sha1 = "4ac05441f4de70a4ec3dd932116346c61b8783d9";
    opts.launcher_region = "USA";
    opts.launcher_game_config = GBARECOMP_DEFAULT_GAME_CONFIG;

    // FFTA relocates position-independent save/flash helpers into a moving
    // stack frame and calls them by computed address; canonicalize those
    // transient copies to their generated native bodies so a reused scratch
    // slot can never execute stale AOT code (see src/ffta_ram_dispatch.h,
    // BRINGUP § Phase 5 save-flow). Cleared by run_game() on every return path.
    g_runtime_ram_dispatch_hook = &ffta::ram_dispatch;

    // Belt and braces: enable the LZSS entry guard at startup too. The mods
    // activation pass disables all entry hooks each launch and re-arms via
    // the reset callback; this covers run paths that skip the pass.
    gba_mod_set_function_hook_enabled("ffta.lzss-guard", 1);

    // Touch pad idle auto-hide (device decision 2026-10-08; 15 s per user
    // request): after 15 s of screen-wide touch inactivity the pad hides;
    // any touch reveals it and then acts normally. Inert without a pad.
    opts.touch_pad_idle_hide_seconds = 15;

    if (on_mobile) {
#if defined(__ANDROID__)
        // Durable miss journaling on device (mobile has no exit-time report
        // when a session hangs or is killed): every missed PC rewrites this
        // proposal fragment in the app's files/ dir the moment it is bridged,
        // so the device doubles as a harvestable audit surface. Overwrite=0
        // keeps any externally provided path authoritative. on_mobile is only
        // true on Android (mobile_prepare_process returns false elsewhere),
        // so this is the same code path — just explicitly compiled out of the
        // Windows/POSIX-desktop targets, whose libc does not carry setenv
        // (MSVC) — the call was previously guarded by flow only.
        setenv("GBARECOMP_MISS_FRAG",
               "recomp_master_misses_AFXE.toml.frag", 0);
        // Issue #6: user-visible battery saves + save states (no-op when
        // external storage is unavailable).
        ffta_redirect_player_data(args);
#endif
        // Phones fill the screen with the desktop-validated expanded view
        // (decision 2026-10-08); physical-pixel sizing keeps the runtime
        // chrome readable, resume after an OS kill, touch-friendly UI.
        opts.resize_view_sizing = gbarecomp::RunOptions::ViewSizing::Density;
        opts.resume_suspend_state_on_launch = true;
        opts.ui_touch_friendly = true;
    }

#if defined(GBAGAME_RECOMP_UI)
    // Mobile args carry --no-launcher, so this returns false on device.
    if (game_launcher_preboot(args, opts)) return 0;
#endif
    std::vector<char*> av;
    av.reserve(args.size());
    for (auto& arg : args) av.push_back(arg.data());
    return gbarecomp::run_game(static_cast<int>(av.size()), av.data(), opts);
}

#if defined(__ANDROID__)
extern "C" int SDL_main(int argc, char** argv) {
    // Desktop-sized host stack for the recompiled corpus (mobile_platform.h).
    return gbarecomp::mobile_run_with_stack(ffta_main, argc, argv);
}
#else
int main(int argc, char** argv) {
    return ffta_main(argc, argv);
}
#endif
