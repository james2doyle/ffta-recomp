# ffta-decomp (charlie-troy) — reference summary

Cloned reference material for the annotation pass. The clone lives **outside
this repo** at `/home/james/Git/refs/ffta-decomp` (re-clone:
https://github.com/charlie-troy/ffta-decomp). It pins the same ROM
(`rom_sha1 4ac05441f4de70a4ec3dd932116346c61b8783d9`).

## What it contains (surveyed 2026-10-07)

- `data/functions.json` — 173 byte-matched functions, all `sub_*`-named and
  already present in `symbols/ffta_symbols.tsv`. No function-name windfall.
- `data/manual_functions.json` — 18 more auto-named entries.
- `data/asm_symbols.txt` — still-assembly call targets; **3 real names**,
  imported to `symbols/ffta_data_symbols.tsv`:
  `UnitStat 0x080C7EA4`, `AbilityProp 0x080CCD50`, `AbilityMpCost 0x0812ED98`.
- `data/sym_{rom,ewram,iwram,driver_fns}.txt` — small registries; the audio
  driver file carries descriptive m4a names worth seeding/naming later:
  dispatcher `0x08141500`; sound-task step `0x08141520`; song-start-shaped
  `0x08141540`; stop/start variant `0x08141570`; song→player readers
  `0x081451C0`/`0x081452C0`; player status `0x081452F4`; command dispatcher
  `0x0814513C`.
- `docs/` — **38 analysis docs** (battle/AI weighted). Highest-value for us:
  `turn-order.md`, `unit-struct.md`, `unit-flags.md`, `unit-ai-table.md`,
  `ai-evaluator-cfg.md`, `ai-evaluator-cases.md`, `ai-case-rules.md`,
  `ai-strategy-profiles.md`, `ai-effect-status-map.md`, `ability-table.md`,
  `item-table.md`, `job-table.md`, `mission-data.md`, `map-data.md`,
  `audio-driver.md`, `text.md`, `validation.md`, `battle-fixtures.md`,
  `whole-battle-trace.md`, plus a `receipts/` directory.
- `src/batchN/sub_*.c` + `asm/` — the partial decomp sources (auto-named).

## Companion: FFTA_Engine_Hacks (LeonarthCG)

`/home/james/Git/refs/FFTA_Engine_Hacks` — job/race customization docs, a
per-animation data tree (`Engine Hacks/jobAndRaceCustomization/…`), and an
Event-Assembler buildfile. Mostly mod-facing data; the address→description
index was already consumed into BRINGUP (§ FFTA_Engine_Hacks study).

## Use

- **Naming**: data names are behavior-neutral (imported freely); function
  seeds are attract-gated and route-gated (see the playbook's coverage
  strategy).
- **Understanding**: read the docs when debugging or validating battle/AI/
  audio behavior — turn order, AI evaluator cases, unit-struct fields, MP2K
  tables — instead of re-deriving.
- Cite and summarize; do not commit the clone or bulk-copy its docs.
