# AGENTS.md — FFTA Recomp (agent instructions)

IMPORTANT: Prefer retrieval-led reasoning over pre-training-led reasoning for
GBA recompilation, ROM disassembly, and gbarecomp framework tasks. Read
`README.md` (setup + the playtest/healing loop) first, then this file (rules
of engagement); `BRINGUP.md` is the decision log and
`ffta-bootstrap-prompt.md` the historical origin. Verify every ROM claim with
`tools/disarm.py` disassembly and cite the address.

## Project

Static recompilation of Final Fantasy Tactics Advance (USA, AFXE) to native PC
using [mstan/gbarecomp](https://github.com/mstan/gbarecomp). The retail ROM
lives at `game.gba` (repo root) and is **never committed** — no ROM-derived
bytes in git history, ever (this includes generated/, saves, patches, frames).

- ROM identity: SHA-1 `4ac05441f4de70a4ec3dd932116346c61b8783d9`, MD5
  `cd99cdde3d45554c1b36fbeb8863b7bd`, 16,777,216 bytes.
- Verified facts (entry point, crt0, IRQ, m4a driver, RAM map) with evidence
  live in `BRINGUP.md` § "2026-10-06 — Phase 0". Do not re-derive; do cite.

## Ground rules (never violate)

1. Never guess. Every ROM claim (function start, code vs data, entry point)
   comes from disassembly actually run, address cited. Unverified → say so.
2. First divergence only. When recomp ≠ emulator, debug the first divergence;
   downstream symptoms are consequences.
3. Never edit `generated/`. Curation happens in `game.toml` and `src/`.
4. Every `game.toml` entry needs disassembly evidence in its `note`.
5. Log every decision in `BRINGUP.md` (date, action, result, conclusion).
   Commit after every milestone.
6. A step failing inexplicably 3 times → stop, write state to `BRINGUP.md`,
   report. Don't thrash.
7. gbarecomp's own docs (`gbarecomp/PRINCIPLES.md`, `gbarecomp/DEBUG.md`,
   `gbarecomp/CLAUDE.md`, `gbarecomp/docs/TOML_SCHEMA.md`) supersede the
   bootstrap prompt on conflict. Read `gbarecomp/PRINCIPLES.md` before any
   debugging session.

## Environment notes

- Linux (Arch). No `pip3`/`arm-none-eabi-*`; use `uv` + `.venv/` (capstone)
  for Python work. `tools/disarm.py <start> <end> [arm|thumb]` disassembles
  (hex GBA addresses); run via `.venv/bin/python`.
- mGBA: system `mgba-sdl`/`mgba-qt` 0.10.5 installed (pacman, `extra`) for
  manual reference use. The Phase 5 harness uses the framework's **own**
  mGBA oracle instead — libmgba 0.10.5 built from source into
  `gbarecomp/third_party/mgba` and wrapped as `gbarecomp_oracle` (TCP) —
  see § "Oracle & frame diff" below.
- BIOS: `[bios] hle = false` requires a real BIOS dump at
  `gbarecomp/bios/gba_bios.bin` (user-supplied, never committed; SHA-1
  `300c20df6731a33952ded8c436f7f186d25d3492`). Do not download a BIOS.
- SDL2 present at /usr (framework found it during configure).

## Commands

Framework tool build (already done; re-run only after submodule change):

```sh
cmake -S gbarecomp -B gbarecomp/build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build gbarecomp/build --target gba_recompile gba_scan --parallel 8
```

ROM sanity scan: `./gbarecomp/build/gba_scan game.gba`

Regenerate static code (Phase 3+; uses `game.toml`):

```sh
./gbarecomp/build/gba_recompile --rom game.gba --config game.toml \
  --out generated --max-functions 65536
```

The canonical regen also passes `--symbols symbols/ffta_symbols.tsv` and
`--data-symbols symbols/ffta_data_symbols.tsv` when present (facts from
charlie-troy/ffta-decomp + engine-hacks-derived rows; seeds/names must not
change behaviour — the attract gate guards this). `tools/cycle.py` and
`tools/coverage_report.py` add them automatically.

Build the game binary (Phase 3+):

```sh
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build --target FFTARecomp --parallel 8
```

Run (needs BIOS + ROM paths; both must hash-verify):

```sh
./build/FFTARecomp --bios gbarecomp/bios/gba_bios.bin --rom game.gba
# headless: --frames N --no-window --dump-png out.png
```

Coverage loop (after every run): read the exit banner
(`self_heal_coverage=...`) and `recomp_master_misses_AFXE.toml.frag` /
`recomp_coverage_AFXE.json` next to the exe. Review proposals, **manually
merge** real ones into `game.toml`, regenerate, rebuild, rerun — until
`FULLY_STATIC`. Never auto-write `game.toml`.

Crash sessions: the `.frag` flushes only at clean exit — after a crash, run
`tools/cache_harvest.py --out logs/proposal.frag` to recover the miss pcs
from `recomp_cache` unit filenames.

Session resolve: `tools/resolve.py --trace <csv> [--load-state <state>]
[--frames N]` strict-replays a recording, seeds each miss through a temp
overlay, rebuilds and repeats until FULLY_STATIC. A trace with a mid-session
savestate reload jumps backward — split it with `tools/trace_split.py` and
resolve each segment. Accumulated seeds land in
a proposal file (game.toml is never auto-edited) — merge them, then run a
normal `tools/cycle.py` + strict replay as the acceptance.

Interactive playtest (the healing loop's front end — README § "The playtest
→ healing loop"): `tools/play.sh [--scale N | --fullscreen | --tcp-observe
PORT]`. Letter-key keymap in `build/keybinds.ini` (example:
`tools/playtest_keybinds.ini.example`); records `logs/playthrough.csv`,
proposes to `logs/playtest_misses.frag` (clean-exit flush only), archives the
previous session's savestates/traces under `saves/`, battery save at
`saves/playtest.sav`.

Coverage report (three lenses — executed path / walker's static reach /
pointer-pool reach): `.venv/bin/python tools/coverage_report.py` (defaults
to a 1200-frame strict run; `--frames N`, `--json` for machine-readable,
`--log FILE` to reuse an existing run log). Trial configs are derived from
`game.toml` and regenerated in a throwaway temp dir with a cold cache —
`game.toml` and `generated/` are never touched.

Attract regression gate (run after every `game.toml` change; exit 0 = PASS,
`--repin` to adopt deliberate visual changes):
`.venv/bin/python tools/attract_check.py`

Lockstep dual-engine probes (regions / pixels / cells / PNG dumps; free
ports; encodes the park-phase model from § "Oracle & frame diff"):
`.venv/bin/python tools/dualrun.py --help`

Miss evidence packs (after a non-strict `GBARECOMP_MISS_FRAG` harvest):
`.venv/bin/python tools/misspack.py logs/missN.frag [--stubs | --pc 0x...]`

Standard change cycle (cold regen → aligned-dispatch sanity → build →
attract gate; `--harvest N` also runs a non-strict miss harvest):
`.venv/bin/python tools/cycle.py [--frames N] [--harvest N]`

Instruction-ring queries (on `GBARECOMP_INSN_TRACE` + `GBARECOMP_FP_SAVE`
dumps; capstone decode):
`.venv/bin/python tools/ringscan.py --file /tmp/fp.bin [--pc P | --reg R |
--reg-range LO HI] [--cyc LO HI] [--context N]`

## Oracle & frame diff (Phase 5)

The validation harness compares our runner against gbarecomp's own mGBA
oracle (the framework's mGBA 0.10.5 checkout — distinct from the system
mGBA install used for manual eyeballing).

Build the oracle (one-time; needs network for the mGBA clone; re-run only
after framework/submodule changes):

```sh
cd gbarecomp
bash oracle/setup-mgba.sh           # clones mGBA 0.10.5 -> third_party/mgba,
                                    # builds libmgba.a (~25 s)
cmake -B build -S . -DGBARECOMP_BUILD_ORACLE=ON
cmake --build build --target gbarecomp_oracle --parallel 8
```

Binary: `gbarecomp/build/oracle/gbarecomp_oracle` — TCP server, default
port 19843; args `--bios <real bios> --rom <rom> --port N`; run with
cwd=`gbarecomp/` (default BIOS path is cwd-relative). Key JSON-line
commands: `emu_step`/`emu_step_to_vblank` (one runFrame = one PPU frame),
`emu_vblank_count`, `emu_screenshot` (240x160 RGB888 hex),
`read_emu_{iwram,ewram,vram,pal,oam,rom,io}`, `emu_set_keys`.

**Comparison protocol** (learned the hard way — see BRINGUP § Phase 5):
- Both engines park at **VBlank-start** (source-verified; the old "mGBA
  stops at the wrap" note was wrong). The real phase difference is CPU-side:
  our runner executes the VBlank IRQ handler before parking (post-handler);
  mGBA raises the IRQ and vectors it at the start of the next step
  (pre-handler). Same-index **state** reads are therefore offset by exactly
  one handler's effects (native ahead — e.g. snow RNG Δ=13 chain steps/frame
  during the title animation; BRINGUP § "park-phase semantics"). **Pixels**
  compare fine same-index (latched completed frames; static stretches
  byte-exact; bounded band diffs on mid-frame-animated content). Keep
  per-frame deltas for memory-divergence detection; use stable frames for
  golden hashes.
- Framework-ready tools: `gbarecomp/oracle/diff_cart.py` (absolute
  PAL/OAM/VRAM/IWRAM byte compare; `--native-exe ../build/FFTARecomp
  --rom ../game.gba --bios bios/gba_bios.bin`), `diff_frame.py`,
  `gba_tcp.py` (manual driver). Our wrapper: `python3 tools/framediff.py
  --lo 4 --hi 300` (spawns both engines, delta mode, JSON report to
  `/tmp/ffta_framediff/`, exit 1 on divergence).
- Sync on hardware events (VBlank counts), never raw frame indexes
  (gbarecomp/CLAUDE.md § SYNC RULES); debug region **writes**, not screen
  pixels, until memory matches.
- Frame dumps/saves are ROM-derived: write to `/tmp/` or `logs/`
  (gitignored) only — never commit them. Recomp-side capture envs:
  `GBARECOMP_FRAMEDUMP_DIR/_START/_COUNT` (windowed path; one PNG per
  guest frame), `--dump-png` (single frame, works `--no-window`), TCP
  `screenshot`.

## Repo layout

| Path | What |
|---|---|
| `game.toml` | Per-game config — identity-pinned; audit batches a–h2 (evidence in `note`s) |
| `src/` | Host code: `main.cpp` + integration |
| `generated/` | Recompiler output — gitignored, never edited |
| `gbarecomp/`, `recomp-ui/` | Pinned submodules (see below) |
| `tools/` | Full harness — see README § Repository layout; key ones: `play.sh` (playtest), `resolve.py` (strict resolve loop), `trace_split.py` (split non-monotonic traces), `cache_harvest.py` (crash-safe harvest), `cycle.py` (change cycle), `attract_check.py` (golden gate), `misspack.py` (evidence packs), `coverage_report.py` (three lenses), `framediff.py`/`dualrun.py` (oracle diffs), `disarm.py`, `keyprobe.py`, `ringscan.py` |
| `.agents/skills/` | Project-local agent skills — `gbarecomp-recomp-playbook` (portable playtest/healing/audit playbook; task-grouped references under `references/`) |
| `inputs/` | Deterministic keyinput traces (`<frame>,0x<hex>` active-low, sticky) — `title_to_newgame.csv`, `session2_battle_trace.csv` |
| `symbols/` | Curated symbol seeds + data names (charlie-troy/ffta-decomp facts + engine-hacks-derived, attributed); consumed via `--symbols` / `--data-symbols` |
| `BRINGUP.md` | Decision log — the project's memory |
| `README.md` | Setup, run instructions, the playtest/healing loop, contribution guide |
| `game.gba` | Retail ROM, gitignored |

Submodule pins (2026-10-06): gbarecomp @ `ecc9c55` (main; newer than the
2952aff pin in reference game repos — newest main was chosen deliberately),
recomp-ui @ `cac2b8f`. Nested: arm-recomp-core @ 15fc7b7, rbengine @ 2a03e7,
recomp-net @ c58f125.

## Bring-up status & next milestone

- Phase 0 (ROM recon): **COMPLETE** — see `BRINGUP.md`.
- Phase 1 (framework setup): **COMPLETE** — submodules pinned, tools built.
- Phase 2 (game.toml): **COMPLETE** — identity-pinned, validated (1072 funcs).
- Phase 3 (first recompile/build/run): **COMPLETE** — BIOS recomp generated
  (770 funcs) and linked; host project (CMakeLists.txt, src/main.cpp,
  launcher UI) builds; headless runs: 60/120/240 frames FULLY_STATIC (strict),
  480 frames NOT_STATIC (12 misses) with full miss/coverage artifacts in
  `logs/` (gitignored, ROM-derived — never commit).
- Phase 4 (audit loop): **COMPLETE for the 480-frame horizon** — strict
  480 = **FULLY_STATIC** (0 misses, 0 interpreted, exit 0); corpus
  1072 → 1438 functions via 13 `[[extra_func]]` + 4 `[[code_copy]]` audit
  entries (evidence per entry in `game.toml` + `BRINGUP.md` § Phase 4).
  IWRAM code copies (IRQ dispatcher, RAM helpers, byte-copy, flash getter)
  mapped from live-dump + ROM byte-match; ROM gaps seeded at verified
  prologues (walks cascade). Artifacts: `logs/{cov,miss,run}_v*`, 
  `logs/strict_v9.log`.
- Phase 5 (validation harness + audit loop): **near done.** Harness complete
  (oracle/framediff/dualrun/attract gate/misspack/cycle/coverage_report/
  ringscan) plus playtest tooling (`play.sh`, `cache_harvest.py`,
  `resolve.py`). Ten sessions integrated (batches a–n): corpus 23.4k →
  40,518 emitted units; walker's reach ≈ 98.8 %; pointer-pool lens ≈ 77.2 %
  (proxy, not a goal — the bar is FULLY_STATIC on executed paths). Every
  executed path is FULLY_STATIC (strict replays: boot→newgame 6000 f; state2
  battle 60k f; session-5 112k f; session-7 battle f19k→21.5k) and the
  attract hash is unchanged since pinning. Remaining: main-game content past
  the first non-tutorial battle (completed 2026-10-07; pure play → harvest),
  f6000+ attract contact sheet, upstream note on the bridge stop-contract
  runaway. Crash playbook:
  BRINGUP § "Battle-session crash" / "Crash #2" (harvest → merge → resolve
  → cycle).
- Reference projects (mstan's Emerald/FRLG/RS/MinishCap/WWT clones) ship
  reviewed-seed overlays + input-CSV + golden-SHA gates; our harness adds
  frame-diff against a real mGBA oracle (they have none).
- Android port (research done 2026-10-06; not started): the app shell already
  lives in the pinned gbarecomp (`platform/android/`); the port is a thin
  `android/` Gradle dir + CMake `if(ANDROID)` SHARED `main` branch +
  `src/main.cpp` mobile hooks + JDK 17/SDK env. Templates: Emerald/WWT
  `android/` dirs. Independent of Phase 5, but device builds run with
  self-heal disabled (misses fail loudly). Details: BRINGUP § "Android port
  findings".

## Environment gotchas (learned in Phase 3)

- Audit/verify runs must be **cold-cache**: the self-heal overlay cache
  perturbs IRQ-resume landing PCs run-to-run, so warm-run miss lists are not
  stable evidence. `tools/cycle.py` does a cold regen; strict runs are
  inherently cold. For one-off checks `rm -rf recomp_cache` first.
- Miss tracing without code changes: `GBARECOMP_MISS_IWRAM_DUMP` (state at
  first IWRAM miss), `GBARECOMP_IWRAM_DUMP` (exit state),
  `GBARECOMP_WRAM_TRACE`+`_LO/_HI` (per-frame write diff),
  `GBARECOMP_INSN_TRACE=1`+`GBARECOMP_FP_SAVE` (per-instruction ring;
  window = last ~8.4 M insns — size `--frames` so the event is in-window).
  Pinned TCP surface: `step`/`run_frames`/`set_keyinput`/`screenshot`/
  `registers`/`state_hash` + memory reads exist; `run_to_pc`/`get_registers`/
  `call_stack`/`rdb_*` do not.
- `tools/disarm.py` halts silently at the first undecodable halfword —
  use narrow windows anchored on known boundaries.
- `GBARECOMP_INPUT_REPLAY` is applied by the headless `--frames` loop only —
  TCP `run_frames`/`step` does NOT apply replay events (check KEYINPUT at
  0x04000130 if in doubt). Run replay gates headless.
- `[[code_copy]]` maps decoding only; runtime entry PCs inside a copied span
  still need `[[extra_func]]` entries (seed via tools/misspack + a
  source-side prologue scan of the copied span).
- Desktop playtest keyboard: on Linux desktops with an input-method daemon
  (IBus/GNOME), special keys (Enter/Backspace) can be swallowed inside the
  game window. Use a letter-only map (`build/keybinds.ini`; example:
  `tools/playtest_keybinds.ini.example`) and verify presses with
  `GBARECOMP_INPUT_RECORD` or `tools/keyprobe.py`.
- Window size: `--scale N` (1–8; window = N×240 × N×160; `--scale 8` =
  1920×1280, the max). `--view-width` is the *widescreen view* feature, not
  window size — unsupported games (FFTA) clamp it to 240 and it does
  nothing; the runtime prints `extended view requested ... but this game
  has not opted in` when asked (`--quiet` hides it). Adaptive /
  resize-driven view (`--resize-view`) is likewise game-owned
  (`RunOptions::max_view_width` / `resize_driven_view`, defaults 240/false
  in the runner; only a mod can opt in — `gba_mod_view_width` /
  `gba_mod_adaptive_view_enabled`). `--fullscreen` = borderless desktop
  fullscreen. Live fullscreen/window-size keys are system hotkeys bound in
  `config.ini` `[KeyMap]` (rebindable in the launcher).

- BIOS recompile must run with cwd = `gbarecomp/` (or output lands in the
  wrong `src/runtime/generated_bios/`); after generating, **re-run CMake
  configure** (not just build) so the framework re-detects
  `bios_recompiled.cpp`.
- Linux stack: host main thread needs RLIMIT_STACK raised (src/main.cpp
  raise_stack_limit does this; hard limit must be unlimited).
- Non-strict self-heal runs are safe at long horizons now
  (present-in-place + background healing): the session-5 acceptance replay
  runs 112,000 frames headless; strict runs are faster.
- Run examples: smoke `GBARECOMP_STRICT_STATIC=1 ./build/FFTARecomp --bios
  gbarecomp/bios/gba_bios.bin --rom game.gba --frames 2400 --no-window`;
  session replays via `tools/resolve.py`; coverage via
  `tools/coverage_report.py`.

## Validation discipline

- Every `game.toml` change → regenerate → rebuild → run
  `tools/attract_check.py` (golden gate; exit 0 required) and
  `tools/framediff.py` for state-level deltas. Regression tooling lives in
  `tools/`; use it instead of hand-rolling probes (`tools/dualrun.py`,
  `tools/misspack.py`).
- After every playtest session: harvest (`.frag` on clean exit, else
  `tools/cache_harvest.py`) → merge reviewed seeds → `tools/resolve.py` on
  the session trace until FULLY_STATIC → `tools/cycle.py` → commit with a
  BRINGUP entry.
- Debug via gbarecomp's TCP debug surface (`--tcp`), not printf; state claims
  as "per the frame ring at f=N (vblank=M)".
- FFTA known hard spot (CORRECTED 2026-10-06): the 0x080C7EC0/0x080C85A0/
  0x080C9EF4/0x080CA33C/0x080CA7CC cluster is unit/job/ability/stat
  **data accessors** (ROM-verified), not the VM; the **event interpreter is
  0x08122xxx-0x08123xxx** (scripts at 0x089A5E4C+). Read BRINGUP
  § "FFTA_Engine_Hacks study" before auditing there.
- Community references for naming: Data Crystal wiki (ROM/RAM maps),
  LeonarthCG/FFTA_Engine_Hacks (address→description index; VM-cluster
  correction — BRINGUP § "FFTA_Engine_Hacks study"), FFHacktics forum;
  spiiin/FFTAUtils (map-data formats + verified data regions — see BRINGUP
  § "Map-data regions"); charlie-troy/ffta-decomp (revision-exact partial
  decomp; battle/AI + audio/text docs — BRINGUP § "charlie-troy/ffta-decomp
  study").
