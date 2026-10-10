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
- Hardcoded absolute machine paths in tools or docs (the author's home
  directory) — they break every other checkout and leak the author's
  layout. Resolve the repo root from `__file__` in tools, describe external
  mirrors without machine paths in docs, and add a repo-hygiene test that
  greps tracked files for absolute home-path patterns.
- Letting the playtest loop run for hours without closing a batch: smaller
  sessions converge faster and make bisecting trivial.
- Nested submodules in the patch workflow: exporting the outer repo's
  consolidated diff picks up an inner repo's dirty gitlink
  (`Subproject commit …-dirty`) and GNU patch cannot apply that hunk —
  exclude the nested path from the outer export, keep a separate
  consolidated patch per nested repo, and route patch validation to the
  right repo by filename prefix.
- A bootstrap script whose patch step iterates a whole patch *directory*
  silently misroutes when one file targets a *nested* repo: the reverse
  probe (idempotence check) fails at the wrong root, the forward probe
  fails with "No such file or directory", and the bootstrap dies
  mid-run on every tree that has the nested patch applied. Route every
  patch by its filename prefix to the repo it targets — and **test the
  idempotence claim empirically** (run the step against a fully-applied
  tree *and* a fresh-clone simulation of pristine pins) instead of reading
  it: the claim was wrong here exactly one nested patch later.
- Android build bootstraps need the *desktop* corpus first: an Android
  build consumes the generated corpus but cannot produce it (the
  recompiler is a desktop tool), so the preflight must check corpus
  presence *and freshness vs the config* before the expensive Gradle
  build, or the APK embeds a stale corpus silently.

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
  ring of the last few million instructions answers "did PC X run, and what
  did the flow do around it" with no breakpoint mechanics. Query by
  PC/register/cycle. Cautions: the window moves with run length AND shrinks
  with execution density (an idle stretch spans ~120 frames; a busy load can
  fill the whole ring in ~5 — size the run so the event sits near the end,
  and take several capture slices when exploring a multi-frame sequence).
  The same input applied by a stepped server vs a batch replay lands on
  *slightly different frames* — pick one regime per investigation and never
  compare absolute frame numbers across regimes. With a hit limit (`--max N`)
  a scan stops early: the printed cycle range is *scan progress*, not the
  ring's extent — raise the limit before concluding "no hits". Dumps run
  hundreds of MB each (tmpfs counts as RAM) — delete after use.
- **Abort-on-write watchpoints are the sharpest tool for runaway/divergence
  onsets.** Gate by address, min-frame, and exact value so the abort fires on
  the *corrupted* write, not the legit one; pick the corruption's FIRST
  touched byte as the address so the handler's trailing event window still
  contains the entry into the bad loop. Abort handlers dump the last N trace
  events (default small; raise it — it clamps at the ring capacity, a few
  thousand events). A long runaway flushes the window: capture the onset,
  don't chase the aftermath — and min-frame gating doubles as a "skip the
  initialization fill I already understand" knob, so the abort lands on the
  write that matters.
- **Zero-over-zero writes are invisible to value-diff traces.** A clear or
  fill that writes zeros over already-zero memory produces no diff entries
  at all — an initialization step can silently "not exist" in a per-frame
  write trace while still running every load. When hunting fills/clears
  (scene eviction, buffer setup), use abort-on-write traps (they see the
  stores); when a value trace shows nothing where you expected activity,
  ask whether the expected effect is a no-op in VALUE terms.
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

### Offline state census: parse the save-state container

Save-state files are usually an **uncompressed tagged container** — magic,
version, ROM hash, then a section table of `{tag, len, payload}` per
subsystem (CPU/BUS/IO/AUDIO/SAVE/PPU/META are typical). Read the framework's
`serialize()` order once (do not guess) and you can extract everything
without running anything: the IO payload is the raw IO page (DISPCNT,
BGxCNT, scrolls at the saved moment); the bus payload concatenates the RAM
regions plus PAL/VRAM/OAM (e.g. EWRAM + IWRAM + PAL + VRAM + OAM, in that
order for one framework version — verify). Answers that used to need a live
session: "are the margin tile columns actually filled?", "which
screenblocks hold content?", "what does this struct hold at the saved
moment?" — a one-minute census that beats a run-and-probe loop when
designing a fix. (Locate sections by parsing the table; a known IO
signature — e.g. the BGxCNT byte sequence — is a quick cross-check.)

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

- **Verify input landing, always.** Injected keys are silently eaten when
  the game window doesn't have focus; read the KEYINPUT register
  (active-low, `read_io 0x04000130`) *during* the hold to prove the press
  reached the machine. "The game ignored input" conclusions are invalid
  without a catch-verified down-read.
- **Wayland sessions:** X11 injection tools (xdotool) cannot reach a
  native Wayland game window — and may not even enumerate it — so use
  kernel-level injection (ydotool). X11 window management is unreliable
  there too; prefer app-side input (the runner's own `set_keyinput`) when
  the debug port is available.

### Device (mobile) live sessions

- Extra runtime args arrive via an app-private `debug-args.txt` (create
  with `adb run-as`); `--tcp-observe PORT` + `adb forward` gives the same
  read-only surface as desktop.
- Live-journal dispatch misses to the app files directory (env-gated frag
  path): a hung or killed session never runs exit-time reports, so the
  live journal is the only harvest.
- No-root forensics: `run-as` same-uid `/proc` reads (thread-stack labels,
  `syscall`, `/proc/<pid>/mem` dumps) symbolized against the unstripped
  build; `debuggerd` is root-gated on production builds. Leave a wedged
  session alive while harvesting; restart only after captures.
- Never send a queued savestate request while the guest is stalled — it
  waits for the next present and wedges the single-client observe server.
- Touch overlays: an auto-hidden pad must let the revealing touch act —
  consuming the wake gesture forces a double tap and reads as input lag in
  menu-heavy games (learned on FFTA's pad idle-hide, 2026-10-08).

### Game-owned engine hooks: lifecycle and build flags

Engines that expose hook seams (provider pointers, margin/policy flags,
function-entry plugins) typically **clear game-owned hooks on every run
start** so nothing leaks between sessions — installs made at process start
are silently wiped. Install from inside the run instead: the runner's
per-game callbacks (an "after the expanded view is authorized" init hook, a
per-frame policy hook) or the mod activation/reset plugin lifecycle. When a
mod/plugin API fails to *link*, check the build before blaming versions:
several framework APIs compile only behind a build option (e.g. a mods
flag), so `nm <runtime archive> | grep <symbol>` tells you whether the
function is in the linked set or was never compiled in. A missing symbol
can be a configure flag, not an older pin — and the pin itself is worth
verifying with a live `git ls-remote` against the actual remote tip before
planning an update.

The lifecycle has sharp edges and its ordering is **structural**. The
activation pass runs **on every run** (catalog state can be recomputed
mid-session) and fires *after* the runner's per-game cleanup has already
cleared game-owned hook state — so **install hooks from the activation
plugin**, and use a **reset callback** (fires immediately after the
engine's disable-all) to clear your own presentation state and re-arm any
function-entry guards. Note entry plugins register **disabled** — something
must enable them. Ship the plugin through the engine's catalog
(`mods/preloaded/…` beside the executable, gated on game id + ROM hash) so
activation is a reviewed config act, not a boot-time side effect. Verify
the feature-disabled fallback explicitly, and state which parts of the
feature are game code (per-frame policy hooks) vs plugin-owned — game-code
parts survive with the plugin off.

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
extent before believing a wide render. Two more traps from shipping one:
(a) **always-black margins may be a POLICY, not missing content** — engines
commonly black out ("pillarbox") margin columns unless the game declares
them authored, and a state-load path can force that policy on; check the
engine's margin-policy gates before hunting VRAM for missing tiles;
(b) the expanded path needs its own proof — the wide frame's central
native-width region must be **pixel-identical** to a faithful render
(crop-compare), margins decoded and sanity-checked, default-off must keep
the golden hash, and a stale view request must not silently enable the
feature.

Runner shutdown: the window-close path can hang in teardown (observed:
debug listener closes, then an XInput poll hits the destroyed window and a
joinable thread destructor raises `terminate called without an active
exception`; the process lingers). The TCP `quit` command is the reliable
shutdown — keep a one-line helper (connect, send `{"cmd":"quit"}`) and
prefer it for scripted sessions. SIGTERM may be swallowed. Verify a clean
exit by checking that the process leaves within a few seconds and the
wrapper's archive/flush steps ran.

Finding game state and the code around it (portable): (1) parse the
save-state container directly for an offline census (see below) and
byte-diff before/after saves - changed fields reveal the variables (camera,
counters, flags); (2) query the FP ring for instructions whose registers
hold an address/value (`--reg`, `--reg-range`) to find both readers/writers
and generic helpers; (3) trap writers with an abort-on-memory-write env
(+ runtime trace) for the caller chain - RAM/VRAM works; IO-register traps
may not fire at all; (4) for IO-path writes use the MMIO capture ring and
watch DMA destinations explicitly - but remember the capture layer can
itself be buggy: a one-shot "suppress nested taps" flag in the bus write
path swallowed whole DMA transfers kicked inside its window (every
destination write of the transfer vanished). When expected register writes
never appear, bisect the capture path for reentrancy guards before blaming
the guest; (5) the DMA watch matches the EXACT address as a transfer steps -
watch a region's first word, and remember a transfer starting deeper in the
region never prints. Static BL scans miss pointer-table entries; prefer
runtime traps.

Name discoveries in the durable index as soon as their role is verified:
seed/symbol files propagate names into generated code (grep-able forever),
data-symbol files carry RAM-struct names + a field comment block, and a
reference doc holds the deep detail with probe recipes. Cross-link the
three. This turns one session's archaeology into the next session's
starting point instead of a repeat expedition.

Hanging GUI runner? Inspect before killing. `ps -L` thread states and
/proc/<pid>/task/*/wchan are ptrace-free and usually name the stuck thread
(futex_wait = a join or lock; poll/epoll = a server or event wait); gdb
attach needs either being an ancestor or kernel.yama.ptrace_scope=0. Keep
a reproduced hang alive until its state is captured. Prefer an
in-protocol quit command over signals for closing sessions (desktop signal
handlers may not exist at all), and remember window-close teardown can
differ per video backend — test the one the players actually use.

Window-close "hangs" debug recipe: test the app's OWN quit keybind first
(here: ESC). If that exits cleanly, the quit machinery is fine and the CLOSE
EVENT is the bug — check which SDL the binary actually links (`sdl2-compat`
is an SDL3 shim whose event translation can drop backend close requests).
Inject test input with `ydotool` on Wayland (uinput-level; ESC = keycode 1;
`ydotool key 1:1 1:0`). Watchdog probes: a runner's debug server may serve
ONE client at a time — disconnect other watchers before issuing commands or
they will time out (a timed-out quit can still land moments later).

Canonicalizer hooks that dispatch into generated fragments can recurse on
split-boundary crossings: when a relocated routine was cut into units
(setup/loop/tail) and your hook matches by "bytes at pc or pc+2", the setup
unit's fall-through re-dispatch of the cut address arrives with mid-run
registers and satisfies the pc+2 match again. Gate pc+2-style matches on
fresh-entry register state (or run a full canonical body) so crossings fall
through to the fixed table instead of re-entering the setup.

Suspiciously empty probe results deserve the same scrutiny as crashes: a
scan that captured 0 hits may mean a silently truncated window (a loop
guard capped at a hard iteration count), a breakpoint mechanism that does
not fire for the probed address class (dispatch-entry yields never see
mid-function PCs), or a fixtured input file that no longer exists. Make
capture tools fail loudly on the empty/ambiguous case, and scale guards
with the requested window instead of using constants.

Relocated-code hooks that byte-verify a helper against its ROM source can be
fooled when the game re-plants the same helper at a stack address that a
mid-run resume PC also occupies: a byte-match then looks like a fresh call,
and re-running the canonical body (second prologue push + setup re-run)
tears the caller's stack by one frame — the caller's epilogue then pops a
stale local as a return address. Key entry identity on the live loop
sentinel register (e.g. r2 == -1 means the copy is already in progress) and
fall through to the resume labels instead of re-entering the body. Two more
rules learned the same week: byte-verify hooks must handle BOTH ISA modes —
a thumb-only canonicalizer silently declines ARM-planted routines (every
ARM dispatch becomes a miss; extend the hook and its unit tests rather than
seeding the fixed address), and fixed-address seeds cover only the
canonical body — moving plants belong to the byte-verify table.
