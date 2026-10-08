# FFTA Recomp

Native PC recompilation of **Final Fantasy Tactics Advance** (GBA, USA / AFXE)
built on the [mstan/gbarecomp](https://github.com/mstan/gbarecomp) framework.

This is not an emulator. The game's ARM/Thumb code is statically translated to
host C++ (AOT), compiled, and executed natively — with a **self-healing
coverage** loop that bridges any not-yet-translated code at runtime, records
it, and feeds it back into the offline corpus so the next build is fully
static. It is intended to be *honest*: every run reports exactly how much ran
as statically recompiled code (`self_heal_coverage=FULLY_STATIC ...` or the
precise miss count).

**Current status (2026-10-07):** boots (BIOS LLE), plays the attract loop,
title, new game, intro, battles, and now complete **Totema and magic summons**
(the save-menu/summon stalls were fixed via the LZSS-decoder entry guard +
RAM-copy fixups — BRINGUP § "Summon crash") — with **every executed path
FULLY_STATIC** (zero interpreted instructions) at last verification.
Interactive playtest sessions are integrated through audit batch **ae**,
plus the event-crawl batches **af/ag** (24 batches): corpus **54,327 emitted
units**, walker's static reach ≈ 97.6 %, pointer-pool lens ≈ 99.9 % (proxies —
a route is done when FULLY_STATIC on
its replay). The **offline coverage push**'s goal (pool reach) was then
achieved deliberately: strict-push verified seeds (event-crawl batches
**af/ag**) lifted the corpus to 54,327 (~99.9 % of the 54,404 trial pool)
with the attract hash byte-exact — the blind speculative path itself stays
off (interior-split hazard: a single split of the guarded LZSS decoder
regressed a route). The attract regression
gate hash has been stable since pinning. Remaining work: the annotation pass
(next), the event/script static walk, the save-flow divergence fix (open
investigation below — no observed hangs remain), a long-run attract contact
sheet, and one upstream note.

> **You must own the game and BIOS.** Both are user-supplied, hash-verified at
> launch, and **never committed** (no ROM-derived bytes in git history, ever —
> that includes `generated/`, `saves/`, `logs/`, patches, and frame dumps).
> No game code, graphics, text, or audio is included — this repository is
> tooling and notes only — and the project is unofficial: not affiliated with
> or endorsed by Square Enix or Nintendo.

- ROM: Final Fantasy Tactics Advance (USA), SHA-1
  `4ac05441f4de70a4ec3dd932116346c61b8783d9`, 16,777,216 bytes → `game.gba`
- BIOS: SHA-1 `300c20df6731a33952ded8c436f7f186d25d3492` →
  `gbarecomp/bios/gba_bios.bin` (dump your own; do not download one)

---

## Requirements

- Linux x86-64 (developed on Arch; other unixes untested)
- CMake ≥ 3.20 + Ninja, GCC or Clang (C++17), SDL2 (dev), git
- Python 3.10+ with `capstone`, installed into a repo-local `.venv/`
- Optional: a system mGBA install (`mgba-qt`) for side-by-side eyeballing

## Setup

```sh
git clone <repo-url> ffta-recompiled && cd ffta-recompiled
git submodule update --init --recursive

# Python venv for the tooling (disassembler, audit harness)
uv venv .venv && uv pip install --python .venv capstone
#   (or: python3 -m venv .venv && .venv/bin/pip install capstone)

# 1. framework tools (one-time; re-run only after submodule changes)
cmake -S gbarecomp -B gbarecomp/build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build gbarecomp/build --target gba_recompile gba_scan --parallel 8

# 2. place game.gba (repo root) and gbarecomp/bios/gba_bios.bin
#    (launch fails loudly if either hash is wrong)

# 3. the game binary
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build --target FFTARecomp --parallel 8

# 4. smoke: strict, headless, no input — expect FULLY_STATIC in the banner
GBARECOMP_STRICT_STATIC=1 ./build/FFTARecomp \
  --bios gbarecomp/bios/gba_bios.bin --rom game.gba --frames 2400 --no-window
```

Optional — the mGBA oracle used by the frame-diff harness (needs network
once; distinct from a system mGBA):

```sh
cd gbarecomp && bash oracle/setup-mgba.sh \
  && cmake -B build -S . -DGBARECOMP_BUILD_ORACLE=ON \
  && cmake --build build --target gbarecomp_oracle --parallel 8
```

Regeneration after `game.toml` edits (normally `tools/cycle.py` does this
plus the sanity checks and the attract gate):

```sh
./gbarecomp/build/gba_recompile --rom game.gba --config game.toml \
  --symbols symbols/ffta_symbols.tsv --data-symbols symbols/ffta_data_symbols.tsv \
  --out generated --max-functions 65536
cmake --build build --target FFTARecomp --parallel 8
```

## Run it

```sh
tools/play.sh                     # windowed, instrumented (see the loop below)
tools/play.sh --scale 8           # bigger window: Nx240 x Nx160 (1-8; 8 = 1920x1280)
tools/play.sh --fullscreen        # borderless desktop fullscreen
tools/play.sh --tcp-observe 19850 # window + live debug port (tools/keyprobe.py 19850)
GBARECOMP_WS_WIP=1 tools/play.sh --scale 4 --view-width 320  # widescreen dev override;
                                      # margins wrap — see reference/widescreen.md
# close a session: press ESC in-game (verified clean), or script it:
.venv/bin/python tools/quit.py 19850  # clean close (see BRINGUP § "Close-hang investigation")
./build/FFTARecomp --bios gbarecomp/bios/gba_bios.bin --rom game.gba \
  --frames 6000 --no-window       # headless; add --dump-png out.png for a frame
```

- **Keyboard:** the map lives in `build/keybinds.ini` (next to the exe; SDL
  scancode names = physical QWERTY positions). A verified all-letters example
  is `tools/playtest_keybinds.ini.example` (`a=X b=Z select=Q start=D l=W
  r=R`, arrows for the D-pad). Letters are deliberate: on desktops with an
  input-method daemon (IBus on GNOME), special keys like Enter/Backspace can
  be swallowed inside game windows.
- **Savestates:** `Shift+F1..F9` = save slot, `F1..F9` = load. Slot files are
  `game.state1..9` next to the ROM; per-session copies are archived under
  `saves/` by play.sh at launch.
- **Battery save:** Flash 64 KB at `saves/playtest.sav` (via play.sh).
- **External saves:** any raw 64 KiB flash image (e.g. another emulator's
  `.sav`, or a community container unpacked to raw) can be played by passing
  it last — `tools/play.sh --save-path saves/<file>.sav` (last-wins over
  play.sh's default). Work on a copy: in-game saves rewrite the file.
- **Window size:** `--scale N` (1–8). `--view-width` is NOT a window-size
  flag — it is the widescreen *view* feature and FFTA clamps it to 240 by
  design.
- **Debug:** `--tcp` is structurally headless; use `--tcp-observe PORT` for a
  windowed session with the debug port.

## The playtest → healing loop

This is the core contribution workflow, and it is what every play session
feeds. When the game executes code that has not been statically recompiled
yet ("a miss"): the runtime **bridges** it with the reference interpreter,
**heals** it by compiling it on the fly into `recomp_cache/` (used natively
from then on), and **records a TOML proposal** for the offline corpus. A
watchdog aborts loudly if a bridge ever spins (never silent corruption).

The diagram below maps the loop end to end; the numbered steps that follow
are the same loop in prose.

```mermaid
flowchart TD
    Play["🎮 1 · Play — tools/play.sh"] --> Runtime
    Runtime["runtime self-heal: miss → bridge (interpret)<br/>→ heal to recomp_cache → native from then on"] --> Spin{"bridge spins?"}
    Spin -->|"yes — watchdog"| Abort["❌ loud abort → crash-classes table"]
    Spin -->|"no — keep playing"| Exit
    Abort --> Harvest
    Exit{"2 · session exit"} -->|"clean"| Frag["📝 .frag proposals + playthrough.csv"]
    Exit -->|"crash"| Harvest["🧲 cache_harvest.py --new"]
    Frag --> Merge
    Harvest --> Merge
    Merge["✍️ 3 · review + merge seeds into game.toml<br/>(misspack.py evidence · never auto-written)"] --> Resolve
    Resolve["🔁 4 · resolve.py --trace … [--load-state …]"] --> Strict{"strict replay FULLY_STATIC?"}
    Strict -->|"miss at pc"| Seed["seed via temp overlay<br/>(accumulated → proposal file)"]
    Seed --> Resolve
    Strict -->|"yes"| Cycle["⚙️ 5 · cycle.py — cold regen → dispatch sanity<br/>→ build → attract gate"]
    Cycle --> Gate{"attract gate PASS?"}
    Gate -->|"no"| Fix["fix first divergence"]
    Fix --> Resolve
    Gate -->|"yes"| Accept{"final strict replay FULLY_STATIC?"}
    Accept -->|"no"| Resolve
    Accept -->|"yes"| Commit["✅ 6 · commit game.toml + BRINGUP entry"]
    Commit -->|"next session feeds the loop"| Play

    classDef step fill:#87CEEB,stroke:#333,stroke-width:2px,color:darkblue
    classDef decision fill:#FFD700,stroke:#333,stroke-width:2px,color:black
    classDef success fill:#90EE90,stroke:#333,stroke-width:2px,color:darkgreen
    classDef failure fill:#FFB6C1,stroke:#DC143C,stroke-width:2px,color:black
    class Play,Runtime,Frag,Harvest,Merge,Resolve,Seed,Cycle step
    class Spin,Exit,Strict,Gate,Accept decision
    class Commit success
    class Abort,Fix failure
```

**1 — Play.** `tools/play.sh [--scale 8]` and just play. The launcher
instruments everything:

| Artifact | What it is |
|---|---|
| `logs/playthrough.csv` | your exact input trace — replayable (`GBARECOMP_INPUT_REPLAY`) |
| `logs/playtest_misses.frag` | TOML proposals — **journaled live as misses occur** (an unclean close/kill no longer loses them) and rewritten with final counts at a clean exit; play.sh archives the previous session's as `saves/frag_prev_*.frag` |
| `recomp_cache/<sha>/gcc/<plat>/<abi>/` | completed heals: `<PC>_<hash>_<t\|a>.{c,dll,log}` |
| `saves/` | archived previous-session savestates + traces, battery save |

**2 — Close the session.**
- The `.frag` is written as you play (every new miss journals the proposal),
  so both clean exits and kills/hangs leave the miss list on disk; a clean
  exit rewrites it with final counts.
- If a session still looks odd, recover the healed PCs with
  `.venv/bin/python tools/cache_harvest.py --new` (reads the heal cache
  filenames). Paste the terminal output too — abort messages name the pc.

**3 — Merge reviewed seeds** into `game.toml` (`[[extra_func]]` /
`[[jump_table]]` / `[[code_copy]]`, each with a disassembly-evidence `note`;
`tools/misspack.py <frag>` builds the evidence pack). Never auto-write
`game.toml`; proposals are reviewed.

**4 — Resolve to static.** `.venv/bin/python tools/resolve.py --trace
logs/playthrough.csv [--load-state saves/<state>] [--frames N]` — it
strict-replays your session, seeds each miss through a temporary overlay,
rebuilds and repeats until `FULLY_STATIC`, then writes the accumulated seeds
to a proposal file for merging. If you reloaded a savestate mid-session, the
trace jumps backward and replay rejects it — split it first with
`.venv/bin/python tools/trace_split.py --trace logs/playthrough.csv` and
resolve each segment from the same start state.

**5 — Verify.** `.venv/bin/python tools/cycle.py` (cold regen →
dispatch-alignment sanity → build → attract gate) and one final strict replay
of the session as the acceptance: `GBARECOMP_STRICT_STATIC=1
GBARECOMP_INPUT_REPLAY=logs/playthrough.csv ./build/FFTARecomp ...` — expect
`self_heal_coverage=FULLY_STATIC dispatch_misses=0`.

**6 — Commit** `game.toml` + a dated entry in `BRINGUP.md`. Never commit
`logs/`, `saves/`, `generated/`, or anything else ROM-derived.

**Crash classes you may meet** (all loud, all documented in `BRINGUP.md`):

| Message | Meaning |
|---|---|
| `dispatch miss for pc=… no generated function` | Normal coverage gap: bridged + healed. Feed it to the corpus. |
| `SELF-HEAL bridge for 0x… exceeded 200000000 instructions … Aborting` | Bridge stop-contract limitation (crash #1/#2 in BRINGUP). Harvest the cache, seed the path static, retry. |
| `SELF-HEAL bridge hit interpreter NotImplemented/Undefined at pc=…` | A genuine interpreter-lowering gap in gbarecomp. Report; fix belongs upstream. |

## Verification & regression

- **Strict mode** (`GBARECOMP_STRICT_STATIC=1`) disables the heal cache,
  background healing, and interpreter bridging — any miss aborts. A green
  strict run is the definition of "statically recompiled".
- **Attract gate:** `tools/attract_check.py` pins the SHA-256 of a 1200-frame
  attract run; it runs inside `cycle.py` after every `game.toml` change.
  `--repin` only for deliberate visual changes.
- **Full gate:** `.venv/bin/python tools/check.py` — host unit tests
  (C++ + Python), the attract gate, and strict route replays (user
  save-load, sessions G/K) against frozen fixtures in `saves/regress/`
  (sha-pinned). Run it before declaring "no regressions"; checks run
  concurrently by default (`--jobs N`; auto = min(8, CPUs) — `--jobs 1` for
  serial) with per-run save/coverage isolation; `--fast` for the quick
  subset. `tools/savecheck.py` validates raw/RTN5 saves offline.
- **Coverage lenses:** `tools/coverage_report.py` reports executed path
  (ground truth), walker's static reach, and pointer-pool reach (a proxy —
  not a goal; FFTA needs FULLY_STATIC on executed paths, not 100 % of a
  proxy). `--json` for machine-readable output.

Current snapshot (2026-10-07, strict 1200-frame run; refresh with
`.venv/bin/python tools/coverage_report.py`):

| Lens | Mapped / total | % |
|---|---|---|
| **Executed path** (strict 1200-frame run) | everything that ran | **100 % — FULLY_STATIC, zero interpreter fallback** |
| **Walker's static reach** (whole-ROM scan trial) | **54,327 / 55,643** emitted units | **≈ 97.6 %** |
| **Pointer-pool reach** (speculative-harvest trial) | **54,327 / 54,404** | **≈ 99.9 %** |

Rows 2–3 are proxies with different denominators (no ground-truth function
inventory exists); a route is done when its replay is FULLY_STATIC. Corpus:
54,327 emitted units (interior split units + IWRAM code-copy included); the
speculative-harvest trial kept 2,122 pointer candidates out of 104,907
PC-relative literals (`false` in `game.toml` by policy).

**Open investigation (2026-10-07):** the save **load/save flow** diverges on
certain save contents — the oracle builds the decoded save-slot descriptor
at guest `0x02000000` during the load; our build leaves it zeroed, and the
later in-game save then reads garbage descriptors and runs away (a copy loop
called with `source = ~count`; the same signature as a downloaded save's
load stall). The validator (`0x0813B57C` + checksum `0x0813ADF0`) and the
read loop are proven identical on both engines (verified with the
instruction ring — earlier read-count asymmetry was a probe artifact). A
deterministic repro + tooling (`tools/readseq_probe.py`, `tools/dualrun.py`)
are in place — see BRINGUP § "Save-flow divergence narrowed…"; root cause in
progress.
- **Oracle frame-diff:** `tools/framediff.py --lo 4 --hi 300` (native vs the
  framework's mGBA oracle; bounded band diffs on animated content are
  expected and documented in BRINGUP § "park-phase semantics") and
  `tools/dualrun.py` for lockstep region/pixel probes.
- **Acceptance replays in the repo today:** boot → new game
  (`inputs/title_to_newgame.csv`, 6000 f), the battle continuation
  (`inputs/session2_battle_trace.csv` + a matching state), and each session's
  own trace (via `resolve.py`). All strict-clean as of the last commit.

## Repository layout

| Path | What |
|---|---|
| `game.toml` | Per-game config: identity pin + all audit seeds (evidence in `note`s) |
| `src/` | Host integration: `main.cpp`, launcher boot, stack setup |
| `tests/` | Host unit tests for `src/` custom code: `ctest --test-dir build -R ram_dispatch` (or run `./build/ffta_unit_tests` directly) |
| `generated/` | Recompiler output — gitignored, **never edited** |
| `gbarecomp/`, `recomp-ui/` | Pinned framework submodules (see `AGENTS.md` for pins) |
| `tools/` | The whole harness: `play.sh`, `check.py` (regression gate), `savecheck.py` (save validation), `resolve.py`, `cache_harvest.py`, `cycle.py`, `attract_check.py`, `misspack.py`, `coverage_report.py`, `framediff.py`, `dualrun.py`, `ringscan.py`, `keyprobe.py`, `trace_split.py`, `disarm.py`, … |
| `.agents/skills/` | Project-local agent skills — `gbarecomp-recomp-playbook`, a portable healing-loop/audit playbook with task-grouped references |
| `inputs/` | Deterministic input traces (`<frame>,0x<hex>` active-low, sticky) |
| `symbols/` | Curated symbol seeds (attributed; consumed via `--symbols`) |
| `BRINGUP.md` | Decision log — the project's memory; read it |
| `AGENTS.md` | Rules of engagement for agents; read it before changing anything |
| `ffta-bootstrap-prompt.md` | Historical origin document (the original brief) |

## Contributing

Full rules live in `AGENTS.md`; the essentials:

1. **Never guess.** Every ROM claim comes from disassembly you ran, address
   cited; every `game.toml` entry carries its evidence in `note`.
2. **Never edit `generated/`.** Curation happens in `game.toml` and `src/`.
3. **ROM hygiene.** No ROM-derived bytes in git, ever.
4. **First divergence only** when comparing against the emulator.
5. **Log decisions** in `BRINGUP.md` (date, action, result, conclusion) and
   commit after every milestone.
6. **Don't auto-write `game.toml`** — proposals are reviewed by a human/agent
   before merging.
7. Stuck three times? Stop, write the state to `BRINGUP.md`, report.

## References & attribution

- [mstan/gbarecomp](https://github.com/mstan/gbarecomp) — the recompilation
  framework (read its `PRINCIPLES.md`, `DEBUG.md`, `docs/TOML_SCHEMA.md`);
  `recomp-ui` for the launcher/runtime UI.
- Community research (used as reference only, with attribution — see
  `BRINGUP.md` studies): Data Crystal wiki (ROM/RAM maps), LeonarthCG/
  FFTA_Engine_Hacks (address index), spiiin/FFTAUtils (map-data formats),
  charlie-troy/ffta-decomp (revision-exact partial decomp; **no license —
  never ingest its sources/logs, reference only**), FFHacktics forum.
- Port credits and third-party terms: `THIRD_PARTY_ATTRIBUTION.md` (the
  `reference/datacrystal/` pages are GFDL 1.2 — license text included
  alongside them).

## Thanks

Nothing here would exist without work other people shared. Thank you to:

- **[mstan](https://github.com/mstan)** — the
  [gbarecomp](https://github.com/mstan/gbarecomp) framework and
  [recomp-ui](https://github.com/mstan/recomp-ui), plus the reference-game
  recompilations whose conventions we studied — and the R.A.I.D. community
  around them.
- **Bregalad and loveemu** — "GBA Mus Ripper" / `sappy_detector.c`, the
  basis of our m4a engine detection, with the
  [berg8793](https://github.com/berg8793/gba-mus-ripper) and
  [CaptainSwag101](https://github.com/CaptainSwag101/gba-mus-ripper) forks
  for cross-checking.
- **The [Data Crystal](https://datacrystal.tcrf.net/) contributors** — the
  FFTA ROM/RAM maps, scripting and compression pages (recovered via the
  Wayback Machine) that seeded many symbols.
- **[LeonarthCG](https://github.com/LeonarthCG)** —
  [FFTA_Engine_Hacks](https://github.com/LeonarthCG/FFTA_Engine_Hacks), the
  address index that anchored our engine studies.
- **[charlie-troy](https://github.com/charlie-troy)** —
  [ffta-decomp](https://github.com/charlie-troy/ffta-decomp), a
  revision-exact partial decomp used for naming and cross-checks.
- **[spiiin](https://github.com/spiiin)** —
  [FFTAUtils](https://github.com/spiiin/FFTAUtils), map-data formats and
  verified data regions.
- **BCROBERT, JoKyR, Terence Fergusson, and the GameFAQs code-guide authors
  (Adrammelech, labmaster, TetrisTheMovie, Vegikachu)** — the notes and
  guides that mapped FFTA's structures and formulas.
- **The [FFHacktics](https://ffhacktics.com/) community** — home of the
  long-running FFTA research that made all of this findable.
- **The [mGBA](https://mgba.io/) project** — the emulator we use as the
  differential-testing oracle.

Redistribution terms for anything included here live in
`THIRD_PARTY_ATTRIBUTION.md` and `reference/datacrystal/README.md`.

## License

The project's own code and documentation are licensed **PolyForm
Noncommercial 1.0.0** (`LICENSE`) — free to use, share, and modify for
noncommercial purposes. Third-party components keep their own terms (the
`gbarecomp` framework: PolyForm NC; `recomp-ui`: MIT;
`reference/datacrystal/`: GFDL 1.2) — see `THIRD_PARTY_ATTRIBUTION.md`.

## Roadmap

1. **Offline coverage push (tabled 2026-10-07).** The speculative literal
   harvest reaches +4,912 units, but it split the guarded LZSS decoder at an
   interior entry (`0x08005544`): the save-menu route resumes into the
   unguarded interior, bypasses the entry check, and runs away (f17,794;
   31.8 GB RSS). Reverted. Re-trial needs (a) a **route-level golden gate** —
   a long strict replay of the save-menu route as a first-class regression
   check (the 1,200-frame attract gate is too short to catch this class), and
   (b) an **interior-split policy** so speculative interior roots cannot
   bypass entry guards (guard extension and/or seed exclusion).
2. **Reference-material annotation pass (next active).** Recovered DataCrystal
   pages + BCROBERT notes + charlie-troy/engine-hacks material: data names
   (`UnitStat`, `AbilityProp`, `AbilityMpCost`, `gSongTable`, `gMPlayTable`,
   `gRngState`), m4a driver-function names, and battle/AI/audio doc
   cross-references; name-only changes, attract-gated.
3. **Event/script static walk (breadth lever) — landed.** Batches **af/ag**
   2026-10-07: scripts validated (62 blocks / 213 scripts, no code pointers);
   family tables are compiler switches; 188 strict-push verified seeds from
   the trial literal pool lifted 50,015 → 54,327 units (~99.9 % of the
   54,404 pool), attract hash byte-exact, routes FULLY_STATIC. Tool:
   `tools/eventcrawl.py` (`--trial-dir`). Remainder: 77 pool units + walker
   leftovers (proxy only).
4. **Save-flow divergence (open investigation).** No observed hangs remain:
   the relocated-stub fixups (`src/ffta_ram_dispatch.h`) and the LZSS entry
   guard (`[[mod_function_hook]]` → `ffta.lzss-guard`) closed every observed
   stall, and the summon routes replay strict-clean. The underlying
   stale-frame divergence in the save-scan/load flow is still to be
   root-caused upstream; watch for subtle degradations around in-game saves.
5. Main-game content (play → harvest → resolve) plus long-run attract contact
   sheet (f6000+) and the upstream note on the bridge stop-contract runaway:
   battles and summons completed 2026-10-07; sessions remain the bug-hunter
   and the acceptance corpus.
   - Annotation leftovers **done** (passes 3-6): data-region names (104 rows
     in `symbols/ffta_data_symbols.tsv`), decompressor entry corrected to
     `0x0801F098` (+ SWI thunk `0x08141868`), event-VM anchors named
     (`symbols/ffta_symbols.tsv` § 5) with `reference/event-vm.md`; FAQ
     26118 mine closed (all codes encrypted — no raw addresses left in it).
6. **Android port** (research done; the app shell ships inside gbarecomp).
   Note: device builds run with self-heal disabled — the static coverage this
   loop builds is its prerequisite.
7. Widescreen — **W1 landed 2026-10-08** (`reference/widescreen.md`): the
   world-map camera struct is at `0x02002C10-0x02002C1F` (v-scroll at
   `+0x0C`), the eased-update code at `0x08038BF2`/`0x08038C3E`, and the
   register apply is a **guest-owned hardware-DMA write** (helper family
   `0x08001300-0x08001420`; not visible to `GBARECOMP_MMIO_CAP`). Still
   open: W1b (locate the strip drawer — watch VRAM on world-map/battle
   ENTRY), then **W2** widen the 256-px field tilemaps to 512-wide + extend
   the drawer behind a mod hook + camera bias at the struct level; **W3**
   per-scene policy (menus pillarbox) + opt-in via `opts.max_view_width` in
   `src/main.cpp`. Dev override for experiments: `GBARECOMP_WS_WIP=1
   --view-width N` (renders wide headless today; margins currently show
   wrapped BG columns). An optional mod layer from the notes' verified hack
   sites (QoL/difficulty/test-speed) once the core is done.
8. Community/upstream (optional): gbarecomp issue covering the bridge
   stop-contract and relocated-stub resume classes; share the
   reverse-engineered save-record format when the wiki scene is reachable.
