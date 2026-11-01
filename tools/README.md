# tools/ — the harness

The developer/testing harness around the game: playtest instrumentation,
the coverage/healing loop, regression gates, Android checks, and
ROM-analysis utilities.

**For playing, run the built binary directly** — see
[docs/README.md](../docs/README.md). `tools/play.sh` is the *testing*
entry, not the play entry. For when-to-run-what (workflows, gates, CI), see
[tests/README.md](../tests/README.md).

## Build and release

| Tool | What |
|---|---|
| `make_release.py` | Desktop release packager (issue #3 R-track): allowlist stage → private-material sweep (hash-pinned ROM/BIOS rejection) → deterministic portable zip; refuses a stale build. `--binary PATH` stages a specific executable (release cuts use `build-compat/FFTARecomp`). `--apk` adds the guarded public Android APK artifact (clean repackage, ROM-less, `--expect public`). `--windows` adds the static cross-compiled Windows exe artifact (MinGW static, zero DLLs, objdump-guarded, wine-smoked; ROM-less). Runs as `check.py --only release` |
| `make_appimage.py` | Steam-Deck/Linux AppImage packager: reuses the Linux allowlist stage, adds the pinned appimagetool + type-2 runtime/desktop/icon, a writable-XDG `AppRun` wrapper (saves/config beside the unpacked exe), Steam Deck fullscreen defaults, a post-build squashfs private-material sweep, and a strict 2400-frame packaged-AppImage smoke. Output `release-stage/FFTARecomp-<version>-linux-x86_64.AppImage` |
| `compat_build.py` | Builds `build-compat/FFTARecomp` in the pinned Debian 12 container (`tools/compat/Containerfile`, glibc 2.36) and refuses binaries whose GLIBC symbol floor exceeds `--max-glibc`. Needed because a rolling-host build can require a newer glibc than SteamOS ships. Podman (with a btrfs/vfs fallback) and Docker supported |
| `publish_release.py` | Local release pipeline: builds the Linux zip/APK, static Windows zip, and Steam Deck AppImage (compat binary by default), verifies every artifact's guard, writes `SHA256SUMS-<tag>.txt`, uploads to the tag's draft release, and optionally publishes it. The GitHub tag workflow only creates the draft shell — no ROM or build runs on GitHub |
| `win_cross_deps.py` | Pinned static cross-dependency prefix for `--windows`: raylib only (raylib-only since the 2026-10 launcher track) into `cross-prefix/` (idempotent markers; sha256-pinned tarballs). Why source builds: Arch has no mingw binary library packages (and MSYS2 is Windows-only). `fetch` / `build` / `status` / `clean` / `purge` |
| `mingw-x64.cmake` | CMake cross toolchain for `--windows` (x86_64-w64-mingw32, prefix-first search) |

## Regression gates

| Tool | What |
|---|---|
| `check.py` | Full regression gate: host unit tests, seam guards (backend + framework test doubles), offline `stub-backend` compile, attract hash, widescreen smoke, strict route replays (`--fast`, `--only a,b`, `--jobs N`) |
| `cycle.py` | Change cycle after `game.toml`/`src/` edits: cold regen → dispatch sanity → build → attract gate |
| `attract_check.py` | Attract golden gate (`--repin` only for deliberate changes) |
| `ws_check.py` | Widescreen smoke test (fixtures `saves/ws_fixtures/`) |
| `savecheck.py` | Save-image validation |
| `cadence_probe.py` | Render-path update-cadence gate (the compute-at-60/read-at-30 detector): pauses the pacer on `--tcp`, steps exactly one VBlank at a time, asserts the 60 Hz scheduler invariants (frame_step parities, `gVblankCounter`) and no every-other-frame consumer on the presented surfaces (io/oam/pal/vram + display-reg shadow; IWRAM staging alternation is the double-buffer slot write and only reported). `--strict`, `--regions`, `--json`; `check.py --only cadence` |
| `hle_audit.py` | BIOS HLE coverage audit (registered suite `hle-audit`): forces HLE, runs attract + route B, asserts every executed SWI is HLE-taken; needs the built exe and local fixtures |
| `hangrepro.py` | Deterministic suspend→A hang regression (registered suite `hangrepro`, `check.py --only hangrepro`); skips without `game.state3` + `saves/playtest.sav` |
| `check_raylib_backend_complete.py` | Completeness guard for the single-generation window seam (Phase 4b); run by `check.py --only raylib-backend` with `tools/tests/test_check_raylib_backend_complete.py` |
| `coverage_report.py` | Coverage report, three lenses (executed path, walker reach, pointer pool) |

## Playtest and debugging

| Tool | What |
|---|---|
| `play.sh` | Instrumented windowed playtest: input recording, live miss journaling, persistent battery save, previous-session archiving. Extras: `--tcp-observe PORT`, `--scale N`, `--fullscreen`. Procedure: [tests/README.md](../tests/README.md) § Playtesting & debugging |
| `desktop_accept.py` | Headless free-run acceptance scoring (`--mode tcp` / `--mode window`); registered suites `desktop-accept` / `desktop-accept-window` |
| `keyprobe.py` | Live KEYINPUT monitor for a running instance (`tools/play.sh --tcp-observe PORT`) |
| `hangprobe.py` | Read-only hang probe for the `--tcp-observe` channel (FFTA-tuned: dumps the vblank wake flag + IRQ vector) |
| `audio_session.py` | Live audio-fault triage around a play session: samples `audio_state`+`frame` (20 Hz) and `audio_trace` (4 Hz; launch the game with `GBARECOMP_AUDIO_FIFO_TRACE=1`), records the sink monitor, then prints a report (producer rate vs 65536 Hz, frame cadence, FIFO fill/empty events, broadband-transient + 0.3-5 Hz modulation scan). Use with `play.sh --tcp-observe PORT`; `--max-seconds`, `--no-record`, `--sink` |

## Android

| Tool | What |
|---|---|
| `android_static_check.py` | Device-free Android checks: identity pins, payload contract, hygiene (CI tier 1) |
| `android_apk_check.py` | APK content guard for built APKs (`--expect public/private`) |
| `validate_android.sh` | On-device acceptance gate: install → launch → assertions → evidence |
| `android_press_test.py`, `android_lifecycle_test.py`, `android_touch_test.py`, `android_trace_replay.py`, `android_pill_test.py` | On-device gates (press, suspend/kill/relaunch, touch pad, trace replay, touch-pill) — see [android/README.md](../android/README.md) § Device gate |

## Specialized probes

Bring-up probes retained because their unique checks are still reproducible
by hand. They are not part of the default gate.

| Tool | What |
|---|---|
| `chunkprobe.py` | Chunked PC breakpoint over a long trace; logs every hit's registers |
| `spinhunt.py` | Drives a route over TCP in chunks and detects a silent PC spin; dumps registers, guest stack, and nearby IWRAM |
| `pc0_hunt.py` | Catches the anomalous `pc=0` transfer in the windowed press flow |
| `eventcrawl.py` | Static event/script walk (roadmap item 3) |
| `readseq_probe.py` | Captures the save-driver read-call sequence on the native build and oracle; requires the optional oracle build first (see [reference/oracle-harness.md](../reference/oracle-harness.md)) |
| `derail_loop.sh` | Hunts the rare windowed-only press-path derail into BIOS |

**Framework-protocol tools live in the framework:** the rings/traces/TCP/
heal-loop/oracle tooling (`framediff.py`, `dualrun.py`, `resolve.py`,
`misspack.py`, `cache_harvest.py`, `ringscan.py`, `trace_split.py`,
`quit.py`, `livewatch.py`, `disarm.py`, `m4a_detect.py`) moved into
`gbarecompx/tools/` (2026-10-18) — they speak framework formats, serve
any gbarecomp game, and are tested in the fork's own CI guard job. Run
them from THIS repo root (the framework convention: `game.toml`,
`game.gba`, `bios/`, `generated/`, `logs/` in the cwd), e.g.
`.venv/bin/python gbarecompx/tools/misspack.py logs/missN.frag`.
