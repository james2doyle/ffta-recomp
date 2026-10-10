# Debugging: divergence, hangs, spins, wedges

Load this when a run crashes, hangs, or behaves differently from the
emulator.

## Order of operations

1. Reproduce deterministically (state + trace, bounded with a timeout).
2. Decide what class the failure is: coverage miss vs behavioral divergence
   vs environment/tooling problem.
3. Apply first-divergence: find the earliest difference from a known-good
   reference and fix that; everything downstream is consequence.

## Finding a writer: the chained-traps recipe

When you need the code behind a memory effect you only observe as "this
changes" (a region redraw, a register commit, a buffer refresh):

1. **Where/when, cheaply** — per-frame value-diff trace the target region:
   which bytes change, in which frames, net direction. (Blind spots: zero
   writes and within-frame transients — see tooling pitfalls.)
2. **Mechanism** — if the target is fed by hardware DMA, arm a DMA watch on
   the region's first address (exact-address match as the transfer steps)
   and log channel/src/dst for attribution; abort-on-write traps cover the
   CPU-store case (and reveal fills the value trace cannot see).
3. **Who** — capture the instruction ring over that window (size the run so
   the window covers it; dense frames shrink the window — slice if needed)
   and scan for accesses: registers holding the address (`--reg-range`),
   filtered by cycle window; the entry record's LR is the caller.
   Repeat one level up until the driver's inputs (a struct/camera) appear.

Each level narrows: frames → instruction window → caller chain → input
data. Do not skip straight to step 3 when the mechanism is unknown — most
"who wrote this" hunts that stall are mechanism confusion (DMA vs CPU vs
the capture layer's own bugs).

## Redirects: keep the CPU mode coherent with the target

`runtime_dispatch`-family redispatching derives thumb/arm from the live
CPSR.T (not from the pc's low bit). A runtime side (resume helpers,
unwind paths, close handlers) that redirects a pc while the CPU carries a
stale mode will resolve the target in the wrong mode: table miss → self-
heal bridge → interpreter `Undefined` → loud abort, plus a misleading
`mode="arm"`/`mode="thumb"` miss proposal that must not be seeded. Snapshot
the expected mode at the point the flow was interrupted and force it on
the redirect.

## Present-in-place runners never unwind on vblank

When the host presents frames from inside the guest's yield hook
(present-in-place), a wedged guest can remain inside a single dispatch
forever — frames keep presenting, the screen stays frozen, and no new
`runtime_dispatch` occurs (so dispatch-boundary healing never runs).
Diagnose by pc sampling (churn inside a data region or gate loop) plus the
watchdog dump; the fix pattern for a pending runtime-side redirect is a
one-shot unwind: expose a `pending_resume()` predicate and have the yield
hook return true once while it is armed, so the runner redispatches and
the redirect can act.

## Catching corrupted transfers

- A `set_break_pc` park is a capture point: the ring dumped at the park
  (`GBARECOMP_BREAK_FP` pattern) ends with the instruction that transferred
  to the break pc, registers included — usable on surfaces without an
  fp_save command. Pair it with an engine-side entry dump
  (`..._BRIDGE_ENTRY_FP`) because the bridge's own interpreted records
  overwrite the ring within ~1 s of a miss.
- When a pc looks like garbage, search guest RAM for the exact value before
  theorizing: corrupted return targets are often verbatim stack words
  (a return popped an adjacent slot). `read_iwram` around SP is the cheap
  check.
- Before attributing a failure to BIOS/CPU semantics, validate the semantics
  in the accuracy reference (mGBA source is readable): the whole
  System-mode-SPSR / boot-trampoline story here turned out to match the
  reference exactly, and the real bug was engine-side corruption. Web docs
  (GBATEK, annotated disassemblies) plus emulator source settle these
  questions; cite them in a reference note rather than guessing.

## Ring walks: falsify the story, then diff the delta

The per-instruction ring is ground truth over every bookkeeping log: a
computed/printed "return target" can disagree with the PC the CPU actually
fetched next. When a control transfer looks wrong, dump the ring **at the
failure site** (a debugger call to the ring-save function works mid-run;
exit-time dumps are lost on aborts) and read the fetch sequence around the
hand-off — the real target is whichever PC the next record fetches. An
exception return that pops a guest-stack value can legitimately land inside
a *different* function's argument setup, several bytes off any known
boundary; disarm the landing site before theorizing.

Per-instruction rings can be dumped while the guest is alive
(`GBARECOMP_INSN_TRACE=1` + the TCP `fp_save <path>` command; no crash or
watchdog trip needed). Format: 16-byte header `<IIQ>`, then 80-byte
records `<Q18I` = cycles, pc, cpsr, r0..r12, sp, lr, r15.

- Falsify first: count the event under suspicion across the dump. ("The
  wait loop never sees its flag" turned into counting flag-reads with the
  expected value, exit-path entries, and flag set/clear writers — the
  story inverted in minutes: the loop exited 126×, and the only pre/post
  behavioral delta was new BIOS SWI activity.)
- Then diff: take two dumps bracketing the event and compare pc-frequency
  histograms; a pc population that appears or vanishes (e.g. new SWI
  paths) is the behavioral delta to chase in the disassembly.

## Spins, hangs, wedges

- A spin in **statically compiled** code is not a coverage gap; adding
  corpus entries cannot fix it. It is a behavioral divergence — compare
  against the emulator from the same state.
- Sample the guest CPU with a debugger launched **as the parent process**
  (`timeout -s INT` + interrupt-on-SIGINT). Attaching to a running process
  is often blocked by ptrace policy. Dump registers and the top of the
  stack; the loop's address, its operands, and its callers identify the
  subsystem. Be aware which globals the runner syncs (and when) before
  treating a dumped register block as the live state.
- Wait loops poll flags that interrupt handlers are supposed to set. If the
  flag never sets, inspect interrupt enable/mask state and the handler path
  before touching the poll loop.
- "Hang" can mean "extremely slow". Measure frame throughput (wall time of a
  bounded run) before declaring a wedge. One wedged frame and one
  pathologically slow frame look identical at 60 seconds.
- When a specific input triggers it, bisect the frames budget to the exact
  first wedged frame. That window is gold for the first-divergence hunt.
- Bound-check a hot loop before calling it a spin: read its exit condition
  and counters (a block looping with a count register that decrements
  normally is healthy engine work — mixers/copiers look spin-like under
  low-rate sampling; dumping PC samples alone misidentifies them).
- Trip/watchdog heuristics fire on healthy busy-waits too (games that poll
  their vblank flag instead of halting; frames/vblank counters advance
  during any spin because the PPU ticks per instruction). A trip is a
  pointer, not proof — the discriminator is whether the loop's exit
  condition ever becomes true.
- If the spin sits in an HLE/shadow-serviced area (audio mixer, timing
  model), suspect host-side model desync before guest logic.
- On devices, an audio output that restarts constantly (repeated platform
  log lines) destabilizes timing and is a prime suspect for wait-loop
  stalls — test the engine's direct-audio mode before deep-diving the
  guest.

## Memory growth triage (climbing RSS during a hang)

- **Classify before guessing.** Sample `/proc/PID/smaps` twice a few seconds
  apart: if the mapping *count* is unchanged and one region's RSS grows, the
  growth is in an existing mapping. A region whose range grows *downward*
  from a fixed end is the main thread stack → suspect **unbounded
  recursion**; a growing heap/anonymous region instead → allocation leak.
- **Heap leaks**: interpose `malloc/calloc/realloc` with a tiny `LD_PRELOAD`
  shim that counts bytes and captures `backtrace()` at thresholds (call
  glibc's `__libc_malloc` family directly to avoid `dlsym` recursion). Blind
  spots: `mremap`, `aligned_alloc`, direct `mmap` paths — wrap or
  syscall-trace those too if nothing shows.
- **Stack/recursion capture**: attaching is often blocked by ptrace policy —
  launch the process *under* gdb instead, then interrupt by sending SIGINT
  to *gdb* (in batch mode it stops the inferior and runs the next scripted
  command, e.g. `bt 60`). Hundreds of identical frames name the recursing
  function directly.
- In re-dispatch machinery, a guest loop that returns to the same address
  with a corrupted LR can recurse one host frame per guest hop — each hop
  may also do full MMIO catch-up (CPU burn plus tens of MB/s of stack
  growth). It is downstream of whatever corrupted the guest state: fix the
  root; meanwhile kill stalled sessions (memory frees on exit) and gate
  probes with write-triggered abort hooks that stop runaways within seconds.

## Split-function busy-waits nest host frames (finite-stack trap)

A spin whose back-edge crosses a generated-function boundary compiles to a
host call per iteration; while the wait's wake condition is unmet, those
frames accumulate and only unwind when the loop finally exits. Desktop runs
with an effectively unlimited main-thread stack, so this presents as RSS
creep; a finite mobile thread stack turns the same wait into a SIGSEGV
(deep tombstone: one return address repeated hundreds of times). The
frame-boundary unwind that would bound it may be suppressed by
present-in-place, whose depth guard counts only call-pushes, not
branch-calls.

- Read a stack dump: a repeated return address + nearest-symbol lookup
  names the recursing call site; growth rate over time tells you whether
  anything bounds it.
- Bound it at runtime: give the game thread a stack budget and unwind
  through the ordinary instruction-boundary yield path once a probe
  crosses it — gated exactly like the frame-present yield (never inside a
  live IRQ handler). This converts an eventual crash into a logged,
  bounded freeze.
- **Guard the guard**: that IRQ-handler gate silently disables itself if the
  handler depth counter ever sticks above zero (observed: a guest return ×
  vblank-IRQ interleave poisons it — the mainline then runs "inside" a
  handler forever, and the guard can never fire). When a guard does not
  fire despite obvious stack growth, print the depth counter at mainline
  PCs before blaming the guard. A second, critical threshold — fire even
  while nested, but only within the last fraction of the stack, where no
  handler could legally complete — keeps the safety net alive in that
  state.
- **Merge it at the source (the durable fix).** Flag the boundary block as
  an interior-resume candidate and extend the finder's alias roll-in to
  cover branch-target blocks that sit beyond a host's linear walk extent
  (e.g. a 2-byte back-edge behind the literal pool): roll the block into a
  host that directly branches to it, grow the host extent over it, and
  make the codegen lower a forward branch to any *labelled* in-body target
  to `goto` (not only backward targets — a forward conditional edge is the
  one a split loop actually takes). Verified shape: the dispatch table
  gains a resume entry for the block address at the host, the split unit
  disappears (corpus count −1), and the loop body contains no
  generated-function call except its exit block. Test the fix by
  objdump: `call`/`ret` pairs between the two halves must become internal
  `jmp`s. Without the roll-in, the candidate stays its own function and the
  per-iteration call pair returns.
- The nesting is a *carrier*: a wait that outlives its expected wake is a
  behavioral stall. Find why the wake never arrives (interrupt-mask state,
  callback stalls) before treating the spin itself as the bug.
- **Turn the nesting into a crash to get a backtrace.** The unwind-and-
  redispatch paths (steppable `--tcp`, frame-driven runs) nest too, and the
  worker thread's finite stack makes it SIGSEGV in seconds — far easier to
  root-cause than an RSS-creeping hang. Recipe: connect, `savestate_load`
  the state (plain `--load-state` is not applied by `--tcp`), drive the
  trigger with `set_keyinput`, `step` until it dies; run the process under
  `gdb -batch -ex run -ex bt --args <exe> … --tcp <port>` and drive it from
  a second process. Confirm exhaustion: `grep -c '^#'` ≈ thread-stack
  bytes ÷ ~60 B/frame; rsp lands at the thread-stack bottom; the repeated
  frame pair names the recursing split.
- Gate the repro: N clean pre-trigger steps + a crash at a fixed distance
  after the trigger means the *trigger* starts the unbounded spin — that
  window (tens of frames) is the first-divergence hunting ground.
- Same convergence, three faces: windowed present-in-place = nesting
  masked into a behavioral churn; unwind-and-redispatch = crash; finite
  mobile stack + guard = bounded freeze. Pick the face that instruments
  best — usually the crash.

## Abandoned handlers and corrupted SVC returns (exception-return containment)

Two containment layers for the same class — guest state corruption inside a
driven interrupt flow — both learned from a suspend→resume hang:

- **An IRQ whose handler never irets poisons the drive loop.** The guest
  keeps executing (the runtime adopts whatever runs next), so the depth
  counter sticks ≥1 forever, the mainline runs "inside" a phantom handler,
  and every IRQ-gated guard dies. Detect the abandonment (a ledger at the
  floor, or N vblank boundaries passed with no return) and **close the IRQ
  coherently**: restore the entry snapshot of the interrupt-enable/mask
  registers and the interrupt vector cell, then let the flow continue.
  A forced close is a recovery tool, not a fix — log it loudly, and
  root-cause what never returned.
- **A supervisor call's return can land at the wrong PC.** On hardware the
  SVC-return address lives in a banked register the guest cannot touch;
  a recomp that shares its register file can have that slot clobbered by
  stack churn before the BIOS epilogue (`pop {…,lr}` → `movs pc,lr`)
  consumes it — the exception return then resumes at whatever the clobber
  left (observed: an SWI inside a driven IRQ handler returned to the
  *IRQ-interrupted* PC instead of its own continuation). **Contain it with
  a continuation ledger**: record the return address at SVC entry, validate
  every SVC-mode exception return against the top entry, and on mismatch
  keep the recorded continuation (loud log). Deliberately do NOT repair
  the return register itself — the legal value comes from the banked
  restore, and writing the continuation there would self-loop a `bx lr`
  site. A soft reset that legally never returns leaves a stale entry:
  clear the ledger at every machine-reset/load origin.
- On-device, the same press flow that reproduces the hang on desktop
  (state load → trigger input) can be driven through the observe TCP
  (savestate load, key-register write) — the input *pipeline* (touch →
  pad → key register) need not be real to exercise the flow.

## On-device hangs without root (Android)

`debuggerd` is root-gated on production builds even for debug apps. Use
`run-as` same-uid access instead: `/proc/<pid>/maps` (thread stacks are
labeled `[anon:stack_and_tls:<tid>]`), `syscall` ("running" = userspace
spin), `/proc/<pid>/mem` via `dd` for stack dumps, `stat` utime/stime for
a real CPU rate. Symbolize dumped pointers against the *unstripped* build
with the NDK's llvm tools. A deep-stack dump plus the repeated return
address identifies the spinning call site; the frames above it name the
flow that entered it. Full recipe: this project's
`reference/dev-gotchas.md` § Android device forensics.

## The observe server: single client, and the savestate trap

The `--tcp-observe` surface serves one client at a time; a long-lived
watcher holds the slot, so disconnect it before other probes. Critically:
`savestate_save` is serviced by the runner at the *next present* — on a
stalled guest that never presents, the request never completes and wedges
the single-client server. On a suspected stall, probe read-only first
(registers, interrupt-enable and flag reads, miss report); never lead with
savestate. Keep a one-shot read-only probe script per project.

## Relocated-code re-entry (planted stubs)

Some engines copy tiny position-independent helpers (copiers, comparators,
getters) into RAM scratch — often *the current stack itself* — and call them
by computed address. Three failure shapes recur:

- **Misaligned re-entry**: the plant address moves between plantings (the
  stack shifts), so a suspended call that resumes at the old address lands
  one instruction off — the prologue is skipped and the body runs from its
  loop with whatever state remains.
- **Stale argument registers**: if the re-entry happens from another
  subsystem's context (task switch, interrupt, resumed state machine), the
  argument registers belong to the *current* code, not the interrupted call.
  Valid-looking args plus one nonsense arg — typically a loop sentinel like
  `0xFFFFFFFF` that the routine itself sets — is the fingerprint.
- **Runaway cascade**: a copier re-entered at its top recomputes its
  remaining count from the stale register and walks gigabytes, corrupting
  RAM; watch for a same-PC tight loop whose memory writes sweep a region.

Diagnosis: park at the *dispatched* pc (the unit entry — loop bodies may not
yield to the breakpoint) and dump ~0x100 bytes of guest stack from SP. A
stale frame holding the suspended operation (its descriptor fields, return
addresses into the original caller) plus the planted routine bytes proves
the re-entry story even when registers look random.

Mitigations, in order of honesty:
1. **Reconstruct the volatile state** in the canonical routine (e.g.
   remaining count = surviving loop register + 1) and run the canonical
   body — preserves semantics when the reconstruction is provably right.
2. **Clamp implausible arguments** (counts beyond any legitimate size) to a
   bounded no-op with a log line — turns hangs into degraded-but-continuing
   behavior as a stopgap while the true flow divergence is fixed.
3. Fix the upstream flow divergence so the stale re-entry never happens.

## Savestate-related wedges

- Host-side models (HLE mixers, shadow devices) that are not part of the
  serialized state desync after a load. Keep unqualified HLE/shadows off by
  default, and mark any subsystem that refuses to serialize.
- Bisect state-restore vs game data: replay the same inputs from a fresh
  boot + in-game save. If that works, the wedge lives in the restore path,
  not in the save data.
- Preserve the repro state immediately — play sessions overwrite slots.
  Archive copies before running anything that could overwrite.

## Battery-save flows (scan / validate / write)

Save subsystems are a top divergence habitat — they mix I/O, checksums, and
multi-record state, and their failures cascade into RAM corruption:

- The game usually keeps **redundant records** (mirrored copies, monotonic
  counters, per-record checksums). It scans them, validates (magic compare,
  then checksum-field blanking + checksum recompute over the record), picks
  the newest, and only then acts. A divergence anywhere in that scan turns
  record fields into garbage descriptors, and a bulk copy called with a
  nonsense length becomes a multi-gigabyte runaway that sweeps RAM.
- **Signature to recognize**: a move/copy routine invoked with `source` equal
  to the bitwise complement of `count` (or any swapped/complemented argument
  pair) means the caller consumed garbage record fields — hunt the record
  decode, not the copier. Also watch for "mangled high-byte" pointer families
  (a plausible low half, corrupt region bits).
- **How to compare**: capture the flash read/move driver's call sequence at
  its common call site on both engines, replaying the same trace. Park on the
  call PC and log the argument registers plus LR — at the park, LR is still
  the driver's *caller*, which identifies the flow stage. Diff the sequences:
  the first mismatching call localizes the divergence stage.
- **In-place validation evidence**: on the reference emulator, watch the
  record buffer over the validation window — the game typically blanks the
  checksum and stamp bytes in its working copy before recomputing. If your
  engine's copy still holds the un-blanked bytes later, validation diverged
  inside that window.
- A **foreign-but-valid save** (another region's release, a save-tool file)
  is a free stress test of the scan path: verify its structure first
  (redundant copies nearly identical modulo counters/stamps; the emulator's
  game accepts it), then use it as an oracle-compared repro.
- Keep a pristine copy of any test save; these flows rewrite the file.

## Crash classes worth naming in your docs

| Symptom | Meaning |
|---|---|
| Dispatch miss, bridged cleanly | Normal coverage gap; feed the corpus |
| Bridge/watchdog abort with instruction count | Bridge stop-contract limitation; harvest cache, seed the path static, retry |
| Interpreter NotImplemented/Undefined at a PC | Lowering gap in the framework itself; report upstream |
| Static code spinning (no abort) | Divergence class; oracle-compare, don't add coverage |
| Copy/move loop with an enormous count, RAM swept | Upstream computed garbage (often save-record decode); oracle-compare the scan/validate path |

## Evidence discipline

- One canonical log per investigation in a gitignored logs directory.
- State the sync point of any claim ("per the run at frame N, VBlank M").
- Record the one-line repro recipe in the decision log at the moment you
  find it; reconstruction later is unreliable.
