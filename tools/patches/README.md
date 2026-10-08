# Local framework patches

Working-tree edits kept applied on top of the pinned `gbarecomp/` submodule
(re-apply with `git apply` from `gbarecomp/` after submodule updates):

| Patch | Target | Purpose |
|---|---|---|
| `oracle-save-autoload.patch` | `gbarecomp/oracle/main.cpp` | Make the oracle autoload `<rom>.sav` next to the ROM |
| `selfheal-journal-close-hardening.patch` | `gbarecomp/src/runtime/{runtime_arm_default_aborts,overlay_loader,runtime}.cpp` | Durable live miss-frag journal + bounded heal-worker shutdown (see `BRINGUP.md` § close-hardening) |
| `mmio-cap-dma-reentrancy.patch` | `gbarecomp/src/gba/gba_io.{h,cpp}` | MMIO-cap per-call record control — fixes guest-DMA destination writes being swallowed by the write32 split flag (see `BRINGUP.md` § MMIO cap gap) |

All patches are verified to apply forward to the pinned submodule commit
(and reverse from the patch-applied dev tree). `tools/check.py` includes a
`patches` check that fails if a file is mangled, empty, or drifts from
the submodule state; if you edit gbarecomp further, re-export with
`git --no-pager -C gbarecomp diff --no-ext-diff --no-color` (a plain
`git diff` piped through a pager/formatter produces non-apply-able files —
that happened once, see BRINGUP).

`gbarecomp` is licensed **PolyForm Noncommercial 1.0.0** (© 2026 Matthew
Stanley); patched copies remain under its terms. These files are diffs only —
no upstream source is vendored here.
