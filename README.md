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

## Quick start

Requirements: CMake ≥ 3.20 + Ninja, GCC or Clang (C++17), SDL2 (dev), git,
Python 3.10+ — plus the two dumps above. Everything after cloning is one
idempotent script:

```sh
git clone --recursive <repo-url> ffta-recompiled && cd ffta-recompiled
cp /path/to/ffta-usa.gba game.gba
cp /path/to/gba_bios.bin gbarecomp/bios/gba_bios.bin
python3 build.py            # deps → recompile → build → smoke test (FULLY_STATIC)
tools/play.sh --scale 4     # play: 4x window (960x640)
```

Controls: arrows = D-pad, X = A, Z = B, Enter = Start, Backspace = Select,
C = L, V = R. Re-run `build.py` after pulling; it skips finished steps.

Prefer the script over the manual route ([docs/manual-build.md](docs/manual-build.md)
— reference + troubleshooting for every step above). Android is a separate
target: [android/README.md](android/README.md).

## Display options

```sh
tools/play.sh --scale 8 --screen backlit   # bigger window + GBA-screen color
```

- `--scale N` (1–8, default 3): window size is N×240 × N×160 pixels
  (4 → 960x640, 8 → 1920x1280). `play.sh` forwards extra flags to the binary.
- `--screen KIND`: GBA screen simulation — `raw` (default, exact passthrough),
  `unlit`, `frontlit`, `backlit`, `classic`. Also via `[video].screen` in
  `game.toml`, or the `GBARECOMP_SCREEN` environment variable.
- Widescreen up to 448 px (`--view-width`, `--resize-view`) is a validated
  feature with its own model — guide: [reference/widescreen.md](reference/widescreen.md).

Headless runs are for scripts and gates; use `tools/play.sh` for anything
interactive:

```sh
./build/FFTARecomp --bios gbarecomp/bios/gba_bios.bin --rom game.gba \
  --frames 6000 --no-window       # headless; add --dump-png out.png for a frame
```

Session recording, savestates, debug ports and clean shutdown are covered in
**[tests/README.md](tests/README.md)**.

## Status

All bring-up phases are complete; **every executed path replays
strict-FULLY_STATIC** (zero interpreter fallback), and the attract
regression hash has been stable since pinning. Widescreen (W1–W3, up to
448 px) and the **Android port** are landed and device-verified
([android/README.md](android/README.md)) — the current engine passed the
on-device boot, press-acceptance and suspend/kill/resume lifecycle gates
2026-10-09. Open items and gating decisions live in `AGENTS.md` § Status;
the dated decision log, evidence and crash playbooks are `BRINGUP.md`.

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
| `build.py` | Fresh-clone bootstrap — submodules → dumps → venv → patches → tools → BIOS → corpus → build → smoke (see Quick start) |
| `build_apk.py` | Android bootstrap — preflight → private Gradle build (ROM+BIOS embedded) → APK content guard → install + device gate (android/README.md § Build) |
| `game.toml` | Per-game config: identity pin + all audit seeds (evidence in `note`s) |
| `src/` | Host integration: `main.cpp`, launcher boot, stack setup |
| `android/` | Android target: Gradle project + engine-shell wiring, runtime TOML, payload defaults, device gate — guide `android/README.md` |
| `tests/` | Host unit tests + the testing guide — playtesting, healing loop, gates, CI (`tests/README.md`) |
| `docs/` | Deep-dive build docs — the manual setup route (`docs/manual-build.md`) |
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
4. **Log decisions** in `BRINGUP.md` (date, action, result, conclusion) and
   commit after every milestone.
5. **Don't auto-write `game.toml`** — proposals are reviewed by a human/agent
   before merging.

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

Nothing here would exist without work other people shared:

- **[mstan](https://github.com/mstan)** — the
  [gbarecomp](https://github.com/mstan/gbarecomp) framework and
  [recomp-ui](https://github.com/mstan/recomp-ui), plus the reference-game
  recompilations and the R.A.I.D. community around them.
- **Bregalad and loveemu** — "GBA Mus Ripper" / `sappy_detector.c` behind our
  m4a engine detection ([berg8793](https://github.com/berg8793/gba-mus-ripper)
  and [CaptainSwag101](https://github.com/CaptainSwag101/gba-mus-ripper) forks
  for cross-checking).
- **The [Data Crystal](https://datacrystal.tcrf.net/) contributors** — FFTA
  ROM/RAM maps, scripting and compression pages (via the Wayback Machine).
- **[LeonarthCG](https://github.com/LeonarthCG)** —
  [FFTA_Engine_Hacks](https://github.com/LeonarthCG/FFTA_Engine_Hacks), the
  address index behind our engine studies.
- **[charlie-troy](https://github.com/charlie-troy)** —
  [ffta-decomp](https://github.com/charlie-troy/ffta-decomp), used for naming
  and cross-checks.
- **[spiiin](https://github.com/spiiin)** —
  [FFTAUtils](https://github.com/spiiin/FFTAUtils): map-data formats, verified
  data regions.
- **BCROBERT, JoKyR, Terence Fergusson, and the GameFAQs code-guide authors
  (Adrammelech, labmaster, TetrisTheMovie, Vegikachu)** — structures and formulas.
- **The [FFHacktics](https://ffhacktics.com/) community** — long-running FFTA
  research that made all of this findable.
- **The [mGBA](https://mgba.io/) project** — our differential-testing oracle.

Redistribution terms for anything included here live in
`THIRD_PARTY_ATTRIBUTION.md` and `reference/datacrystal/README.md`.

## License

The project's own code and documentation are licensed **PolyForm
Noncommercial 1.0.0** (`LICENSE`) — free to use, share, and modify for
noncommercial purposes. Third-party components keep their own terms (the
`gbarecomp` framework: PolyForm NC; `recomp-ui`: MIT;
`reference/datacrystal/`: GFDL 1.2) — see `THIRD_PARTY_ATTRIBUTION.md`.
