# GameFAQs code compilations — reference summary (25621 / 26118 / 27385 / 22129)

Four community documents swept 2026-10-07 (copies in a local reference
mirror, `ffta-gamefaqs/`; facts extracted with attribution, not
committed wholesale):

| FAQ | Author | What it holds | Harvest |
|---|---|---|---|
| 27385 | TetrisTheMovie | Clan/Hero name changer: name buffers + 16-bit letter table | `gClanNameBuffer` (+ letter mapping), clan-name terminator trick |
| 25621 | Adrammelech | Codebreaker compilation: per-slot stat codes, money, laws, clan skills, abilities | field-map addresses (see below) |
| 26118 | labmaster | 350 KB patch-code list (items, monsters, clan, battle, slot modifiers) | **queued deep-mine** — the full copy is archived |
| 22129 | Vegikachu | GSA codes (US + JP) | mostly redundant; JP section noted |

## Verified live on our build (state2, 2026-10-07)

- `gMoney` = **0x02001F64** — read **5000** (the player's actual gold).
- `gClanNameBuffer` = **0x020021A0** — decoded `BD80 DE80 DD80 DC80 E280 0000`
  via the 16-bit table = **"Nutsy"** (the default clan name) — exact match.
- `gClanSkills` = 0x020021B6 (8 × u16) — read `[1,0,…]` (plausible).
- `gBattleLaws` = 0x02003C34 (3 bytes) — read 0 in state2 (caveat: laws may
  live elsewhere / judge-off context).

## Unit-record field offsets (two guides agree; base+stride verified in the

JoKyR note: base 0x02000000, stride 0x108)

name-ptr **+0x80** · level **+0x89** (0x8A appears in one code — likely XP
byte; JoKyR's 0x89 verified live) · HP cur/max **+0x98/+0x9A** · MP
**+0x9C/+0x9E** · Atk **+0xA0** · Def **+0xA2** · Pow **+0xA4** · Res
**+0xA6** · abilities bitmap **+0xC0** (0x90 bytes) · Speed **+0x152** ·
JP **+0x156**.

## Cross-checks & notes

- The stat map agrees across 25621 / 26118 / 22129 (independent code sets) —
  strong convergence.
- "All Jobs & All Abilities" code = 0x48 repeats of 0xEEEE step 2 from
  +0xC0 → the abilities area is 0x90 bytes per unit.
- Code guides encode addresses in printable RAM-order; treat any single
  unverified address as a lead (verify live like `gMoney`/`gClanNameBuffer`).

## Queued

- Deep-mine `faq_26118_full.md` sections: Items (slot modifiers, item IDs),
  Monsters (bank, stats), Clan (mission items, law cards), Battle (ally
  status table), Appendices (race & job modifier) — extract further
  verified-able labels in a later pass.

## 26118 deep-mine — CLOSED (2026-10-07)

Scanned the full 350 KB copy: every code is an **encrypted CodeBreaker pair**
(8+8 hex); there are no raw addresses to extract (apparent "03xx" hits are
encrypted code-word fragments, not addresses). The usable content (per-slot
stat map) was already captured via 25621/22129, which cross-agree with it —
see Section 7 of `symbols/ffta_data_symbols.tsv`. Re-open only if a CBA
decryption is ever wired up; not needed today.
