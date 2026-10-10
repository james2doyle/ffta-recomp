# Android (FFTARecomp)

Status 2026-10-08: **playable on device** — skeleton, build, first boot,
widescreen and the device gate are all verified on a Xiaomi Mi 11
(Android 14/API 34). Working reference for the Android target — moved here
from the repo root (2026-10-09; previously `ANDROID.md`); `BRINGUP.md` keeps
the dated decision log and `reference/dev-gotchas.md` § Android device
forensics has the on-device debugging recipe. Re-verification after the
2026-10-09 engine fixes is pending — run § "On-device suspend/resume
protocol" on the next phone session.

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
- **Testing** via private ROM-embedded APKs (`-PprivateRom/-PprivateBios`):
  debug-signed, auto-named `…-PRIVATE-rom-included.apk`, never committed or
  distributed (`.gitignore` covers `*.apk`). Public builds import ROM/BIOS
  through the phone UI with SHA-1 pins.
- **Pad idle auto-hide**: the touch pad hides after 15 s of screen-wide
  touch inactivity (`touch_pad_idle_hide_seconds = 15` in `src/main.cpp`);
  any touch reveals it and then acts normally — a tap after the quiet
  period is never swallowed (engine patch: `touch-pad-idle-hide.patch`).

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
# Private test build (ROM+BIOS embedded; arm64 only for speed; the
# -Pprivate* paths resolve relative to android/app, hence ../../):
./gradlew :app:assembleDebug -PgbaAbis=arm64-v8a -PgbaNativeJobs=12 \
  -PprivateRom=../../game.gba -PprivateBios=../../gbarecomp/bios/gba_bios.bin
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

## On-device suspend/resume protocol (the manual gate)

The device gate (`tools/validate_android.sh`) asserts **boot health only**
(process alive, activity resumed, `cpu_backend=static-recompiled`, no misses,
no crashes). The port's worst historical bug class — the suspend→A phantom
IRQ chain (split-loop nesting → stack exhaustion on the 256 MiB game thread;
`BRINGUP.md` § 2026-10-09) — is **structurally invisible to it**: the gate
cannot inject inputs, and its screenshot is pulled, never compared. The
desktop gates exercise the chain (`tools/hangrepro.py`,
`tools/desktop_accept.py`), but the device build carried *none* of the
2026-10-09 engine fixes at last contact (2026-10-08). Run this protocol
manually after every engine-affecting change until an instrumented driver
exists.

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
sources, a private build's embedded ROM/BIOS must match the pins
(hash-verified), a public build must embed neither, `libmain.so` must exist
exactly once per ABI, both activities must stay `sensorLandscape` with the
build type's debuggable flag, and the zip must be free of duplicate / stray /
oversized entries (the junk-blob class below). `--apk PATH` selects a
specific file; `--expect public|private` asserts the build mode.

## Known behavior

- **Split-loop nesting (fixed 2026-10-09, `607ca07`):** the vblank wait
  loop (`0x08000418` ↔ `0x08000428`) was two generated functions, so every
  spin iteration nested two host calls — the stack-exhaustion carrier for
  the suspend-flow hang. The finder's gap roll-in + in-body forward gotos
  now keep the loop in ONE host frame (dispatch entry
  `{0x08000428u, 1u, 1u, gf_vblank_wait_loop}` — a resume alias). The
  IRQ abandon-close (`d152a46`) additionally closes a handler that never
  iret'd, so a stalled spin can no longer leave `g_irq_nest_depth` stuck.
- **Host-stack guard** (`tools/patches/host-stack-guard-desktop.patch`):
  retained as the second line of defense — a spin that still fails to
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
  forensics. Device re-verification after these two fixes is pending — run
  § "On-device suspend/resume protocol" on the next phone session.
- Repackaging after a native relink can leave a junk blob inside an
  incrementally updated APK (67 MB vs the normal 37 MB, observed once);
  `rm -rf android/app/build` before packaging when artifact size matters
  (native objects under `android/app/.cxx` are preserved). The APK content
  guard flags duplicate and unexpected large entries, so this class cannot
  ship silently.
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
