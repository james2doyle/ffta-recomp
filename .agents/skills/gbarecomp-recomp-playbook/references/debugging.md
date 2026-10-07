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

## Savestate-related wedges

- Host-side models (HLE mixers, shadow devices) that are not part of the
  serialized state desync after a load. Keep unqualified HLE/shadows off by
  default, and mark any subsystem that refuses to serialize.
- Bisect state-restore vs game data: replay the same inputs from a fresh
  boot + in-game save. If that works, the wedge lives in the restore path,
  not in the save data.
- Preserve the repro state immediately — play sessions overwrite slots.
  Archive copies before running anything that could overwrite.

## Crash classes worth naming in your docs

| Symptom | Meaning |
|---|---|
| Dispatch miss, bridged cleanly | Normal coverage gap; feed the corpus |
| Bridge/watchdog abort with instruction count | Bridge stop-contract limitation; harvest cache, seed the path static, retry |
| Interpreter NotImplemented/Undefined at a PC | Lowering gap in the framework itself; report upstream |
| Static code spinning (no abort) | Divergence class; oracle-compare, don't add coverage |

## Evidence discipline

- One canonical log per investigation in a gitignored logs directory.
- State the sync point of any claim ("per the run at frame N, VBlank M").
- Record the one-line repro recipe in the decision log at the moment you
  find it; reconstruction later is unreliable.
