# Event VM reference — interpreter family 0x08122xxx-0x08123xxx

Facts gathered 2026-10-07 (engine-hacks patch comments + charlie-troy/ffta-decomp
docs + our own disassembly + `tools/eventcrawl.py`) and extended 2026-10-11
(LeonarthCG/FFTA_Event_Editor opcode definitions cross-checked against our ROM;
BRINGUP § 2026-10-11). Verify claims with `tools/disarm.py` before acting;
cite this file's addresses.

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

## The two VMs (2026-10-11: editor definitions verified against our ROM)

The 0x08122xxx-0x08123xxx region is the **scene/cutscene script VM**, driven by
the dispatch table **gSceneOpcodeTable @0x083A7EE4**: 114 valid entries × 6 B
(u16 opcode size + u32 thumb handler). A second, smaller VM handles
**conditionals**, driven by **gCondOpcodeTable @0x0836D5A4** (17 entries × 6 B).
Opcode *sizes* from the editor match our ROM 114/114 and 17/17; handler PCs
were read from our ROM (the editor's in-code handler addresses are EUR-ROM —
never import them; symbols file § 19 documents the trap).

- Event record (`gEventList` @0x08A19970): 234 × 4 B {script, scene, text-list,
  pad}; the text list equals the script id **except text list 61 = hardcoded
  no dialogue**; pad byte is 0 in all 234 entries.
- Conditional types (8, per `gConditionalTypeList` @0x08A1A908 → per-type
  lists): Map node reached / Map node selected / Mission accepted / Turn start /
  Action start / Action end / Turn end / Victory condition met.
- Scene VM concurrency model: THREAD / THREAD_WITH_TAG / JOIN / JOIN_TAG
  (tag-join threads); terminators END (0x02), GO_TO (0x19), op 0x17; branches
  carry signed halfword offsets (`s_half_arg`).
- Text engine control codes (0x40-prefixed): VARNAME 0x25, SPACE 0x3E, CLS 0x63,
  NL 0x6E, NAME 0x72, WS 0x73, WAIT 0x74 (+ which take extra bytes).
- The editor's LZSS decompressor is the same format as `lzss_decompress`
  (0x0800543C): BE length at src+0, stream at src+4 — independent confirmation.
- Named handler rows live in `symbols/ffta_symbols.tsv` § 19
  (`scene_*` / `cond_*`); table + pointer-cell rows in
  `symbols/ffta_data_symbols.tsv` § 16.

## VM mechanics (from engine-hacks hook sources)

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
| 0x08122A00 | scene op 0x70 handler entry (per gSceneOpcodeTable @0x083A7EE4; the "enclosing unit" note below referred to pre-table backscan) | dispatch table, verified 2026-10-11 |
| 0x08123670 | battle event-VM spawn command (interior of an emitted span) | ffta-decomp docs/ai-findings.md:879 |
| 0x08123860 | unit containing the "healing opcode" patch site | engine-hacks _MasterHackInstaller.event:58 |
| 0x0812386C | healing opcode patch site ("end of any mission") | same |
| 0x08123898 | mission script-trigger (reads mission table 0x08563A70 +0x01) | ffta-decomp docs/mission-data.md:359-365 |
| 0x08123B68 | unit containing the death-opcode patch site | engine-hacks Ironman/Ironman.event:8 |
| 0x08123B7C | death-opcode patch site | same |
| 0x08125578 | "get character pointer" | engine-hacks checkDeath.s:19,41 |

Name-only symbol rows for the emitted primaries live in
`symbols/ffta_symbols.tsv` § 5 (anchors) and § 19 (full opcode-handler maps).
Interiors stay documented here (seeding an interior is the interior-split
hazard — see BRINGUP § offline push).

## Related recognition anchors (decompressor family)

- **0x0801F098** = the decompressor's real entry (the older 0x0801F100 anchor
  is an interior offset). Body: u16-LE length header, decode loop into a base
  register — recognized during the summon-hang hunts (BRINGUP § "Summon crash").
- **0x08141868** = single SWI 0x0C (CpuFastSet) thunk; sits on the
  decompressor's SWI path.
- **0x0800543C** = the LZSS decoder with the runtime entry guard
  (`[[mod_function_hook]]` → `ffta.lzss-guard`; BRINGUP § "Summon crash").
