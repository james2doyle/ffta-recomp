# Debugging: divergence, hangs, spins, wedges

Load this when a run crashes, hangs, or behaves differently from the
emulator.

## Order of operations

1. Reproduce deterministically (state + trace, bounded with a timeout).
2. Decide what class the failure is: coverage miss vs behavioral divergence
   vs environment/tooling problem.
3. Apply first-divergence: find the earliest difference from a known-good
   reference and fix that; everything downstream is consequence.

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
- If the spin sits in an HLE/shadow-serviced area (audio mixer, timing
  model), suspect host-side model desync before guest logic.

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
