# Android (FFTARecomp)

Status 2026-10-08: **playable on device** — skeleton, build, first boot,
widescreen and the device gate are all verified on a Xiaomi Mi 11
(Android 14/API 34). This doc is the working reference for the Android
target; `BRINGUP.md` keeps the dated decision log.

## How the port is structured

The **app shell lives in the engine**, not this repo:
`gbarecomp/platform/android/` (present at the pinned engine revision) carries
the shared Gradle template (`gbarecomp-app.gradle`), the Java activities
(`org.gbarecomp.GbaSetupActivity` — SAF file picker with size/SHA-1
verification → app-private storage; `org.gbarecomp.GbaGameActivity`), the
vendored SDLActivity sources, and the CMake root that builds SDL2 and then
the game project. The game project must define a **SHARED target named
`main`** (`libmain.so`, loaded by SDLActivity).

This repo therefore adds only a thin surface:

| File | Role |
|---|---|
| `android/app/build.gradle` | `ext.gbaGame` identity block + applies the engine template |
| `android/game_android.toml` | Runtime-only TOML, staged to `files/variants/final_fantasy_tactics_advance/game.toml` |
| `android/payload/mods/state.toml` | Default mod selection for fresh installs (widescreen on — see "Mods state" below) |
| `android/{build,settings}.gradle`, `gradle.properties`, wrapper | Gradle 8.11.1 / AGP 8.10.1 project |
| `android/app/src/main/res/…` | `app_name`, original vector launcher icon (no third-party art) |
| `CMakeLists.txt` (`if(ANDROID)`) | Target `main` instead of `FFTARecomp`; forced mods; SDL/UI guards |
| `src/main.cpp` | `mobile_prepare_process` preflight, phone run options, `SDL_main` via a 256 MiB pthread |
| `tools/validate_android.sh` | Device acceptance gate (assertions + evidence pull) |

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
- **Testing** via private ROM-embedded APKs (`-PprivateRom/-PprivateBios`):
  debug-signed, auto-named `…-PRIVATE-rom-included.apk`, never committed or
  distributed (`.gitignore` covers `*.apk`). Public builds import ROM/BIOS
  through the phone UI with SHA-1 pins.

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

Prerequisites (this machine): JDK 21 (`/usr/lib/jvm/java-21-openjdk` — the
default JDK 27 is too new for Gradle 8.11.1), Android SDK at
`/opt/android-sdk` (platform 35, build-tools 35, cmake 3.22.1, NDK
27.1.12297006), `adb`, and the engine's SDL submodule initialized
(`git -C gbarecomp submodule update --init platform/android/third_party/SDL`).

```sh
cd android
export JAVA_HOME=/usr/lib/jvm/java-21-openjdk ANDROID_HOME=/opt/android-sdk
# Private test build (ROM+BIOS embedded; arm64 only for speed):
./gradlew :app:assembleDebug -PgbaAbis=arm64-v8a -PgbaNativeJobs=12 \
  -PprivateRom=../game.gba -PprivateBios=../gbarecomp/bios/gba_bios.bin
# Distributable build (no ROM/BIOS; import via the phone UI):
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

## Known behavior

- **Host-stack guard** (`tools/patches/mobile-host-stack-guard.patch`): a spin
  that fails to unwind — the split vblank-wait loop (`0x08000418` ↔
  `0x08000428`) — now unwinds through the runtime's standard yield path
  before the 256 MiB game-thread stack is exhausted, logging
  `runtime: host-stack guard unwind count=… pc=…` to `android-runtime.log`.
  If the underlying stall recurs on device, expect a bounded freeze with
  guard lines rather than a native crash — grab the log for the next step.
- Repackaging after a native relink can leave a junk blob inside an
  incrementally updated APK (67 MB vs the normal 37 MB, observed once);
  `rm -rf android/app/build` before packaging when artifact size matters
  (native objects under `android/app/.cxx` are preserved).
- 256-wide title/UI BGs show tilemap wrap fragments at wide views — the same
  margin policy that desktop validated (the W3 rules pillarbox the world map
  and clip UI layers; scenes whose *main* BG is a 256 tilemap wrap
  cosmetically). Field/battle 512-rings render authored margins — verified on
  the intro field at 356x160.
- Gate screenshots taken ~40 s after launch can catch the intro's zoom
  animation mid-frame; that is timing, not a rendering fault.

## Deferred (do later, in rough order)

1. Release packaging: keystore/signing, arm64-only release, APK content
   guard, version stamping.
2. Touch-first input scheme (the engine's virtual pad is the v1 control).
3. Perf/size pass (first build only measured qualitatively).
4. Upstream note: mods-state default persistence on launcher-less runs.
5. AGENTS.md / README pointers and roadmap update.
