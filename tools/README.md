# tools/ — the harness

The developer/testing harness around the game: playtest instrumentation,
the coverage/healing loop, regression gates, Android checks, and
ROM-analysis utilities.

**For playing, run the built binary directly** — see
[docs/README.md](../docs/README.md). `tools/play.sh` is the *testing*
entry, not the play entry. For when-to-run-what (workflows, gates, CI), see
[tests/README.md](../tests/README.md).

| Tool | What |
|---|---|
| `play.sh` | Instrumented windowed playtest: input recording, live miss journaling, persistent battery save, previous-session archiving. Extras: `--tcp-observe PORT`, `--launcher`, `--scale N`, `--fullscreen` |
| `check.py` | Full regression gate: host unit tests, attract hash, widescreen smoke, strict route replays (`--fast`, `--only a,b`, `--jobs N`) |
| `make_release.py` | Desktop release packager (issue #3 R-track): allowlist stage → private-material sweep (hash-pinned ROM/BIOS rejection) → deterministic portable zip; refuses a stale build. `--apk` adds the guarded public Android APK artifact (clean repackage, ROM-less, `--expect public`). `--windows` adds the static cross-compiled Windows exe artifact (MinGW static, zero DLLs, objdump-guarded, wine-smoked; ROM-less). Runs as `check.py --only release` |
| `win_cross_deps.py` | Pinned static cross-dependency prefix for `--windows`: zlib / freetype / harfbuzz / SDL2 into `cross-prefix/` (idempotent markers; sha256-pinned tarballs). Why source builds: Arch has no mingw binary library packages (and MSYS2 is Windows-only). `fetch` / `build` / `status` / `clean` / `purge` |
| `mingw-x64.cmake` | CMake cross toolchain for `--windows` (x86_64-w64-mingw32, prefix-first search) |
| `cycle.py` | Change cycle after `game.toml`/`src/` edits: cold regen → dispatch sanity → build → attract gate |
| `resolve.py` | Strict-replay miss seeder — seeds a trace's misses through a temp overlay, repeats until FULLY_STATIC (`--trace <csv>`, `--load-state`) |
| `cache_harvest.py` | Post-crash miss harvesting (`--out logs/proposal.frag`) |
| `misspack.py` | Evidence pack for a miss fragment (`--stubs`, `--pc 0x...`) |
| `attract_check.py` | Attract golden gate (`--repin` only for deliberate changes) |
| `ws_check.py` | Widescreen smoke test (fixtures `saves/ws_fixtures/`) |
| `savecheck.py` | Save-image validation |
| `ui_check.py` | recomp-ui runtime-UI tests: the settings-overlay model + ImGui presentation (layout, list scroll-follow and touch drag-scroll). Builds with just a C/C++ compiler — `check.py --only ui-tests` |
| `desktop_accept.py` | Headless free-run acceptance scoring (`--mode tcp` / `--mode window`) |
| `coverage_report.py` | Coverage report, three lenses |
| `framediff.py` / `dualrun.py` | Oracle frame-diff / lockstep differential runs |
| `cadence_probe.py` | Render-path update-cadence gate (the compute-at-60/read-at-30 detector): pauses the pacer on `--tcp`, steps exactly one VBlank at a time, asserts the 60 Hz scheduler invariants (frame_step parities, `gVblankCounter`) and no every-other-frame consumer on the presented surfaces (io/oam/pal/vram + display-reg shadow; IWRAM staging alternation is the double-buffer slot write and only reported). Drives flows with `--replay <input-trace>` (format: `reference/dev-gotchas.md` § Input trace format) or `--script "step:buttons,…"`, adds `--watch addr:len`, `--strict`, `--regions`, `--json`; `check.py --only cadence` |
| `ringscan.py` | Instruction-ring query (`--file`, `--pc`, `--reg-range`) |
| `keyprobe.py` | Live debug-port inspector |
| `trace_split.py` | Split mid-session reload traces |
| `disarm.py` | ROM disassembler — the evidence source behind every address claim in the project |
| `m4a_detect.py` | m4a audio-engine detection (Bregalad lineage) |
| `android_static_check.py` | Device-free Android checks: identity pins, payload contract, hygiene (CI tier 1) |
| `android_apk_check.py` | APK content guard for built APKs (`--expect public/private`) |
| `validate_android.sh` | On-device acceptance gate: install → launch → assertions → evidence |
| `android_press_test.py`, `android_lifecycle_test.py`, `android_touch_test.py`, `android_trace_replay.py` | On-device gates — see [android/README.md](../android/README.md) |
| `patches/` | Local framework patches (gbarecomp, its nested arm-recomp-core, recomp-ui) — see [patches/README.md](patches/README.md) |

The remaining scripts (`chunkprobe.py`, `hangprobe.py`, `hangrepro.py`,
`spinhunt.py`, `pc0_hunt.py`, `eventcrawl.py`, `hle_audit.py`,
`livewatch.py`, `readseq_probe.py`, `derail_loop.sh`, `quit.py`, …) are
one-off probes from bring-up sessions; the table above is the maintained
harness.
