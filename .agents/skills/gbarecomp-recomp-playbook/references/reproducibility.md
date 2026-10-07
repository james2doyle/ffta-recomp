# Reproducibility: savestates, traces, crash harvesting, playtest ergonomics

Load this when setting up or debugging the capture side of the loop: making
sessions deterministic, replaying them, recovering evidence after a crash.

## Session artifacts

Keep sessions cheaply reproducible with **savestate + input trace** pairs.
Archive both on every launch; a play session overwrites its slots, so the
archiver is what makes "the previous session" recoverable. Keep a battery
save too — some bugs only reproduce through the game's own save/load path.

## Replay semantics to verify once, then never assume

- **Frame budgets after loading a state** usually mean N frames *from the
  state*, not an absolute counter. Measure before any bisect; wrong
  assumptions cost hours.
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
or after the state's frame.

## Crash-safe harvesting

- Clean exit: the proposal file is the miss list.
- Crash: nothing flushed. Recover the healed PCs from the **heal-cache unit
  filenames**, which encode `PC_hash_mode.ext`. The cache is the evidence;
  harvest it before anything else touches the build.
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
