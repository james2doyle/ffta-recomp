# Dev gotchas — harness traps, run modes, environment

Moved out of `AGENTS.md` on 2026-10-08 (was § Environment notes + §
Environment gotchas); load it when operating the harness, debugging run
modes, or touching the RAM-dispatch / save machinery. Every trap below cost
real hours once.

## Environment

- Linux (Arch). No `pip3`/`arm-none-eabi-*`: use `uv` + `.venv/` (capstone).
  Disassemble with `gbarecompx/tools/disarm.py <start> <end> [arm|thumb]` (hex GBA
  addresses) via `.venv/bin/python`.
- BIOS: `[bios] hle = false` requires a real dump at
  `gbarecompx/bios/gba_bios.bin` (user-supplied, never committed; SHA-1
  `300c20df6731a33952ded8c436f7f186d25d3492`). Never download a BIOS.
- System mGBA (`mgba-qt` 0.10.5) is for manual eyeballing only — the
  validation harness uses the framework's own oracle:
  `reference/oracle-harness.md`.
- `gbarecompx/tools/disarm.py` halts silently at the first undecodable halfword — use
  narrow windows anchored on known boundaries, and always state the mode
  (`arm`/`thumb`): wrong-mode output reads as plausible garbage.
- Data-vs-code traps: pointer tables masquerade as code (cross-check the
  other mode; validate against known structure). For runtime-relocated
  IWRAM blobs, dump via `read_iwram` during a live session and disassemble
  with capstone at the known base — partial dumps of unknown base are
  useless.
- **Input injection: `ydotool` only.** This session is Wayland and the
  game window is native — `xdotool` cannot see or reach it (user directive:
  never use it). Verify a press actually lands by reading KEYINPUT
  (`read_io 0x04000130`, active-low) while the key is held; silent focus
  loss eats injected keys, and "the game ignored input" is not a valid
  conclusion without that check.

## Run modes and tracing

- **Cold-cache everything that is evidence.** The self-heal overlay cache
  perturbs IRQ-resume landing PCs run-to-run; warm-run miss lists are not
  stable. `tools/cycle.py` regens cold; strict runs are inherently cold;
  `rm -rf recomp_cache` before one-off checks.
- `GBARECOMP_INPUT_REPLAY` is applied by the headless `--frames` loop only —
  TCP `run_frames`/`step` does NOT apply replay events (check KEYINPUT at
  0x04000130 if in doubt). Run replay gates headless.
- `--tcp` mode does NOT process `--load-state` (silently skipped — no
  `savestate_loaded` line). Load over TCP with `savestate_load {path}`
  (GBAS container; refuses wrong SHA-1/version).
- Desktop repro of the Android save-hang (2026-10-09): `--tcp` +
  `savestate_load game.state3` → `step`×98 → `set_keyinput 0x03FE` ×4 →
  `0x03FF` → deterministic SIGSEGV ~26 steps later. gdb bt: ~284k nested
  `gf_vblank_wait_loop` ↔ `gf_vblank_wait_loop_cont` frames = host-stack
  exhaustion (~60 B/frame); pre-press 600 steps clean. Drive it alongside
  `gdb -batch -ex run -ex bt --args …` for the tombstone. Mechanism + fix
  candidates: `BRINGUP.md` § 2026-10-09.
- Tracing without code changes: `GBARECOMP_MISS_IWRAM_DUMP` (state at first
  IWRAM miss), `GBARECOMP_IWRAM_DUMP` (exit state), `GBARECOMP_WRAM_TRACE`
  +`_LO/_HI` (per-frame write diff), `GBARECOMP_INSN_TRACE=1` +
  `GBARECOMP_FP_SAVE` (per-instruction ring, ~8.4 M-insn window — size
  `--frames` so the event lands inside; query with `gbarecompx/tools/ringscan.py`).
- Pinned TCP surface: `step`/`run_frames`/`set_keyinput`/`screenshot`/
  `registers`/`state_hash` + memory reads exist; `run_to_pc`/`get_registers`/
  `call_stack`/`rdb_*` do not.
- `FFTA_DISPATCH_LOG=1` (see `src/ffta_ram_dispatch.h`) logs every RAM-
  dispatch hook branch (enter/case1/case2/resume-passthru/fall) with
  registers to stderr.
- Long non-strict runs are safe (present-in-place + background healing; the
  session-5 acceptance replay runs 112,000 frames headless). Strict runs are
  faster and are the acceptance.

## Pre-boot launch screen (the 2026-10 raygui launcher)

- **Bare invocation opens the launch screen** — a real raylib window. Every
  scripted/headless run must pass an explicit path or a headless flag:
  `--rom`, `--bios`, `--no-window`, `--frames`, `--load-state`, `--tcp`
  each skip the screen (`gbarecomp::launcher_should_skip_screen`); anything
  else shows it. A CI job that boots the binary bare gets a window (or a
  GL failure) instead of a game — that is the trap, not a hang.
- **The screen never validates a ROM itself.** Picks flow through
  `gbarecomp::resolve_asset` (hash + CRC validation, writes `rom.cfg`).
  **Select ROM** uses the picker's forced path (bypasses a valid cache —
  2026-10 repick fix); the first-boot auto-open uses the normal cache
  fast path.
- **No dialog provider = clean failure, never stdin.** Before showing a
  dialog the picker probes with `tinyfd_openFileDialog("tinyfd_query", …)`:
  `no_solution` (or any console mode) returns a hard error
  ("no file dialog available; use --rom"). Headless/SSH/CI and wine
  bare-extraction runs fail loudly instead of blocking. The wine release
  smoke therefore always passes `--rom`/`--bios` explicitly
  (`tools/make_release.py wine_smoke`).
- **Box art is optional at runtime**: the launcher loads
  `assets/img/boxart.png` beside the executable (CMake `stage_boxart`
  target in dev builds; release staging copies it from
  `recomp/launcher/boxart.png`). Missing file → the text fallback renders;
  not an error.

## Sessions and close handling

- Close with **ESC in-game** (verified clean, rc≈0, ~2 s teardown). The
  titlebar X / Alt+F4 close request is NOT delivered under the current SDL
  stack (binary links `sdl2-compat` = an SDL3 shim; BRINGUP § "Close-hang
  investigation"); SIGTERM/SIGINT are not close mechanisms either. Scripted
  fallback: `.venv/bin/python gbarecompx/tools/quit.py <tcp-observe port>` — play.sh
  archives savestates/traces and flushes the miss frag on either path.
- The `--tcp-observe` server serves ONE client at a time — disconnect
  watchers before probing or commands will time out.
- Desktop keyboards: with an input-method daemon (IBus/GNOME), special keys
  (Enter/Backspace) can be swallowed inside the game window. Use the
  letter-only keymap (`tools/playtest_keybinds.ini.example`; copy to
  `build/keybinds.ini`) and verify with `tools/keyprobe.py` or
  `GBARECOMP_INPUT_RECORD`.
- Window size vs view: `--scale N` (1–8) resizes the window; `--view-width`
  is the widescreen *view* (FFTA opts in, up to 448; `--resize-view` follows
  the window aspect, windowed-only by design; `--fullscreen` = borderless).
  Validation: `tools/ws_check.py`; internals: `reference/widescreen.md`.

## Deep-debug toolkit (gdb, rings, guest watchpoints)

Built during the 2026-10-09 hang walk (BRINGUP § 2026-10-09 later); every
recipe below is validated there.

- **gdb batch with a script file**: `gdb -batch -ex "file <exe>" -ex
  "set args …" -x script.gdb` — `-ex`/`-x` run in command-line order, so
  `file` must come before `-x` (otherwise "No symbol table is loaded").
  Release builds have no `-g`: use a side build (`cmake -B build-gdb
  -DCMAKE_BUILD_TYPE=RelWithDebInfo`) for typed access (struct fields,
  `g_cpu.R[15]`, `'gbarecomp::g_active_bus'`).
- **Auto-continue logging breakpoints**: gdb python `Breakpoint` subclasses
  whose `stop()` prints and returns False (rate-limit heavy tags). Used for
  `runtime_irq`/callback entries with `$rsp` = the per-frame stack-depth
  curve (chain growth/retention shows up immediately).
- **Guest-RAM hardware watchpoints**: watch the runner's host mirror of a
  guest cell — e.g. `'gbarecomp::g_active_bus'->iwram_[0xE10]` — and log
  writer pc + new value per hit: identifies every writer of a flag
  (`gpc=0x0800051C` sets it, `gpc=0x08000416` clears it, …) and when a
  writer stops.
- **Per-instruction rings, dumped while ALIVE**: `GBARECOMP_INSN_TRACE=1`
  + TCP `fp_save {path}` (works in `--tcp`; call it between steps — no
  watchdog trip needed). Format: 16-byte header `<IIQ>`, then 80-byte
  records `<Q18I` = cycles, pc, cpsr, r0..r12, sp, lr, r15. Count the
  event under suspicion (e.g. "the spin never exits" dies instantly:
  flag-read=1 count == exit count), then diff pc histograms between two
  dumps bracketing the event — a new/vanishing pc population is the
  behavioral delta (the SWI-family diff pinned the 2026-10-09 hang).
  `gbarecompx/tools/ringscan.py` queries the same files.
- **Guard-gate signature**: a depth-gated guard that never fires while the
  stack visibly grows → print `g_irq_nest_depth` at mainline PCs; a stuck
  ≥1 (poisoned by a guest-return × IRQ interleave) disables the
  `nest_depth == 0` gate. See BRINGUP § 2026-10-09 later.
- **BIOS addresses you will see in rings** (standard GBA BIOS; roles here
  chain-verified 2026-10-09): `0x00` reset vector → `0x68` init; `0x84/0x88`
  init path that switches to ARM; `0x18` IRQ vector; `0x64`/`0x13C`
  `subs pc, lr, #4` exception-return sites (ARM `-4` compensation is wrong
  for a THUMB LR — watch for off-by-2/4 returns); `0x170..0x188` SWI entry /
  epilogue; `0xB56..0xB9C` CpuFastSet-style copy loop region.
- **The ring is ground truth over bookkeeping logs**: the 2026-10-09 chain
  showed an `exc-ret new_pc=0x814186E` log line while the actual fetch
  sequence resumed at `0x8033BA` — computed/logged values can disagree with
  what the CPU really executed; confirm every hand-off in the per-instruction
  ring before drawing conclusions.
- **Present-in-place never unwinds on vblank** (windowed runner): a wedged
  guest can stay inside one dispatch forever (frames still present, screen
  frozen, no new `runtime_dispatch`). Diagnostic: pc sampling churns in a
  data region; the fix pattern for a runtime redirect is the one-shot
  unwind hook `runtime_abandon_resume_pending()` consulted by
  `runtime_should_yield` (2026-10-09, BRINGUP § windowed close-route).
- **Observe vs full TCP surfaces differ in command availability**: the
  `--tcp-observe` surface accepts `set_break_pc`/`set_keyinput`/reads but
  NOT `fp_save` ("callback not wired") and no step; the full `--tcp` surface
  has everything but the windowed derail (stack-slot slip family) did NOT
  reproduce there (0/16) — run repro hunts in the mode that catches it
  (`--tcp-observe`). Ring dumps on observe come from the ENGINE-side hooks:
  `GBARECOMP_BRIDGE_ENTRY_FP`, `GBARECOMP_BRIDGE_ABORT_FP`, and
  `GBARECOMP_BREAK_FP` (dump when a `set_break_pc` park fires — the last
  record is the instruction that TRANSFERRED to the break pc, with full
  registers).
- **Garbage-pc triage trick that worked**: when a dispatch miss/abort shows
  a nonsense target (0x080000F0, 0x00000FF8, mid-function addresses), read
  the loaded state's RAM and search for the value — the derail targets were
  verbatim STACK WORDS near SP (e.g. `[0x03007EBC]=0x080000F0`), i.e. a
  return popped an adjacent slot. Check `read_iwram` around SP before
  theorizing about code.
- **The BIOS cart-boot trampoline (0x1C-0x64) and System-mode SPSR**: the
  soft-reset path runs the BIOS SWI dispatcher in SVC, but the dispatcher
  itself switches to **System** (`msr cpsr_cf, (spsr & 0x80) | 0x1F`, at
  0x158-0x160) before calling services — services (CpuSet/CpuFastSet/soft
  reset) legitimately run in System. The post-reboot resume uses
  `mrs spsr`/`msr spsr` + `subs pc, lr, #4` from System mode and depends on
  the ARM7TDMI System-mode SPSR storage behavior; our engine (and the
  reference interpreter) treat SPSR access in User/System as
  undefined/no-restore, so the resumed dispatch keeps the wrong T (ARM into
  a thumb address — miss → bridge → Undefined abort, cf. 0x08000494/0x0FF8).
- **IWRAM addresses worth knowing in stall triage**: `[0x03007FFC]` =
  the ISR vector (healthy: `0x03000F10`, the game's IWRAM IRQ dispatcher;
  the 2026-10-09 phantom trampled it to `0x080000FC`); `[0x03000E10]` =
  the save flow's completion marker the crt0 frame gate (`gf_vblank_wait_loop`)
  waits on (nonzero exits; the healthy flow writes `0x0100`). NEITHER is
  IRQ-ticked — a stalled flow waiting on `0x03000E10` means the save flow
  never completed, not that IRQs are off.
- **`runtime_dispatch` derives thumb/arm from `CPSR.T`, not the pc bit**
  — redirecting a pc while the CPU carries a stale mode resolves the
  target in the wrong mode (table miss -> bridge -> Undefined). Always
  make the mode coherent with the redirect.
- **Ring dump at any breakpoint**: launch with `GBARECOMP_INSN_TRACE=1`
  (the fingerprint ring must be armed) and, at a gdb stop, call
  `runtime_fp_save_file("/tmp/fp.bin")` — the whole per-instruction ring
  (8.4M records; `<Q18I`: cycles, pc, cpsr, r0-r12, sp, lr) dumps without
  needing a clean process exit. This caught the 2026-10-09 handler-loss
  chain end to end (BRINGUP § true root).

## Android device forensics (no root)

Build/run/gate and known device behavior: `android/README.md`.

Stock Android 14: `debuggerd -b <pid>` is root-gated even for debuggable
apps, `/proc/<pid>/task/<tid>/stack` is unreadable, and SIGTERM is not a
close mechanism — but `run-as <pkg>` (debug build) gives full same-uid
access, which is enough:

- Thread stacks are labeled in `/proc/<pid>/maps` as
  `[anon:stack_and_tls:<tid>]`; the recompiled game thread's is the
  ~256 MiB one. `ps -AT` lists tid/name/state (state is the 9th column).
- Same-uid reads that work via `run-as`: `maps`, `stat` (utime+stime
  deltas ≈ CPU rate; one-shot `top` percentages mislead), `syscall`
  ("running" = userspace spin; otherwise the blocked syscall + args incl.
  sp), and `/proc/<pid>/mem` (`dd bs=4096 skip=<addr/4096>` seeks).
- Pull dumps out via the app dir: `adb shell run-as <pkg> dd
  if=/proc/<pid>/mem of=files/x.bin bs=4096 skip=N count=M`, then
  `adb exec-out run-as <pkg> cat files/x.bin > /tmp/x.bin` (delete the
  device copy afterward).
- Symbolize stack pointers with the NDK's `llvm-symbolizer`/`llvm-nm`
  against the UNSTRIPPED build output
  (`android/app/build/intermediates/cxx/Release/*/obj/arm64-v8a/libmain.so`;
  the in-APK lib is stripped). The lib's runtime base is its first `r-xp`
  map: `vaddr = runtime_addr - base`. A repeated return address across a
  deep stack names the recursing call site directly.
- Device sessions read extra runtime args from `files/debug-args.txt`
  (create with `run-as`; e.g. `--tcp-observe 19888` +
  `adb forward tcp:19888 tcp:19888`). Observe servers are single-client;
  `savestate_save` queues for "the next present", so on a stalled guest it
  never completes and WEDGES the server — probe read-only
  (`tools/hangprobe.py`) instead.
- Miss proposals on device: live journaling needs `GBARECOMP_MISS_FRAG`
  (FFTA sets it in `src/main.cpp` `on_mobile`); the exit-time report never
  runs on a hung/killed session.
- `set_break_pc` (observe) unwinds dispatches when a guest PC is reached —
  powerful for "does this code ever run", but on an IRQ-path PC it can
  trip the engine's handler-abandon rail (4 M dispatches) and the session
  derails into a crash afterward. Use it as the last probe, on a session
  you don't need to keep.
- Save transplant: `am force-stop` first, then `run-as <pkg> mkdir -p
  files/saves`, `adb push` to `/data/local/tmp`, `run-as cp` into place,
  md5-compare, relaunch. Validate the image first with
  `tools/savecheck.py`. The game keeps redundant record groups — an
  interrupted write is ignored in favor of the previous valid group.
  (Players import through the setup screen's save card instead, issue #20;
  this recipe is the forensics path for sessions where the UI is bypassed.)

## BIOS recompile, build, stack

- BIOS recompile must run with cwd = `gbarecompx/` **and pass
  `--config ../bios/emibios_gba_bios.toml`** — else output lands in the wrong
  `src/runtime/generated_bios/`, or only 666 of 770 functions are discovered
  and strict runs abort on a miss at pc `0x300`. After generating, **re-run
  CMake configure** (not just build) so the framework re-detects
  `bios_recompiled.cpp`.
- Linux stack: the host main thread needs RLIMIT_STACK raised
  (`src/main.cpp` `raise_stack_limit`; hard limit must be unlimited).
- Windows cross build (`tools/make_release.py --windows`): the exception
  is prefix poisoning, not flags. If the exe links a third-party DLL
  (objdump guard names it — `libstdc++/libgcc/winpthread/raylib deps`),
  the cross prefix leaked a dynamic artifact: rebuild it
  (`tools/win_cross_deps.py build` prunes `*.dll`/`*.dll.a` after every
  install by design), then the exe. If the game configure "loses" raylib,
  `GBARECOMP_MINGW_PREFIX_UNIX` must point at the prefix and
  `CMAKE_PREFIX_PATH` at the toolchain's `FFTACROSS_PREFIX` — the engine
  falls back to `C:/msys64/…` paths that don't exist on a Linux cross
  box. Determinism rule (R2, byte-proven): never post-link strip a PE
  (`strip` rewrites TimeDateStamp per run — link-time `-s` only), and
  always verify byte-equality across a **wipe**-rebuild, not an in-tree
  rebuild.

## RAM-resident code and saves

- FFTA's save/flash driver re-plants position-independent helpers at
  stack-relative addresses and calls them via `bx` veneers; fixed dispatch
  entries (esp. `static_resume_all` aliases) can run stale AOT for a
  re-planted slot (2026-10-07 load-hang). Every RAM-range dispatch goes
  through `src/ffta_ram_dispatch.h` (`g_runtime_ram_dispatch_hook`), which
  byte-verifies live copies against their ROM source and runs the canonical
  generated body. New copied-routine families get a template there — never a
  bare fixed address (BRINGUP § "Load-hang root cause & fix").
- Save flows are stable since the mid-copy resume fix (commit `1eeb60f`,
  `r2 == 0xFFFFFFFF` passthru): the found-save repro and all save routes
  replay strict-clean; open-bus reads are oracle-identical (BRINGUP
  cont.2–4). Open-minor: ~950-frame native-vs-oracle flow offset.
- Validate external saves structurally first:
  `.venv/bin/python tools/savecheck.py <save>` (raw 64 KiB images + RTN5
  containers; checksum = the game's own CRC, reversed + verified).
- `[[code_copy]]` maps decoding only; runtime entry PCs inside a copied span
  still need `[[extra_func]]` seeds (probe with `gbarecompx/tools/misspack.py` +
  a source-side prologue scan).

## Submodules (the framework is the gbarecompx fork)

- The `gbarecompx` submodule points at **james2doyle/gbarecompx**
  (`https://github.com/james2doyle/gbarecompx.git`) — the framework fork
  carrying every former local patch as committed history (launch screen,
  tinyfiledialogs picker, emibios default BIOS, host-stack guard, SWI
  ledger, mmio cap, …) plus the post-fork work (LCD/menu stack). There are
  **no working-tree patches**: framework changes are fork commits, pushed,
  then the game repo's gitlink moves.
- Nested pins (inside the fork's own `.gitmodules`): arm-recomp-core →
  james2doyle/arm-recomp-core @ `cd010b5`
  (`feat/in-body-forward-goto` — in-body forward gotos, how the split
  vblank loop stays in one host frame; master `1f13cdf` merged
  `fix/link-startup-cycles`), rbengine @ `2a03e7`, recomp-net @ `c58f125`.
- Framework upstream sync = merge `mstan/gbarecomp` main into the fork,
  re-verify (attract + strict replays), push, then move the game repo's
  gitlink — a deliberate milestone, not a routine pull (the 2026-10-12
  drift lesson still applies; the `check.py --fast` gates referee it).
- Dev-box fetch/push: on boxes where `https://github.com` hangs at a
  credential prompt (headless, no helper), set a repo-local rewrite once —
  `git config url."git@github.com:".insteadOf "https://github.com/"` — so
  submodule fetches AND the raylib FetchContent clone go over SSH;
  `.gitmodules` keeps the https URL for CI and fresh clones. Beware the
  orphaned-`ninja` trap when killing a build: kill the `ninja` child too,
  or the next `cycle.py` build races it and loses `.o` files at link.

## Android native build + input traps (2026-10-17)

- **`#if __ANDROID__` code has no desktop compile gate.** The stub and
  headless tiers compile it out entirely; the first real syntax check is
  the APK build's NDK compile. Commit AFTER an APK build verifies, not
  before — the pad-hook work landed two android-only compile errors this
  way (incomplete `android_app` type, then a missing include dir), both
  invisible to every desktop tier.
- **Gradle does not track submodule CMakeLists changes.** The `.cxx`
  configure stays stale while edited sources recompile against old
  include dirs ("file not found" for a header whose include dir was
  just added). `touch CMakeLists.txt` (the GAME's — a tracked configure
  input) forces the reconfigure — which then trips the APK preflight's
  regen-stamp freshness check, so re-run `tools/cycle.py` to re-stamp
  before rebuilding the APK.
- **KeyCharacterMap fallback synthesis** (the "menu on B" mechanism): an
  UNHANDLED key event makes the InputDispatcher synthesize the device
  keymap's fallback — `Generic.kcm` maps `BUTTON_B→BACK`,
  `BUTTON_A→DPAD_CENTER`, `BUTTON_X→DEL`, `BUTTON_Y→SPACE`,
  `BUTTON_SELECT→MENU` —
  arriving ~36 ms after the raw press with
  `AKEY_EVENT_FLAG_FALLBACK` (0x400) and keyboard auto-repeat while
  held. Invisible to `getevent` (injected dispatcher-side, not via
  uinput), so kernel captures look clean while the app sees doubles.
  The runtime's Android pad hook consumes the gamepad-button range plus
  fallback-tagged BACK/CENTER (`android_gamepad.h`; keycode-trust, not
  source-trust), so real Back presses (no fallback flag) keep the menu
  gesture. Guide and Y open the settings menu by design
  (`pad_opens_menu`); any OTHER button reaching the menu is the fallback
  bug above. Debugging "button X opens the menu": the `pad-census:`
  logcat lines print keycode, source AND flags — check the flag first.

- **Android haptics (2026-10-20).** `VibratorManager` + `CombinedVibration`
  are API 31+; `InputDevice.getVibrator()` is API 16 (deprecated at 31);
  `Vibrator.hasAmplitudeControl` and `VibrationEffect.createOneShot` are API
  26 (amplitude 1..255, or `DEFAULT_AMPLITUDE`). A bare `vibrate(effect)`
  carries `USAGE_TOUCH`, and OEMs that disable touch haptics drop it
  silently — attribute game pulses as `VibrationAttributes.USAGE_MEDIA`
  (API 33+) or `AudioAttributes.USAGE_GAME` (API 26-32); the framework's
  phone sink does both. The app must be in the foreground. JNI: raylib
  exports `GetAndroidApp()` but does not declare it in `raylib.h`; include
  the glue header for `struct android_app`. NDK C++ `JNIEnv`/`JavaVM` are
  objects with member calls (`env->GetObjectClass`), not the C function
  tables (`(*env)->...`).

## Run examples

- Strict smoke: `GBARECOMP_STRICT_STATIC=1 ./build/FFTARecomp --bios
  bios/emibios_gba_bios.bin --rom game.gba --frames 2400 --no-window`
- Session replay: `gbarecompx/tools/resolve.py --trace <csv>`; coverage:
  `tools/coverage_report.py`.

## Device gate: unattended runs bounce to the launcher (2026-10-16)

`validate_android.sh` failed only "resumed activity" on a phone nobody
was touching, while the app itself ran fine (log: cpu_backend, no misses,
crash buffer clean — 5/6 checks passed). Reproduced: after
force-stop + `am start` of `GbaSetupActivity` (AUTOSTART), the game
resumes, then ~10 s later `ResumedActivity` reports the launcher —
the ROM's `mUserActivityTimeoutOverrideFromWindowManager=10000` counts
user-activity idle in 10 s when no human input lands, and the phone
dozes/locks, bouncing the task to the launcher inside the gate's 40 s
wait. adb `monkey`/`am start` do NOT reset that timer; the screen
staying on (`stay_on_while_plugged_in=7`) does not either. Every gate
that passed earlier ran with the phone attended. Recipe: wake + unlock
(face/PIN) and have the user touch the phone around the gate's wait, or
accept the 5-check evidence for an unattended install and re-run the
resumed-activity check at the next attended session. (A future gate
option: a `--wait-under-40` or an adb `input keyevent WAKEUP` inside the
wait loop — untested; do not add blind.)
