# BCROBERT — "FFTA notes v12.2" reference summary

Preserved copy: local reference mirror outside the repo (directory
`ffta-notes-bcrobert`; pack dated 2013–2015; author BCROBERT, hacking
credits include Darthatron). Facts extracted below with attribution; the
pack itself is reference-only and is not committed.

## What was harvested (2026-10-07)

- `BASIC ROM MAP.txt` (~70 offsets) → table names imported to
  `symbols/ffta_data_symbols.tsv` (item/job/unit/law/ability data, mission
  families, treasure-hunt tables, text anchors; offsets +0x08000000).
- `"get speed formula"` (0x0812E368) → named in `symbols/ffta_symbols.tsv`;
  disarm-verified thumb `push {r4,r5,lr}` prologue.
- `structures.txt` record layouts (see below) — kept as reference for
  validation work, not as symbols.
- `minor hacks.txt` byte sites — future mod-layer candidates (see below).
- `ID values/` (races, elements, classes, items, item effects, ability
  effects, passive/reaction abilities, worn-on) — value tables for
  test-data and cross-checks.

## Record layouts (structures.txt highlights)

- Item `0x0851D1A0`, Job `0x08521A14`, Job requirements `0x085231A4`,
  Recruitment `0x08529788`, Unit `0x0852A4D0`, Laws `0x08528F34`,
  Ability `0x0855187C` (matches our `gAbilityTable`), Ability effects
  `0x08553E70`, Combo `0x0852736C`.
- Ability `properties` bitfield key: R = Reflectable, I = Ignore Reaction,
  O = Offensive, # = self-target, & = return-magic trigger, S = Stealable,
  X = Cover-blocked, L = Learning trigger, B = Beastmaster, M = silenced-OK,
  C = double-cast, @ = Morpher, P = physical, A = absorb-MP, T = throw.
- Mission record field offsets (month, deadline, dispatch duration, item
  rewards, law-card rewards, clan points, XP, gold×200, AP×10, recruit
  index, mission-item requirements, skill/level/job requirements, cost×200).
- Treasure hunt structures: `0x08391BBC` (4), `0x08391BD0` (3),
  `0x08391BE8` (2), `0x08391C08` (2+2), `0x08391C78` (random).

## Verified cross-checks

- 0x0812E368 speed formula ✓ (our disarm study); Parley KO scaling at
  0x0812D3D4/D3F4 ✓ (matches our earlier BRINGUP verification).
- Item data 0x0851D1A0 ↔ DataCrystal structures agree; ability data
  0x0855187C = our `gAbilityTable`.

## Mechanics worth remembering

- **Ability use is restricted by available animations.** "If they use an
  ability and the game freezes, it is generally because they have no sprite
  stored at the location designated by the ability." (Resonates with our
  summon/ability hang hunts — keep in mind when a freeze is ability-shaped.)
- "Last Quicken" calls Quicken's data — ability substitution propagates.
- Card shop: 10–20 random cards; odds 65/25/5/5 (first 20 / next 20 /
  Dmg2 / ranked antilaw).
- Combo multiplier scales with JP up to 5× (cap site 0x0813049A).
- Revival restores 50% max HP (site 0x08131A6A).

## Future mod-layer candidates (byte sites)

Level cap 0x080C9BAE/0x080C9BAA; EXP gain 0x0812E658; accuracy modifiers
0x0812C61E/62C/648/656/664 and 0x0812D1C6/D4; MP regen 0x08093096; MP gen
0x080C98F2; Parley cap 0x0812D3D4; Damage>MP rollover 0x080A256A/0x080A2C88.
