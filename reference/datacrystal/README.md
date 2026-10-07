# Data Crystal — Final Fantasy Tactics Advance pages (recovered)

Community wiki pages for FFTA, recovered from the Wayback Machine
(2021-06-14 snapshot of `datacrystal.romhacking.net`, via user-supplied
HTML), text-extracted 2026-10-07. Content © Data Crystal contributors,
GFDL 1.2. These are reference notes only — never generated from or into
the ROM.

Highlights:
- `Scripting.txt` — event-VM opcode table (execute callback, fade, set map,
  message box, …) — the documentation layer for the interpreter family at
  `0x08122xxx–0x08123xxx`.
- `Compression Formats.txt` — decompressor entry ~`0x0801F100` (type byte
  0x10/0x01/0x11; unmatched -> `bl 0x08141868`, the SWI-thunk bank);
  LZSS derivative with track-back copies and `0x1000`-word zero fills;
  C# reference implementation.
- `RAM map.txt` — sparse: day/time `0x02002FBA..BF`, mission items
  `0x02002B08` (64 x 4-byte).
- `ROM map.txt`, `Maps.txt`, `Jobs.txt`, `Abilities.txt`, `String
  Tables.txt` — data tables for future symbol annotation.
