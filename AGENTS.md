# AGENTS.md — FFTA Recomp (agent instructions)

IMPORTANT: Prefer retrieval-led reasoning over pre-training-led reasoning for
GBA recompilation, ROM disassembly, and gbarecomp framework tasks. Read
`README.md` (setup + run) and `tests/README.md` (playtesting, healing loop,
gates, CI) first, then this file (rules of engagement); `BRINGUP.md` is the
decision log. Verify every ROM claim with
`gbarecompx/tools/disarm.py` disassembly and cite the address. Deep detail is not kept
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

1. **Never guess.** Do: run `gbarecompx/tools/disarm.py` and cite the address; label
   anything unverified as unverified.
2. **First divergence only.** Do: root-cause the earliest difference against
   the oracle; downstream symptoms are consequences.
3. **Never edit `generated/`.** Do: curate `game.toml` and `src/`.
4. **Evidence in every `game.toml` entry.** Do: every seed carries a
   disassembly-evidence `note` (build packs with `gbarecompx/tools/misspack.py`).
5. **Log every decision in `BRINGUP.md`** (date, action, result, conclusion)
   and commit after every milestone.
6. **Three strikes.** Do: after 3 inexplicable failures, stop, write the
   state to `BRINGUP.md`, report — don't thrash.
7. **Framework docs win.** `gbarecompx/{PRINCIPLES,DEBUG,AGENTS}.md` +
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
3. For state-level claims also run `gbarecompx/tools/framediff.py`; freeze any new
   route worth guarding as a fixture + `check.py` entry.
4. Commit with a dated `BRINGUP.md` entry.

**B. Playtest → healing loop** — after every session (full version:
`tests/README.md` § "The playtest → healing loop"):
1. Harvest: the miss proposals are journaled live in
   `logs/playtest_misses.frag`; after a crash also run
   `gbarecompx/tools/cache_harvest.py --out logs/proposal.frag` (heal-cache filenames).
   The run's own output is the exit banner (`self_heal_coverage=…`) plus
   `recomp_master_misses_AFXE.toml.frag` / `recomp_coverage_AFXE.json` next
   to the exe.
2. Review + **manually** merge seeds into `game.toml` (never auto-write);
   **update `symbols/*.tsv` in the same session** — naming-only function
   entries for every newly-identified function, data-symbol entries with
   measured sizes for every newly-identified table (a skipped symbols
   update is how a whole subsystem gets re-discovered from scratch).
3. `.venv/bin/python gbarecompx/tools/resolve.py --trace <csv> [--load-state <state>]`
   — strict-replays, seeds misses through a temp overlay, repeats until
   `self_heal_coverage=FULLY_STATIC`. Split mid-session reload traces with
   `gbarecompx/tools/trace_split.py` first.
4. Acceptance: workflow A, plus a final strict replay of the session.

**Debugging:** use the TCP debug surface + capture envs (never printf);
state claims as "per the frame ring at f=N (vblank=M)"; traps, run modes and
close handling live in `reference/dev-gotchas.md`.

## Commands (canonical quick reference)

```sh
# framework tools (re-run after submodule changes)
cmake -S gbarecomp -B gbarecompx/build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build gbarecompx/build --target gba_recompile gba_scan --parallel 8
# regenerate static code (canonical form; cycle.py wraps this)
./gbarecompx/build/gba_recompile --rom game.gba --config game.toml \
  --symbols symbols/ffta_symbols.tsv --data-symbols symbols/ffta_data_symbols.tsv \
  --out generated --max-functions 65536
# build the game (mods flag links the widescreen plugin lifecycle)
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DGBARECOMP_ENABLE_MODS=ON
cmake --build build --target FFTARecomp --parallel 8
# run (BIOS + ROM hash-verify at launch)
./build/FFTARecomp --bios bios/emibios_gba_bios.bin --rom game.gba \
  --frames 2400 --no-window
```

| Task | Command |
|---|---|
| Fresh-clone bootstrap | `python3 build.py` (idempotent; `--force`, `--no-smoke`, `--jobs N`) |
| Full regression gate | `.venv/bin/python tools/check.py` (`--fast`; `--jobs N`; `--only a,b`) |
| CI subset (no dumps needed) | `--only unit-cpp,unit-py,android-static` — `.github/workflows/ci.yml` |
| Android static checks (device-free) | `tools/android_static_check.py` — suite `android-static` in `tools/check.py` |
| Android APK content guard | `tools/android_apk_check.py [--apk …] [--expect public/private]` — opt-in `check.py --only android-apk` |
| Release packager (issue #3 R-track) | `.venv/bin/python tools/make_release.py [--apk \| --windows] [--binary build-compat/FFTARecomp] [--version V]` — allowlist stage → private-material sweep → deterministic portable zip (Linux zip + public APK + static Windows exe) |
| SteamOS compat binary (Steam Deck floor) | `.venv/bin/python tools/compat_build.py [--jobs N]` — Debian 12 container (glibc 2.36), refuses newer GLIBC symbols; output `build-compat/FFTARecomp` |
| Steam Deck AppImage | `.venv/bin/python tools/make_appimage.py --version V --binary build-compat/FFTARecomp` — pinned appimagetool + type-2 runtime, writable-XDG AppRun, squashfs sweep, packaged FULLY_STATIC smoke |
| Publish a release (local) | `.venv/bin/python tools/publish_release.py --version vX.Y [--upload-only \| --publish]` — builds all four public artifacts, verifies guards, writes `SHA256SUMS`, uploads to the tag's draft release; GitHub never sees the ROM |
| MinGW cross prefix (R2) | `.venv/bin/python tools/win_cross_deps.py build` — pinned static raylib into `cross-prefix/` (idempotent `.done` markers; `status`, `clean`, `purge`) |
| Widescreen smoke | `.venv/bin/python tools/ws_check.py` (fixtures `saves/ws_fixtures/`) |
| Playtest (windowed, instrumented) | `tools/play.sh [--scale N \| --resize-view \| --tcp-observe PORT]` |
| Attract golden gate | `.venv/bin/python tools/attract_check.py` (`--repin` only for deliberate changes) |
| Miss evidence pack | `.venv/bin/python gbarecompx/tools/misspack.py logs/missN.frag [--stubs \| --pc 0x...]` |
| Oracle diff / lockstep probes | `gbarecompx/tools/framediff.py --lo 4 --hi 300`; `gbarecompx/tools/dualrun.py --help` |
| Coverage (three lenses) | `.venv/bin/python tools/coverage_report.py` |
| Instruction-ring query | `gbarecompx/tools/ringscan.py --file /tmp/fp.bin [--pc P \| --reg R \| --reg-range LO HI]` |
| Unit tests only | `cmake --build build --target ffta_unit_tests && ctest --test-dir build -R ram_dispatch` |

## Codebase map

| Path | What |
|---|---|
| `game.toml` | Per-game config: identity pin + all audit seeds (evidence in `note`s) |
| `src/` | Host code: `main.cpp` (hooks/plugins), `ffta_ram_dispatch.h`, pre-boot launch-screen call |
| `android/` | Android target: Gradle project, runtime TOML, payload defaults, device gate — guide `android/README.md` |
| `generated/` | Recompiler output — gitignored, never edited |
| `tools/` | The harness — key ones listed in the table above; full list: `tools/README.md` |
| `.agents/skills/` | `gbarecomp-recomp-playbook` — portable playtest/healing/audit playbook (SKILL.md routes its references) |
| `mods/` `inputs/` `symbols/` `reference/` | Widescreen catalog; input traces; symbol seeds; study notes |
| `gbarecompx/` | Pinned submodule = the framework fork (`james2doyle/gbarecompx`, **public**; every former patch is committed history there; owns the framework tests + agent rules `gbarecompx/AGENTS.md`) — do not update casually (pin bumps: `reference/dev-gotchas.md` § Submodules) |

## Status (2026-10-19)

All phases complete; **every executed path strict-FULLY_STATIC**; corpus
**63,134 emitted units** (device-resume healing batch, BRINGUP late);
attract hash stable since pinning; widescreen W1–W3 complete; save/summon
hangs fixed; suspend-flow phantom closed (IRQ abandon-close + split-loop
gap roll-in — issue #30 fixes);
**Android port** landed and device-verified 2026-10-08, current engine
re-verified on device 2026-10-09 (boot gate, press acceptance, suspend/kill/
relaunch lifecycle — guide `android/README.md`); **emibios migration**
(issue #17) complete — launch BIOS is committed clean-room repo material;
**release track** (issue #3) complete through the Steam Deck AppImage —
Linux zip, public APK, **static MinGW Windows exe**, and the
**glibc-2.35 AppImage** built in the pinned Debian 12 container, all
guarded, deterministic where applicable, and live on **v2.0** (packager +
cross-prefix + compat machinery: `tools/make_release.py`,
`tools/win_cross_deps.py`, `tools/compat_build.py`,
`tools/make_appimage.py`). Releases are built and uploaded locally
(`tools/publish_release.py`); the tag workflow is GitHub-hosted and
ROM-free — it only creates the draft release shell. Remaining:
offline-push re-trial (gated on an interior-split policy), f6000+ contact
sheet, upstream note on the bridge stop-contract, APK release-signing key
(`gbaKeystore` vs debug — still debug-signed). History, evidence,
crash playbooks: `BRINGUP.md`.

### CI, test ownership, and controller input (2026-10-17, complete)

- **tier-1 CI fixed** after the rename era: a stale `build/` cache
  (restore-keys fallback carried a pre-rename `GBARECOMP_ROOT` past the
  hash key; `set(... CACHE)` never overwrites) plus folded-backslash
  YAML continuations silently swallowing the stub flag — both fixed in
  `.github/workflows/ci.yml`; first fully green run since the rename.
- **gbarecompx is public** (`james2doyle/gbarecompx`) — the submodule
  fetches on CI without credentials.
- **Android controllers** device-verified on the AYN Odin (APK
  1.6-119): a glue-level capture trusts the KEYCODE, not the source
  bits (the raylib #5387 device class — buttons flagged KEYBOARD were
  dead), and consumes KeyCharacterMap fallback synthesis (the OS turned
  unhandled BUTTON_B into BACK — the "menu on B" symptom). Face buttons
  map label-wise; the pad's menu button (or Y) and the Back key both open the
  settings overlay; right trigger = fast-forward; left stick = d-pad.
- **Android haptics (2026-10-20, issue #30 Phases 1+3):** the platform
vibrator sink is live (`android_haptics_pulse` → `GbaGameActivity.vibrate`,
media/game-attributed) and `host_primary_haptic` routes by last-used input
modality. Controller motors (Phase 2 glue capture), the battle-damage hook
(Phase 4), and the haptics setting (Phase 5) remain deferred.

**Sharp scaling verified at the pixels** (fractional layouts differ
  ~70%, exact-integer layouts identical — the designed inertness per
  the rsn8887 recipe) and the menu's status line names the inert case.
- **Test ownership split**: the game's CI tests only game code —
  `tests/unit/` is 3 files (ram_dispatch, speed_boost, ws_margin); the
  framework's tests (HostWindow contracts, backend selection, host-stack
  guard, frame pacer, the present pipeline) moved to
  `gbarecompx/tests/runtime/` and run in the fork's four-job CI
  (86/86 stub, 88/88 raylib tier). Framework-side agent rules:
  `gbarecompx/AGENTS.md`.

### Launcher track (2026-10-16 → 2026-10-18, complete) — recomp-ui removed; raygui launch screen

Plan: `.opencode/RAYGUI_LAUNCHER.md`. recomp-ui removed entirely
(submodule, seam flags, patches, `ui-tests` suite, SDL2/freetype/harfbuzz
cross-deps). The pre-boot surface is **framework code in the gbarecompx
fork** (not game-repo `src/` — plan erratum corrected 2026-10-18):
`gbarecompx/src/runtime/launcher.h` (`LauncherBackend` contract),
`launcher_raygui.cpp` (Play / Select ROM / drag-and-drop / gamepad nav /
first-boot picker), `launch_screen_model.h` — with tinyfiledialogs
v3.21.2 vendored at `gbarecompx/third_party/tinyfiledialogs/` for native
dialogs on every platform (console fallback disabled via the
`tinyfd_query` probe — headless fails fast, never blocks on stdin).
`asset_picker` dialog loop ungated (Win32 impls replaced with tinyfd);
`force_pick` fixes Select ROM silently no-op'ing on a valid cache.
Settings live only in the in-game menu; `--rom`/`--bios`/`--no-window`/
`--frames`/`--load-state`/`--tcp` skip the screen. Box art: Justme488 USA
cover (license unknown, sign-off given 2026-10-16; URL + SHA-256 +
EmuMovies credits in `THIRD_PARTY_ATTRIBUTION.md`), staged beside the exe
as `assets/img/boxart.png` (dev: CMake `stage_boxart`; release: packager).
Attract golden unchanged throughout (`1EF4C118…`).

**Repoint (was the remaining launcher-track item — done 2026-10-18):** the
build now points at the published gbarecompx remote directly — the
`gbarecomp` submodule IS the fork (`52c73d9`), the patch suite
(`tools/patches/` + the `patches` check suite + `build.py`'s apply step)
is retired, and fresh clones build the game binary again. The nested
`arm-recomp-core` pin moved to the published fork branch (`cd010b5`,
`feat/in-body-forward-goto` — the former working-tree-only patch work is
now committed history). Framework-side follow-ups (dead `launcher_seam.h`
et al. in the fork, Flatpak XDG portal) remain logged in BRINGUP, not
dropped.

## Reference index (load what the task needs)

| Topic | Load |
|---|---|
| Decisions, priors, corrections, crash playbooks | `BRINGUP.md` |
| Quick start, features, controls, building | `README.md` |
| What this is, running/display options, repository map, contributing | `docs/README.md` |
| Harness tool list | `tools/README.md` |
| Study-notes index, sources, credits | `reference/README.md` |
| Manual setup route (no build.py) + troubleshooting | `docs/manual-build.md` |
| Playtest/debug cookbook, healing loop, gates, coverage, CI, unit tests | `tests/README.md` |
| Android target: build, run, device gate, controller support, known behavior | `android/README.md` |
| Harness traps: run modes, capture envs, close handling, RAM-dispatch, saves, submodule pins, Android native build + input traps | `reference/dev-gotchas.md` |
| Oracle + frame-diff protocol (park phase, sync rules, builds) | `reference/oracle-harness.md` |
| Widescreen internals + validation | `reference/widescreen.md` |
| Fast-forward controls, 2–10x speed setting, expected behavior | `docs/fast-forward.md` |
| Event VM + scripts | `reference/event-vm.md` |
| Community source summaries (decomp, engine hacks, FAQs, notes) | `reference/{ffta-decomp,fergusson-mechanics,bcrobert-notes,jokyr-hack-guide,ffta-gamefaqs-code-guides}.md` |
| BIOS boot/SoftReset/System-SPSR semantics (validated vs GBATEK + mGBA source) | `reference/gba-bios-boot-and-spsr.md` |
| Framework truth + config schema | `gbarecompx/PRINCIPLES.md`, `DEBUG.md`, `docs/TOML_SCHEMA.md` |
| Portable gbarecomp practice (loop, triage, verification) | `.agents/skills/gbarecomp-recomp-playbook/` |
