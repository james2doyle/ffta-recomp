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
  narrow windows anchored on known boundaries.

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
- `tools/patches/*.patch` are working-tree edits to `gbarecomp/` —
  re-apply after submodule updates; `tools/check.py --only patches`
  validates all of them (forward against the pristine pin, reverse when
  applied).

## Run examples

- Strict smoke: `GBARECOMP_STRICT_STATIC=1 ./build/FFTARecomp --bios
  gbarecomp/bios/gba_bios.bin --rom game.gba --frames 2400 --no-window`
- Session replay: `tools/resolve.py --trace <csv>`; coverage:
  `tools/coverage_report.py`.
