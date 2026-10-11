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

## Coverage strategy: breadth first, proof by playing

The speculative pointer/table trial is not only a lens — it is a **harvest
lever**. Once per-session merges have flattened to tens of units (ordinary
discovery has converged), flip it on for real:

1. Enable the harvest in the config; cold regenerate + build.
2. The golden gate must pass at the **same hash** — to that point the added
   seeds have changed zero observable behavior (the attract window is the
   review). If the hash moves, curate the seeds down instead.
3. Strict-replay the load-bearing routes as acceptance.
4. Expect a large one-time corpus jump (order: +10%); every subsequent
   build carries it.

Playing is what remains for the three things no static scan can supply:

- **Runtime divergences** — corrupted calls, bad counts, hangs, wedges.
  These exist as behavior only; sessions surface them.
- **Runtime-constructed code** — RAM-resident copies, stack-planted stubs,
  interrupt dispatcher spans. No literal points at them; they need live
  capture plus disassembly.
- **Acceptance evidence** — a route is proven only by its strict replay of a
  real session. Sessions *are* the acceptance corpus.

Operational order: play early to build the initial corpus and flush out the
big bugs; when yield flattens, take the breadth lever; then play again for
verification and each new subsystem.

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
- Typical convergence is **0–2 iterations**; a session that breaks into new
  code can chain several more, one per newly reached entry point (each a
  clean start, not a retry). Persistently missing the *same* PC usually
  means a wrong entry (bad boundary or wrong ISA mode), not bad luck.
- Strict replay surfaces PCs the interactive session never touched (input
  timing differs slightly). Seed them too.
- If the containing start is already in the config and an interior still
  misses, seed the interior PC directly — a seeded start does not guarantee
  the walker covered every interior the session reached.
- **Stop on out-of-range miss PCs.** A "miss" PC outside the addressable
  code image (or in hardware I/O space) means the replay itself diverged —
  a behavioral bug, not a coverage gap. Abort the loop with a clear message
  and fix the divergence; never seed such a PC into the overlay.
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
- **Route-level gates for harvest-scale changes.** A short golden window
  (boot/attract) cannot catch regressions that only appear deep in a
  session. Changes that add *speculative* coverage (whole-image pointer or
  table harvest) need a **long strict replay of a real route** as a gate —
  and watch that replay's RSS. The failure we hit was not a wrong pixel: a
  speculative split created a dispatchable **interior** entry inside a
  guarded routine; the route resumed into the unguarded interior, bypassed
  the entry check, and ran away (30+ GB RSS). When a harvest changes route
  behavior: **revert first**, then design the interior-split policy (extend
  guards to interior roots, or exclude the span from speculation) and the
  route gate, then re-trial. Entry guards (function-entry hooks) never cover
  interior entries — plan for that explicitly.

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
- Replaying a recorded input trace from boot keeps engines in lockstep only
  until the first UI/RNG divergence. Menu-heavy sessions drift silently —
  one side takes a different branch and every later screen differs. For
  mid-session states, navigate the oracle *to* the state by screenshots
  instead of trusting trace replay.

## External saves as verification material

Before using a found/downloaded save as a repro or regression fixture:

1. **Shape**: file size equals the chip size (e.g. 64 KiB flash); the
   redundant record copies differ only in counters/stamps/checksums.
2. **Container**: if it came packed (community format), unpack, check the
   container's CRC/sizes, and prefer a raw export when one is available —
   byte-compare the two when both exist.
3. **Acceptance**: the emulator's game itself must accept it (slot list
   renders, load completes). That is stronger evidence than any checksum
   you reverse-engineer — but if the emulator rejects it, stop: you are
   debugging a corrupt file, not a recomp divergence.
4. Then diff *both engines* on the same save + trace: any behavioral
   difference is by definition a divergence (the file is identical), and a
   valid-but-unusual save exercises scan/validate paths your own playthrough
   never reached.

## One-command regression gate (lock the "good spot" in)

When a project reaches an all-green state, freeze it as a single gate
command so later changes cannot regress silently:

- **Layer the checks by cost**: fast host tests (unit tests + data-format
  validators) first, then expensive end-to-end gates (golden-frame hash,
  strict route replays) — early failures surface before slow work runs.
- **Freeze route fixtures** (input trace + save/state + frame budget) in a
  dedicated directory, and pin every binary-content input with a hash
  assertion. A fixture that silently disappears or gets overwritten turns
  the check into a vacuous pass — this happened (a /tmp save copy was
  cleaned up, so a strict route "passed" for days without ever running the
  flow it existed to guard). Fail loudly when a fixture is missing or its
  hash changed. Keep the gate's copies **separate from files normal play
  overwrites** (savestate slots): copy the states under the dedicated
  directory so ordinary use cannot invalidate the gate, and define
  missing-vs-changed semantics per fixture class — environment-dependent
  fixtures (local states) skip *with the reason surfaced through the
  aggregate gate*; repo-shipped fixtures (committed input traces) hard-fail.
- **Unit-test the custom layer**, never the generated code: semantics of
  hand-written hooks/fixups, and one named regression test per fixed bug
  (e.g. "a mid-run boundary crossing must fall through, not re-enter").
- **Validate data formats with the game's own algorithm where reversible**
  (save checksums, compression), anchor the implementation against every
  known-good sample, and test the validator against crafted corrupt inputs
  so it provably fails on damage.
- Make the gate one command (`tools/check.py [--fast|--only NAME]`) with
  per-check PASS/FAIL lines and a non-zero exit unless everything passes.
  A comma-separated `--only` subset of the no-private-material checks makes
  a fork-safe CI tier from the same gate (see below).
- **Concurrent checks need per-run isolation — including engine temp
  files.** A parallel gate that isolates dump/save/coverage paths can still
  race on engine-managed state (observed: two launches collided on a shared
  `state.toml.tmp`; the loser's retry deleted the winner's published file).
  Stress the harness with N parallel runs, then fix the shared path at the
  engine level and export it as a patch rather than serializing by default.
- **Split CI by what may leave your machine.** Public tier (forks
  included): host unit tests + patch integrity — patch checks
  forward-validate against the pristine submodule, so they run on a fresh
  clone with no game data. Private tier: everything needing the game image
  or fixtures, on a self-hosted runner with the material pre-placed (or a
  token-gated private bundle), trusted events only — a PR job on a runner
  that can read the ROM is an exfiltration path. Install the tier's tool
  deps explicitly on the runner (observed: the Python unit tests import a
  tool that needs capstone — local runs pass via `.venv`, so the gap only
  shows as an import abort in CI; pin the wheel to the `.venv` version).
- **Give device/emulator-facing gates a device-free CI tier.** Most of a
  device gate's failure surface is testable without the device: assert the
  config contract that breaks silently (identity pins consistent across
  build files, payload/default-state files the runtime persists, no
  private/binary artifacts tracked) and self-test the gate script itself by
  putting a fake external tool (`adb`) first on `PATH`, selected by a
  scenario env var — the clean scenario must pass and pull evidence; miss,
  crash, missing-input and stuck-launch scenarios must fail with the right
  assertion. Keep boot/rendering/perf acceptance on real hardware.
- **Drive device acceptance over the observe/debug surface, not synthesized
  touch.** A boot-health gate asserts liveness only; the flows that
  historically broke a port (a save→suspend→resume chain, a specific press)
  can be driven end to end over the runner's debug TCP: stage a savestate
  into app-private storage (`adb push` + `run-as cp`), load it (the queued
  load command), write the key register (the input register write command),
  assert frame advancement (the run-status/ping surface — check which
  counters the observe context actually wires; the free-run context may
  wire none) and scan the app log + crash buffer for the anomaly markers.
  The OS-lifecycle contract (background→flush+suspend state+marker, kill,
  relaunch auto-resume, marker cleared) is adb-drivable the same way —
  `input keyevent HOME`, `am force-stop`, `am start` — and shares machinery
  with the save/resume flows, so gate it explicitly. Caveats that cost an
  evening: adb-synthesized *taps* are OS-filtered on some ROMs (swipes
  pass, taps never dispatch — verify at the launcher before blaming your
  app; zero lines on the touchscreen's evdev node during `input tap` is
  the signature), private-storage reads return *binary* (a flash battery
  save) — use `exec-out` and binary modes, or the hash-compare of a UTF-8
  decode dies; and a kill closes the observe socket — reconnect with a
  fresh socket per attempt, not the dead one.
- **Guard the shipped artifact, not just the build.** A post-build pass over
  the packaged binary catches what source checks cannot: payload files must
  byte-match the staging inputs; private/test embeds must hash-match the
  pins (and distributable builds must embed none); the per-ABI library
  inventory and manifest facts must match the build config; and duplicate,
  stray, or oversized entries must fail (incremental repackaging can leave a
  junk blob — observed once as 67 MB vs the normal 37 MB). It runs on the
  host after a build; keep it opt-in when CI cannot produce the artifact.
- **Entry-list audits miss slack: bound the container, not just the
  inventory.** The same incremental-repackaging class has a second form
  observed 2026-10-09: ~30 MB of *stale bytes in the slack between the last
  zip entry and the signing block* — a whole prior build's entry data left
  in place (stale local headers + central entries in the gap, compressed
  entropy). Invisible to any `infolist()`-based check: the entry walk sees
  only the ~15 live entries and passed 8/8 on the bloated APK. Bound the
  file size by the sum of the compressed entries + header/signing overhead
  (+ a small slack allowance); on violation, diagnose the gap byte-wise
  (the first stale local header names its prior-build filename). Remedy:
  clean the packaging output directory and rebuild — the artifact must come
  back within overhead of the entry sum.
- **Wrap the verified fresh-clone recipe in one idempotent bootstrap
  script.** Keep it stdlib-only on the system interpreter (it runs before
  the project venv exists), make every step detect completion (submodules,
  venv + tool deps, patch apply-check, tool build, BIOS/corpus mtime
  gates, host build), hash-verify the user-supplied dumps with actionable
  hints and fail before any long build, and keep the manual route as a
  reference document. A recipe you validated once by hand should be
  executable by every newcomer the same way.
- **Gate your submodule patches if you keep them.** Each patch must apply
  to the pristine pin (or be already applied and reverse cleanly) — and
  exports must be made with `--no-pager --no-ext-diff --no-color`: diff
  output run through a formatter is wrapped and no longer applies
  ("No valid patches in input" — this cost a fresh-clone morning).
  Verify by glob (`*.patch`) so new patches are covered automatically.
- **Game-presentation expansions need default-off evidence.** For a
  widescreen/expanded view: the golden hash holds at the default width, the
  expanded frame's central native region is pixel-identical to a faithful
  render, margins decode to sane content (not wrap, not policy black), and
  a stale env/CLI request cannot silently enable a feature the build
  disabled. Run the matrix at **≥2 widths**, and when the engine's internal
  field model is wider than the visible window, fill margins by sampling its
  authored columns — never by extending or synthesizing content. Cover
  transitions and motion: margins ride the same compositor (they dim with
  fades — gate "margins never brighter than the center" instead of
  special-casing), and an idle-vs-action stale guard proves margins
  refresh. Headless automation cannot see windowed-only behaviors
  (resize-driven view) — say so in the docs and eyeball those manually.
