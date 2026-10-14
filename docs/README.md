# docs/ — how it works, running the game, and the repository map

Deep-dive documentation. The [root README](../README.md) is the short
story (quick start, features, controls, building); this folder holds the
rest: project status, what the recompilation actually is, how to run and
tune the built binary, the manual build route, the full repository map,
and the contribution rules.

## Status

All bring-up phases are complete. The game boots and runs on Linux,
Windows and Android — menus, battles, event scripts, cartridge saves — with
every executed path replaying strict-FULLY_STATIC (zero interpreter
fallback) and the attract-mode regression hash stable since pinning. The
Windows build is a static MinGW cross-compile from the same tree
(`tools/make_release.py --windows` — zero DLL dependencies, import-table
guarded, wine-smoked, byte-reproducible; see tests/README.md § the release
packager). Android is
device-verified on a Xiaomi Poco X3 Pro (Android 14): boot,
press-acceptance, and the suspend/kill/relaunch lifecycle gates passed
2026-10-09. Builds are experimental, so back up important saves and report
repeatable crashes.

Open items and gating decisions: [AGENTS.md](../AGENTS.md) § Status.
Dated evidence, history, and crash playbooks: [BRINGUP.md](../BRINGUP.md).

## What this is

This is not an emulator. *Final Fantasy Tactics Advance*'s ARM/Thumb
machine code is statically translated ahead-of-time into host C++ by
[gbarecomp](https://github.com/mstan/gbarecomp), compiled, and executed
natively. The bundled clean-room BIOS
([bios/README.md](../bios/README.md)) is recompiled and linked like the rest
of the machine.

Coverage is audited with a **self-healing loop**: instrumented playtests
journal every unmapped code fragment as a proposal, proposals are
hand-merged into `game.toml` with disassembly evidence, and strict replays
re-verify until every executed path is FULLY_STATIC — zero interpreter
fallback. The loop itself is documented in
[tests/README.md](../tests/README.md).

Framework truth supersedes any summary here:
[gbarecomp/PRINCIPLES.md](../gbarecomp/PRINCIPLES.md),
[DEBUG.md](../gbarecomp/DEBUG.md), and
[docs/TOML_SCHEMA.md](../gbarecomp/docs/TOML_SCHEMA.md).

## Running the built game

For play, run the self-built binary directly. With no arguments it opens
the [recomp-ui](https://github.com/mstan/recomp-ui) launcher — select your
ROM and select **Play**. The BIOS is pre-filled from `game.toml` (the
bundled clean-room build); launcher settings persist in
`build/config.ini`, and the **Skip launcher** toggle boots straight into
the game. To bypass the UI entirely:

```sh
./build/FFTARecomp --bios bios/emibios_gba_bios.bin --rom game.gba
```

> **`tools/play.sh` is not the play entry.** It is the instrumented testing
> harness (input recording, live miss journaling, savestate archiving) —
> see [tests/README.md](../tests/README.md).

### Display options

| Flag | What |
|---|---|
| `--scale N` | window scale 1–8 (default 3): the window is N×240 × N×160 px (4 → 960×640, 8 → 1920×1280) |
| `--screen KIND` | GBA screen simulation: `raw` (default, exact passthrough), `unlit`, `frontlit`, `backlit`, `classic` |
| `--fullscreen` | borderless desktop fullscreen |
| `--linear-filter` / `--sharp-filter` / `--affine-filter` | output scaling filters |
| `--view-width N`, `--resize-view` | widescreen **view** up to 448 px — a validated feature with its own model: [reference/widescreen.md](../reference/widescreen.md) |

The screen model is also settable via `[video].screen` in
[game.toml](../game.toml) or the `GBARECOMP_SCREEN` environment variable.
`--view-width` changes the widescreen *view*, not the window — use
`--scale` for window size.

Headless flags (`--frames N`, `--no-window`, `--dump-png`, `--load-state`,
`--tcp-observe PORT`, …) exist for scripts, regression gates, and debugging,
not for play. Run modes and their traps:
[tests/README.md](../tests/README.md) and
[reference/dev-gotchas.md](../reference/dev-gotchas.md).

## Frame interpolation

[frame-interpolation.md](frame-interpolation.md) documents the
display-rate interpolation feature (issue #9): the decoupled display
clock, the true-midpoint scroll-shift intermediates, and the three
motion guards (layer consensus, rebase veto, HUD pin) — with the
FFTA-specific findings that shaped them and a porting checklist for
other gbarecomp games.

## Manual build route

[manual-build.md](manual-build.md) documents, step by step, what
`python3 build.py` automates — the reference and troubleshooting route when
a step needs to run by hand. Prefer `build.py`; it is idempotent and every
step detects whether it is already done.

## Repository layout

| Path | What |
|---|---|
| `build.py` | Fresh-clone bootstrap — submodules → dumps → venv → patches → tools → BIOS → corpus → build → smoke ([README § Quick start](../README.md#quick-start)) |
| `build_apk.py` | Android bootstrap — preflight → private Gradle build (ROM embedded; BIOS bundled from `bios/`) → APK content guard → install + device gate ([android/README.md § Build](../android/README.md)) |
| `game.toml` | Per-game config: identity pin + all audit seeds (evidence in `note`s) |
| `src/` | Host integration: `main.cpp` (hooks/plugins), launcher boot, stack setup |
| `android/` | Android target: Gradle project + engine-shell wiring, runtime TOML, payload defaults, device gate — guide `android/README.md` |
| `tests/` | Host unit tests + the testing guide — playtesting, healing loop, gates, CI (`tests/README.md`) |
| `docs/` | This guide, the frame-interpolation deep dive (`docs/frame-interpolation.md`), and the manual setup route (`docs/manual-build.md`) |
| `generated/` | Recompiler output — gitignored, **never edited** |
| `mods/` | Preloaded mod catalog shipped beside the exe — the default-enabled `ffta.enhancement.widescreen` manifest activating the linked `ffta.widescreen` plugin |
| `inputs/` | Deterministic input traces (`<frame>,0x<hex>` active-low, sticky) |
| `symbols/` | Curated symbol seeds (attributed; consumed via `--symbols`) |
| `bios/` | The bundled clean-room launch BIOS — `bios/README.md` |
| `tools/` | The harness — full list in `tools/README.md` |
| `reference/` | Study notes, sources, and credits — `reference/README.md` |
| `.agents/skills/` | Project-local agent skills — `gbarecomp-recomp-playbook`, a portable healing-loop/audit playbook |
| `gbarecomp/`, `recomp-ui/` | Pinned framework submodules — do not update casually (pins + local patches: `reference/dev-gotchas.md`) |
| `BRINGUP.md` | Decision log — the project's memory; read it |
| `AGENTS.md` | Rules of engagement for agents and contributors |
| `THIRD_PARTY_ATTRIBUTION.md` | Third-party terms and redistribution rules |

## Contributing

Full rules live in [AGENTS.md](../AGENTS.md); the essentials:

1. **Never guess.** Every ROM claim comes from disassembly you ran, address
   cited; every `game.toml` entry carries its evidence in `note`.
2. **Never edit `generated/`.** Curation happens in `game.toml` and `src/`.
3. **ROM hygiene.** No ROM-derived bytes in git, ever.
4. **Log decisions** in [BRINGUP.md](../BRINGUP.md) (date, action, result,
   conclusion) and commit after every milestone.
5. **Don't auto-write `game.toml`** — proposals are reviewed by a
   human/agent before merging.

The coverage/healing workflow (play → harvest → resolve → verify) is
documented in [tests/README.md](../tests/README.md).
