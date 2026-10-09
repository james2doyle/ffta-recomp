# Reproducibility: savestates, traces, crash harvesting, playtest ergonomics

Load this when setting up or debugging the capture side of the loop: making
sessions deterministic, replaying them, recovering evidence after a crash.

## Session artifacts

Keep sessions cheaply reproducible with **savestate + input trace** pairs.
Archive both on every launch; a play session overwrites its slots, so the
archiver is what makes "the previous session" recoverable. Keep a battery
save too — some bugs only reproduce through the game's own save/load path.

**Proposal-file lifecycle.** The miss-proposal file is *journaled live*: it
is rewritten (atomically) the moment each new miss is recorded, so a hung or
killed close no longer loses it; a clean exit rewrites it with final counts,
and a zero-miss session leaves the previous file untouched (stale, not new).
Archive the proposal at every launch next to state+trace, and treat the
**heal cache as a second durable store**: it accumulates across sessions and
"units not yet in the config" is always the authoritative to-do list.

## Replay semantics to verify once, then never assume

- **Frame budgets after loading a state** usually mean N frames *from the
  state*, not an absolute counter. Measure before any bisect; wrong
  assumptions cost hours. The budget must also reach the **last replay
  event** (events key on absolute guest frames) — a budget misread as an
  absolute target runs minutes of idle emulation that looks exactly like a
  hang.
- **Input-replay events are keyed to the guest frame counter.** A loaded
  state restores that counter at the state's saved frame, so events at
  small relative numbers (0, 60, 80) all fire *immediately* at load and
  your press never lands where you meant — a no-op that looks like "the
  input didn't work". Author replay events as absolute guest frames ≥ the
  state's frame (the "state loaded" log line prints it). Tool-side frame
  counters may legitimately restart at 0 — check which counter each tool
  keys on before correlating.
- **Sessions that load a save in-game need that battery save for replay.**
  A replay booting with a different (or absent) battery save diverges at
  the load screen before the interesting code — pass the session's save
  through to the replay driver (e.g. `resolve.py --save-path`). The input
  trace alone is not the whole input.
- **Replay application differs by run mode.** Headless batch loops typically
  apply the input replay; interactive/debug stepping servers typically do
  not. If in doubt, read the key-input register at the first interesting
  frame.
- **Traces are sparse**: `frame,keyinput` pairs, active-low, written only
  when keys change. "No events for 5,000 frames" is normal (idle), not a
  recording failure.

## Trace monotonicity

A mid-session savestate reload makes the guest frame counter jump
**backward**; linear replay then rejects the trace. Split it into monotonic
segments and replay each segment from the same starting state.

```python
def split_monotonic(events):
    """events: [(frame, value), ...] -> segments that are strictly increasing.
    Replay each segment from the SAME start state."""
    segs, cur, prev = [], [], None
    for ev in events:
        if prev is not None and ev[0] < prev:
            segs.append(cur); cur = []
        cur.append(ev); prev = ev[0]
    if cur:
        segs.append(cur)
    return segs
```

Cross-check which state was reloaded: load each candidate state briefly and
read its recorded frame number; the segment's first event frame must be at
or after the state's frame. A reload also invalidates a boot-based replay of
the *whole* trace from the reload onward — the replayed timeline never
performs the load. See the live-session section below before trying anyway.

## Live-session debugging (when replays cannot reproduce)

The replay pipeline reproduces only sessions whose inputs formed a
*continuous* timeline. Two discontinuities break it:

- **Mid-session state loads.** "Load the tricky-state, retry the tricky
  thing" is the most natural play style — and it is exactly the session a
  boot-based replay cannot reproduce. If replays of such a session keep
  coming back clean while the live session hangs, that is the explanation,
  not a mystery.
- **Live-vs-stepped regimes.** An interactive/observing process and a
  headless batch can diverge in timing-sensitive subsystems. A hang seen
  live that never appears in a replay is a live-regime problem: debug it
  live.

**Decision rule.** Two clean replays of a live hang = stop replaying. Bank
the session's heals (merge → resolve → regenerate) and play on: every round
removes more live heal sites, and the next live freeze is better evidence.
Replays remain the oracle for *deterministic* routes (strict acceptance,
bisects); they are not the oracle for live-only hangs.

**Live capture pattern (window + debug port).** Run the session in the
windowed observe mode (window + read-only debug port — distinct from the
headless debug port; see tooling notes). Attach exactly one long-lived
watchdog polling registers / state-hash / frame-counter every couple of
seconds. The **frame counter is the hang signal**: it stops advancing inside
a real hang; a static pc with a moving frame counter is a legitimate wait
(BIOS loops, menu idles). On detection, snapshot registers + hash + a stack
window *while the game is still frozen*, then kill. This converts "it hung
again" into a pc + caller chain with zero reproduction effort.

**Loop hygiene.** Never launch a play session while a regenerate/build runs
(the player would be on a stale binary and the build contends for CPU).
Sequence: harvest → merge → resolve → cycle → commit → relaunch fresh build.

## Crash-safe harvesting

- The proposal file is journaled live as misses occur — read it directly
  after ANY session end (clean, kill, or hang).
- Second source: the **heal-cache unit filenames**, which encode
  `PC_hash_mode.ext`. Harvest the cache before anything else touches the
  build.
- Capture abort message text too; a bridge/watchdog abort usually names the
  offending PC and the stop target — that PC is your next resolver seed.

```python
import pathlib, re

UNIT = re.compile(r"^([0-9A-Fa-f]{8})_[0-9A-Fa-f]{8}_([ta])\.[A-Za-z0-9.]+$")

def harvest_healed(cache_root):
    out = set()
    for f in pathlib.Path(cache_root).rglob("*"):
        m = UNIT.match(f.name)
        if m:
            out.add((int(m.group(1), 16), "thumb" if m.group(2) == "t" else "arm"))
    return sorted(out)
```

Validate the convention against your framework version's cache naming before
trusting the regex.

## Playtest ergonomics

- Prefer **letter-only keymaps** when desktop input daemons swallow special
  keys (Enter, Backspace). Verify key delivery with a key probe or the
  recorded trace itself.
- Window scaling and view extension are different features. If a game has
  not opted into an extension, requests are silently clamped — not a bug to
  chase.
- Give the player a small ritual: save battery → save state → note anything
  weird in the moment. Those notes become decision-log fodder.
- Repro recipe for anything left open, written down immediately: state
  file + trace file + frames budget + one-line symptom.
