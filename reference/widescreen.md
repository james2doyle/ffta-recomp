# Widescreen reference — FFTA field camera, strip, and apply paths

Facts from the 2026-10-08 investigation (BRINGUP § "Widescreen W1"). All
addresses verified with `tools/disarm.py`/live TCP probes unless labeled as
hypotheses. ROM = AFXE (sha1 4ac05441…).

## Finding this code (durable index — start here)

Grep the names, not the hex:

- `grep worldmap_camera symbols/ffta_symbols.tsv` — the five named units
  and what they do (section 6 there has the evidence note).
- `grep worldmap_camera generated/dispatch_table.cpp` (or any generated
  file) — the emitted functions under those names.
- `grep gWorldMapCamera symbols/ffta_data_symbols.tsv` — the camera struct
  row (section 8 has the field map).
- The scroll-register apply has **no named entry** (guest DMA helpers at
  0x08001300-0x08001420, pointer-reached); search this doc for that range.
- `grep display_regs_commit symbols/ffta_symbols.tsv` — the per-frame
  39-halfword display-register commit (DMA0 from `gDisplayRegShadow`;
  § "Scroll register apply").
- `grep "lzss_decompress\|scene_gfx_load" symbols/ffta_symbols.tsv` — the
  scene-load strip pipeline (W1b; § "W1b — the strip drawer").
- `grep strip_scroll_compute symbols/ffta_symbols.tsv` — the scroll/desc
  compute feeding the descriptor walk (0x0801C984; § W1b battle notes).

Named units (all already emitted; names assigned 2026-10-08):

| Name | Address | Role |
|---|---|---|
| `worldmap_camera_ease` | 0x08038BF2 | ease step, delta > 0 branch |
| `worldmap_camera_ease_cont` | 0x08038C3E | continuation (applies +0x0C) |
| `worldmap_camera_coord_write` | 0x080376A2 | writes +0x08 coordinate |
| `worldmap_camera_head` | 0x080328BA | writes +0x00 flags/head |
| `worldmap_camera_flags_read` | 0x0804C044 | reads +0x00/0x18/0x19 |

To re-derive from scratch (other scenes/axes), use the probe recipes at the
bottom of this file (savestate diff → abort trace → FP ring).

## Operational index (run + validate)

- Run wide: `--view-width 320|384|448` or `--resize-view` (windowed; same
  ceiling). Validate: `tools/ws_check.py` — 6 cases x 3 widths; needs the
  **sha-pinned** dedicated fixture copies `saves/ws_fixtures/` (local-only,
  game-derived; the frame budgets + CSV event frames are pinned to these
  exact states — exit 2 when missing or changed) plus the committed
  `inputs/ws_*.csv`. The copies keep the player's `game.state1..9` slots
  free for GUI testing. Also runs inside `check.py` as `ws_smoke`.
- Plugin + manifest: `src/main.cpp` (`register_ffta_mod_plugins` /
  `ffta_ws_activate`), `mods/preloaded/packages/ffta.enhancement.widescreen/1.0.0/`
  (shipped to `<exe>/mods` by a CMake POST_BUILD rule). Framework race fix
  for parallel launches: `tools/patches/mod-state-publish-race.patch`.

## Display facts (world map + battle, mode 0)

- **World map:** BG0/BG1 = field layers, tilemaps 256x512 (size=2): BG0 at
  screenblock 0x5000 (blocks 0x5000+0x5800), BG1 at 0x6000 (+0x6800); both
  only **256 px wide** — margins wrap via the tilemap edge (W3 policy case).
- **Battle/pub:** BG0 (0x6000) / BG1 (0x7000) = the **field ring, 512x256
  (size=1)** — a 64-column window with REAL surrounding content; BG2
  (0xE000) / BG3 (0x5000) carry the scrolling/animating layers (their
  HOFS moves during pans; empty in the probed battle state). Margins here
  sample the ring itself and render true content (W2 landed).
- Vertical scroll pans via the tilemap wrap on the world map; horizontal
  **battle pans** move BG2/BG3 HOFS with strip-ring redraws (the ring layers
  themselves keep HOFS static at 0x80 — content slides).

## World-map camera state (battle: NOT this struct — see § W1b battle notes)

Struct around **0x02002C10-0x02002C1F** (reached via object at IWRAM
0x03002810, `[[0x03002810]+4] = 0x02002C10`):

| Offset | Observed | Guess |
|---|---|---|
| +0x00 byte | 97 -> 65 | mode/flags byte (bit 0x40 read by 0x0804C2xx) |
| +0x02 | 0x1E00 -> 0x8700 | strip/chunk pointer (moves per node) |
| +0x08 u16 | 256 -> 330 | camera coordinate (eased) |
| +0x0A | 0x6950 -> 0x8A50 | strip data pointer (moves per node) |
| +0x0C u16 | 151 -> 192 | **BG v-scroll — ends up in BG0/BG1VOFS** |
| +0x0E u16 | 151 -> 206 | eased twin (fine value; stepped 152,153… live) |
| +0x18/0x19 | flags | read by 0x0804C2xx (byte + signed, cmp 0x17) |

Twin copy seen at 0x0200197A/0x0200197C (same pointers) — likely a second
descriptor (load/backup copy).

## Camera update code (the "ease + apply" chain)

- **0x08038BF2 / 0x08038C3E** — one split unit (interior split): the ease
  step. Delta r2 = target-current: `> 0` and `<= 3` → use as-is, `<= 0xB` →
  delta/2, else delta/4 (rounding included); writes struct +0x0E, +0x11
  flags, +0x10; calls 0x081426B8 (shared math helper).
- **0x080376A2** — writes struct +0x08 (camera coordinate) (eased likewise).
- **0x080328BA** — writes struct +0x00 (came from the node-move event chain).
- Reader **0x0804C24A-0x0804C288** — reads flags/coords (+0x00 bit 0x40,
  +0x18, signed +0x19 vs 0x17) — likely node/UI logic (not yet identified).
- Live trace proof: abort-on-write 0x02002C1C caught the first ease step
  `pc=0x08038C5E value=0x98 (152)` with the full event chain (BRINGUP).

## Scroll register apply = guest-owned DMA

- The scroll registers are NOT written by a plain `strh`. The guest programs
  hardware DMA and waits: helper family at **0x08001300-0x08001420** writes
  DMA SAD/DAD/CNT (`str r6,[r2]`, `str r7,[r2,#4]`, CNT with enable bit,
  then polls bit 31) and appears with DAD values 0x04000010/12/14/16
  (BG0/1 HOFS/VOFS) in the FP ring. Entries are reached via pointers, not
  BLs (scan found no static callers).
- **Capture (FIXED 2026-10-08):** these writes now appear in
  `GBARECOMP_MMIO_CAP`. The `heal_gate` Journal suspicion was wrong — the
  cause was `gba_io.cpp`'s write32 split-suppression flag: a 32-bit store of
  the DMA CNT field (kick pc 0x0800073C, now named `display_regs_commit`
  0x08000718; the 0x0800072x-3C sequence sets the channel up, helper form
  `str r0,[r2,#8]` at 0x080013E0) executes the whole
  transfer while the flag is set, so every destination write was swallowed.
  Fixed by per-call record control — patch
  `tools/patches/mmio-cap-dma-reentrancy.patch`; see BRINGUP § "MMIO cap gap".
- **What the fixed cap shows** (world-map recenter repro): the display commit
  is a per-frame **DMA block copy** of a shadow struct — 39 halfwords
  `0x04000008..0x04000054` (BGxCNT/HOFS/VOFS, affine, windows, blend), one
  copy per frame, kick pc 0x0800073C; during the pan the copied VOFS values
  step 0x97→0xA1 in lockstep with the camera ease.

## W1b — the strip drawer: LOCATED (2026-10-08, world map → pub load)

`lzss_decompress` (0x0800543C; r0 = dst, r1 = src — BE length at src+0,
stream at src+4; the entry the `ffta.lzss-guard` seam protects). Scene loads
decompress pre-baked strips into EWRAM staging, then stream them to VRAM by
DMA — the "drawer" is this decompress+upload pipeline, driven per load step:

- Fills/evictions come from a scene state cluster (0x08023Fxx/0x080240xx),
  then the graphics load; decoder callers observed: `scene_gfx_load`
  0x08022A04 (via 0x08022A2E; dst 0x02003CB0), 0x0801A620, 0x080CB8C6.
- Content lands in the field screenblocks by DMA from EWRAM staging
  (e.g. ch=0, dad=0x06006800, src=0x0200BDDC/0x0200BA5C, 32x16-bit chunks;
  staging written by the decoder itself — e.g. 0x0200B80A at frame ~204).
- Verified on the world map → Sprohm/pub load (repro: game.state2 + A,A):
  screenblocks 0x6000/0x6800/0x7000/0x7800 fill frames ~193-196; 0x5000/
  0x5800 later (196-236). Battle-map variant not yet observed (same
  pipeline expected — confirms with a battle-entry repro).

Repro/tooling: VRAM value trace (`GBARECOMP_WRAM_TRACE` on 0x06005000-7FFF)
for where/when; FP ring + `ringscan.py --cyc/--reg-range` for who; DMA watch
for upload attribution. NOTE: 0x02003CB0 is SHARED scratch (both the save
driver and this loader decompress into it) — the historical save-vs-scene
churn around that address was this overlap.

### Battle pans redraw the strips (2026-10-08; mid-battle overview, game.state1)

- Battle field layers are **BG2/BG3** (horizontal pan = BG2HOFS/BG3HOFS
  0x04000018/0x1C stepping ~0x12/frame while easing; BG0/BG1 VOFS animate
  separately). The world-map camera struct 0x02002C10 is **not** used in
  battle.
- Panning **rewrites the field screenblocks** 0x06006000-0x06007FFF (frames
  ~62-115 for a right-hold) via the strip pipeline: `strip_refresh_engine`
  0x0801AC78 -> `strip_refresh` 0x0801B7F8 -> `strip_blit` 0x0801AF08
  (chunked staging -> VRAM: manual ch0 DMA 32x16-bit chunks, src += 0x80 /
  dst += 0x40, busy-poll; CpuSet variant too).
- Staging (0x0200B000-ish) is **pre-composed** (zero writes during the run;
  the decoder does NOT run per pan step) — the blit walks offset counters in
  `gStripBlitDesc` (0x02007F40, 0x28-byte entries; +0x24/+0x26 advance with
  the pan). The internal model is **64 columns wide** (`cmp #0x3f`) = 512 px:
  the engine already handles >=512-px-wide maps internally; the visible
  window is 256 px.
- W2 hooks are now concrete: extend at `strip_blit` / the descriptor walk
  (materialize extra columns) rather than at the decoder. *(Superseded:
  W2 m1 landed by sampling the ring's authored columns directly — no strip
  extension was needed.)*

## W2 — authored margins: LANDED (milestone 1, 2026-10-08)

Run it: `./build/FFTARecomp … --view-width 320` (default stays faithful 240;
capability = `opts.max_view_width` in `src/main.cpp` — raised to **448** in
W3 m2; `GBARECOMP_WS_WIP` is no longer needed at any supported width). The
game installs margin hooks from the trusted activation plugin
(`ffta.widescreen`, W3 m3 — this replaced the original
`RunOptions::extended_view_init` install, which no longer exists):

- `g_ws_authored_margin_layers = 1` — margin columns render from the guest's
  own BGs (the 512-wide field rings) instead of the pillarbox policy black;
  savestate loads then keep the pillarbox policy off.
- `g_ws_obj_native_clip = 1` — parked off-screen OAM stays out of margins.

Verified (headless, --view-width 320): battle at rest + pans (f100/f150) —
margins 100 % filled with the ring's own content; center fidelity: wide
center `[40..280)` == faithful 240 render, pixel-identical (0/38,400).
**Correction (2026-10-08, W3 session):** the W2-era "pub" check ran without
`GBARECOMP_INPUT_REPLAY` set, so it never left the world map — it was a
world-map wrap check, not the pub. The pub was re-verified under W3 (below).
World map: margins are its 256-px map's **wrapped edge** → pillarboxed in W3.

Reference notes (2026-10-08):
- **EmeraldRecomp** (`docs/WIDESCREEN_EXPERIMENT.md`,
  `src/mods/emerald_adaptive_view_plugin.cpp`) is the reference for the
  wrap-case: host-synthesized margins via `g_ws_tilemap_provider` (padded map
  + metatile decode), a host object layer (`g_ws_obj_margin_provider`), UI
  edge-anchoring (`g_ws_bg_xy_provider` + `..._layers = 1`), **fail-closed
  pillarbox** (`Ready ? 0 : 1` each frame), verification probes and smoke
  tools. FFTA needs no provider machinery for field scenes; the
  UI-anchoring model is the reference if HUD stays wide.
- **WarioWareTwistedRecomp** has no widescreen implementation.
- Engine note: `mod_runtime.cpp` (activation/reset plugins,
  `gba_mod_set_view_width`) links only when the build enables its mods
  option — adopted here 2026-10-08 (`-DGBARECOMP_ENABLE_MODS=ON`); the pin
  itself is the latest main (`git ls-remote` verified). Seams used:
  reset/activation plugins (W3 m3 — `extended_view_init` was the pre-m3
  seam, now removed) + `RunOptions::extended_view_frame` for the per-frame
  policy + fn-entry plugins.

## W3 — per-scene margin policy: LANDED (milestone 1, 2026-10-08)

Implemented in `src/main.cpp` via `RunOptions::extended_view_frame` (runs at
every emulated frame start, before scanline 0):

- **Pillarbox policy:** scenes whose field BGs are 256-px tilemaps
  (BG0/BG1 size=2 — the world map) get `g_ws_pillarbox = 1`; the 512-wide
  ring scenes (battle/pub, size=1) keep authored margins (pillarbox off).
- **UI-layer margin skip:** BG2/BG3 (256-wide UI screens: menus, funds,
  dialogue panels) return "no pixel" outside the native 240 span via
  `g_ws_bg_x_provider` (+ `..._layers = (1<<2)|(1<<3)`), so their edges can
  never wrap into the margins.

Verified matrix (headless, --view-width 320): battle — margins 100 %
(filled through pan replays); pub — margins 100 % and CLEAN after the UI
skip (menu/funds fragments gone; center vs faithful 0/38,400 differing);
world map — black pillarbox bars (0 non-black margin pixels); attract gate
byte-exact; `check.py` 8/8; routes FULLY_STATIC. Spot check: battle at 384
fills its 72-px margins too (completed in W3 m2 — full 320/384/448 matrix).

(The W3 polish + lifecycle items that were still open — transition fades,
world-map fade-in, ring recenters, and the activation-plugin migration —
landed as milestone 3 at the end of this file.)

## W3 milestone 2: smoke test + full 320/384/448 matrix — LANDED (2026-10-08)

- **`tools/ws_check.py`** — per scene fixture x view width: headless engine
  runs in parallel (`--jobs`, isolated dump/save/coverage/frag paths);
  checks (a) the wide render's center `[extra_left, +240)` is pixel-identical
  to the faithful 240 render, (b) the margin census matches the per-scene
  policy (ring scenes filled >=99 %, world map exact black), (c) an
  idle-vs-pan stale guard on the margins (must differ >=2 %). Fixtures:
  the dedicated copies `saves/ws_fixtures/{battle_overview,world_map}.state`
  (moved there in the W3 wrap-up so the player's own state slots stay free)
  + committed
  `inputs/ws_pub_enter.csv` / `inputs/ws_pan_right.csv`; exit 2 = fixtures
  missing (fresh clone). `--report-only` prints the census for calibration.
- **Matrix result (PASS, 4 cases x 3 widths, ~2.6 s wall):** world map
  margins 0 % (pillarbox exact) at every width; pub and battle 100 % filled;
  center 0/38,400 differing everywhere; stale guard 96.2 / 92.2 / 81.4 %
  idle-vs-pan margin change at 320/384/448.
- **Capability raised:** `opts.max_view_width` 320 -> 448 plus resize-driven
  view enabled (`resize_driven_view = true`, `max_resize_view_width = 448`).
  `--resize-view` is now authorized (windowed by design; headless stays
  faithful 240). Default remains 240.
- **Gotcha (fixture budgets):** `--frames` is the frame count run AFTER a
  state load, NOT an absolute guest target; the budget must cover the input
  CSV's absolute-guest-frame events (each case in `ws_check.py` notes its
  guest end frame). The first calibration pass ran 51,917-frame marathons
  (~3 min/run) because of this reading; corrected runs are ~1 s.
- Gate integration: `check.py` gains `ws_smoke` (9 checks total).

## W3 milestone 3: transitions + lifecycle migration — LANDED (2026-10-08) — W3 COMPLETE

- **Transitions verified (probe frames recorded per case):** world->pub entry
  fades through full black (guest 52027: center and margins all 0), then the
  pub fades in with the margins dimming *with* the center (guest 52067:
  margin max 249 = center max 249, means track). Leaving the pub (B@52120,
  fixture `inputs/ws_pub_exit.csv`) fades through black again and the world
  map returns pillarboxed (guest 52347: margins exactly 0, center mean 179).
  Ring pans/recenters refresh the margins (stale guard). The margins sample
  the same BG layers through the same compositor as the center, so
  engine-wide effects (BLDY fades) apply uniformly — no transition-specific
  policy needed; the smoke test locks the invariant in: margins may be black
  or dim with the scene, never brighter than the center (+8 tolerance).
- **Smoke test now 6 cases x 3 widths:** world_idle, pub_idle, **pub_fade**
  (transition invariant), **pub_exit** (pillarbox restored after leaving the
  pub), battle_idle, battle_pan + stale guard.
- **Lifecycle migration:** game-owned hooks install through the trusted
  activation pass — `gba_mod_register_reset_callback` (clears presentation
  state, then re-arms the lzss entry guard after the engine's disable-all)
  and `gba_mod_register_activation_plugin("ffta.widescreen", ...)` (installs
  the authored-margin hooks). Manifest
  `mods/preloaded/packages/ffta.enhancement.widescreen/1.0.0/manifest.toml`
  (feature `widescreen`, default-enabled, target `ffta-us` + ROM SHA-1),
  shipped to `<exe>/mods` by a CMake POST_BUILD rule; `opts.mod_game_id =
  "ffta-us"` enables the pass. `extended_view_init` is gone; the per-frame
  policy stays as `extended_view_frame` (game code, not a hook the runner
  clears). Feature-disabled fallback verified: engine-default margin
  sampling returns (the OBJ clip + UI-layer skip are the plugin-owned
  polish); the game runs and the per-scene policy still applies.
- **Framework race fixed (patched):** parallel launches each publish
  `mods/state.toml`; the shared `state.toml.tmp` name let one process's
  rename consume another's file (ENOENT), whose retry then removed the
  freshly published output. Patch
  `tools/patches/mod-state-publish-race.patch` (unique per-PID temp;
  exported + reverse-checked); 4/4 parallel smoke runs clean after.
- Gates: `cycle` PASS (attract byte-exact); `check.py` 9/9 (the patches
  check now validates 4 patch files); `ws_smoke` 6 cases x 3 widths PASS.

## Probe recipes used (reproducible)

- State vars: TCP `savestate_save` before/after an action; byte-diff the
  GBAS files (file offsets map ~linearly into EWRAM: offset = guest -
  0x02000000 + 0xFC in the 2026-10-08 container).
- Code touching a var: FP ring (`GBARECOMP_INSN_TRACE=1` +
  `GBARECOMP_FP_SAVE=path`; dumped on every clean exit) + `tools/ringscan.py
  --reg/--reg-range`.
- Writer/caller chain: `GBARECOMP_ABORT_ON_MEM_WRITE_ADDR` (+
  `GBARECOMP_RUNTIME_TRACE=1`) — works for RAM/VRAM, NOT for IO registers.
- Guest DMA attribution: `GBARECOMP_DMA_WATCH_ADDR`.
