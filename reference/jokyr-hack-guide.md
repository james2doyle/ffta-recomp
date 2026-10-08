# JoKyR — "Advanced Hacking Guide" (GameFAQs, 2005) reference summary

Source: https://gamefaqs.gamespot.com/gba/560436-final-fantasy-tactics-advance/faqs/40618
(JoKyR, v2.0, US version; cc-by-nc-sa-era GameFAQs terms — facts extracted with
attribution; guide not committed). Verified against our build/ROM 2026-10-07.

## Verified live (state2 probe, post-scene-rebuild)

- **Party unit array**: base `0x02000000`, **stride 0x108**, 24 slots.
  - name pointer at `+0x80` (char1 → `0x02001F1C`; matches the guide's default)
  - level byte at `+0x89` (read = 3, in the documented 0–50 range)
  - imported as `gPartyUnits` (0x18C0 span) + `gPartyNameBuffer`.
- **Growth-item counters**: `0x02002031..34` (Sequence / Sapere Aude /
  Peytral / Acacia Hat), 8-bit each, +1 per associated mission, max 0xFF;
  read 0 (consistent — those are tournament/link missions). Imported as
  `gGrowthItemCounters`.

## Verified ROM-side

- Name strings in ROM use the **8-bit scheme**: `0x01` start byte, then
  char bytes (`16-bit value >> 8 + 1`), `0x00` terminator. Checked
  `0x085512C7`: `01` + 9 chars + `00` = "Montblanc" — matches the guide.

## Mechanics notes

- Character level (0x00–0x32) has **no direct stat effect**; it drives
  dispatch-mission competence and **enemy level scaling** (average party
  level); level-ups (stat gains) are independent of level.
- Growth items: stat = base + counter (cap 255); mission lists listed in the
  guide (Sequence: 40 + Link 1–3, Sapere Aude: 41 + Link 4–6, Peytral: 43,
  Acacia Hat: 42 + Link 7–9).
- Names: two schemes — 16-bit (main/clan, `0x0000` terminator, truncatable by
  pointer offset) and 8-bit (NPC/ROM strings, `0x01` start). Pointers live in
  the party array; scheme is interchangeable in practice (per guide).

## Leads

- The guide repeatedly cites **Terence Fergusson's Mechanics Guide**
  (formulas/lists) and TetrisTheMovie's name-changer guide — candidates for
  the next fetch. Labmaster's hacking primers were the author's source.

## Probe pitfall (learned here)

TCP RAM reads after `--load-state` can lag the scene's EWRAM rebuild
(paragraph above: 0 nonzero @60f → 730 @300f → 5.5k @600f). Wait ≥600 frames
before trusting EWRAM reads on a loaded state; IWRAM is live from the start.
