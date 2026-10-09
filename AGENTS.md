# AGENTS.md — FFTA Recomp (agent instructions)

IMPORTANT: Prefer retrieval-led reasoning over pre-training-led reasoning for
GBA recompilation, ROM disassembly, and gbarecomp framework tasks. Read
`README.md` (setup + run) and `tests/README.md` (playtesting, healing loop,
gates, CI) first, then this file (rules of engagement); `BRINGUP.md` is the
decision log. Verify every ROM claim with
`tools/disarm.py` disassembly and cite the address. Deep detail is not kept
here — load it via § "Reference index" only when the task needs it.

## Project

Static recompilation of Final Fantasy Tactics Advance (USA, AFXE) to native
PC using [mstan/gbarecomp](https://github.com/mstan/gbarecomp). The retail
ROM lives at `game.gba` (repo root) and is **never committed**; no
ROM-derived bytes in git history, ever (generated/, saves, patches, frames
included).

- ROM SHA-1 `4ac05441f4de70a4ec3dd932116346c61b8783d9`, 16,777,216 bytes.
- Verified ROM facts (entry point, crt0, IRQ, m4a, RAM map): BRINGUP
  § Phase 0. Do not re-derive; cite.
- Mapping priors: the 0x080C7EC0/85A0/9EF4/A33C/A7CC cluster is unit/job/
  ability **data accessors**, not the VM; the event interpreter is
  **0x08122xxx–0x08123xxx** (BRINGUP § "FFTA_Engine_Hacks study").

## Ground rules (never violate)

1. **Never guess.** Do: run `tools/disarm.py` and cite the address; label
   anything unverified as unverified.
2. **First divergence only.** Do: root-cause the earliest difference against
   the oracle; downstream symptoms are consequences.
3. **Never edit `generated/`.** Do: curate `game.toml` and `src/`.
4. **Evidence in every `game.toml` entry.** Do: every seed carries a
   disassembly-evidence `note` (build packs with `tools/misspack.py`).
5. **Log every decision in `BRINGUP.md`** (date, action, result, conclusion)
   and commit after every milestone.
6. **Three strikes.** Do: after 3 inexplicable failures, stop, write the
   state to `BRINGUP.md`, report — don't thrash.
7. **Framework docs win.** `gbarecomp/{PRINCIPLES,DEBUG,CLAUDE}.md` +
   `docs/TOML_SCHEMA.md` supersede other notes; read PRINCIPLES before any
   debugging session.
8. **Public-repo hygiene.** Do: summaries + attribution only, never verbatim
   third-party text (sole exception: the licensed GFDL 1.2
   `reference/datacrystal/` set); keep `THIRD_PARTY_ATTRIBUTION.md` current;
   no screenshots or ROM-derived captures in git.

## Workflows

**A. Change cycle** — after any `game.toml` / `src/` change:
1. `.venv/bin/python tools/cycle.py` — cold regen → dispatch sanity → build
   → attract gate.
2. `.venv/bin/python tools/check.py` — full gate (host tests, attract,
   widescreen smoke, strict route replays over frozen fixtures).
3. For state-level claims also run `tools/framediff.py`; freeze any new
   route worth guarding as a fixture + `check.py` entry.
4. Commit with a dated `BRINGUP.md` entry.

**B. Playtest → healing loop** — after every session (full version:
`tests/README.md` § "The playtest → healing loop"):
1. Harvest: the miss proposals are journaled live in
   `logs/playtest_misses.frag`; after a crash also run
   `tools/cache_harvest.py --out logs/proposal.frag` (heal-cache filenames).
   The run's own output is the exit banner (`self_heal_coverage=…`) plus
   `recomp_master_misses_AFXE.toml.frag` / `recomp_coverage_AFXE.json` next
   to the exe.
2. Review + **manually** merge seeds into `game.toml` (never auto-write).
3. `.venv/bin/python tools/resolve.py --trace <csv> [--load-state <state>]`
   — strict-replays, seeds misses through a temp overlay, repeats until
   `self_heal_coverage=FULLY_STATIC`. Split mid-session reload traces with
   `tools/trace_split.py` first.
4. Acceptance: workflow A, plus a final strict replay of the session.

**Debugging:** use the TCP debug surface + capture envs (never printf);
state claims as "per the frame ring at f=N (vblank=M)"; traps, run modes and
close handling live in `reference/dev-gotchas.md`.

## Commands (canonical quick reference)

```sh
# framework tools (re-run after submodule changes)
cmake -S gbarecomp -B gbarecomp/build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build gbarecomp/build --target gba_recompile gba_scan --parallel 8
# regenerate static code (canonical form; cycle.py wraps this)
./gbarecomp/build/gba_recompile --rom game.gba --config game.toml \
  --symbols symbols/ffta_symbols.tsv --data-symbols symbols/ffta_data_symbols.tsv \
  --out generated --max-functions 65536
# build the game (mods flag links the widescreen plugin lifecycle)
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DGBARECOMP_ENABLE_MODS=ON
cmake --build build --target FFTARecomp --parallel 8
# run (BIOS + ROM hash-verify at launch)
./build/FFTARecomp --bios gbarecomp/bios/gba_bios.bin --rom game.gba \
  --frames 2400 --no-window
```

| Task | Command |
|---|---|
| Fresh-clone bootstrap | `python3 build.py` (idempotent; `--force`, `--no-smoke`, `--jobs N`) |
| Full regression gate | `.venv/bin/python tools/check.py` (`--fast`; `--jobs N`; `--only a,b`) |
| CI subset (no dumps needed) | `--only unit-cpp,unit-py,patches` — `.github/workflows/ci.yml` |
| Widescreen smoke | `.venv/bin/python tools/ws_check.py` (fixtures `saves/ws_fixtures/`) |
| Playtest (windowed, instrumented) | `tools/play.sh [--scale N \| --resize-view \| --tcp-observe PORT]` |
| Attract golden gate | `.venv/bin/python tools/attract_check.py` (`--repin` only for deliberate changes) |
| Miss evidence pack | `.venv/bin/python tools/misspack.py logs/missN.frag [--stubs \| --pc 0x...]` |
| Oracle diff / lockstep probes | `tools/framediff.py --lo 4 --hi 300`; `tools/dualrun.py --help` |
| Coverage (three lenses) | `.venv/bin/python tools/coverage_report.py` |
| Instruction-ring query | `tools/ringscan.py --file /tmp/fp.bin [--pc P \| --reg R \| --reg-range LO HI]` |
| Unit tests only | `cmake --build build --target ffta_unit_tests && ctest --test-dir build -R ram_dispatch` |

## Codebase map

| Path | What |
|---|---|
| `game.toml` | Per-game config: identity pin + all audit seeds (evidence in `note`s) |
| `src/` | Host code: `main.cpp` (hooks/plugins), `ffta_ram_dispatch.h`, launcher boot |
| `android/` | Android target: Gradle project, runtime TOML, payload defaults, device gate — guide `android/README.md` |
| `generated/` | Recompiler output — gitignored, never edited |
| `tools/` | The harness — key ones listed in the table above; full list: README § Repository layout |
| `.agents/skills/` | `gbarecomp-recomp-playbook` — portable playtest/healing/audit playbook (SKILL.md routes its references) |
| `mods/` `inputs/` `symbols/` `reference/` | Widescreen catalog; input traces; symbol seeds; study notes |
| `gbarecomp/`, `recomp-ui/` | Pinned submodules — do not update casually (pins + local patches: `reference/dev-gotchas.md`) |

## Status (2026-10-08)

All phases complete; **every executed path strict-FULLY_STATIC**; corpus
**55,103 emitted units** (walker 97.8 % / pool 99.3 % proxies — a route is
done when its replay is FULLY_STATIC, not when a proxy moves); attract hash
stable since pinning; widescreen W1–W3 complete; save/summon hangs fixed;
**Android port** landed and device-verified 2026-10-08 (guide
`android/README.md`). Remaining: offline-push re-trial (gated on an
interior-split policy), f6000+ contact sheet, upstream note on the bridge
stop-contract, Android release prep — README § Roadmap. History, evidence,
crash playbooks: `BRINGUP.md`.

## Reference index (load what the task needs)

| Topic | Load |
|---|---|
| Decisions, priors, corrections, crash playbooks | `BRINGUP.md` |
| Setup, run, layout, roadmap | `README.md` |
| Playtest/debug cookbook, healing loop, gates, coverage, CI, unit tests | `tests/README.md` |
| Android target: build, run, device gate, known behavior | `android/README.md` |
| Harness traps: run modes, capture envs, close handling, RAM-dispatch, saves, submodule pins, framework patches | `reference/dev-gotchas.md` |
| Oracle + frame-diff protocol (park phase, sync rules, builds) | `reference/oracle-harness.md` |
| Widescreen internals + validation | `reference/widescreen.md` |
| Event VM + scripts | `reference/event-vm.md` |
| Community source summaries (decomp, engine hacks, FAQs, notes) | `reference/{ffta-decomp,fergusson-mechanics,bcrobert-notes,jokyr-hack-guide,ffta-gamefaqs-code-guides}.md` |
| Framework truth + config schema | `gbarecomp/PRINCIPLES.md`, `DEBUG.md`, `CLAUDE.md`, `docs/TOML_SCHEMA.md` |
| Portable gbarecomp practice (loop, triage, verification) | `.agents/skills/gbarecomp-recomp-playbook/` |
