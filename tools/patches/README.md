# Local framework patches

Working-tree edits kept applied on top of the pinned `gbarecomp/`
submodule — and, for `arm-recomp-core-*` patches, its nested
`external/arm-recomp-core` submodule (patches are routed by that filename
prefix; everything else targets `gbarecomp` itself).

**Re-apply after a submodule update with the consolidated patches:**

```sh
git -C gbarecomp apply ../tools/patches/gbarecomp-local.patch
git -C gbarecomp/external/arm-recomp-core apply \
  ../../../tools/patches/arm-recomp-core-local.patch
```

Each `*-local.patch` is one pristine→dev diff of its repo's whole tracked
tree. `tools/check.py`'s `patches` check (1) sanity-validates every file in
this directory per the rules below (forward against its target's pin, or
reverse on the patched dev tree) and (2) replays pin + each consolidated
patch and requires the result to byte-match the corresponding dev tree
(tracked files, including gitlink entries skipped) — it fails on any drift
between the recorded patches and the actual submodule states. **After any
further framework edit, regenerate the matching consolidated patch** (export
commands below) or the check fails.

The per-feature files below are **reference diffs** (history and
attribution): each applies forward to the pin individually and
reverse-checks on the dev tree, but they are **not a sequential re-apply
set** — their contexts interleave after historical re-exports, and no
permutation stacks cleanly (verified 2026-10-09). Use the consolidated
patch to re-apply; use these files to see what each change was for.

| Patch | Target | Upstream? | Purpose |
|---|---|---|---|
| `gbarecomp-local.patch` | whole dev tree (canonical re-apply unit) | — | Consolidated pristine→dev diff; replay-verified byte-identical to the dev tree by `check.py` `patches` |
| `arm-recomp-core-local.patch` | nested repo `gbarecomp/external/arm-recomp-core` (canonical re-apply unit) | **Yes** (high) | In-body forward gotos (2026-10-09): a direct branch whose target lies inside the current function's extent AND carries a label (backward target, or a gap block rolled in as an alias) lowers to `goto L_<addr>` instead of a C call — how the split vblank loop stays in one host frame (see `BRINGUP.md` § split-loop gap roll-in). General codegen improvement for any game with split loops. |
| `oracle-save-autoload.patch` | `gbarecomp/oracle/main.cpp` | **Yes** (low) | Make the oracle autoload `<rom>.sav` next to the ROM (via `mCoreLoadFile` + `mCoreAutoloadSave`) instead of a raw `loadROM`, aligning it with standard mGBA frontend behavior so save/load-flow comparisons work. |
| `selfheal-journal-close-hardening.patch` | `gbarecomp/src/runtime/{runtime_arm_default_aborts,overlay_loader,runtime}.cpp` | **Yes** (medium) | Durable live miss-frag journal (written per-miss, env-gated) + bounded heal-worker shutdown (stop abandons queue; only in-flight compile finishes). Both are crash-safety/robustness fixes. |
| `mmio-cap-dma-reentrancy.patch` | `gbarecomp/src/gba/gba_io.{h,cpp}` | **Yes** (critical) | MMIO-cap per-call record control. A global `g_mmio_split` flag in `write32` suppressed nested records; when a 32-bit write covered CNT_L+CNT_H (e.g. FFTA DMA-helper `str r0,[r2,#8]`), the kicked DMA's destination writes were silently swallowed. Fix: per-call `record` parameter; synthetic halves pass `record=false`, reentrant writes keep recording. |
| `mod-state-publish-race.patch` | `gbarecomp/src/runtime/mod_runtime.cpp` | **Yes** (medium) | Pid-unique mod-state publish temp — concurrent launches (parallel harnesses, multiple instances) could consume each other's `state.toml` rename, then delete the freshly published output. Fix: `state.toml.<pid>.tmp`. |
| `host-stack-guard-desktop.patch` | `gbarecomp/src/runtime/{mobile_platform.h,mobile_platform.cpp,runtime_bus_bridge.cpp,runtime.cpp}` | **Yes** (parts; medium) | Host-stack budget guard: a wedged split vblank-wait loop nests host frames per spin and exhausts the 8 MiB desktop TCP game thread stack. Guard unwinds via the yield path within 2 MiB of the bottom; critical tier fires even in a stuck IRQ-nest state. Also moves `emit_exit_diagnostics()` before the worker join (lost-frags on unclean kill). The abandon-resume one-unwind hook is project-specific but small. |
| `irq-handler-abandon-close.patch` | `gbarecomp/src/armv4t/runtime_arm.cpp` | **Conditional** (high) | `runtime_irq`'s drive loop closes an IRQ whose handler never iret'd (ledger at the IRQ floor, or ≥4 VBlank boundaries in the loop) instead of adopting whatever runs next — fixes the stuck `g_irq_nest_depth` phantom. Close is coherent: restores IE/IME and the IWRAM ISR vector `[0x03007FFC]`, then arms a one-shot flow-continuation resume (`g_abandon_resume_pc`) redirecting the first post-close dispatch with mode coherence from `CPSR.T`. The abandon-detect + close principle is general; the flow-continuation resume is FFTA-specific and complex — upstream may want a simpler version without the resume redirect. |
| `touch-pad-idle-hide.patch` | `gbarecomp/src/runtime/{runtime.h,runtime.cpp,host_window.h,host_window.cpp}` | **Feature** (low) | Virtual pad idle auto-hide (`RunOptions::touch_pad_idle_hide_seconds`): the pad hides after N s of touch inactivity; any touch reveals it and then acts. UX enhancement for touch devices, not a correctness fix. |
| `swi-return-ledger.patch` | `gbarecomp/src/armv4t/runtime_arm.cpp` | **Yes** (high; the issue #30 R1 root containment) | SWI-return continuation ledger: `runtime_swi`'s LLE entry records the SVC-return continuation (`return_address` — the SWI site + instruction width); every SVC-mode exception return (`runtime_exception_return` + the interpreted note) validates `new_pc` against the ledger top and keeps the recorded continuation on mismatch (loud log). Ring-proven root (2026-10-09): the BIOS SWI epilogue (`0x184 pop {fp,ip,lr}` / `0x188 movs pc,lr`, disarm-verified) returned to the IRQ-interrupted PC (`0x080033BA`) instead of the recorded veneer continuation (`0x814186E`) when the shared R[14] slot was clobbered mid-drive — on hardware LR_svc is banked and untouchable, so this pins the recomp divergence, not guest behavior. Ledger cleared at every machine-reset / savestate-load origin (`runtime_fp_reset`); SoftReset's never-returned SWI leaves only a harmless stale entry. |

## Upstream priority (audit 2026-10-09)

Recommended order for proposing to gbarecomp:

1. `mmio-cap-dma-reentrancy` — correctness bug; any game with 32-bit DMA config writes loses DMA tracking.
2. `mod-state-publish-race` — clear concurrency fix for multi-process usage.
3. `arm-recomp-core` + the gap-roll-in hunk in `gbarecomp-local.patch` (`src/recompile/function_finder.cpp`) — split-loop codegen; should go together.
4. `selfheal-journal-close-hardening` — durability + bounded shutdown, universally valuable.
5. `host-stack-guard-desktop` — robustness for finite-stack threads (strip the project-specific resume hook if upstream prefers).
6. `oracle-save-autoload` — small usability fix.
7. `irq-handler-abandon-close` — high value but complex; consider upstreaming only the abandon-detect + close without the resume redirect.
8. `swi-return-ledger` — the R1 containment for the same issue-#30 family (see #7); small, self-contained, no guest-visible behavior on a legal return.
9. `touch-pad-idle-hide` — feature request; not a correctness issue.

Export after further submodule edits (regenerates the canonical patch; the
replay check above goes red until you do):

```sh
git --no-pager -C gbarecomp diff --no-ext-diff --no-color -- . \
  ':(exclude)external/arm-recomp-core' > tools/patches/gbarecomp-local.patch
git --no-pager -C gbarecomp/external/arm-recomp-core diff --no-ext-diff \
  --no-color > tools/patches/arm-recomp-core-local.patch
```

A plain `git diff` piped through a pager/formatter produces non-apply-able
files — that happened once (see BRINGUP); `--no-ext-diff --no-color` is
mandatory. The `:(exclude)external/arm-recomp-core` pathspec keeps the dirty
nested submodule's gitlink out of gbarecomp-local.patch (GNU patch cannot
apply a submodule-commit hunk; the nested repo is covered by its own
consolidated patch).

`gbarecomp` is licensed **PolyForm Noncommercial 1.0.0** (© 2026 Matthew
Stanley); patched copies remain under its terms. These files are diffs only —
no upstream source is vendored here.
