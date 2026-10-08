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
- The per-frame display-register commit (39-halfword DMA block copy, kick pc
  ~0x0800073C) also has no named entry — see § "Scroll register apply".

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

## Display facts (world map + battle, mode 0)

- Four BGs enabled. **BG0/BG1 = field layers**, tilemaps 256x512 (size=2):
  BG0 at screenblock 0x5000 (blocks 0x5000+0x5800), BG1 at 0x6000
  (+0x6800); both are only **256 px wide** — the core widescreen obstacle.
- BG2 (0x7000) / BG3 (0x7800) = static 256x256 UI. Mode 0, 16/256-color mix.
- Vertical scroll pans via the tilemap wrap; horizontal h stayed 0 at every
  reachable world-map node (travel east unresolved — needs a node whose
  camera actually clamps h > 0, or a battle-map probe).

## World-map camera state (battle field TBD — likely same family)

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
  the DMA CNT field (kick pc 0x0800073C; the 0x0800072x-3C sequence sets the
  channel up, helper form `str r0,[r2,#8]` at 0x080013E0) executes the whole
  transfer while the flag is set, so every destination write was swallowed.
  Fixed by per-call record control — patch
  `tools/patches/mmio-cap-dma-reentrancy.patch`; see BRINGUP § "MMIO cap gap".
- **What the fixed cap shows** (world-map recenter repro): the display commit
  is a per-frame **DMA block copy** of a shadow struct — 39 halfwords
  `0x04000008..0x04000054` (BGxCNT/HOFS/VOFS, affine, windows, blend), one
  copy per frame, kick pc 0x0800073C; during the pan the copied VOFS values
  step 0x97→0xA1 in lockstep with the camera ease.

## W1b — the strip drawer (still open; leads)

The 256-wide tilemaps hold the drawn strip. Within-map pans need no redraw
(FP ring: zero VRAM-range register touches during pans), so the drawer runs
on scene/map load (world-map entry, map transitions, possibly long node
jumps). Next probes:
- Watch VRAM (abort-on-write 0x06005000 / 0x06006000) during world-map
  ENTRY (from a menu/battle), and during battle map entry.
- The struct pointers +0x02/+0x0A and DataCrystal `gMap*` fields
  (gMapTileData 0x02007CB0 et al.) are the likely inputs of that drawer.
- Static BL scan is weak here (pointer tables/`bx`); prefer runtime traps.

## W2 sketch (unchanged, sharpened)

1. Widen the field tilemap (relocate BG0/BG1 to 512-wide, size=3) and extend
   the loader/drawer to fill the extra columns (43+ px per side for 320).
2. Camera bias: with the DMA-apply path identified, the cleanest hook is the
   camera struct/update (add (W-240)/2 offset at apply time), avoiding
   touching the guest's DMA helper.
3. Policy: wide only where margins are materialized (world map, battle
   field); menus/UI pillarbox (static BGs).

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
