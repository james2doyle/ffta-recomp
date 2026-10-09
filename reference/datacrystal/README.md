# Data Crystal — Final Fantasy Tactics Advance pages (recovered)

Community wiki pages for FFTA, recovered from the Wayback Machine
(2021 captures of `datacrystal.romhacking.net`, via user-supplied HTML; the
Wayback banner and each page's source URL/oldid are kept in-file), text-
extracted 2026-10-07.

**License:** content © Data Crystal contributors, redistributed under the
**GNU Free Documentation License 1.2** — full text in
`LICENSE-GFDL-1.2.txt`; each page's original license footer is intact.
Modifications from the originals: HTML → plain-text extraction only (no
content edits). These files stay under GFDL 1.2; the rest of the repository
is PolyForm Noncommercial 1.0.0 (`LICENSE`, `THIRD_PARTY_ATTRIBUTION.md`).

Highlights:
- `Scripting.txt` — event-VM opcode table (execute callback, fade, set map,
  message box, …) — the documentation layer for the interpreter family at
  `0x08122xxx–0x08123xxx`.
- `Compression Formats.txt` — decompressor entry ~`0x0801F100` (type byte
  0x10/0x01/0x11; unmatched -> `bl 0x08141868`, the SWI-thunk bank);
  LZSS derivative with track-back copies and `0x1000`-word zero fills.
- `RAM map.txt` — sparse: day/time `0x02002FBA..BF`, mission items
  `0x02002B08` (64 x 4-byte).
- `ROM map.txt`, `Maps.txt`, `Jobs.txt`, `Abilities.txt` — data tables for
  future symbol annotation.

Not included: the recovered **String Tables** page. It is a raw dump of the
game's in-game text ripped from the ROM, so it would put ROM-extracted text
in git — against the project's hygiene rule, so it is not distributed with
this repository.
