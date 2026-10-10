# FFTA Recomp

> Native PC recompilation of **Final Fantasy Tactics Advance** (GBA, USA / AFXE) built on the [mstan/gbarecomp](https://github.com/mstan/gbarecomp) framework.

This is not an emulator. The game's ARM/Thumb code is statically translated to
host C++ (AOT), compiled, and executed natively — with a **self-healing
coverage** loop so the next build is fully static.

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

- CMake ≥ 3.20 + Ninja, GCC or Clang (C++17), SDL2 (dev), git
- Python 3.10+ with `capstone`, installed into a repo-local `.venv/`
  (`build.py` sets this up; `uv` recommended, plain `python3 -m venv` works
  too)
- Your own dumps: the FFTA (USA) ROM and a GBA BIOS dump — both
  hash-verified at launch (see the block above) and never committed
- Optional: a system mGBA install (`mgba-qt`) for side-by-side eyeballing

## Setup (fresh clone → running game)

Everything after cloning is wrapped in one idempotent script — place your
dumps and run:

```sh
git clone --recursive <repo-url> ffta-recompiled && cd ffta-recompiled
cp /path/to/ffta-us.gba game.gba
cp /path/to/gba_bios.bin gbarecomp/bios/gba_bios.bin
python3 build.py
```

`build.py` runs, in order: submodules → dump validation → `.venv/`
(pinned capstone) → framework patches → framework tools → BIOS recompile →
static corpus → `build/FFTARecomp` → strict 2400-frame smoke (expect
`FULLY_STATIC`). The first run takes a few minutes (two
builds plus the corpus).

<details>
<summary>Manual route (what build.py automates — reference + troubleshooting)</summary>

The manual sequence was verified end-to-end from a fresh clone on
2026-10-08 (submodules → tools → patches → BIOS → corpus → build → strict
smoke + attract gate).

**1. Clone with submodules.**
```sh
git clone <repo-url> ffta-recompiled && cd ffta-recompiled
git submodule update --init --recursive
# If a submodule worktree comes up empty, re-run with --checkout --recursive
```

**2. Place your dumps** — `game.gba` at the repo root (FFTA USA) and
`gbarecomp/bios/gba_bios.bin` (your own BIOS dump). Launch verifies both
hashes and fails loudly if either is wrong or missing.

**3. Python venv for the tooling** (disassembler, audit harness):
```sh
uv venv .venv && uv pip install --python .venv capstone
#   (or: python3 -m venv .venv && .venv/bin/pip install capstone)
```

**4. Apply the local framework patches** (recommended — the tooling below
assumes them; the two **consolidated** `*-local.patch` files are the
canonical re-apply units — per-feature files are reference diffs whose
contexts interleave, so apply them only onto a pristine submodule, before
the consolidated ones, and only if you need the attribution history):

```sh
cd gbarecomp
git apply ../tools/patches/gbarecomp-local.patch
cd external/arm-recomp-core && git apply ../../../tools/patches/arm-recomp-core-local.patch && cd ../..
cd ..
```

`tools/check.py --only patches` guards their validity — each file must be
apply-able forward against the pristine pin (the CI condition) and
reverse against the patched tree, and the replay must byte-match the dev
tree (`tools/patches/README.md`).

**5. Build the framework tools** (one-time; re-run only after submodule
changes):
```sh
cmake -S gbarecomp -B gbarecomp/build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build gbarecomp/build --target gba_recompile gba_scan --parallel 8
```

**6. Recompile the BIOS (one-time).** Run it *from `gbarecomp/`* so the
output lands in `gbarecomp/src/runtime/generated_bios/`, and pass the
project's BIOS config — it seeds the 770 named BIOS functions and
identity-checks the dump (without it only 666 are discovered and strict
runs abort on a miss at pc `0x300`):
```sh
cd gbarecomp && ./build/gba_recompile --bios bios/gba_bios.bin \
  --config bios/gba_bios.toml && cd ..
```

**7. Generate the game's static code corpus** (also after every `game.toml`
change — `tools/cycle.py` wraps this with the sanity checks and the attract
gate):
```sh
./gbarecomp/build/gba_recompile --rom game.gba --config game.toml \
  --symbols symbols/ffta_symbols.tsv --data-symbols symbols/ffta_data_symbols.tsv \
  --out generated --max-functions 65536
```

**8. Configure and build the game binary:**
```sh
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DGBARECOMP_ENABLE_MODS=ON
cmake --build build --target FFTARecomp --parallel 8
```

(`GBARECOMP_ENABLE_MODS=ON` links the framework's mod lifecycle APIs —
activation/reset plugins, view-width requests — used by the game's
widescreen hooks; verified gate-neutral.)

**9. Sanity.** Strict, headless, no input — expect `FULLY_STATIC` in the
banner:
```sh
GBARECOMP_STRICT_STATIC=1 ./build/FFTARecomp \
  --bios gbarecomp/bios/gba_bios.bin --rom game.gba --frames 2400 --no-window
```
And optionally the attract gate, which pins the exact frame hash:
```sh
.venv/bin/python tools/attract_check.py    # PASS + exit 0 expected
```

</details>

Then play — `tools/play.sh` (guide: `tests/README.md`).

<details>
<summary>Troubleshooting</summary>

- `build.py` stops at **dumps** → the ROM/BIOS is missing or has the wrong
  hash (expected SHA-1s at the top of this README); it never downloads them.
- `build.py` stops at **framework patches** → the submodule drifted from
  its pin; check `git -C gbarecomp status`.
- `gba_recompile: command not found` → step 5 was not run in this checkout.
- `generated_bios/` stays empty / BIOS never loads → step 6 was run from the
  wrong directory (`cd gbarecomp` first). If strict runs instead abort with
  a dispatch miss near pc `0x300`, step 6 ran without
  `--config bios/gba_bios.toml`.
- Launch aborts with an identity/hash error → wrong or missing dump; compare
  the SHA-1s listed at the top of this README.
- CMake cannot find SDL2 → install the dev package (see Requirements).
- `import capstone` fails in tools → step 3's venv (use
  `.venv/bin/python tools/...`).
- A submodule directory is empty after cloning → step 1's retry line.
- Window refuses to close, or a session wedges → `tools/quit.py <port>`; see
  `tests/README.md` § Playtesting & debugging.
- After `game.toml` edits: regenerate (step 7) → rebuild → attract gate, i.e.
  `.venv/bin/python tools/cycle.py`.

</details>

Optional — the mGBA oracle used by the frame-diff harness (needs network
once; distinct from a system mGBA):

```sh
cd gbarecomp && bash oracle/setup-mgba.sh \
  && cmake -B build -S . -DGBARECOMP_BUILD_ORACLE=ON \
  && cmake --build build --target gbarecomp_oracle --parallel 8
```

## Status & Roadmap

All bring-up phases are complete; **every executed path replays
strict-FULLY_STATIC** (zero interpreter fallback), and the attract
regression hash has been stable since pinning. Widescreen (W1–W3, up to
448 px) and the **Android port** are landed and device-verified
([android/README.md](android/README.md)) — the current engine passed the
on-device boot, press-acceptance and suspend/kill/resume lifecycle gates
2026-10-09. Decision log, evidence, crash playbooks: `BRINGUP.md`.

Remaining, roughly in order:

1. **Offline-push re-trial** — re-run the speculative
   `speculative_literal_harvest` trial now that the interior-split hazard
   is closed (split-loop gap roll-in, issue #30); gated on an
   interior-split policy decision.
2. **f6000+ contact sheet** — long-run attract captures beyond the
   2400-frame pin, eyeballed before extending the gate horizon.
3. **Upstream notes on the bridge stop-contract** — the self-heal bridge's
   200M-instruction runaway abort vs. computed-jump entries without a
   matching return frame (issue-#30 family context).
4. **Android release prep** — keystore/signing, arm64-only release,
   version stamping (`android/README.md` § Deferred); the Robolectric shell
   tests and the NDK cross-compile in CI from the same list.

## Run it

```sh
tools/play.sh                     # windowed, instrumented — the normal way to play
tools/play.sh --scale 8           # windowed, bigger (guide: tests/README.md)

./build/FFTARecomp --bios gbarecomp/bios/gba_bios.bin --rom game.gba \
  --frames 6000 --no-window       # headless; add --dump-png out.png for a frame
```

Headless runs are for scripts and gates; use `tools/play.sh` for anything
interactive. Session recording, controls, savestates, debug ports and clean
shutdown are covered in **[tests/README.md](tests/README.md)**.

## Testing & debugging

All testing, debugging and verification workflows live in
**[tests/README.md](tests/README.md)**:

- **Play & record** — `tools/play.sh` (instrumented sessions, savestates,
  debug port; keymap `build/keybinds.ini`)
- **Coverage/healing loop** — play -> harvest -> merge seeds -> `tools/resolve.py`
  -> `tools/cycle.py`
- **Regression gate** — `.venv/bin/python tools/check.py` (host tests,
  attract, widescreen smoke, strict route replays)
- **CI** — `.github/workflows/ci.yml` (fork-safe tier 1) and the full-gate
  tier split
- **Android** — device gate `tools/validate_android.sh` (install → launch →
  assertions → evidence) plus device-free checks `tools/android_static_check.py`
  (CI tier 1); build/run guide: [android/README.md](android/README.md)

## Repository layout

| Path | What |
|---|---|
| `build.py` | Fresh-clone bootstrap — submodules → dumps → venv → patches → tools → BIOS → corpus → build → smoke (see Setup) |
| `game.toml` | Per-game config: identity pin + all audit seeds (evidence in `note`s) |
| `src/` | Host integration: `main.cpp`, launcher boot, stack setup |
| `android/` | Android target: Gradle project + engine-shell wiring, runtime TOML, payload defaults, device gate — guide `android/README.md` |
| `tests/` | Host unit tests + the testing guide — playtesting, healing loop, gates, CI (`tests/README.md`) |
| `generated/` | Recompiler output — gitignored, **never edited** |
| `mods/` | Preloaded mod catalog shipped beside the exe — the default-enabled `ffta.enhancement.widescreen` manifest activating the linked `ffta.widescreen` plugin |
| `gbarecomp/`, `recomp-ui/` | Pinned framework submodules (see `reference/dev-gotchas.md` for pins) |
| `tools/` | The whole harness: `play.sh`, `check.py` (regression gate), `ws_check.py` (widescreen smoke), `savecheck.py` (save validation), `resolve.py`, `cache_harvest.py`, `cycle.py`, `attract_check.py`, `android_static_check.py` (device-free Android checks), `android_apk_check.py` (APK content guard), `misspack.py`, `coverage_report.py`, `framediff.py`, `dualrun.py`, `ringscan.py`, `keyprobe.py`, `trace_split.py`, `disarm.py`, … |
| `.agents/skills/` | Project-local agent skills — `gbarecomp-recomp-playbook`, a portable healing-loop/audit playbook with task-grouped references |
| `inputs/` | Deterministic input traces (`<frame>,0x<hex>` active-low, sticky) |
| `symbols/` | Curated symbol seeds (attributed; consumed via `--symbols`) |
| `BRINGUP.md` | Decision log — the project's memory; read it |
| `AGENTS.md` | Rules of engagement for agents; read it before changing anything |

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

The coverage/healing workflow (play → harvest → resolve → verify) is
documented in [tests/README.md](tests/README.md).

## References & attribution

- [mstan/gbarecomp](https://github.com/mstan/gbarecomp) — the recompilation
  framework (read its `PRINCIPLES.md`, `DEBUG.md`, `docs/TOML_SCHEMA.md`);
  `recomp-ui` for the launcher/runtime UI.
- [mstan/EmeraldRecomp](https://github.com/mstan/EmeraldRecomp) and
  [mstan/WarioWareTwistedRecomp](https://github.com/mstan/WarioWareTwistedRecomp)
  — reference implementations for the widescreen margin/UI-anchoring model
  (studied for `reference/widescreen.md`).
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
