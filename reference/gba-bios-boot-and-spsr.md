# GBA BIOS boot, SoftReset, and System-mode SPSR — validated notes

Sources cross-checked 2026-10-09 (web + mGBA 0.10.5 source + our own rings):
GBATEK "BIOS Reset Functions"; the annotated BIOS disassembly
(camthesaxman/gba_bios) and the "GBA BIOS Reference" (retrointernals);
mGBA 0.10.5 `src/arm/arm.c`, `src/arm/isa-arm.c`,
`include/mgba/internal/arm/isa-inlines.h`. Summarized; no third-party text
copied beyond short factual quotes.

## Facts (validated)

- Vector table: 0x00 reset `b 0x68`; 0x08 SWI `b 0x140`; 0x18 IRQ `b 0x128`;
  **0x1C = shared Undefined/Abort/FIQ/reserved handler** ("devkit debug
  hook"): it push-saves {r12,lr} + {spsr,cpsr}, checks the cart header byte
  0x0800009C for 0xA5 (devkit marker). Normal carts (FFTA): not 0xA5 →
  branch to its restore path (**0x54-0x64**): pop {spsr} → `msr spsr_fc,r12`
  → pop {r12,lr} → **`subs pc, lr, #4`** — i.e. resume at LR-4 with whatever
  the S-bit-PC write's CPSR-restore semantics are.
- Reset flow after a soft reset: reset vector checks POSTFLG (0x04000300);
  if already-booted (soft reset) it masks I/F and **diverts to 0x1C** (the
  handler above) instead of re-running the cold boot. This is the path our
  press-flow derail walks (ring: pc=0 → 0x68 → 0x1C → 0x54-0x64).
- GBATEK SoftReset (SWI 00): clears 0x200 bytes (0x03007E00-0x03007FFF),
  resets SP_svc/irq/sys, zeroes R0-R12, LR_svc, SPSR_svc, LR_irq,
  SPSR_irq, enters system mode; "does not return to the calling procedure";
  the final jump uses the [0x03007FFA] flag (0 → 0x08000000 ROM,
  nonzero → 0x02000000 RAM), ARM state.
- **System/User-mode SPSR (ARMv4T)**: "no SPSR in these modes" (ARM ARM).
  mGBA models it as: `_ARMModeHasSPSR(mode) = mode != MODE_SYSTEM &&
  mode != MODE_USER` — an S-bit PC write in System performs **no CPSR
  restore**; but `MRS/MSR spsr` still read/write a live SPSR slot that is
  swapped with per-bank storage on mode changes (System maps to the shared
  non-exception bank). Our engine implements the same (no-restore gate +
  a USER/shared bank slot), and the reference interpreter documents the
  same rule.

## Consequence for our engine (validated)

Our engine's behavior on the whole 0x1C-handler / `msr spsr` + `subs
pc,lr,#4` sequence **matches mGBA and the interpreter model** — the
System-mode SPSR roundtrip is *not* the divergence. In the captured derail
the flow had already gone off path before this trampoline: ring records
show the game's wait-loop context (state3 pc 0x0800041A) jumping to the
CpuSet-region (0xB68..0xB9A BIOS) and then **pc=0 in ARM state** — a
corrupted transfer (the classic phantom family), which then walks the
reset-vector → 0x1C → trampoline → S-bit return with `LR=0x08000499`
→ dispatch ARM to 0x08000494 (mid-thumb) → self-heal bridge → interpreter
Undefined at 0x4EC → abort. The 0x0FF8 case is the same shape with a
thumb-tagged garbage value.

So: the fix belongs to the **corrupted-transfer (pc value) family** — find
what produces the anomalous pc (0 / 0x0FF8) at a return boundary in the
resumed-from-savestate flow — not to the SPSR/bank machinery.

## Harness notes

- `tools/derail_loop.sh` reproduces the derail (~12 %/run, windowed).
- Ring dumps: `GBARECOMP_BRIDGE_ENTRY_FP` / `GBARECOMP_BRIDGE_ABORT_FP`
  (entry = the only moment the pre-miss generated-code context survives);
  `GBARECOMP_SWI_TRACE` logs SWI HLE/LLE + SVC banking.
- A breakpoint at pc=0 (`set_break_pc`) parks the anomalous transfer so the
  pre-transfer ring + registers can be captured.
