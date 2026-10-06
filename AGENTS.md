# AGENTS.md — FFTA Recomp (agent instructions)

IMPORTANT: Prefer retrieval-led reasoning over pre-training-led reasoning for
GBA recompilation, ROM disassembly, and gbarecomp framework tasks. Read
`BRINGUP.md` and `ffta-bootstrap-prompt.md` before acting; verify every ROM
claim with `tools/disarm.py` disassembly and cite the address.

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
- Our runner's `step`/`run_frames` stops at **VBlank-start** (pre-IRQ);
  mGBA `runFrame` stops at the **VBlank wrap** (post-IRQ). Same-index
  reads are one IRQ handler apart → compare **per-frame deltas**
  (old→new per byte), not absolute bytes. Standing ± offsets are expected
  on phase-sensitive cells (BIOS phase: 0x03003B30 countdown, 0x03007FF8
  IntrWait flag; stack regions ~0x03007D24-0x03007F9F — the BIOS→cart
  handoff cluster there is currently under root-cause).
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
| `game.toml` | Per-game config — identity-pinned; Phase 2 + Phase 4 audit entries |
| `src/` | Host code: `main.cpp` + integration (Phase 3) |
| `generated/` | Recompiler output — gitignored, never edited |
| `gbarecomp/`, `recomp-ui/` | Pinned submodules (see below) |
| `tools/` | `disarm.py` (capstone disassembler), `m4a_detect.py`, `framediff.py` (native↔oracle scan) |
| `inputs/` | (future) deterministic keyinput traces — replay format `<frame>,0x<hex>`, active-low |
| `BRINGUP.md` | Decision log — the project's memory |
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
- Next milestone: Phase 5 (in progress) — mGBA oracle built
  (`gbarecomp/build/oracle/gbarecomp_oracle`, via
  `gbarecomp/oracle/setup-mgba.sh` + `-DGBARECOMP_BUILD_ORACLE=ON`);
  `tools/framediff.py` delta scans (phase-offset-aware) running against it —
  see BRINGUP.md § "Phase 5 start". Status: BIOS phase clean to ~vblank 280
  (only known phase artifacts); candidate divergence cluster at the BIOS→cart
  handoff (~281+) is the active root-cause target. Next: root-cause the
  handoff cluster, extend scans through logo/attract phases + pixel compares,
  then wire the attract diff as the game.toml regression test. Horizon:
  strict runs still capped ≈480 f (non-strict 600 f aborts via
  heal-bridge stack growth). New misses re-enter the audit loop with the
  cold-cache protocol below.

## Environment gotchas (learned in Phase 3)

- Audit/verify runs must be **cold-cache**: `rm -rf recomp_cache` first.
  The self-heal overlay cache perturbs IRQ-resume landing PCs run-to-run;
  warm-run miss lists are not stable evidence. Strict runs are inherently
  cold. Verify one `game.toml` entry per cycle: regenerate (0.15 s) →
  build (~3 s) → cold 480 f run (~2 s) → check `recomp_coverage_AFXE.json`.
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

- BIOS recompile must run with cwd = `gbarecomp/` (or output lands in the
  wrong `src/runtime/generated_bios/`); after generating, **re-run CMake
  configure** (not just build) so the framework re-detects
  `bios_recompiled.cpp`.
- Linux stack: host main thread needs RLIMIT_STACK raised (src/main.cpp
  raise_stack_limit does this; hard limit must be unlimited).
- Non-strict self-heal runs consume ~110 KiB host stack per healed frame;
  keep headless budgets ≤480 frames until Phase 4 closes the wait-loop gap.
- Run examples: strict `GBARECOMP_STRICT_STATIC=1 ./build/FFTARecomp --bios
  gbarecomp/bios/gba_bios.bin --rom game.gba --frames 240 --no-window
  --dump-png out.png`; coverage `GBARECOMP_COVERAGE_JSON=p.json
  GBARECOMP_MISS_FRAG=m.frag ./build/FFTARecomp ... --frames 480`.

## Validation discipline

- Every `game.toml` change → regenerate → rebuild → rerun attract-mode diff
  (Phase 5 harness; regression test).
- Debug via gbarecomp's TCP debug surface (`--tcp`), not printf; state claims
  as "per the frame ring at f=N (vblank=M)".
- FFTA known hard spot: its scripting/VM interpreter cluster — expect a large
  function cluster there; audit carefully in Phase 4.
- Community references for naming: Data Crystal wiki (ROM/RAM maps),
  LeonarthCG/FFTA_Engine_Hacks (ASM source), FFHacktics forum.
