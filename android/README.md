# Android (FFTARecomp)

Status 2026-10-09: **playable on device, current engine re-verified** —
skeleton, build, first boot, widescreen and the device gate are verified on
a Xiaomi Mi 11 (Android 14/API 34), and the current engine (split-loop gap
roll-in, IRQ abandon-close, SWI-return ledger, touch idle-hide) passed the
on-device gates 2026-10-09 on a Xiaomi M2102K1AC / Poco X3 Pro (Android
14/API 34): boot gate (`validate_android.sh`) GATE PASSED, press acceptance
(`tools/android_press_test.py` — savestate load → A press → one legal
abandon-close → frames advance), and the suspend/kill/relaunch lifecycle
(`tools/android_lifecycle_test.py`, 15/15 — marker survives `force-stop`,
auto-resume at the exact frame). adb-synthesized **taps are OS-filtered on
this ROM** (swipes pass) — press flows are driven through the observe TCP
(`set_keyinput`), not `input tap`. Working reference for the Android
target — moved here from the repo root (2026-10-09; previously
`ANDROID.md`); `BRINGUP.md` keeps the dated decision log and
`reference/dev-gotchas.md` § Android device forensics has the on-device
debugging recipe.

## How the port is structured

The **app shell lives in the engine**, not this repo:
`gbarecompx/platform/android/` (the raylib framework; the pinned submodule
still carries the retired shell) carries the shared Gradle template
(`gbarecomp-app.gradle`), the Java activities (`org.gbarecomp.GbaSetupActivity`
— SAF file picker with size/SHA-1 verification → app-private storage;
`org.gbarecomp.GbaGameActivity`, a `NativeActivity` subclass since Phase 4f),
and the CMake root that builds the game project. The game project must define
a **SHARED target named `main`** (`libmain.so`; the manifest's
`android.app.lib_name` loads it, and the vendored `native_app_glue` runs
`android_main` on its 256 MiB thread).

This repo therefore adds only a thin surface:

| File | Role |
|---|---|
| `android/app/build.gradle` | `ext.gbaGame` identity block + applies the engine template |
| `android/game_android.toml` | Runtime-only TOML, staged to `files/variants/final_fantasy_tactics_advance/game.toml` |
| `android/payload/mods/state.toml` | Default mod selection for fresh installs (widescreen on — see "Mods state" below) |
| `android/{build,settings}.gradle`, `gradle.properties`, wrapper | Gradle 8.11.1 / AGP 8.10.1 project |
| `android/app/src/main/res/…` | `app_name`, original vector launcher icon (no third-party art) |
| `CMakeLists.txt` (`if(ANDROID)`) | Target `main` instead of `FFTARecomp`; forced mods; raylib entry guards |
| `src/main.cpp` | `mobile_prepare_process` preflight, phone run options, the NativeActivity `main` on the glue thread |
| `tools/validate_android.sh` | Device acceptance gate (assertions + evidence pull) |
| `tools/android_press_test.py` | On-device press acceptance over the observe TCP (savestate load → `set_keyinput` A press → frames/anomaly/crash assertions) |
| `tools/android_lifecycle_test.py` | On-device suspend/kill/relaunch lifecycle gate (15 assertions: flush, marker survival, auto-resume, reconnect) |
| `tools/android_touch_test.py` | Touch-pad realism check (real-pipeline tap → KEYINPUT/journal/gesture); adb taps are OS-filtered on this ROM — see § Touch realism |
| `tools/android_static_check.py` | Device-free checks: identity pins, payload contract, hygiene, fake-`adb` gate self-test (suite `android-static`) |
| `tools/android_apk_check.py` | APK content guard for built APKs (payload vs sources, embed pins, libs/ABI, manifest, junk/duplicates) — `check.py --only android-apk` |

Runtime behavior on device (engine `mobile_platform.cpp`): chdir to the
app-private `files/` root, stdout+stderr → `files/android-runtime.log`,
appends the staged TOML and `--no-launcher`, sets
`GBARECOMP_SELFHEAL_RECOMPILE=0` (dispatch misses bridge **loudly** and are
harvested offline — the device doubles as a coverage-audit surface). Extra
runtime args can only arrive via an app-private `debug-args.txt` (adb
`run-as`), e.g. `--tcp-observe 19888`.

## Decisions (2026-10-08)

- **applicationId** `org.gbarecomp.fftarecomp`; **variant**
  `final_fantasy_tactics_advance` (matches `[game] short_name`).
- **Orientation** `landscape` (activity `sensorLandscape`).
- **View** expanded to fill the screen: `android/game_android.toml` sets
  `[video] resize_view = true` (the Android opt-in for the desktop-validated
  resize-driven path) → on the Mi 11's 3200x1440 display the logical view is
  **356x160**, presented at ~9x filling the screen. `RunOptions.max_view_width
  = 448` stays the ceiling. Desktop keeps its opt-in flag (`--resize-view`).
- **Mods** runtime is built in (the widescreen feature installs through the
  trusted-plugin lifecycle); the catalog and a default `state.toml` are staged
  into the payload.
- **Testing** via private ROM-embedded APKs (`-PprivateRom`): debug-signed,
  auto-named `…-PRIVATE-rom-included.apk`, never committed or distributed
  (`.gitignore` covers `*.apk`). Public builds import the ROM through the
  phone UI with a SHA-1 pin; the launch BIOS is the bundled clean-room
  emibios staged into every payload (`bios/emibios_gba_bios.bin`,
  `biosRequired=false` — issue #17), so no BIOS is ever picked.
- **After EVERY device playtest, harvest the miss journal** (same rule as
  desktop `play.sh` sessions): the runtime writes
  `logs/recomp_master_misses_AFXE.toml.frag` + `recomp_coverage_AFXE.json`
  to the user-visible external dir
  (`/sdcard/Android/data/org.gbarecomp.fftarecomp/files/logs/`) in
  report-only mode — bridges are loud but tolerated. Pull it (`adb shell
  cat …` or the gate's evidence dir), review, and merge genuine seeds
  into `game.toml` **plus the same-session symbols check**
  (`symbols/ffta_symbols.tsv` naming-only entries for new functions,
  `symbols/ffta_data_symbols.tsv` entries with measured sizes for new
  tables — see tests/README.md § the healing loop) — never auto-merged.
  An unharvested device journal is silent coverage debt: the 2026-10-11
  gAbilityAnimationTable batch (218 records, 137 handlers) sat invisible
  in the app's log dir until a gate run happened to resume that
  session's suspend state.
- **Pad idle auto-hide**: the touch pad hides after 15 s of screen-wide
  touch inactivity (`touch_pad_idle_hide_seconds = 15` in `src/main.cpp`);
  any touch reveals it and then acts normally — a tap after the quiet
  period is never swallowed (framework fork feature).

## Mods state (why `payload/mods/state.toml` ships)

The engine's runtime commit persists a raw `enabled = false` for
default-enabled features that were never explicitly touched (there is no
launcher pass on mobile to seed defaults), which would silently switch the
authored widescreen margins off from the second launch on. Shipping an
explicit `enabled = true` state makes the selection durable. `state.toml` is
player-owned afterwards: reinstalls never overwrite it, and players can
toggle the feature in the runtime settings menu (long-press / three-finger
tap). Candidate upstream note for gbarecomp.

## Build (Linux)

> The framework-level APK packaging rules (the scaffold contract, the
> private/distributable personalities, corpus freshness, repackage
> hygiene, versionName) live in `gbarecompx/packaging/README.md` §
> Android (APK) — this section is the per-game operational recipe.

One command wraps the whole private-build pipeline (preflight → Gradle →
content guard → install + device gate):

```sh
python3 build_apk.py              # arm64 private build, install, gate
python3 build_apk.py --no-install        # build + content guard only
python3 build_apk.py --abi x86_64        # emulator build
```

The prerequisites below are what its preflight checks. The manual route
follows.

Prerequisites (this machine): JDK 21 (`/usr/lib/jvm/java-21-openjdk` — the
default JDK 27 is too new for Gradle 8.11.1), Android SDK at
`/opt/android-sdk` (platform 35, build-tools 35, cmake 3.30.3, NDK
28.2.13676358), `adb`, and the `gbarecompx` framework checkout (the Android
scaffold base since Phase 4f; the Gradle project picks it up automatically
when the directory exists).

```sh
cd android
export JAVA_HOME=/usr/lib/jvm/java-21-openjdk ANDROID_HOME=/opt/android-sdk
# Private test build (ROM embedded; arm64 only for speed; the -PprivateRom
# path resolves relative to android/app, hence ../../; the BIOS is staged
# from the committed bios/ dir by payloadDirs, not a private flag):
./gradlew :app:assembleDebug -PgbaAbis=arm64-v8a -PgbaNativeJobs=12 \
  -PprivateRom=../../game.gba
# Distributable build (no ROM; import via the phone UI):
./gradlew :app:assembleDebug -PgbaAbis=arm64-v8a -PgbaNativeJobs=12
```

Notes: each ABI is a full native compile of the ~55k-unit corpus — always
narrow with `-PgbaAbis` while iterating (a full arm64 build took ~3 min on 12
jobs; libmain.so ≈ 99 MB). `generated/` must be fresh (`tools/cycle.py`
regenerates on desktop). The engine helper scripts under
`gbarecomp/platform/android/tools/` are PowerShell-only; on Linux drive
Gradle/adb directly as above. `sdkmanager` exits 1 after successfully
unzipping an NDK when a root-owned `emulator/package.xml` blocks its legacy
XML rewrite — harmless.

**Release artifact** (issue #3): `tools/make_release.py --apk` builds this
public path itself — preflight via `build_apk.py`, a **clean repackage**
(`android/app/build` removed first; native objects under `android/app/.cxx`
survive, so incremental-repackage slack can never strand bytes in the zip —
the junk class the APK guard's packaging-sanity check rejects), then the
[`tools/android_apk_check.py`](../tools/android_apk_check.py) gate with
`--expect public` before staging `release-stage/FFTARecomp-<version>-android-arm64-v8a.apk`
(debug-signed; the release-key decision is tracked on issue #3).

**APK archive (device A/B comparisons)**: outgoing builds are kept under
`android/artifacts/apk-archive/` (gitignored, like every APK output — private
builds embed the ROM and are never committed) with a `MANIFEST.txt` and
`SHA256SUMS.txt` naming each build's base; public release baselines live in
`release-stage/`. Archive the outgoing build before a base swap (the Phase 4f
raylib/NativeActivity move keeps the pre-4f build there), so device behavior
can be compared side by side. All builds share the debug key, so
`adb install -r` swaps them in place with saves preserved.

## Run + verify on device

```sh
tools/validate_android.sh                # full gate: install → launch → assertions → evidence
tools/validate_android.sh --no-install   # gate the build already installed
```

The gate installs the newest debug APK, launches through
`GbaSetupActivity` with the AUTOSTART extra, and asserts: process running,
`GbaGameActivity` resumed, runtime log says `cpu_backend=static-recompiled`,
no `SELF-HEAL`/`missing static coverage` lines, crash buffer free of
`fftarecomp`. Evidence lands in `android/artifacts/last-run/` (gitignored):
runtime log, miss frag/coverage (absent when clean), crash log, screenshot.

Manual equivalents:

```sh
adb install -r android/app/build/outputs/apk/debug/*PRIVATE*.apk
adb shell am start -n org.gbarecomp.fftarecomp/org.gbarecomp.GbaSetupActivity \
  --ez org.gbarecomp.extra.AUTOSTART true
adb shell run-as org.gbarecomp.fftarecomp cat files/android-runtime.log
```

For TCP debugging: `adb forward tcp:19888 tcp:19888` plus `--tcp-observe
19888` in `files/debug-args.txt`.

## The Android pre-boot surface

The **setup screen (`GbaSetupActivity`) is the Android launcher** — pure
Android, laid out like the desktop launch screen: box-art panel (from the
engine template's `launchBoxartRes` mechanism — staged as a
`drawable-nodpi/launcher_boxart.png` from the tracked
`recomp/launcher/boxart.png`, the same file the desktop build stages),
title, the resolved ROM path in the status line, **PLAY**, **SELECT ROM**
(the system file sheet — SAF, with size/SHA-1 verification), an optional
save import, and the "skip this screen on launch when ready" checkbox.
There is exactly one pre-boot screen per platform: this one on Android, the
C++ raygui launch screen on desktop.

Why the C++ launch screen is desktop-only (2026-10-16 device session): the
mobile platform appends `--no-launcher` (the device gate and the
suspend/resume lifecycle depend on an unattended boot), Android has no
desktop file-dialog backends (tinyfiledialogs' no-backend path prints a
banner and reads stdin), and a NativeActivity's event pump lives on the
native thread — a modal pick across the SAF sheet starves it. The pure
Android screen sidesteps all three.

Debug affordances, all honored through the mutated-args skip
classification (the native entry's argv is raylib's synthetic `{"raylib"}`,
so classification must read the argument vector, not raw argv — guarded by
`android-static`):

- `--no-launcher` skips the desktop launch screen; `run_game` tolerates the
  flag (a fatal "unknown argument" there once killed every mobile boot —
  PLAY appeared dead).
- `debug-args.txt` is **one-shot**: consumed and removed on the boot that
  reads it, so a forced flag can't persist across relaunches. Write
  `--launcher` (`adb shell run-as …`) to force the desktop screen for
  development — its ROM picker has no Android backend and fails cleanly
  (log line, never stdin).

## On-device suspend/resume protocol (the manual gate)

The device gate (`tools/validate_android.sh`) asserts **boot health only**
(process alive, activity resumed, `cpu_backend=static-recompiled`, no misses,
no crashes). The port's worst historical bug class — the suspend→A phantom
IRQ chain (split-loop nesting → stack exhaustion on the 256 MiB game thread;
`BRINGUP.md` § 2026-10-09) — is **structurally invisible to it**: the gate
cannot inject inputs, and its screenshot is pulled, never compared. The
desktop gates exercise the chain (`tools/hangrepro.py`,
`tools/desktop_accept.py`), but the device build carried *none* of the
2026-10-09 engine fixes at last contact (2026-10-08). For the press flow
specifically, `tools/android_press_test.py` drives it over the observe TCP
(`--tcp-observe`) on a live device session — savestate load, A press via
`set_keyinput`, frame advancement, anomaly scan, crash buffer. Run this
protocol manually after every engine-affecting change until the gate grows
native input injection. For longer gameplay reproduction,
`tools/android_trace_replay.py` replays a desktop-recorded input trace the
same way (push state + save, relaunch with observe TCP, feed each
`(frame, keyinput)` row by frame counter — timing good to ~1-3 frames,
enough for feel/audio checks, not cycle-exact work):
`tools/android_trace_replay.py --state saves/regress/battle_move_start.state --trace saves/regress/battle_move_trace.csv`.

**Prep:** fresh APK (`tools/cycle.py` regenerates `generated/`, then
`./gradlew :app:assembleDebug …` per § Build), `adb install -r`, a game save
at or past the in-battle suspend-save point, and this watch running:

```sh
# Live log tail + marker grep (the close/resume markers in order):
adb shell run-as org.gbarecomp.fftarecomp sh -c \
  'tail -f files/android-runtime.log' | \
  grep --line-buffered -E \
  'closing the IRQ|abandon-resume|SWI-return ledger|host-stack guard|SELF-HEAL'
```

**Steps — each observable in the log or on screen:**

| # | Action | Pass criterion | If it fails |
|---|---|---|---|
| 1 | Launch via AUTOSTART, reach a save-capable screen (world map / battle prep) | Frames advance, pad responsive, **no `host-stack guard unwind` lines** | Guard lines = a split loop still nests on device — engine re-triage |
| 2 | Open the system menu → **Suspend Save** (progress indicator appears) | Log shows the save flow complete; **no** `SELF-HEAL` / abort lines | If `SWI-return ledger override` fires repeatedly → the ledger is catching real corruptions on device — capture `android-runtime.log` + screenshot |
| 3 | Watch the save complete → game reboots into the intro/title sequence | Reboot visible; `cpu_backend` line intact after reboot | Hang at the completion gate = the desktop `hangrepro` class on device — pull the full log |
| 4 | **Press A** at the title / resume point (the historical trigger input) | Press acts normally; **no crash-buffer entry** mentioning the package | SIGSEGV/freeze ~seconds after press = the pre-fix phantom class — evidence: `android/artifacts/last-run/` + `adb logcat -d -b crash` |
| 5 | Resume from suspend (OS back gesture / power menu), then suspend→resume **twice** | Game continues each time; no stuck frame, no growing log spam | `g_irq_nest_depth`-style stickiness will show as repeated close/resume markers — record the repetition pattern |
| 6 | Re-run `tools/validate_android.sh --no-install` | GATE PASSED (all five assertions) | Any FAIL = regression vs the boot-only baseline |

**Evidence to pull on any failure:** `android-runtime.log` (full),
`recomp_master_misses_AFXE.toml.frag` + `recomp_coverage_AFXE.json` (a
non-empty frag means device-side misses — feed it to the healing loop per
`tests/README.md`), `crash.log`, screenshot, and the APK's build id
(`aapt2 dump badging | grep version`). Everything lands in
`android/artifacts/last-run/` (gitignored — never committed).

**Markers, what they mean:**

- `closing the IRQ … — closing the IRQ` — the abandon-close fired: a handler
  that never iret'd was closed coherently (IE/IME + ISR vector restored).
  **Expected once** during the suspend→save chain. Repeated lines at other
  times = suspicious.
- `abandon-resume intercept want=… got=…` — the flow-continuation resume
  redirected the first post-close dispatch with mode coherence.
- `SWI-return ledger override: SVC return wants pc=… but …` — the ledger
  caught a corrupted SVC return and kept the recorded continuation. This
  engine build *contains* the fix, so this firing means corruption is live
  on device — that's a finding, not a normal pass line.
- `runtime: host-stack guard unwind count=…` — the budget guard unwound a
  wedged spin. Bounded survival; investigate the spin that forced it.
- Any `SELF-HEAL` / `missing static coverage` — dispatch misses on device:
  the corpus is stale relative to this ROM state — regenerate + rebuild.

**Coverage note:** steps 2–5 cover exactly the flows the desktop acceptance
exercises (`tools/desktop_accept.py --mode tcp` scores the same press /
close / resume). A pass here + the gate's boot assertions is the honest
device-verification claim until the gate grows input injection.

### Device-free checks

`tools/android_static_check.py` (also the `android-static` suite in
`tools/check.py`; CI tier 1 runs it) validates the source-level Android
contract without a phone, an SDK, or a Gradle build: identity/pin consistency
across `android/app/build.gradle`, `game_android.toml` and `game.toml`; the
mods payload (`state.toml` keeps widescreen enabled for fresh installs and
matches the pinned catalog); no private/binary artifacts tracked and the
android build outputs gitignored; plus a fake-`adb` self-test of
`tools/validate_android.sh` — a clean run passes and pulls evidence, while
SELF-HEAL, missing-log, crash-buffer and setup-still-resumed runs fail the
gate with the right assertion, and usage errors exit 2. The device gate on a
real phone stays the authority for runtime behavior.

After a Gradle build, `tools/android_apk_check.py` (`--only android-apk` in
`tools/check.py`; outside the default run — a desktop worktree has no APK)
guards the artifact itself: the packaged payload must byte-match the staging
sources, a private build's embedded ROM must match the pin
(hash-verified), a public build must embed **no ROM** — the bundled
clean-room BIOS (emibios, hash-verified against the config pin) is
expected in **every** build — `libmain.so` must exist
exactly once per ABI, both activities must stay `sensorLandscape` with the
build type's debuggable flag, and the zip must be free of duplicate / stray /
oversized entries (the junk-blob class below). `--apk PATH` selects a
specific file; `--expect public|private` asserts the build mode.

## Saves & states (backup / import)

Battery saves and save states live in the **user-visible external app
directory**, so they can be backed up or imported without root or `run-as`:

| What | Path on shared storage |
|---|---|
| Battery save (64 KiB flash) | `Android/data/org.gbarecomp.fftarecomp/files/saves/ffta_us.sav` |
| Save-state slots 1–9 | `…/files/states/ffta_usa.state<N>` |
| Suspend state + marker | `…/files/states/ffta_usa.suspend.state` (+ `.suspend.pending`) |
| Runtime log | `…/files/logs/android-runtime.log` |
| Miss proposal frag | `…/files/logs/recomp_master_misses_AFXE.toml.frag` (only when misses occur — absent is the clean state) |
| Coverage report | `…/files/logs/recomp_coverage_AFXE.json` |

Diagnostics land beside saves/states (`src/main.cpp ffta_redirect_diagnostics`,
before the engine redirect; `MobileProcessOptions.log_file`). The session
opens with a `[ffta] manifest` line listing every resolved path, so a missing
file is meaningful (never written vs written-then-lost). When external
storage is unavailable the app-private `files/` fallbacks stand. A failed
log open falls back to logcat with a warning instead of silent loss (engine
patch, proposed upstream).

Browse it over USB/MTP, or via adb (`adb shell ls
/sdcard/Android/data/org.gbarecomp.fftarecomp/files`; `adb pull/push` the
`saves/` and `states/` trees). No storage permission is needed: an app
always owns its own external directory. **Import rule:** copy files in while
the app is fully stopped (`am force-stop` first); a foreign `.sav` must
still be the 65536-byte flash image or the boot warning fires.

**Setup-screen import (issue #20, desktop parity):** the setup screen offers
an optional third card, "Save data (optional)" — `CHOOSE SAVE` / `REPLACE
SAVE` through the same SAF picker as ROM/BIOS. The pick is size-validated
(65536 bytes for this game's 512-Kbit flash) and mirrored to both the
app-private `saves/` fallback and the user-visible external `saves/` dir the
runtime actually reads, so a re-import after the first launch is never
stranded by the one-time migration. Status shows `● Verified and ready`
once a valid save exists in either location, `○ Not provided` otherwise —
and PLAY is never gated on it (fresh start without a save stays one tap).
The card only appears when the build declares `saveFile`/`saveSize`
(`android/app/build.gradle`; engine placeholders `gbaSaveFile`/`gbaSaveSize`
→ manifest `gbarecomp.save_file`/`save_size` → `GbaGameConfig`; framework
fork code).

Example — loading a desktop/emulator save on the phone (the battery save
is always named `ffta_us.sav` regardless of where the original came from):

```sh
adb shell am force-stop org.gbarecomp.fftarecomp
adb push /path/to/your-old.sav \
  /sdcard/Android/data/org.gbarecomp.fftarecomp/files/saves/ffta_us.sav
```

Over USB/MTP, copy the file into `Android/data/org.gbarecomp.fftarecomp/
files/saves/` and rename it to `ffta_us.sav` (force-stop the app first,
same rule). The one-time outward migration never overwrites an existing
external copy, so an imported file is safe from it.

How it works: `src/main.cpp` (Android only) resolves the external directory
from the baked applicationId (`/sdcard/Android/data/<pkg>/files`), one-time
migrates any existing
app-private files outward (copy + size-verify + remove original, only when
the external copy is absent — a player-imported file is never overwritten;
the `.suspend.pending` marker is deliberately not migrated), then appends
`--save-path` / `--state-dir` (CLI wins over the staged TOML). The engine
knows `--state-dir` as framework fork code (slots/suspend keep the ROM
basename under that directory). When external storage is unavailable the staged
`game_android.toml` fallback (`files/saves/ffta_us.sav`, states next to the
ROM in `files/roms/`) stands. The device lifecycle gate
(`tools/android_lifecycle_test.py`) asserts the external locations, and
`tools/android_static_check.py` pins the wiring (filenames ↔ `romFile` ↔
TOML) device-free.

## Controller support (2026-10-17)

A gamepad — built-in, like the AYN Odin's, or USB/Bluetooth — drives the
game directly, with the same mapping as desktop:

| Action | Controller |
|---|---|
| A / B | A / B (label-wise) |
| L / R | LB / RB |
| Start / Select | Start / Select |
| D-Pad | D-pad or the left stick (25% deadzone) |
| Fast-forward (hold) | right trigger |
| Settings menu | the pad's menu/center button, Y, the device Back key, or a screen long-press / three-finger tap |

Fast-forward speed (2–10x) is set in the in-game menu's **Assist** section,
alongside the same control on desktop. Full controls and behavior:
[`docs/fast-forward.md`](../docs/fast-forward.md).

Why a capture layer exists (the short version): Android tags every input
event with source flags, and some devices (the Odin, measured:
`KEYBOARD | GAMEPAD | JOYSTICK`) flag their *button* events as keyboard
too — raylib's Android backend then drops them, and the OS "helpfully"
synthesizes fallback keys for the unhandled presses (the device keymap
maps `BUTTON_B→BACK`, `BUTTON_A→DPAD_CENTER`: the classic "B opens the
menu" symptom, arriving ~36 ms late with keyboard auto-repeat while
held). The runtime captures gamepad events at the glue level and trusts
the keycode, not the source bits — face buttons play as GBA buttons, the
d-pad still reaches raylib's keyboard table for menu navigation, and a
real Back press keeps its menu gesture (`android_gamepad.h` in the
framework; the mechanism is written up in
`reference/dev-gotchas.md`).

## Haptics (2026-10-20)

The Android build uses the platform vibrator for host haptics. The FF pill's
existing pulse (`host_haptic_pulse(15, 0.5)`) is the first real consumer.
`host_primary_haptic(strength, ms)` routes a gameplay pulse by primary input
modality: touchscreen → phone vibrator. An active pad is tracked as primary
and will use the controller's motors once the glue device-id capture lands
(Phase 2 of `.opencode/HAPTICS_PLAN.md`, deferred in this pass). Pulses are
attributed as media/game (`VibrationAttributes.USAGE_MEDIA` on API 33+,
`AudioAttributes.USAGE_GAME` below) so OEM "touch haptics off" settings do not
silently drop them. A device without a vibrator is a silent no-op; the
`VIBRATE` permission already ships. Damage-triggered haptics (issue #30
Phase 4) and the haptics setting (Phase 5) are not wired in this pass.
Contract and platform details: [`gbarecompx/docs/HAPTICS.md`](../gbarecompx/docs/HAPTICS.md).

## Known behavior

- **Split-loop nesting (fixed 2026-10-09, `607ca07`):** the vblank wait
  loop (`0x08000418` ↔ `0x08000428`) was two generated functions, so every
  spin iteration nested two host calls — the stack-exhaustion carrier for
  the suspend-flow hang. The finder's gap roll-in + in-body forward gotos
  now keep the loop in ONE host frame (dispatch entry
  `{0x08000428u, 1u, 1u, gf_vblank_wait_loop}` — a resume alias). The
  IRQ abandon-close (`d152a46`) additionally closes a handler that never
  iret'd, so a stalled spin can no longer leave `g_irq_nest_depth` stuck.
- **Host-stack guard** (framework fork code): retained as the second line
  of defense — a spin that still fails to
  unwind (any other split loop) unwinds through the runtime's standard
  yield path before the 256 MiB game-thread stack is exhausted, logging
  `runtime: host-stack guard unwind count=… pc=…` to `android-runtime.log`.
- **Desktop repro (2026-10-09):** `tools/hangrepro.py` (`check.py --only
  hangrepro`) — steppable `--tcp` + `savestate_load game.state3` + A:
  pre-fix it SIGSEGV'd ~26 steps after the press (nested
  `gf_vblank_wait_loop` frames); now the phantom IRQ closes, the loop is
  one frame, and the guest's own flow survives the close (flow-continuation
  resume): the suspend save completes and the game reboots into its intro
  sequence, matching the mGBA oracle (BRINGUP § true root /
  § flow-continuation resume). The in-battle suspend save → title trigger
  is described in `BRINGUP.md` § 2026-10-08/09; on-device capture:
  `tools/hangprobe.py` + `reference/dev-gotchas.md` § Android device
  forensics. Device re-verification after these fixes: **done 2026-10-09**
  (§ On-device suspend/resume protocol → now
  `tools/android_press_test.py` + `tools/android_lifecycle_test.py`,
  both PASS on the current engine — see the status header).
- Repackaging after a native relink can leave a junk blob inside an
  incrementally updated APK (67 MB vs the normal 37 MB, observed once; **a
  second form observed 2026-10-09: ~30 MB of stale bytes in the slack
  between the last zip entry and the APK signing block — a whole prior
  build's entry data left in place; invisible to `infolist()`-based
  checks**); `rm -rf android/app/build` before packaging when artifact size
  matters (native objects under `android/app/.cxx` are preserved). The APK
  content guard flags duplicate and unexpected large *entries*; the
  between-entries slack form needs a file-size vs sum(entries) check.
- 256-wide title/UI BGs show tilemap wrap fragments at wide views — the same
  margin policy that desktop validated (the W3 rules pillarbox the world map
  and clip UI layers; scenes whose *main* BG is a 256 tilemap wrap
  cosmetically). Field/battle 512-rings render authored margins — verified on
  the intro field at 356x160.
- Gate screenshots taken ~40 s after launch can catch the intro's zoom
  animation mid-frame; that is timing, not a rendering fault.

## Deferred (do later, in rough order)

1. Release packaging: keystore/signing, arm64-only release, version
   stamping.
2. Touch-first input scheme (the engine's virtual pad is the v1 control).
3. Perf/size pass (first build only measured qualitatively).
4. Upstream note: mods-state default persistence on launcher-less runs.
5. Robolectric shell unit tests (device-free JVM, no emulator): exercise the
   engine shell's Java logic — SAF import verification (size/SHA-1 reject
   paths, temp-file cleanup), payload install (version marker,
   `state.toml`/`.sav` player-file preservation), `GbaGameConfig`
   merged-manifest wiring — via `./gradlew :app:testDebugUnitTest`. Needs
   test deps (junit + Robolectric) and an SDK-equipped CI tier.
