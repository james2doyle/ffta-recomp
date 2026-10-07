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
