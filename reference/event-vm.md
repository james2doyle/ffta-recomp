# Event VM reference — interpreter family 0x08122xxx-0x08123xxx

Facts gathered 2026-10-07 (engine-hacks patch comments + charlie-troy/ffta-decomp
docs + our own disassembly + `tools/eventcrawl.py`). Verify claims with
`tools/disarm.py` before acting; cite this file's addresses.

## Script storage (validated by tools/eventcrawl.py)

- Master table **0x089A5D54**: 62 monotonic u32 entries, value = target − table
  base; entry0 = 0xF8 = table byte size (62 × 4).
- Each block base starts with `u32 size` (multiple of 4); `count = size/4`;
  entries are block-relative offsets to scripts.
- **213 unique scripts**, 0x089A5E6C..0x089C12C3; the script region ends
  ~0x089C1480 (a different table follows).
- Scripts are raw bytes: 1-byte opcode + inline operands, **no headers**.
- **Scripts carry no code pointers** (eventcrawl scan: 353 address-shaped byte
  runs = operand collisions, 1 false-positive push, 0 real). Code is reached
  via opcodes only — there is nothing to seed from script bytes directly.

## VM mechanics (from engine-hacks hook sources)

- `r7` = instruction pointer (opcode 0x13's first arg read at `[r7+1]`,
  checked vs 0xFE at 0x0812267C).
- `r4` ≈ instruction pointer, `r5` ≈ VM context: next-script pointer stored at
  `[r5+0xC]`; operands read from `[r4+1..3]`
  (FFTA_Engine_Hacks/Ironman/checkDeath.s:62-72).
- Opcode semantics: see `reference/datacrystal/…Scripting.txt` (full opcode
  list; operand widths partially documented — do NOT walk scripts linearly
  without exact widths).

## Anchor PCs (roles: engine-hacks comments / decomp docs; naming-only)

| Address | Role | Evidence |
|---|---|---|
| 0x08122680 | opcode 0x13 first-argument handling (0xFE→0xFF) | engine-hacks jobAndRaceCustomization.event:47 |
| 0x08122AAA | opcode 0x70 handling ("never skip events") | same file:48 |
| 0x08122A00 | enclosing unit of the 0x70 case (interior; not a dispatch row) | disarm backscan |
| 0x08123670 | battle event-VM spawn command (interior of an emitted span) | ffta-decomp docs/ai-findings.md:879 |
| 0x08123860 | unit containing the "healing opcode" patch site | engine-hacks _MasterHackInstaller.event:58 |
| 0x0812386C | healing opcode patch site ("end of any mission") | same |
| 0x08123898 | mission script-trigger (reads mission table 0x08563A70 +0x01) | ffta-decomp docs/mission-data.md:359-365 |
| 0x08123B68 | unit containing the death-opcode patch site | engine-hacks Ironman/Ironman.event:8 |
| 0x08123B7C | death-opcode patch site | same |
| 0x08125578 | "get character pointer" | engine-hacks checkDeath.s:19,41 |

Name-only symbol rows for the emitted primaries live in
`symbols/ffta_symbols.tsv` § 5. Interiors stay documented here (seeding an
interior is the interior-split hazard — see BRINGUP § offline push).

## Related recognition anchors (decompressor family)

- **0x0801F098** = the decompressor's real entry (the older 0x0801F100 anchor
  is an interior offset). Body: u16-LE length header, decode loop into a base
  register — recognized during the summon-hang hunts (BRINGUP § "Summon crash").
- **0x08141868** = single SWI 0x0C (CpuFastSet) thunk; sits on the
  decompressor's SWI path.
- **0x0800543C** = the LZSS decoder with the runtime entry guard
  (`[[mod_function_hook]]` → `ffta.lzss-guard`; BRINGUP § "Summon crash").
