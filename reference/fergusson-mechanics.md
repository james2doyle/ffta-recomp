# Terence Fergusson — FFTA Mechanics Guide (GameFAQs 26262) reference summary

Full copy archived OUTSIDE the repo in a local reference mirror
(`ffta-gamefaqs/fergusson_mechanics.txt`; v0.95, 552 KB, 9,093 lines;
plain-text mirror `alexandria.rpgclassics.com`). Facts summarized with
attribution; the document itself is not committed.

## Section index (line numbers in the full copy)

Definitions (106) · RNG (196) · Ability Effects (313) · Facing (350) · Basic
Hit Rates (393) · Damage Formula (743) · Combos (1064) · Turn Order (1220) ·
Misc Combat Data (1463) · Quests (1554) · Your Clan (1748) · Monster Bank
(2088) · Unit Generation (2307) · Recruitment (2695) · Mission Items (3047) ·
Appendix I: Ability Data (3243).

## Core formulas (condensed)

- **Damage** ≈ `(Att − Def/2) × Power/100`, with a long modifier chain:
  support/status multipliers as N/256 (e.g. Weapon Atk+ 307/256; Turbo MP
  332/256; Berserk 307/256; Frog 25/256; Boost 384/256), caps at 999,
  minimum 1, elemental stage (Absorb > Null > Resist > Weak; Weak ×3/2,
  Resist ×1/2, Absorb negates), critical ×3/2, Expert Guard → 0, then
  random variance ±10%. Attribute sources differ for physical (WAtk/WDef)
  vs magical (MPow/MRes); mission-item bonuses apply per-step.
- **Element-enhancement bug** (documented): enhancement not "used up" for
  Ice/Lightning/Water/Holy/Dark → multiple gear enhancements stack for those
  elements; Fire/Wind/Earth are immune.
- **Combos**: if ≥1 ally joins, multiplier = `base × (10 + 4·JP)/10`
  (a 10-JP combo ≈ 550%); every combo has its own join range and join
  chance (100% for Thief/Ninja/Dragoon/Killer/Morpher etc.). JP is spent
  whether or not allies join; solo combo = normal Fight damage at 100% hit.
- **Hit rates / facing / turn order / RNG**: dedicated sections in the full
  copy — the validation reference for battle behavior.

## Use

- Validation: expected values for battle-math spot-checks against our build.
- Mods: the arithmetic behind the BCROBERT byte-site mods (accuracy, Parley,
  combo cap) and any rebalance work.
- Ports/documentation: the canonical data-model math for a rewrite.

Appendix I ("Ability Data", from line 3243) is effectively a full ability
table dump — useful as cross-reference data, not to be committed.
