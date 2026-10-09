# Local framework patches

Working-tree edits kept applied on top of the pinned `gbarecomp/` submodule.

**Re-apply after a submodule update with the consolidated patch:**

```sh
git -C gbarecomp apply ../tools/patches/gbarecomp-local.patch
```

`gbarecomp-local.patch` is one pristine→dev diff of the whole tracked tree.
`tools/check.py`'s `patches` check (1) sanity-validates every file in this
directory per the rules below and (2) replays pin + consolidated and
requires the result to byte-match the dev tree (tracked files, including
gitlink entries skipped) — it fails on any drift between the recorded
patches and the actual submodule state. **After any further framework edit,
regenerate the consolidated patch** (export command below) or the check
fails.

The per-feature files below are **reference diffs** (history and
attribution): each applies forward to the pin individually and
reverse-checks on the dev tree, but they are **not a sequential re-apply
set** — their contexts interleave after historical re-exports, and no
permutation stacks cleanly (verified 2026-10-09). Use the consolidated
patch to re-apply; use these files to see what each change was for.

| Patch | Target | Purpose |
|---|---|---|
| `gbarecomp-local.patch` | whole dev tree (canonical re-apply unit) | Consolidated pristine→dev diff; replay-verified byte-identical to the dev tree by `check.py` `patches` |
| `oracle-save-autoload.patch` | `gbarecomp/oracle/main.cpp` | Make the oracle autoload `<rom>.sav` next to the ROM |
| `selfheal-journal-close-hardening.patch` | `gbarecomp/src/runtime/{runtime_arm_default_aborts,overlay_loader,runtime}.cpp` | Durable live miss-frag journal + bounded heal-worker shutdown (see `BRINGUP.md` § close-hardening) |
| `mmio-cap-dma-reentrancy.patch` | `gbarecomp/src/gba/gba_io.{h,cpp}` | MMIO-cap per-call record control — fixes guest-DMA destination writes being swallowed by the write32 split flag (see `BRINGUP.md` § MMIO cap gap) |
| `mod-state-publish-race.patch` | `gbarecomp/src/runtime/mod_runtime.cpp` | Pid-unique mod-state publish temp — concurrent launches can no longer consume each other's `state.toml` write |
| `host-stack-guard-desktop.patch` | `gbarecomp/src/runtime/{mobile_platform.h,mobile_platform.cpp,runtime_bus_bridge.cpp,runtime.cpp}` | Host-stack budget guard (mobile + desktop TCP game thread): a spin whose split-function back-edges nest host frames without unwinding (see `BRINGUP.md` § 2026-10-09) unwinds via the standard yield path before the stack is exhausted. Desktop arming: `host_stack_guard_arm_current` on the `--tcp` game thread (2 MiB margin); critical tier fires even in a stuck IRQ-nest state within 0.5 MiB of the bottom. Supersedes the former `mobile-host-stack-guard.patch`. |
| `touch-pad-idle-hide.patch` | `gbarecomp/src/runtime/{runtime.h,runtime.cpp,host_window.h,host_window.cpp}` | Virtual pad idle auto-hide (`RunOptions::touch_pad_idle_hide_seconds`): the pad hides after N s of touch inactivity; any touch reveals it and then acts (see `BRINGUP.md` § Android: virtual pad idle auto-hide) |

Export after further submodule edits (regenerates the canonical patch; the
replay check above goes red until you do):

```sh
git --no-pager -C gbarecomp diff --no-ext-diff --no-color > tools/patches/gbarecomp-local.patch
```

A plain `git diff` piped through a pager/formatter produces non-apply-able
files — that happened once (see BRINGUP); `--no-ext-diff --no-color` is
mandatory.

`gbarecomp` is licensed **PolyForm Noncommercial 1.0.0** (© 2026 Matthew
Stanley); patched copies remain under its terms. These files are diffs only —
no upstream source is vendored here.
