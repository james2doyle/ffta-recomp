# Frame interpolation — how FFTA recomp presents motion at display rate

ffta-recomp issue #9. This doc describes the shipped design: what the
feature does, why each piece looks the way it does, the game-specific
findings that shaped the guards, and what a porter needs to do to get the
same behavior in another [gbarecomp](https://github.com/mstan/gbarecomp)
game. Dated evidence and the full decision history live in
[BRINGUP.md](../BRINGUP.md) (`2026-10-12`/`13` entries); harness traps are
in [reference/dev-gotchas.md](../reference/dev-gotchas.md).

Toggle: **Graphics → Frame interpolation** in the runtime settings menu
(persisted), or `--frame-interp 1` on the command line (Android: staged
`debug-args.txt`). Builds without the runtime UI keep no-op stubs, so
headless acceptance runs are unaffected.

## The problem

The guest produces frames at the GBA's real rate, 59.7275 Hz
(16'777'216 Hz / 280'896 cycles — see `FramePacer::kGbaFrameHz`). The
pacer throttles emulation to that wall-clock rate and presents once per
guest frame. On a faster panel (120 Hz phone, 144 Hz desktop) each guest
frame then dwells on screen for an integer number of panel refreshes —
and 59.7 does not divide 120, so the dwell flips between 2 and 3
refreshes on a beat. While the screen scrolls, that aliasing reads as
judder, and even the steady 2-refresh dwell halves the temporal
resolution of motion.

The fix has three pieces:

1. **Decoupled display clock (3a)** — the frame limiter's idle span is
   subdivided into display-paced *holding presents* instead of one
   present per guest frame.
2. **True-midpoint intermediates (3b)** — holding presents are not
   duplicates: a non-first tick shows the current guest frame shifted
   back by half the measured camera step, so a scrolling world lands on
   its true halfway position every panel refresh.
3. **Motion guards** — three rules that refuse to fabricate motion when
   the register evidence is ambiguous. This is where all the
   game-specific pain is (see [Guards](#guards-why-each-one-exists)).

## Data flow, per presented guest frame

Everything hangs off the single present site in `runtime.cpp`
(`run_game`'s main loop); `FramePacer::wait_for_next_frame(frames, tick)`
gains an optional tick callback:

1. The guest frame has just rendered into `live_fb`. Take a 16-byte
   snapshot of the BG scroll registers (`0x04000010..0x1F`, HOFS/VOFS ×
   4 layers).
2. `dominant_step(prev_snapshot, cur_snapshot)` measures the camera
   step (dh, dv) under the **consensus rule** below. Steps are only
   measured when the present covers exactly one guest frame
   (`banked_frames <= 1`) — a multi-frame present has no single step.
3. **Rebase veto**: if the previous and current guest frames are
   visually identical (sampled mean |diff| < 1.0) while the step is
   nonzero, the step is not motion — clear it.
4. If a step survived, build the midpoint in `interp_fb`:
   `shift_blit(live_fb → interp_fb, −dh, −dv)` shifts the *current*
   frame back by half the step, then `select_static` restores every
   pixel that is byte-identical between the previous and current guest
   frames (screen-locked chrome stays put).
5. Call `pacer->wait_for_next_frame(banked_frames, tick)`. The tick
   callback presents `live_fb` on the first tick and `interp_fb` on
   every later tick until the guest-frame deadline.
6. `interp_prev` (RGB) and `interp_prev_io` (registers) are updated for
   the next round.

The wait callback passes null everywhere else — headless runs,
fast-forward (uncapped), behind-schedule resyncs, and toggle-off waits
keep the historical blocking path bit-for-bit. Guest-time bookkeeping is
identical in both paths; only how the wait is spent differs.

### The interp_shift API (host_platform.h)

Pure arithmetic, no SDL, no guest state — the whole namespace
unit-tests without a display (`tests/unit/test_interp_shift.cpp`, gated
by `INTERP_SHIFT_TESTING`):

| Function | Role |
|---|---|
| `fold_scroll_delta` | Wrap-aware 9-bit scroll delta → [−256, 256] |
| `dominant_step` | Consensus camera step from two register snapshots |
| `frame_mean_abs_diff` | Sampled frame-identity metric (stride 4) |
| `shift_blit` | Half-pixel integer bilinear screen shift, edge-clamped |
| `select_static` | Pin byte-identical prev/cur pixels into the mid |

### Midpoint math

`shift_blit` works in **half-pixel units**: destination (x, y) samples
the source at (x + sh/2, y + sv/2). Because the midpoint shift is −step
and the step is an integer, an odd step lands on a true half-pixel —
the bilinear weights (2−f)·(2−f)/4 blend the two neighbors with exact
integer math (`(v + 2) / 4`); an even step is a pure copy. Three
properties fall out of measuring instead of predicting:

- **Odd steps stay exact** — the halfway position between two integer
  scroll positions genuinely is a half-pixel offset.
- **Snaps halve** — a cut of N px presents as N/2 then 0; no
  overshoot, no invented direction.
- **Still frames are bit-identical** — step (0,0) never reaches the
  blit; the mid degenerates to the live frame.

Why shift the *current* frame back rather than push the *previous* one
forward: the previous frame's presentation is already finished; the
ticks being planned belong to the current frame's dwell, and the true
halfway position between the two frames is `cur − step/2`.

### Display-side pacing

`HostWindow::interp_display_tick` is called once per display tick and
owns the panel cadence:

- The display period comes from `SDL_GetCurrentDisplayMode`, re-queried
  periodically (the counter fires every 600 ticks) so adaptive-refresh
  panels just work; a rate change re-anchors the tick clock.
- If presents block on vsync, the present *is* the pacing and the tick
  skips its own sleep. Otherwise it sleeps until the next display
  boundary — but **never past the guest-frame deadline**: a slower
  panel yields the wait early rather than making the emulator late.
- Unknown display rate degrades to 1 ms pacing (CPU bounded, cadence
  honest); a 60 Hz panel degenerates naturally to ~1 tick per guest
  frame, i.e. the pre-interpolation behavior.
- Telemetry: every ~5 s of ticking, a `interp ticks=… rate=…/s` line on
  stderr — the only remote proof the wait is actually subdividing at
  display rate (used for on-device validation).

## Guards — why each one exists

Every guard answers one question: *is this register step really the
whole screen translating?* A wrong yes fabricates a frame the game never
displayed; a wrong no merely loses one midpoint (retail frame). All of
them are therefore biased to "no midpoint" on doubt.

| Guard | Fires when | What it prevents |
|---|---|---|
| Consensus (`dominant_step`) | Moving layers disagree on the (dh, dv) pair | Non-camera register writes interpolated as camera pans |
| Rebase veto (`frame_mean_abs_diff`) | Frames identical, step nonzero | A compensated rebase on *all* layers read as motion |
| HUD pin (`select_static`) | Pixels byte-identical prev→cur | Screen-locked chrome riding the world shift |
| Single-frame rule (`banked_frames <= 1`) | Present covers k > 1 guest frames | Averaging several per-frame steps into one bogus shift |

### The consensus rule (the big one)

The first implementation picked the largest |dh|+|dv| layer as *the*
camera step. FFTA broke that assumption twice, both during ordinary map
pans:

- **Scroll rebase**: mid-pan the game writes BG2/BG3 HOFS `0 → 648`
  (raw; +136 after the 9-bit mask) and walks it back to 0 over ~0.15 s.
  Frames before, during, and after are visually continuous — the
  register jump is bookkeeping, not motion. The largest-wins rule saw
  |136| beat BG0/BG1's real pan step of −3 and shifted the whole
  composed frame −68 px for one display tick: a single garbled frame
  with an edge-clamped streak strip — the "blip at the end of the map".
- **Overlay dance**: the same layers animate ±18 px legs in the same
  window while the world pans at −4 — smaller wrong shifts (±9 px) on
  mid ticks, the "wild shifting" shimmer.

The rule now: collect the folded (dh, dv) per layer; every layer that
*moved* must report the identical pair. Still layers don't vote (their
pixels are pinned by `select_static` instead). On disagreement the step
is (0,0) and the frame shows live on every tick — exactly the retail
presentation for that instant. Legit pans (all layers in lockstep,
which is what a camera actually is) still interpolate.

### The rebase veto

The consensus rule has one blind spot: a rebase applied to *all four*
layers at once (a long pan crossing the 512 px tilemap wrap) agrees
with itself. The veto closes it from the other side: if the two guest
frames are visually identical (stride-4 sampled mean |diff| < 1.0 per
channel) while some register step is nonzero, there is nothing to
interpolate — no midpoint. When frames really are identical the veto is
a no-op (a midpoint of identical frames is the same frame), so the
threshold is safe to be generous.

### The HUD pin

The midpoint shifts the whole composed frame. Any pixel that is
byte-identical between the previous and current guest frames cannot be
world content that moved — it is screen-locked chrome (menus, clock,
panels, the widescreen border) — so `select_static` restores its exact
bytes after the shift. Flat world areas match either way, so the
compare costs nothing visually where it fires spuriously. A game whose
HUD animates every frame simply gets no pinning; the guard is harmless
there.

## FFTA-specific findings a porter should check for

- **30 Hz content is authored, not clocked.** FFTA's half-rate updates
  are palette-fade ticks (move-range tiles, transition flashes). No
  render-pipeline 60/30 compute/read split can smooth them, and the
  interpolation deliberately does not try — those effects play at guest
  rate identically with interp on or off.
- **Know which layers carry the camera.** FFTA pans BG0+BG1 in
  lockstep; BG2/BG3 mostly ride along but also do rebase/overlay work.
  This split is game behavior, not GBA behavior — measure it.
- **Authored camera violence stays.** The A-button transition whip
  (~+100 px right, snap back) is game-authored; midpoint halves each
  leg and never overshoots. Interpolation is not a stabilizer.
- **Sprites are out of scope.** The midpoint is whole-screen
  translation only; OAM/palette animation is not addressed, by design.
- **Resolution-agnostic.** The midpoint operates on whatever the PPU
  composed (`render_width/height`), so the widescreen render (356×160
  here) interpolates identically.

## Alternatives considered, and why not

| Approach | Verdict | Reason |
|---|---|---|
| Frame blending (`recomp_frame_blend`) | Wired, not exposed | Averages consecutive frames — works with no camera signal at all, but every shown frame is a two-frame mix: ghost trails on cuts, blur on stills. The primitive is upstream (`recomp-ui`) and the host wiring exists, but FFTA's settings menu does not expose it; the right fallback for a game with no measurable camera. |
| VRR / adaptive-sync presentation | Skipped | Solves the aliasing only on VRR panels; adds a second validation surface. |
| 60 Hz compute / 30 Hz read pipeline split | Dead | The 30 Hz content is palette fades — a clocking problem does not exist there. |
| Per-layer host compositing | Rejected for scope | Principled (shift each layer by its own delta), but requires re-compositing layers outside the PPU. `select_static` already covers the common case — static layers — for free. |
| Magnitude thresholds on the step | Rejected | Arbitrary cutoffs silently break legitimate fast pans; the consensus rule expresses the actual invariant. |
| Velocity prediction | Deleted | An early 3b draft extrapolated motion; oscillation and cuts broke it. Measure, never predict. |

## Porting to another game

1. **Wire the tick.** At your present site, pass the tick callback to
   `wait_for_next_frame` when interpolation is on; pass null on every
   other path. Guest-time bookkeeping must stay identical — the wait is
   the only thing that changes.
2. **Pace the ticks.** Port `interp_display_tick`'s rules as-is:
   display-period discovery with periodic re-query, vsync-blocked
   presents as their own pacing, never holding the guest wait past its
   deadline, 1 ms fallback.
3. **Find your camera signal.** Dense-capture a long scroll (see next
   section) with the BG scroll registers beside it. If the camera lives
   in BG0–3 HOFS/VOFS and layers move in lockstep, the shipped
   `interp_shift` code works unchanged.
4. **Keep the guards even if your game seems clean.** The consensus
   rule and the rebase veto cost microseconds and are game-agnostic;
   the rebase that produced FFTA's blip is invisible in casual play and
   was found only by frame-level capture.
5. **If the camera is not scroll-driven** (mode-7/affine camera,
   sprite-driven scrolling), the register snapshot yields nothing and
   the design safely degenerates to retail (affine layers hold stale
   HOFS slots and never vote). Consider frame blending instead — it
   needs no camera model.
6. **Unit-test the arithmetic, not the window.** The entire midpoint
   build is pure functions; test wrap folding, consensus cases, blit
   weights, and the pin against hand-computed values.
7. **Prove the off-path is untouched.** Run your regression/oracle gate
   with interpolation off — the attract-mode hash pin must not move.
   Then do the on-device feel pass with it on; interpolation quality is
   a human verdict, not a hash.

## The debugging method that found the rebase

Condensed; the full playbook is in
[reference/dev-gotchas.md](../reference/dev-gotchas.md).

- **Capture the presented stream, not screenshots.** The presented
  buffer is the exact upload bytes — midpoints included — so
  artifacts-of-the-feature appear in the capture directly. Pair every
  presented poll with a 16-byte register read of `0x04000010..0x1F`.
- **Dense or blind.** ~65–70 polls/s over a single uninterrupted input
  hold caught a 0.15 s event (the rebase) with 503 unique frames.
  Earlier sparse captures (24 frames) straddled the same event and saw
  nothing — capture density, not the pan, was the blocker.
- **First divergence only.** Find the single wrong frame; montage its
  neighbors; wide-range cross-correlation to measure the displacement;
  then read the registers at that timestamp. A one-frame artifact that
  neighbors are continuous around is a midpoint artifact, not a guest
  tear (a tear would garble the live tick too); the edge-clamped
  replicated-column strip is the blit's signature.
- **Distinguish authored from fabricated** by holding the trigger
  constant: replay with interpolation off. If the motion persists, the
  game authored it.

## File map

| File | Role |
|---|---|
| `gbarecomp/src/runtime/host_platform.h` | `interp_shift` namespace: all policy + pure arithmetic |
| `gbarecomp/src/runtime/host_platform.cpp` | `FramePacer::wait_for_next_frame` — banked pacing + tick subdivision |
| `gbarecomp/src/runtime/runtime.cpp` | Present-site wiring: snapshot → step → guards → build → tick loop |
| `gbarecomp/src/runtime/host_window.cpp` | Display pacing, period discovery, telemetry |
| `gbarecomp/src/runtime/runtime.h` | Settings row plumbing (`expose_frame_interp`) |
| `tests/unit/test_interp_shift.cpp` | Display-free unit tests (consensus, blit, pin, metric) |
| `recomp-ui/src/recomp_frame_blend.h` | The blend alternative (upstream shared primitive) |
