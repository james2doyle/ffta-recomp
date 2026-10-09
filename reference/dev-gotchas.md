# Dev gotchas — harness traps, run modes, environment

Moved out of `AGENTS.md` on 2026-10-08 (was § Environment notes + §
Environment gotchas); load it when operating the harness, debugging run
modes, or touching the RAM-dispatch / save machinery. Every trap below cost
real hours once.

## Environment

- Linux (Arch). No `pip3`/`arm-none-eabi-*`: use `uv` + `.venv/` (capstone).
  Disassemble with `tools/disarm.py <start> <end> [arm|thumb]` (hex GBA
  addresses) via `.venv/bin/python`.
- BIOS: `[bios] hle = false` requires a real dump at
  `gbarecomp/bios/gba_bios.bin` (user-supplied, never committed; SHA-1
  `300c20df6731a33952ded8c436f7f186d25d3492`). Never download a BIOS.
- System mGBA (`mgba-qt` 0.10.5) is for manual eyeballing only — the
  validation harness uses the framework's own oracle:
  `reference/oracle-harness.md`.
- `tools/disarm.py` halts silently at the first undecodable halfword — use
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
  `--frames` so the event lands inside; query with `tools/ringscan.py`).
- Pinned TCP surface: `step`/`run_frames`/`set_keyinput`/`screenshot`/
  `registers`/`state_hash` + memory reads exist; `run_to_pc`/`get_registers`/
  `call_stack`/`rdb_*` do not.
- `FFTA_DISPATCH_LOG=1` (see `src/ffta_ram_dispatch.h`) logs every RAM-
  dispatch hook branch (enter/case1/case2/resume-passthru/fall) with
  registers to stderr.
- Long non-strict runs are safe (present-in-place + background healing; the
  session-5 acceptance replay runs 112,000 frames headless). Strict runs are
  faster and are the acceptance.

## Sessions and close handling

- Close with **ESC in-game** (verified clean, rc≈0, ~2 s teardown). The
  titlebar X / Alt+F4 close request is NOT delivered under the current SDL
  stack (binary links `sdl2-compat` = an SDL3 shim; BRINGUP § "Close-hang
  investigation"); SIGTERM/SIGINT are not close mechanisms either. Scripted
  fallback: `.venv/bin/python tools/quit.py <tcp-observe port>` — play.sh
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
  `tools/ringscan.py` queries the same files.
- **Guard-gate signature**: a depth-gated guard that never fires while the
  stack visibly grows → print `g_irq_nest_depth` at mainline PCs; a stuck
  ≥1 (poisoned by a guest-return × IRQ interleave) disables the
  `nest_depth == 0` gate. See BRINGUP § 2026-10-09 later.
- **Ring dump at any breakpoint**: launch with `GBARECOMP_INSN_TRACE=1`
  (the fingerprint ring must be armed) and, at a gdb stop, call
  `runtime_fp_save_file("/tmp/fp.bin")` — the whole per-instruction ring
  (8.4M records; `<Q18I`: cycles, pc, cpsr, r0-r12, sp, lr) dumps without
  needing a clean process exit. This caught the 2026-10-09 handler-loss
  chain end to end (BRINGUP § true root).
- **Recorded patch generation**: `git -C gbarecomp diff --no-ext-diff
  --no-color -- <paths> > tools/patches/<name>.patch` — without both flags
  the output is difft-rendered and/or ANSI-colored and fails `git apply`
  (`tools/check.py --only patches` catches it). When exporting the OUTER
  repo's consolidated patch, exclude a dirty nested submodule's gitlink
  (`-- . ':(exclude)external/arm-recomp-core'`): GNU patch cannot apply a
  `Subproject commit …-dirty` hunk.

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

## BIOS recompile, build, stack

- BIOS recompile must run with cwd = `gbarecomp/` **and pass
  `--config bios/gba_bios.toml`** — else output lands in the wrong
  `src/runtime/generated_bios/`, or only 666 of 770 functions are discovered
  and strict runs abort on a miss at pc `0x300`. After generating, **re-run
  CMake configure** (not just build) so the framework re-detects
  `bios_recompiled.cpp`.
- Linux stack: the host main thread needs RLIMIT_STACK raised
  (`src/main.cpp` `raise_stack_limit`; hard limit must be unlimited).

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
  still need `[[extra_func]]` seeds (probe with `tools/misspack.py` +
  a source-side prologue scan).

## Submodules and local framework patches

- Pins (2026-10-06): gbarecomp @ `ecc9c55` (newest main, chosen
  deliberately), recomp-ui @ `cac2b8f`; nested: arm-recomp-core @ 15fc7b7,
  rbengine @ 2a03e7, recomp-net @ c58f125.
- `tools/patches/*.patch` are working-tree edits to `gbarecomp/`. Re-apply
  after submodule updates with the **consolidated** patches — there are two
  since 2026-10-09: `gbarecomp-local.patch` (one pristine→dev diff of
  gbarecomp; exports with the nested gitlink excluded) and
  `arm-recomp-core-local.patch` (the nested `external/arm-recomp-core`
  repo's first local patch); the per-feature files are reference diffs
  only — their contexts interleave and do not stack in any order (verified
  2026-10-09). `tools/check.py --only patches` validates all of them
  (forward against the pristine pin, reverse when applied; `arm-recomp-core-*`
  files are routed to the nested repo by that filename prefix) and
  **replays pin + each consolidated patch, requiring a byte-match with the
  corresponding dev tree** — it fails on drift or a stale consolidated
  patch. Re-export commands: `tools/patches/README.md`.

## Run examples

- Strict smoke: `GBARECOMP_STRICT_STATIC=1 ./build/FFTARecomp --bios
  gbarecomp/bios/gba_bios.bin --rom game.gba --frames 2400 --no-window`
- Session replay: `tools/resolve.py --trace <csv>`; coverage:
  `tools/coverage_report.py`.
