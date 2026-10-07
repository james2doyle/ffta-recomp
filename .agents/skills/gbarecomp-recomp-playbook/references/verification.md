# Verification: coverage lenses, resolve automation, gates, oracle diffs

Load this when measuring progress, automating the seed-until-static loop, or
comparing against an emulator.

## Coverage: three lenses, one bar

| Lens | Means | Caveat |
|---|---|---|
| Executed path (strict replay of sessions) | ground truth: what the game actually ran | narrowed by how much you played |
| Static reach (whole-image scan trial) | upper bound of the function finder | depends on scan bounds and seeds |
| Speculative pointer/table harvest trial | directional proxy for pointer-reachable code | includes unreachable code; never a goal |

The **bar is fully static on executed paths.** Proxies are steering aids; do
not chase proxy percentages. Denominators differ and no ground-truth
function inventory exists — say so when reporting. Refresh the numbers after
every merge and keep them in the docs.

## Seed-until-static resolve loop

Automate the converged half of the loop:

```
for attempt in 1..N:
    write temp overlay = reviewed config + accumulated seeds   # never auto-edit the real config
    cold regenerate + build
    strict replay of (trace [+ start state]) with the session's frames budget
    if no dispatch miss:  done — acceptance reached
    seed the first miss (containing start, else the PC itself) into the overlay
    append the seed to a proposal file for later human merge
```

- After convergence, review the proposal file and merge it into the real
  config; run a normal cold cycle as the final acceptance (the overlay is
  throwaway).
- Strict replay surfaces PCs the interactive session never touched (input
  timing differs slightly). Seed them too.
- If the session reloaded a state mid-way, replay each monotonic segment
  separately from the same start state; both must pass.

```python
def resolve_until_static(cfg, overlay, trace, state, frames,
                         write_overlay, rebuild, run_strict, first_miss, max_iter=25):
    seeds = []
    for _ in range(max_iter):
        write_overlay(cfg, overlay, seeds)        # temp overlay only
        if not rebuild(overlay):
            raise SystemExit("build failed")
        out = run_strict(overlay, trace, state, frames)   # capture stdout+stderr
        pc = first_miss(out)                      # regex the run's miss line
        if pc is None:
            return seeds                          # fully static: acceptance
        seeds.append(pc)                          # or its containing start
    raise SystemExit("did not converge")
```

Adapt the miss-line regex to the framework's actual abort wording — read its
source or docs rather than guessing.

## Regression gates

After **every** config change: cold regenerate → build → golden-hash gate →
strict acceptance replay.

- **Golden gate:** a fixed-input window (boot, attract loop, demo) recorded
  once, hashed on stable frames. The hash must not change across merges; if
  it must, re-pin it as a deliberate, reviewed act with a decision-log entry.
- Keep acceptance replays bounded with timeouts. Prefer many short strict
  replays over one heroic long run; a strict run exits early on the first
  problem, so it is cheap when things are right.
- Keep one canonical acceptance log per session in a gitignored logs
  directory so the claim stays citable.
- Seeds imported from community decomp projects are for naming/coverage
  only; they must not change behavior. The golden gate guards this.

## Oracle differential testing

Pair the runner against a real emulator fed the same input script.

- **Synchronize on hardware events** (e.g., VBlank counts), never raw frame
  indexes. Sync on events, debug regions, not pixels.
- Both engines park at similar points but service interrupts at different
  phases; a fixed one-handler offset in restored state is expected and
  benign. Use per-frame state **deltas** for divergence detection and
  stable frames for golden hashes.
- Compare memory **regions** byte-wise first; screen pixels later (latched,
  completed frames often still compare at the same index even when the
  CPU-side offset exists).
- Writes are the ground truth to diff; the screen is a symptom.
