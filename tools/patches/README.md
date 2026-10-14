# Local framework patches

Working-tree edits kept applied on top of the pinned `gbarecomp/`
submodule — and, for `arm-recomp-core-*` patches, its nested
`external/arm-recomp-core` submodule; `recomp-ui-*` patches target the
`recomp-ui/` submodule instead. Patches are routed by that filename prefix;
everything else targets `gbarecomp` itself.

**Re-apply after a submodule update with the consolidated patches:**

```sh
git -C gbarecomp apply ../tools/patches/gbarecomp-local.patch
git -C gbarecomp/external/arm-recomp-core apply \
  ../../../tools/patches/arm-recomp-core-local.patch
git -C recomp-ui apply ../tools/patches/recomp-ui-local.patch
```

Each `*-local.patch` is one pristine→dev diff of its repo's whole tracked
tree. `tools/check.py`'s `patches` check (1) sanity-validates every file in
this directory per the rules below — forward against its target's pin, or
reverse on the patched dev tree **plus a pin-forward apply** (the CI
condition: a fresh checkout validates each file against the pristine pin,
so dev-based exports fail — enforced since the 2026-10-09 tier-1 break) —
and (2) replays pin + each consolidated patch and requires the result to
byte-match the corresponding dev tree locally (skipped as trivially-satisfied
on a pristine checkout). It fails on any drift between the recorded patches
and the actual submodule states. **After any further framework edit,
regenerate the matching consolidated patch** (export commands below) or the
check fails.

The per-feature files below are **reference diffs** (history and
attribution): each applies forward to the pin individually and
reverse-checks on the dev tree, but they are **not a sequential re-apply
set** — their contexts interleave after historical re-exports, and no
permutation stacks cleanly (verified 2026-10-09). Use the consolidated
patch to re-apply; use these files to see what each change was for.

| Patch | Target | Upstream? | Purpose |
|---|---|---|---|
| `gbarecomp-local.patch` | whole dev tree (canonical re-apply unit) | — | Consolidated pristine→dev diff; replay-verified byte-identical to the dev tree by `check.py` `patches` |
| `recomp-ui-local.patch` | `recomp-ui/` (canonical re-apply unit) | **Yes** (high) | Runtime settings overlay list scrolling (ffta-recomp issue #24): the host drives the selection (`recomp_runtime_ui_handle_input`) with `ImGuiWindowFlags_NoNavInputs` set, so nothing scrolled the list child when a d-pad/arrow press moved the highlight past the fold (`Scroll.y` frozen while the row walked 284 px below it), and ImGui children scroll only from the wheel or their scrollbar, so a touch swipe did nothing (`recomp-ui`'s SDL backends hand fingers to the UI as a mouse). The patch adds a minimal scroll-follow for host-driven selection plus a touch drag-scroll with a fling; drags mute row hover/click so a swipe cannot activate what it started on. Generic: any host that drives the menu's selection. Regression tests: `recomp-ui` `tests/runtime_ui_imgui_test.cpp` (`list_scroll_case`, `desktop_nav_scroll_case`), run by `tools/check.py --only ui-tests`. |
| `arm-recomp-core-local.patch` | nested repo `gbarecomp/external/arm-recomp-core` (canonical re-apply unit) | **Yes** (high) | In-body forward gotos (2026-10-09): a direct branch whose target lies inside the current function's extent AND carries a label (backward target, or a gap block rolled in as an alias) lowers to `goto L_<addr>` instead of a C call — how the split vblank loop stays in one host frame (see `BRINGUP.md` § split-loop gap roll-in). General codegen improvement for any game with split loops. |
| `oracle-save-autoload.patch` | `gbarecomp/oracle/main.cpp` | **Yes** (low) | Make the oracle autoload `<rom>.sav` next to the ROM (via `mCoreLoadFile` + `mCoreAutoloadSave`) instead of a raw `loadROM`, aligning it with standard mGBA frontend behavior so save/load-flow comparisons work. |
| `selfheal-journal-close-hardening.patch` | `gbarecomp/src/runtime/{runtime_arm_default_aborts,overlay_loader,runtime}.cpp` | **Yes** (medium) | Durable live miss-frag journal (written per-miss, env-gated) + bounded heal-worker shutdown (stop abandons queue; only in-flight compile finishes). Both are crash-safety/robustness fixes. |
| `mmio-cap-dma-reentrancy.patch` | `gbarecomp/src/gba/gba_io.{h,cpp}` | **Yes** (critical) | MMIO-cap per-call record control. A global `g_mmio_split` flag in `write32` suppressed nested records; when a 32-bit write covered CNT_L+CNT_H (e.g. FFTA DMA-helper `str r0,[r2,#8]`), the kicked DMA's destination writes were silently swallowed. Fix: per-call `record` parameter; synthetic halves pass `record=false`, reentrant writes keep recording. |
| `mod-state-publish-race.patch` | `gbarecomp/src/runtime/mod_runtime.cpp` | **Yes** (medium) | Pid-unique mod-state publish temp — concurrent launches (parallel harnesses, multiple instances) could consume each other's `state.toml` rename, then delete the freshly published output. Fix: `state.toml.<pid>.tmp`. |
| `host-stack-guard-desktop.patch` | `gbarecomp/src/runtime/{mobile_platform.h,mobile_platform.cpp,runtime_bus_bridge.cpp,runtime.cpp}` | **Yes** (parts; medium) | Host-stack budget guard: a wedged split vblank-wait loop nests host frames per spin and exhausts the 8 MiB desktop TCP game thread stack. Guard unwinds via the yield path within 2 MiB of the bottom; critical tier fires even in a stuck IRQ-nest state. Also moves `emit_exit_diagnostics()` before the worker join (lost-frags on unclean kill). The abandon-resume one-unwind hook is project-specific but small. |
| `irq-handler-abandon-close.patch` | `gbarecomp/src/armv4t/runtime_arm.cpp` | **Conditional** (high) | `runtime_irq`'s drive loop closes an IRQ whose handler never iret'd (ledger at the IRQ floor, or ≥4 VBlank boundaries in the loop) instead of adopting whatever runs next — fixes the stuck `g_irq_nest_depth` phantom. Close is coherent: restores IE/IME and the IWRAM ISR vector `[0x03007FFC]`, then arms a one-shot flow-continuation resume (`g_abandon_resume_pc`) redirecting the first post-close dispatch with mode coherence from `CPSR.T`. The abandon-detect + close principle is general; the flow-continuation resume is FFTA-specific and complex — upstream may want a simpler version without the resume redirect. |
| `touch-pad-idle-hide.patch` | `gbarecomp/src/runtime/{runtime.h,runtime.cpp,host_window.h,host_window.cpp}` | **Feature** (low) | Virtual pad idle auto-hide (`RunOptions::touch_pad_idle_hide_seconds`): the pad hides after N s of touch inactivity; any touch reveals it and then acts. UX enhancement for touch devices, not a correctness fix. |
| `stick-to-dpad.patch` | `gbarecomp/src/runtime/{input_synth.h,host_window.cpp}` | **Feature** (medium) | Left analog stick doubles as the d-pad (ffta-recomp issue #14): `stick_to_dpad()` maps SDL left-stick axes (-32768..32767, up/left negative) past a 25% deadzone onto the four d-pad bits, additively with the physical d-pad and keyboard; the host poll ORs the result into KEYINPUT like the button map. Pure helper unit-tested by `ffta_unit_tests` (skip probe on a pristine checkout). |
| `speed-toggle-ff-seam.patch` | `gbarecomp/src/runtime/{runtime.h,runtime.cpp}` | **Feature** (low) | Game-driven fast-forward latch (`RunOptions::fast_forward_request`, ffta-recomp issue #11): a game-owned control (FFTA's touch pill in `src/ffta_speed_boost.cpp`) requests the same boost as the Assist hold/latch under the same Assist-enable gate. Null (all other games) leaves the input path byte-identical. |
| `swi-return-ledger.patch` | `gbarecomp/src/armv4t/runtime_arm.cpp` | **Yes** (high; the issue #30 R1 root containment) | SWI-return continuation ledger: `runtime_swi`'s LLE entry records the SVC-return continuation (`return_address` — the SWI site + instruction width); every SVC-mode exception return (`runtime_exception_return` + the interpreted note) validates `new_pc` against the ledger top and keeps the recorded continuation on mismatch (loud log). Ring-proven root (2026-10-09): the BIOS SWI epilogue (`0x184 pop {fp,ip,lr}` / `0x188 movs pc,lr`, disarm-verified) returned to the IRQ-interrupted PC (`0x080033BA`) instead of the recorded veneer continuation (`0x814186E`) when the shared R[14] slot was clobbered mid-drive — on hardware LR_svc is banked and untouchable, so this pins the recomp divergence, not guest behavior. Ledger cleared at every machine-reset / savestate-load origin (`runtime_fp_reset`); SoftReset's never-returned SWI leaves only a harmless stale entry. |
| `android-external-state-dir.patch` | `gbarecomp/src/runtime/runtime.cpp` | Feature (low) | `--state-dir <dir>` (ffta-recomp issue #6): save-state slots (`.stateN`) and the mobile suspend state/marker (`.suspend.state`/`.suspend.pending`) are written under the given directory (ROM basename kept) instead of next to the ROM. Empty (desktop default) preserves historical behavior. The game side (`src/main.cpp`, Android only) points it at the user-visible external app directory with a one-time migration from app-private storage. |
| `launcher-force-ui.patch` | `gbarecomp/src/runtime/launcher_seam.h` | Proposal (medium) | `--launcher` forces the pre-boot UI even when headless-classified flags (`--rom`, `--frames`, …) are present (ffta-recomp issue #5: `play.sh` always passes `--rom`, so the flag never took effect). Without `--launcher`, headless detection still skips silently. Behavior-change proposal for upstream: the previous contract only forced past a persisted skip. |
| `frame-pacer-banked-wait.patch` | `gbarecomp/src/runtime/{host_platform.h,host_platform.cpp,runtime.cpp}` | **Yes** (high) | Banked-frame pacer wait (ffta-recomp issue #8 fix): `FramePacer::wait_for_next_frame(frames=1)` advances the deadline by the banked count, and both present sites pass `frame - last_presented_frame`. Stale-frame present skips used to let banked frames escape throttling (+5% guest wall-clock in battle, audio-bridge flood); one wait now paces all of them. `frames==1` is the old path exactly; fast-forward (k==1 per wait) and the behind-resync are unchanged. Rebased 2026-10-13 for issue #9 3a (tick-callback wait extension): the wait-call, signature, and decl hunks now include the 3a tick lines (banked lines unchanged) so both patch legs stay green on overlap. Rebased again for issue #9 3b (scroll-shift wait extension): the wait-site hunk is now the pin→tree superset (banked comment + 3a/3b wait block incl. the true-midpoint build, the rebase consensus in `dominant_step`, and the `frame_mean_abs_diff` rebase veto). |
| `emibios-launcher-pin-set.patch` | `gbarecomp/src/{gba/gba_bios.h,runtime/launcher_seam.h}` | Feature (medium) | Accept the clean-room emibios BIOS (LGPL-3.0-or-later, coolbho3k/emibios; ffta-recomp issue #17) alongside the retail dump: `GbaBios::kEmibiosSha1` pin + the launcher's `bios_verify` hook tries retail, then emibios. The per-config `[bios].sha1` pin stays the runtime's real gate; this only lets the launcher recognize a config-pinned clean-room BIOS (and a user-supplied emibios) instead of demanding retail. |
| `emibios-bios-dispatch-table.patch` | `gbarecomp/src/runtime/generated_bios/bios_dispatch_table.cpp` | Data (large, mechanical) | The BIOS regeneration for emibios (issue #17) overwrites the upstream-provenance retail `bios_dispatch_table.cpp` with the emibios table (5339 rows vs retail's 5156 — the table is committed upstream "for provenance and overwritten by BIOS regeneration" per its `.gitignore`). Data-only: address/name rows, no code. Regenerate with `build.py` step_bios; the delta must stay in the consolidated patch for the `patches` replay to byte-match. |
| `emibios-public-guard-bundled.patch` | `gbarecomp/platform/android/gbarecomp-app.gradle` | **Conditional** (medium) | Public-artifact guard exemption: a 16 KiB `.bin` whose SHA-1 equals the game-declared `biosSha1` pin (which must differ from the retail default) is declared clean-room BIOS material, staged on purpose for every build including public ones. The retail filename `gba_bios.bin` is never exempt; retail dumps stay unbundleable. Needed by any game bundling a redistributable replacement BIOS in its Android payload. |
| `android-save-picker.patch` | `gbarecomp/platform/android/{gbarecomp-app.gradle,AndroidManifest.xml,java/org/gbarecomp/GbaGameConfig.java,java/org/gbarecomp/GbaSetupActivity.java}` | Feature (low) | Optional battery-save import on the setup screen (ffta-recomp issue #20, desktop parity): `saveFile`/`saveSize` manifest pins (empty = no card), a third "Save data (optional)" SAF card with size validation (exact when pinned, else ≤128 KiB), dual-write to app-private `saves/` + user-visible external `saves/` (issue #6's runtime reads the latter, so an internal-only write would strand re-imports), and `ready()` never gates PLAY on the save. |

## Upstream priority (re-audit 2026-10-09, late)

**Verdict: all 10 patches are necessary** — no duplicates. The two
`runtime_arm.cpp` patches are complementary layers over the same
ring-proven corruption chain: `swi-return-ledger` is the containment
(a corrupted SVC return never lands), `irq-handler-abandon-close` the
recovery (a handler that lost its iret anyway is closed coherently);
`hangrepro` exercises both.

Recommended order for proposing to gbarecomp:

1. `frame-pacer-banked-wait` — pacing correctness: stale-frame present
   skips let banked guest frames escape throttling (measured +5% fast
   clock with an audio-bridge flood on FFTA battle). Small, game-agnostic,
   behavior-identical for the common single-frame case.
2. `mmio-cap-dma-reentrancy` — correctness bug; any game with 32-bit DMA
   config writes loses DMA tracking. Still valid after upstream PR #29
   (2026-10-09): its shared-RAM DMA HLE is a compile-time opt-in that
   bypasses the per-unit bus service entirely (so the default LLE path —
   and its recording gap — is unchanged).
2. `mod-state-publish-race` — clear concurrency fix for multi-process usage.
3. `arm-recomp-core` + the gap-roll-in hunk in `gbarecomp-local.patch`
   (`src/recompile/function_finder.cpp`) — split-loop codegen; should go
   together.
4. `swi-return-ledger` — the issue-#30 R1 containment; small, self-contained,
   no guest-visible behavior on a legal return. Promoted above the recovery
   (#8): it is the principled fix — the close only exists to mop up the case
   the ledger cannot see (an iret lost *before* any SWI).
5. `selfheal-journal-close-hardening` — durability + bounded shutdown,
   universally valuable.
6. `host-stack-guard-desktop` — robustness for finite-stack threads (strip
   the project-specific resume hook if upstream prefers).
7. `oracle-save-autoload` — small usability fix.
8. `irq-handler-abandon-close` — high value but complex; consider upstreaming
   only the abandon-detect + close without the resume redirect.
9. `touch-pad-idle-hide` — feature request; not a correctness issue.
10. `stick-to-dpad` — game-agnostic input courtesy (GBA titles have no
    analog input, so every d-pad-driven game benefits); upstream may want a
    launcher-exposed deadzone/off switch before it lands.
11. `recomp-ui-local` — the recomp-ui runtime-UI fix (a *different* upstream
    repo, `mstan/recomp-ui`; propose there, then bump the pin and drop the
    patch). High value, small and self-contained: it is a presentation bug in
    the shared in-game menu, so every host that drives the menu's selection
    with a d-pad and every touch host hit it.

### Upstream drift (checked 2026-10-09; recomp-ui 2026-10-12)

The `recomp-ui` pin (`cac2b8f`, master) is 39 upstream commits behind as of
2026-10-12 (nested runtime pages via `/`-separated section paths, standard
"Game dimming"/"Menu opacity"/"State slot"/"Pause in menu" rows, confirm-exit
items, launcher pipeline/resolution work). Checked that wave for this fix:
`src/common/backends/imgui/runtime_ui_imgui.cpp` there still has no scroll
handling at all — upstream does not fix issue #24, so the patch is not
subsumed. A `recomp-ui` pin bump would need the same discipline as
`gbarecomp`'s (rebase/re-export, re-run `ui-tests` + the desktop smoke).

The `gbarecomp` pin (`ecc9c55`, 2026-10-03) is ~30 upstream commits behind (the
web/WASM support wave, PR #16; PR #29's opt-in shared-RAM DMA HLE; PR #31's
scanline-HLE default). Verified **none subsume our patches** — PR #29's
`gba_io` rework does not touch `g_mmio_split` recording; `9be5351` is
WASM-availability reporting only; `src/runtime/mod_runtime.cpp` is
untouched — but the same *files* moved (`gba_io.{h,cpp}`,
`runtime_arm.cpp`, `host_window.*`, `overlay_loader.cpp`, `runtime.cpp`,
`oracle/` region). **A pin bump is a deliberate milestone, not a routine
pull**: rebase/re-export every patch, re-run the fresh-clone CI simulation
(pristine-at-pin submodules), and re-verify `hangrepro` +
`desktop-accept` on the new pin before committing it.

Export after further submodule edits (regenerates the canonical patch; the
replay check above goes red until you do):

```sh
git --no-pager -C gbarecomp diff --no-ext-diff --no-color -- . \
  ':(exclude)external/arm-recomp-core' > tools/patches/gbarecomp-local.patch
git --no-pager -C gbarecomp/external/arm-recomp-core diff --no-ext-diff \
  --no-color > tools/patches/arm-recomp-core-local.patch
git --no-pager -C recomp-ui diff --no-ext-diff --no-color \
  > tools/patches/recomp-ui-local.patch
```

A plain `git diff` piped through a pager/formatter produces non-apply-able
files — that happened once (see BRINGUP); `--no-ext-diff --no-color` is
mandatory. The `:(exclude)external/arm-recomp-core` pathspec keeps the dirty
nested submodule's gitlink out of gbarecomp-local.patch (GNU patch cannot
apply a submodule-commit hunk; the nested repo is covered by its own
consolidated patch).

`gbarecomp` is licensed **PolyForm Noncommercial 1.0.0** and `recomp-ui` is
**MIT** (both © 2026 Matthew Stanley); patched copies remain under their
terms. These files are diffs only — no upstream source is vendored here.
