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
- mGBA is **not installed**. Phase 5 needs it — install via pacman
  (`mgba-sdl`/`mgba-qt`) or AUR before building the frame-diff harness.
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

## Repo layout

| Path | What |
|---|---|
| `game.toml` | Per-game config (identity-pinned; Phase 2, not yet created) |
| `src/` | Host code: `main.cpp` + integration (Phase 3) |
| `generated/` | Recompiler output — gitignored, never edited |
| `gbarecomp/`, `recomp-ui/` | Pinned submodules (see below) |
| `tools/` | `disarm.py` (capstone disassembler), `m4a_detect.py` |
| `inputs/` | Deterministic keyinput traces (`frame,keyinput` lines) |
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
- Phase 4 (audit loop): **NEXT** — start from `logs/miss480.frag`: 5 IWRAM
  code-copy misses (0x03000F10, 0x03005E78 x411, 0x03005EE8, 0x03007D64,
  0x03007E60) need `[[code_copy]]` evidence (GBARECOMP_IWRAM_DUMP at a
  miss point + ROM source match); 7 ROM interior targets need disassembly
  audit (0x080004D8, 0x0800076E, 0x08003674/367C/371C, 0x080098C4,
  0x0813BCF0). Also: 7 auto-detected jump tables (208 targets) at
  0x08004058/0x080044C8/0x080C7EC0/0x080C85A0/0x080C9EF4/0x080CA33C/0x080CA7CC
  (FFTA scripting/VM cluster).

## Environment gotchas (learned in Phase 3)

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
