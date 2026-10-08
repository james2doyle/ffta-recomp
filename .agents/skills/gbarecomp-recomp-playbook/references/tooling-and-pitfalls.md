# Tooling to build, pitfalls, and project discipline

Load this when setting up the harness or keeping the project maintainable.

## Tooling checklist (build these early, keep them thin)

1. **Boundary scanner** — for each miss PC: containing start, prologue
   evidence, neighbors. (Snippet in `miss-triage.md`.)
2. **Crash harvester** — healed PCs from cache filenames. (Snippet in
   `reproducibility.md`.)
3. **Trace splitter** — monotonic segments from a session trace. (Snippet in
   `reproducibility.md`.)
4. **Resolve driver** — seed-until-static loop with temp overlay + proposal
   output. (Snippet in `verification.md`.)
5. **Change cycle** — one command: cold regenerate, build, golden gate,
   optional crash harvest.
6. **Coverage reporter** — the three lenses, machine-readable plus a table.
7. **Oracle differ** — synchronized region compares with a bounded report.

Every tool is a small wrapper around the framework CLI plus one insight (a
filename convention, a regex, a split rule). Avoid gold-plating; prefer one
command per frequent step and record it in the README.

## Session close-out checklist

Run this after every play session; it is the whole loop in order.

1. Harvest first (before anything touches the build): proposal file if the
   exit was clean, cache filenames if it crashed.
2. Classify the PCs mechanically (start / interior / none); check the trace
   for backward jumps and split into segments if reload happened. If more
   than one session ran since the last close-out, attribute units by
   heal-cache mtimes and accept each session separately — the per-launch
   state+trace archives make that mechanical.
3. Merge one dated batch; evidence in every note; dedupe against the config
   and earlier batches; never auto-write.
4. Resolve (each segment) until fully static; fold any resolve-added PCs
   into the same batch.
5. Cold regenerate, build, run the golden gate.
6. Log a strict acceptance replay per segment to a canonical file.
7. Refresh the coverage numbers and update status docs.
8. Commit config + docs + one dated decision-log entry with real numbers.

## Pitfalls that cost hours

- Warm-cache audit runs (unstable miss lists). Cold only.
- Absolute-vs-relative frame budgets after loading a state.
- Guessing a function start instead of seeding the miss PC itself.
- Treating a switch's case run as a data table before checking interiors.
- Editing generated output; auto-merging proposals; chasing proxy coverage
  percentages.
- Unbounded runs without timeouts; stray runner processes from earlier
  commands skewing measurements.
- Game-derived bytes in version control.
- Assuming "hang" = crash; assuming "static code ran" = "static code correct".
- Forgetting that a clean strict replay of one session says nothing about
  paths the session never executed.
- Assuming a live session's bridge list is complete: strict replay regularly
  catches 1–2 extra PCs per session — budget a resolve iteration for them.
- Trusting savestates across builds when bisecting: rebuilds can move what
  the state maps to; regenerate the state when in doubt.
- Letting the playtest loop run for hours without closing a batch: smaller
  sessions converge faster and make bisecting trivial.

## Decision log and docs discipline

- One dated entry per session/batch in a decision log: action, result,
  conclusion. Include repro recipes for anything left open.
- Keep the README runnable for a fresh agent: setup, exact commands, the
  loop, invariants, and current status with real numbers.
- Framework docs (principles, debug guides, config schema) supersede your
  notes on conflict — read them before debugging sessions and cite them.
- Acknowledge corrections explicitly (e.g., "known hard spot" reposited by
  evidence) so stale folklore does not survive in the docs.
- Commit after every milestone; a clean tree with a dated log beats a
  perfect memory.
- **Breakpoint commands over a debug socket are usually yield predicates,
  not one-shot traps.** After a hit you must *clear the break, step one
  instruction, then re-arm*; stepping (or re-arming) without clearing looks
  like an infinite loop of identical fake hits parked on the same PC.
- **A yield predicate cannot fire mid-block.** A break set on a PC *inside*
  one compiled block silently never triggers there, so any count it produces
  is a lower bound. Cross-check surprising breakpoint counts against the
  instruction ring before concluding divergence — "engine A made 1 read, B
  made 4" can be pure instrumentation artifact.
- **Prefer the instruction ring for per-instruction truth.** An always-on
  ring of the last few million instructions (window ≈ the last ~120 frames;
  size the run so the event is in-window) answers "did PC X run, and what
  did the flow do around it" with no breakpoint mechanics. Query by
  PC/register/cycle. Two cautions: the window moves with run length, and the
  same input applied by a stepped server vs a batch replay lands on
  *slightly different frames* — pick one regime per investigation and never
  compare absolute frame numbers across regimes.
- **Abort-on-write watchpoints are the sharpest tool for runaway/divergence
  onsets.** Gate by address, min-frame, and exact value so the abort fires on
  the *corrupted* write, not the legit one; pick the corruption's FIRST
  touched byte as the address so the handler's trailing event window still
  contains the entry into the bad loop. Abort handlers dump the last N trace
  events (default small; raise it — it clamps at the ring capacity, a few
  thousand events). A long runaway flushes the window: capture the onset,
  don't chase the aftermath.
- **Long routes (tens of thousands of frames) are probe-able in minutes:**
  drive frames in N-frame chunks between trace events instead of one frame
  per round-trip. For hot target PCs, arm the breakpoint *late* (just before
  the window of interest) so legitimate calls don't drown the probe; add
  stop-on-first-hit and dump ~0x100 bytes of guest stack from SP at the park
  — parked frames lose their caller at the PC level, but the stack keeps it.
- **Keep the machine idle during lockstep/timing probes.** A concurrent
  build or regeneration slows both engines and can trip the tool's command
  timeout — which then looks exactly like the stall you are hunting. Check
  for stray compiler jobs before trusting a "timed out" verdict.
- **External saves:** emulator-native raw images for the same chip type are
  interchangeable; community formats are often compressed containers
  (header + size fields + CRC + packed payload). Unpack to the raw chip
  size, verify the container's own CRC, and byte-compare against any second
  export of the same save before trusting the conversion.
- **Loading a non-default battery save into an instrumented launcher:**
  pass the save argument *last* so it wins over the launcher's built-in
  default (verify by the runner's "save loaded" log line), and always work
  on a copy — save flows rewrite the file.

### Debug-port memory reads on loaded states

A load-state run restores registers + IWRAM immediately, but **EWRAM is
repopulated by the scene over the following frames** (observed: 0 nonzero
bytes at +60 frames, 730 at +300, ~5.5k at +600 after a battle-state load).
TCP/board reads taken too early return believable zeros — wait several
hundred frames (or until the scene visibly runs) before trusting EWRAM
contents on a loaded state. Fresh-boot reads and IWRAM reads are reliable
immediately. A fresh boot shows live EWRAM within seconds — use that as the
control when a read looks suspiciously empty.

### Live sessions: window + debug port (`--tcp-observe`) and the stall watchdog

Plain `--tcp` is **structurally headless** (its branch returns before window
init) — it can never show a window. The windowed debug combo is
`--tcp-observe <port>`: reads, touch commands, memory reads, state hashes,
queued savestates — **no stepping**. The observe listener serves a handful of
sequential clients and then stops accepting (observed: refused after one
long-lived watcher disconnected), so use exactly **one long-lived watcher**
per session and keep ad-hoc queries off its port.

Recipe: `tools/livewatch.py <port>` (poll registers/state_hash/frame every
2 s; on ~10 s of no frame-counter progress — a real stall; pc-stalls with a
moving frame counter are legitimate waits — snapshot regs + hash + an IWRAM
stack window while the game is frozen). Consult the frozen registers *before*
killing anything: this converts "it hung again" into a pc + stack + caller
chain without any replay. The frame counter is the hang signal; the pc is
the diagnosis.

### Coverage breadth: script/event crawl + literal-pool triage

- Game script bytecode usually carries **no code pointers** (opcodes only);
  scanning script bytes for ROM-address-looking u32s is noise (operand
  collisions). Don't seed from it.
- Data tables full of code pointers split into two classes: compiler
  **switch tables** (case dispatch — tightly clustered, often repeated
  targets that do NOT start with a prologue) and real **callback/handler
  tables** (targets = function starts). Discriminator: the **exact
  first-instruction test** — the halfword at the target must be
  `push {..., lr}` (thumb 0xB5xx). Loose "scan forward for a prologue"
  checks get fooled by the next function in line.
- Strongest breadth candidates: diff a **speculative literal-pool regen**
  (trial config, cold cache, scratch dir) against the live corpus, filter to
  strict-push starts, then seed in small scoped batches (one region/family
  per batch) with evidence notes. The attract gate + strict route replays
  arbitrate — one bad interior split can regress a route. Cascades are
  common: a handful of island seeds can pull in hundreds of units.

Refinements from lifting an entire pool: (1) membership = the dispatch
table's **per-row addresses** (starts AND resume points); name-based
extraction under-reports and leaks emitted functions back into the candidate
list. (2) A candidate must be a trial **primary start** (resume=0 row) — a
resume point is an interior pc. (3) Scope batches by region so any gate
failure bisects cleanly; cascades can be huge (15 seeds -> +523; 173 seeds ->
+4,312, ending within 77 units of the whole speculative pool).

TCP-mode gotchas (cost real probes): `--tcp` does NOT process
`--load-state` (silently skipped, no savestate line) — load over TCP with a
`savestate_load {path}` command. And when experimenting with the wide PPU
path (`GBARECOMP_WS_WIP=1 --view-width N` works headless with no opt-in):
a field BG tilemap narrower than the view does not error — the renderer
WRAPS its edges, producing margins that look plausible but are wrong
(mirrored edge columns). Verify margin content against the game's true
extent before believing a wide render.

Runner shutdown: the window-close path can hang in teardown (observed:
debug listener closes, then an XInput poll hits the destroyed window and a
joinable thread destructor raises `terminate called without an active
exception`; the process lingers). The TCP `quit` command is the reliable
shutdown — keep a one-line helper (connect, send `{"cmd":"quit"}`) and
prefer it for scripted sessions. SIGTERM may be swallowed. Verify a clean
exit by checking that the process leaves within a few seconds and the
wrapper's archive/flush steps ran.

Finding game state and the code around it (portable): (1) save a state
before/after an action and byte-diff the container - changed fields reveal
the variables (camera, counters, flags); (2) query the FP ring for
instructions whose registers hold an address/value (`--reg`, `--reg-range`)
to find both readers/writers and generic helpers; (3) trap writers with an
abort-on-memory-write env (+ runtime trace) for the caller chain - RAM/VRAM
works, IO registers may not (guest-DMA and write-observer paths can bypass
the capture ring entirely); (4) watch DMA destinations explicitly when the
guest programs hardware DMA. Static BL scans miss pointer-table entries;
prefer runtime traps.

Name discoveries in the durable index as soon as their role is verified:
seed/symbol files propagate names into generated code (grep-able forever),
data-symbol files carry RAM-struct names + a field comment block, and a
reference doc holds the deep detail with probe recipes. Cross-link the
three. This turns one session's archaeology into the next session's
starting point instead of a repeat expedition.
