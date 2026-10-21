#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <algorithm>
#include <string>
#include <vector>

#include "runtime.h"
#include "runtime_arm.h"
#include "mod_function_hooks.h"
#include "mod_runtime.h"
#include "ffta_ram_dispatch.h"
#include "ffta_lzss_guard.h"
#include "ffta_haptics_hook.h"
#include "ffta_speed_boost.h"
#include "ffta_ws_margin.h"
#include "mobile_platform.h"

#if defined(__ANDROID__)
#include <filesystem>
#include <system_error>
#endif

#include "launcher.h"

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

// ── Battle-damage haptics (mod_function_hook, game.toml) ────────────────────
// Definition: src/ffta_haptics_hook.h. Two damage seams feed one pulse
// pipeline, and one display hook releases it (issue #30, 2026-10-20):
//   1. ffta::haptics_damage_hook @ 0x080A2210 — the HP delta helper (unit
//      hp@+0x18 layout); covers the helper-family apply paths.
//   2. ffta::haptics_hp_store_hook @ 0x080A3250 — the enemy-unit direct
//      store (hp@+0x1C/max@+0x1E); the Air Render-style apply path that
//      never calls the helper (proven by the abort-on-write trace, BRINGUP).
//   3. ffta::haptics_popup_hook @ 0x080A8BF8 — the damage-number popup
//      spawn; releases the armed pulse so the buzz lands with the number
//      for every animation length.
// The observers filter positive deltas + the live-battle gate, then route
// one 120 ms pulse through host_primary_haptic. Registered below via
// GBA_MOD_CONSTRUCTOR.

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
// The BG margin columns are deliberately left to the engine's
// window-controlled sampling: FFTA swaps layer roles per scene (the move
// overlay moves the field ring to BG2/BG3; the Totema summon runs its
// effect layers at 256 px), so any fixed layer skip loses real content —
// the original "BG2/BG3 = UI" skip showed the alias seam in the move state,
// and a tilemap-width skip cut the summon. The policy below keeps the
// world-map pillarbox; the sprite clip keeps parked OBJ out of the margins.
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
    gba_mod_set_function_hook_enabled("ffta.haptics", 1);
    ffta::haptics_reset();
}

// Activation plugin "ffta.widescreen" (manifest:
// mods/preloaded/packages/ffta.enhancement.widescreen). Installs the
// authored-margin hooks after the runner's game-owned cleanup; a disabled
// feature simply leaves the engine-default margin policy in place.
static void ffta_ws_activate() {
    // The engine's window-controlled margin sampling stands (the behavior the
    // wide-view validation accepted); see the note above the frame policy.
    // No OBJ clip either: the wide view must reveal the units the camera has
    // panned past (user-reported: sprites vanished in the margins while the
    // level/BG stayed drawn). The parked-sprite question is tracked
    // separately — see the BRINGUP entry.
    std::fprintf(stderr, "[ffta] ws: margin policy installed (ffta.widescreen)\n");
}

GBA_MOD_CONSTRUCTOR(register_ffta_mod_plugins) {
    gba_mod_register_function_entry_plugin("ffta.lzss-guard", 0x0800543Cu, 1,
                                           ffta::lzss_entry_guard);
    gba_mod_register_function_entry_plugin("ffta.haptics", 0x080A2210u, 1,
                                           ffta::haptics_damage_hook);
    gba_mod_register_function_entry_plugin("ffta.haptics", 0x080A3250u, 1,
                                           ffta::haptics_hp_store_hook);
    gba_mod_register_function_entry_plugin("ffta.haptics", 0x080A8BF8u, 1,
                                           ffta::haptics_popup_hook);
    gba_mod_register_reset_callback(ffta_mod_reset);
    gba_mod_register_activation_plugin("ffta.widescreen", ffta_ws_activate);
}

// ── Widescreen (W3/W4): per-scene margin policy ────────────────────────────
// Two rules, both read from the per-frame IO snapshot (no guest-RAM state):
//
// 1. Pillarbox (W3): the world map's field BGs are 256-px-wide tilemaps
//    (size=2), so its margin samples land on the tilemap's wrapped edge —
//    pillarbox those scenes.
//
// 2. UI-layer margin suppression (2026-10-16, re-lands the 2026-10-15 W2
//    interim rule): FFTA's UI panels — chat bubbles, portrait plates, pub
//    rumor/law screens, confirm dialogs — are 256-px tilemaps (BGxCNT
//    size==0) whose margin samples wrap into the panel's own edge columns
//    ("chat text bubbles are wrapping/repeating"). The wide compositor
//    samples tilemap px (x - extra_left + hofs) mod 256 continuously, so a
//    256-px panel repeats its border/interior/text in the margins wherever
//    its scroll lands — pinned pixel-exact on four device captures and the
//    desktop pub replay (BRINGUP). Size-0 layers therefore never paint
//    margin columns: suppress their samples outside the native 240 span.
//    Captured disconfirmations, in order: BLDCNT is NOT a condition (the
//    pub conversation runs blended, bldcnt=0x3348, with the bubble up);
//    window-enable is NOT a condition either (the desktop pub bubble has
//    DISPCNT window bits 13/14 SET while all four device conversation
//    captures have the same registers configured but the enable bits CLEAR
//    — a windows gate would have armed nowhere on the device). The only
//    stable discriminator is the size field. Battle move/pan/menu keeps its
//    margins because ALL FOUR layers are the 512-px ring there (no size-0
//    layer — captured; the same fact that made the interim fix fix the move
//    state). Sprites: the device windows OBJ out of the margins (winout
//    0x2F) and the desktop pub parks off-screen sprites (issue #26) — no
//    sprite content is suppressed with the BGs. The rule was withdrawn
//    2026-10-15 for the Totema report, but its summon A/B (BRINGUP) shows
//    the summon window pixel-identical with the rule enabled — the report
//    was presentation-side; re-landed with that A/B plus the ws matrix and
//    the bubble-fixture A/B (GBARECOMP_FFTA_UI_GATE=0) as the gates.
//
// Runs at every emulated frame start, before scanline 0; inert at native
// width (only the wide compositor reads these).
static int ffta_ws_ui_gate(int bg, int output_x, int screen_y, int* out_hw_x) {
    // The tested span logic (ffta_ws_margin.h): -1 suppresses the sample
    // outside the native span, 0 keeps the hardware X in it. out_hw_x stays
    // null — no remap, only suppression.
    return ffta::ws_ui_gate_sample(static_cast<int>(g_ws_frame_left),
                                   output_x);
}

void ffta_ws_margin_policy(const gbarecomp::ExtendedViewFrameInfo* frame) {
    if (!frame || !frame->io || frame->io_size < 0x10) return;
    g_ws_frame_left = frame->extra_left;
    g_ws_frame_right = frame->extra_right;
    // Issue #30 Phase 4: a savestate load bumps the runtime state epoch —
    // clear the haptics pipeline so armed pulses / stale popup frames from
    // the pre-load world cannot leak (the mods reset callback does not run
    // on TCP loads, the path the device/replay tooling uses). Then release
    // the armed damage haptic: the pulse fires when the damage-number popup
    // spawns (or at the grace deadline). Rides this existing per-frame
    // callback — no new framework seam.
    static std::uint64_t haptics_epoch = 0;
    if (frame->state_epoch != haptics_epoch) {
        haptics_epoch = frame->state_epoch;
        ffta::haptics_reset();
    }
    ffta::haptics_frame_service(frame->frame_count);
    if (frame->extra_left == 0 && frame->extra_right == 0) return;
    const std::uint8_t* io = frame->io;
    const unsigned bg0 = io[0x08] | (io[0x09] << 8);
    const unsigned bg1 = io[0x0A] | (io[0x0B] << 8);
    const bool world_map_tilemaps =
        ((bg0 >> 14) & 3u) == 2u && ((bg1 >> 14) & 3u) == 2u;
    g_ws_pillarbox = world_map_tilemaps ? 1 : 0;

    // Rule 2: the per-frame size-0 layer mask (the tested decision lives in
    // ffta_ws_margin.h) drives both the provider install and its layer
    // admission. Empty mask -> provider uninstalled (the engine's sampling
    // stands, zero added traffic). The env opt-out is the A/B arm for the
    // fixture gates (and an emergency kill-switch).
    static const bool ui_gate_disabled =
        std::getenv("GBARECOMP_FFTA_UI_GATE") &&
        std::getenv("GBARECOMP_FFTA_UI_GATE")[0] == '0';
    const unsigned mask =
        ui_gate_disabled ? 0u : ffta::ws_ui_gate_layers(io, frame->io_size);
    g_ws_bg_x_provider_layers = mask;
    g_ws_bg_x_provider = mask ? &ffta_ws_ui_gate : nullptr;
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

// User-visible external app directory (.../Android/data/<pkg>/files/).
// The Android base is the raylib/NativeActivity scaffold (Phase 4f): the path
// is derived from the baked applicationId (mobile_platform.h); nullptr keeps
// the app-private files/ fallback in both redirect helpers below.
const char* ffta_external_storage_path() {
#if defined(__ANDROID__) && defined(GBARECOMP_ANDROID_PACKAGE)
// App-specific external dir: needs no permission, is MTP-visible over USB,
// and /sdcard tracks the current user (the real port may upgrade this to JNI
// getExternalFilesDir).
#define FFTA__STR(x) #x
#define FFTA__XSTR(x) FFTA__STR(x)
    static const char kExt[] = "/sdcard/Android/data/" FFTA__XSTR(
                                   GBARECOMP_ANDROID_PACKAGE) "/files";
#undef FFTA__XSTR
#undef FFTA__STR
    return kExt;
#else
    return nullptr;
#endif
}

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
    const char* ext = ffta_external_storage_path();
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

// Diagnostics (log/frag/coverage) live in the user-visible external app
// directory next to saves/states, so they can be pulled over USB/MTP or adb
// without root or `run-as` — the app-private files/ tree is invisible to file
// managers and (as of 2026-10-11) silently fails all writes on some sessions
// (game runs, zero log/frag/json, no error — the engine's freopen has no
// fallback). Sets GBARECOMP_MISS_FRAG/GBARECOMP_COVERAGE_JSON (env, Overwrite=0
// keeps any externally provided path authoritative) and returns the absolute
// log path for MobileProcessOptions.log_file. Empty when external storage is
// unavailable: the engine's app-private defaults stand.
std::string ffta_redirect_diagnostics() {
    const char* ext = ffta_external_storage_path();
    if (!ext || !*ext) {
        std::fprintf(stderr, "[ffta] logs: external storage unavailable, "
                             "keeping app-private files/\n");
        return {};
    }
    const std::filesystem::path logs = std::filesystem::path(ext) / "logs";
    std::error_code ec;
    std::filesystem::create_directories(logs, ec);
    if (ec) {
        std::fprintf(stderr, "[ffta] logs: cannot create %s (%s)\n",
                     logs.c_str(), ec.message().c_str());
        return {};
    }
    setenv("GBARECOMP_MISS_FRAG",
           (logs / "recomp_master_misses_AFXE.toml.frag").c_str(), 0);
    setenv("GBARECOMP_COVERAGE_JSON",
           (logs / "recomp_coverage_AFXE.json").c_str(), 0);
    std::fprintf(stderr, "[ffta] logs: external logs=%s\n", logs.c_str());
    return (logs / "android-runtime.log").string();
}

// Startup manifest: first log lines after the engine redirect, listing every
// resolved diagnostics/player path. A missing file is then meaningful (never
// written vs written-then-lost) without needing run-as to go look.
void ffta_log_manifest(const std::string& log_path) {
    const char* frag = std::getenv("GBARECOMP_MISS_FRAG");
    const char* cov = std::getenv("GBARECOMP_COVERAGE_JSON");
    std::fprintf(stderr, "[ffta] manifest log=%s frag=%s coverage=%s\n",
                 log_path.empty() ? "(app-private android-runtime.log)" : log_path.c_str(),
                 frag && *frag ? frag : "(app-private default)",
                 cov && *cov ? cov : "(app-private default)");
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
#if defined(__ANDROID__)
    // Diagnostics first: the external log path must be resolved before the
    // engine redirects stderr (mobile_prepare_process opens log_file). The
    // returned string owns the path, so hold it past the call.
    const std::string external_log = ffta_redirect_diagnostics();
    if (!external_log.empty()) mobile.log_file = external_log.c_str();
#endif
    const bool on_mobile = gbarecomp::mobile_prepare_process(args, mobile);
#if defined(__ANDROID__)
    // Manifest after the redirect: stderr now flows to the log file, so
    // these are its first lines.
    if (on_mobile) ffta_log_manifest(external_log);
#endif
#if defined(__ANDROID__)
    // Mobile args carry --no-launcher: the setup screen is the Android
    // launcher. The pre-boot launch screen exists on device and now works
    // (SAF pick via android_saf_bridge, payload box art) but stays opt-in
    // via a --launcher debug arg until the mobile boot flow is redesigned
    // around it — the device gate and the suspend/resume lifecycle depend
    // on an unattended boot.
    #if defined(GBAGAME_BUNDLED_ROM)
    // Private build with the ROM staged: drop the vacuous flag and boot.
    // (Public builds stop at the #else below — skipping setup is only valid
    // with a bundled ROM.)
    args.erase(std::remove(args.begin(), args.end(), "--no-launcher"),
               args.end());
#else
    // Public build: the ROM arrives through the setup flow (SAF import).
    // Boot only when the staged ROM is actually there (cwd is the app files
    // dir; the TOML's ../../roms/<file> resolves beside it) rather than
    // refusing outright — the pre-4f shell never hit this path (its
    // compiled-in launcher made this whole block unreachable), and a public
    // raylib build must boot after an import exactly like it always did.
    std::error_code rom_ec;
    if (!std::filesystem::is_regular_file("roms/ffta_usa.gba", rom_ec)) {
        std::fprintf(stderr,
                     "[ffta] no staged ROM: import one through the setup "
                     "screen (roms/ffta_usa.gba missing)\n");
        return 1;
    }
#endif
#endif

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
    gba_mod_set_function_hook_enabled("ffta.haptics", 1);

    // Touch pad idle auto-hide (device decision 2026-10-08; 15 s per user
    // request): after 15 s of screen-wide touch inactivity the pad hides;
    // any touch reveals it and then acts normally. Inert without a pad.
    opts.touch_pad_idle_hide_seconds = 15;

    // Issue #11 (speed toggle, Phase 0): keep the engine's Assist surface
    // enabled. The raygui in-game menu exposes the Fast-forward speed row
    // under Assist; hold-to-boost (Tab / 2 / right-trigger) already worked.
    // Rewind stays suppressed: rewind_history_seconds defaults to 0, so no
    // rewind row or history is created (known wart: the old launcher listed
    // a Rewind binding row; the binding is inert without history).
    opts.expose_assist_tools = true;

    // Issue #11 (speed toggle, Phase 1): FFTA-owned touch pill. Tap the
    // top-center "FF" pill to latch the same boost the physical hold paths
    // and menu latch provide; the engine polls speed_boost_requested() once
    // per input pump under the shared Assist-enable gate. Presentation-only
    // on desktop (the pill appears on touch activity, never for keyboard).
    opts.host_overlay = &ffta::speed_boost_overlay;
    opts.fast_forward_request = &ffta::speed_boost_requested;

    if (on_mobile) {
#if defined(__ANDROID__)
        // Durable miss journaling on device (mobile has no exit-time report
        // when a session hangs or is killed): every missed PC rewrites the
        // proposal fragment the moment it is bridged, so the device doubles
        // as a harvestable audit surface. ffta_redirect_diagnostics already
        // pointed GBARECOMP_MISS_FRAG at external logs/; Overwrite=0 keeps
        // that authoritative and this app-private default only stands when
        // external storage is unavailable. on_mobile is only
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

#include "launcher.h"

#if defined(GBARECOMP_USE_RAYLIB)
    // Skip the pre-boot launcher for headless / explicit-path invocation
    // (--rom/--bios/--no-window/--frames/--load-state/--tcp/--no-launcher).
    // Bare invocation shows the screen; --launcher forces it even for
    // scripted-looking runs (play.sh passes --rom). Constraint 7.
    //
    // Classify the MUTATED args vector, not the raw argv: on Android the
    // native entry's argv is raylib's synthetic {"raylib"}, so every flag
    // the mobile layer appended (--no-launcher, the staged TOML, the
    // debug-args.txt entries) is invisible to an argv-based check — which
    // made the launch screen un-skippable on device (2026-10-16 finding).
    // The POSTURE stands (2026-10-16, user decision): Android's pre-boot
    // surface is the platform setup activity (pure Android/SAF); the raygui
    // launch screen is desktop-only. --launcher (a debug arg) can still
    // force the screen on device for development; its ROM picker fails
    // cleanly there (no desktop dialog backends — see asset_picker.cpp).
    if (gbarecomp::launcher_wants_screen(args) ||
        !gbarecomp::launcher_should_skip_screen(args)) {
        if (auto backend = gbarecomp::create_launcher_backend()) {
            gbarecomp::LauncherConfig cfg;
            cfg.argv0 = argc > 0 ? argv[0] : nullptr;
            cfg.first_boot_pick = true;
            auto res = backend->run(cfg);
            if (res.kind == gbarecomp::LauncherResult::Kind::Quit)
                return 0;
            if (res.kind == gbarecomp::LauncherResult::Kind::Launch) {
                args.push_back("--rom");
                args.push_back(res.rom);
                if (!res.bios.empty()) {
                    args.push_back("--bios");
                    args.push_back(res.bios);
                }
            }
        }
    }
#endif
    std::vector<char*> av;
    av.reserve(args.size());
    for (auto& arg : args) av.push_back(arg.data());
    return gbarecomp::run_game(static_cast<int>(av.size()), av.data(), opts);
}

#if defined(__ANDROID__)
// Raylib (NativeActivity) entry: android_native_app_glue calls main() on the
// glue thread, and raylib is glue-thread-bound (its ALooper polling fails on
// any other thread). So the game runs HERE, not on mobile_run_with_stack's
// pthread — the vendored glue (platform/android/native_app_glue) sizes this
// thread to kMobileGameStackBytes. Arm the stack guard for it directly (same
// 32 MiB margin run_stacked keeps).
int main(int argc, char** argv) {
    gbarecomp::host_stack_guard_arm_current(32u * 1024u * 1024u);
    return ffta_main(argc, argv);
}
#else
int main(int argc, char** argv) {
    return ffta_main(argc, argv);
}
#endif
