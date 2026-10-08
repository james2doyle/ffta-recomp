---
name: gbarecomp-recomp-playbook
description: Portable field playbook for gbarecomp-family static recompilation game projects (retail ROM to a native PC binary driven by a hand-curated function corpus plus runtime self-heal). Covers the playtest-to-healing coverage loop, miss triage into config entries, savestate and input-trace reproducibility, crash-safe proposal harvesting, seed-until-static acceptance, emulator oracle differential testing, regression gates, and session discipline. Use when working on a gbarecomp-style recomp repository: auditing misses, building or running the replay and verification harness, triaging crashes/hangs/wedges, measuring coverage, or onboarding a contributor or agent.
---

# gbarecomp Recompilation Playbook

Portable practice from running a gbarecomp-style project to a playable state.
Replace "the game" with yours, "the config" with your curation file, "the
runner" with your built binary. Nothing here depends on a specific game or
helper script.

**Vocabulary.** A **miss** is guest code reached at runtime that has no
statically recompiled function. The runtime **bridges** it with an
interpreter, **heals** it by compiling it into a native cache (used from then
on), and records a **proposal** for the offline corpus. The project converges
by converting proposals into reviewed, evidence-bearing config entries until
every executed path is **fully static** (zero dispatch misses, zero
interpreted instructions).

## The core loop

1. **Play** with the instrumented launcher; the session records an input
   trace and savestates, and archives the previous session's artifacts.
   When hunting a live-only hang, play in windowed-observe mode with the
   frame-stall watchdog attached (see `references/reproducibility.md`).
2. **Close.** The proposal file is journaled live as misses occur — durable
   across hung/killed closes; a clean exit rewrites it with final counts.
   Harvest the heal-cache unit filenames as a second source.
3. **Merge** reviewed proposals into the config, with disassembly evidence in
   every note. Never auto-write the config; never edit generated code.
4. **Resolve until static.** Strict-replay the session; seed the first miss
   through a temporary overlay; rebuild; repeat until no miss remains.
5. **Verify.** Cold regenerate, build, run the golden-hash gate, then one
   final strict replay of the session as the acceptance — and keep it: add
   the route to the project's one-command regression gate over frozen
   fixtures, and write a named regression test for every bug fixed
   (`references/verification.md`).
6. **Commit** config + a dated decision-log entry for the batch.

**Breadth vs depth.** While the corpus is young, playing is the primary
discovery tool; once per-session merges flatten to tens of units, take the
cheap breadth lever instead — enable the static pointer/table harvest in one
config flip (golden gate + strict replays as review) — and keep playing for
what scans cannot supply: runtime divergences, runtime-constructed code, and
acceptance evidence. Details in `references/verification.md`.

## Invariants (never violate)

- Only a strict replay with zero dispatch misses and zero interpreted
  instructions counts as done for a path. Nothing weaker counts.
- Audits and acceptance runs are cold-cache: the self-heal cache changes
  which PCs dispatch and makes warm-run miss lists unstable.
- First divergence only: when runner and emulator disagree, root-cause the
  earliest difference; everything downstream is consequence.
- Three-strikes rule: a step failing inexplicably three times → stop, write
  the state to the decision log, report. Do not thrash.
- Game-derived artifacts (ROMs, saves, states, dumps, logs) never go into
  version control.

## Task router

Load the reference for the task at hand; do not read them all at once.

| Task | Reference |
|---|---|
| Turn miss PCs into config entries (boundaries, switches, tables, RAM code) | `references/miss-triage.md` |
| Sessions: savestates, input traces, replay semantics, crash harvesting, live-session watchdogs, playtest ergonomics | `references/reproducibility.md` |
| Coverage numbers, lenses, breadth strategy, seed-until-static automation, regression gates, oracle diffs | `references/verification.md` |
| Crashes, hangs, spins, wedges, writer hunts, recomp-vs-emulator divergence | `references/debugging.md` |
| Harness tools to build, pitfalls that cost hours, offline state census, engine-hook lifecycle, decision-log and docs discipline | `references/tooling-and-pitfalls.md` |
