# docs/ — how it works, running the game, and the repository map

Deep-dive documentation. The [root README](../README.md) is the short
story for players (release quick start, features, controls); this folder
holds the rest: project status, what the recompilation actually is, how to
run and tune the built binary, the manual build route, the full repository
map, and the contribution rules.

## Documentation map

| Need | Authoritative document |
|---|---|
| Play: release quick start, features, controls | [root README](../README.md) |
| Build from source (manual route) | [manual-build.md](manual-build.md) |
| Test, heal coverage, run gates and CI | [tests/README.md](../tests/README.md) |
| Tool inventory and usage | [tools/README.md](../tools/README.md) |
| Android target: build, device gate, controls | [android/README.md](../android/README.md) |
| ROM/RAM research, study notes, credits | [reference/README.md](../reference/README.md) |
| Contributor rules and agent instructions | [AGENTS.md](../AGENTS.md) |
| Dated decisions, evidence, crash playbooks | [BRINGUP.md](../BRINGUP.md) |
| Framework internals and config schema | [PRINCIPLES.md](../gbarecompx/PRINCIPLES.md), [DEBUG.md](../gbarecompx/DEBUG.md), [TOML_SCHEMA.md](../gbarecompx/docs/TOML_SCHEMA.md) |

## Status

All bring-up phases are complete. The game boots and runs on Linux,
Windows and Android — menus, battles, event scripts, cartridge saves — with
every executed path replaying strict-FULLY_STATIC (zero interpreter
fallback) and the attract-mode regression hash stable since pinning. The
Windows build is a static MinGW cross-compile from the same tree
(`tools/make_release.py --windows` — zero DLL dependencies, import-table
guarded, wine-smoked, byte-reproducible; see tests/README.md § the release
packager). Linux/Steam Deck ships as a portable zip and an AppImage built
in a Debian 12 container for a SteamOS-safe glibc floor (the produced
binaries require glibc 2.35); the AppImage's `AppRun` unpacks to a
writable XDG data directory because the game keeps `rom.cfg`, settings and
saves beside its executable. Android is
device-verified on a Xiaomi Poco X3 Pro, a Xiaomi Mi 11, and an AYN Odin:
boot, press-acceptance, suspend/kill/relaunch, controller, and haptics
gates passed between 2026-10-08 and 2026-10-22. Builds are experimental, so
back up important saves and report repeatable crashes.

Open items and gating decisions: [AGENTS.md](../AGENTS.md) § Status.
Dated evidence, history, and crash playbooks: [BRINGUP.md](../BRINGUP.md).

## What this is

This is not an emulator. *Final Fantasy Tactics Advance*'s ARM/Thumb
machine code is statically translated ahead-of-time into host C++ by
[gbarecompx](https://github.com/james2doyle/gbarecompx) (the project's
actively developed fork of [gbarecomp](https://github.com/mstan/gbarecomp)),
compiled, and executed natively. The bundled clean-room BIOS
([bios/README.md](../bios/README.md)) is recompiled and linked like the rest
of the machine.

Coverage is audited with a **self-healing loop**: instrumented playtests
journal every unmapped code fragment as a proposal, proposals are
hand-merged into `game.toml` with disassembly evidence, and strict replays
re-verify until every executed path is FULLY_STATIC — zero interpreter
fallback. The loop itself is documented in
[tests/README.md](../tests/README.md).

Framework truth supersedes any summary here:
[gbarecompx/PRINCIPLES.md](../gbarecompx/PRINCIPLES.md),
[DEBUG.md](../gbarecompx/DEBUG.md), and
[docs/TOML_SCHEMA.md](../gbarecompx/docs/TOML_SCHEMA.md).

## Running the built game

For play, run the self-built binary directly. With no arguments it opens
the pre-boot launch screen — the first boot opens the native file picker;
pick your ROM and select **Play**. The BIOS is pre-filled from `game.toml`
(the bundled clean-room build), the pick is cached in `rom.cfg`, and the
in-game menu's settings persist in `config.ini`/`keybinds.ini` beside the
executable. To bypass the screen entirely:

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

### Fast-forward

Fast-forward controls, the in-game **Assist → Fast-forward speed** row
(2–10x), and expected audio/frame behavior are documented in
[fast-forward.md](fast-forward.md).

### Headless flags

Headless flags (`--frames N`, `--no-window`, `--dump-png`, `--load-state`,
…) exist for scripts, regression gates, and debugging, not for play. The
windowed-observe exception is `--tcp-observe PORT` (a window plus a read-only
debug port); plain `--tcp` is structurally headless. Run modes and their traps:
[tests/README.md](../tests/README.md) and
[reference/dev-gotchas.md](../reference/dev-gotchas.md).

## Releasing

The public release never involves the ROM on GitHub. A `v*` tag workflow
(GitHub-hosted) only creates a **draft** release shell; the maintainer
builds and verifies the artifacts locally, where the dump lives:

```sh
python3 build.py
.venv/bin/python tools/check.py --jobs 8
.venv/bin/python tools/publish_release.py --version vX.Y
# inspect the draft, then:
.venv/bin/python tools/publish_release.py --version vX.Y --upload-only --publish
```

`publish_release.py` builds the Linux zip, public APK, static Windows zip,
and Steam Deck AppImage (desktop binaries from the pinned Debian 12 compat
container), re-verifies each artifact's guard, writes
`SHA256SUMS-vX.Y.txt`, and uploads them to the tag's draft. The artifacts
are ROM-less production builds: players pick their own dump in the
launcher. `workflow_dispatch` on the tag workflow prepares the draft for an
existing tag as a recovery path.

## Manual build route

[manual-build.md](manual-build.md) documents, step by step, what
`python3 build.py` automates — the reference and troubleshooting route when
a step needs to run by hand. Prefer `build.py`; it is idempotent and every
step detects whether it is already done.

## Repository layout

| Path | What |
|---|---|
| `build.py` | Fresh-clone bootstrap — submodules → dumps → venv → tools → BIOS → corpus → build → smoke ([manual-build.md](manual-build.md)) |
| `build_apk.py` | Android bootstrap — preflight → private Gradle build (ROM embedded; BIOS bundled from `bios/`) → APK content guard → install + device gate ([android/README.md § Build](../android/README.md)) |
| `game.toml` | Per-game config: identity pin + all audit seeds (evidence in `note`s) |
| `src/` | Host integration: `main.cpp` (hooks/plugins, launch-screen boot), `ffta_ram_dispatch.h`, stack setup |
| `android/` | Android target: Gradle project + engine-shell wiring, runtime TOML, payload defaults, device gate — guide `android/README.md` |
| `tests/` | Host unit tests + the testing guide — playtesting, healing loop, gates, CI (`tests/README.md`) |
| `docs/` | This guide + the manual setup route (`docs/manual-build.md`) |
| `generated/` | Recompiler output — gitignored, **never edited** |
| `mods/` | Preloaded mod catalog shipped beside the exe — the default-enabled `ffta.enhancement.widescreen` manifest activating the linked `ffta.widescreen` plugin |
| `inputs/` | Deterministic input traces (`<frame>,0x<hex>` active-low, sticky) |
| `symbols/` | Curated symbol seeds (attributed; consumed via `--symbols`) |
| `bios/` | The bundled clean-room launch BIOS — `bios/README.md` |
| `tools/` | The harness — full list in `tools/README.md` |
| `reference/` | Study notes, sources, and credits — `reference/README.md` |
| `.agents/skills/` | Project-local agent skills — `gbarecomp-recomp-playbook`, a portable healing-loop/audit playbook |
| `gbarecompx/` | Pinned framework submodule = the fork (`james2doyle/gbarecompx`; every former local patch is committed history there) — do not update casually (pin bumps: `reference/dev-gotchas.md` § Submodules) |
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
