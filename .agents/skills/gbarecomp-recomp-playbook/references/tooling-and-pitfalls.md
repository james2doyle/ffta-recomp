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
