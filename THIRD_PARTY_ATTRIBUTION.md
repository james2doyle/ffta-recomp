# Third-Party Attribution

FFTA Recomp's own code and documentation are licensed PolyForm
Noncommercial 1.0.0 (see `LICENSE`). This file lists the third-party work
the project builds on or derives from, and the terms that apply. **No game
content is included in this repository**: no ROMs, BIOS dumps, game
graphics/text/audio, saves, or recompiled output — everything runs from
user-supplied dumps.

## Framework submodules

| Component | Upstream | License |
|---|---|---|
| `gbarecomp/` | <https://github.com/mstan/gbarecomp> | PolyForm Noncommercial 1.0.0, © 2026 Matthew Stanley |
| `recomp-ui/` | (same author) | MIT, © 2026 Matthew Stanley |

Working-tree patches in `tools/patches/` modify gbarecomp sources; patched
copies remain under gbarecomp's terms (see `tools/patches/README.md`).

## Oracle tooling

`gbarecomp/oracle/setup-mgba.sh` clones
[mgba-emu/mgba](https://github.com/mgba-emu/mgba) (MPL-2.0) into an ignored
`third_party/` directory to build the frame-diff oracle. Not tracked, not
redistributed here.

## Ported tool

| Our file | Upstream | What | Terms |
|---|---|---|---|
| `tools/m4a_detect.py` | Bregalad & loveemu — `sappy_detector.c` ("GBA Mus Ripper" lineage; forks: [berg8793](https://github.com/berg8793/gba-mus-ripper), [CaptainSwag101](https://github.com/CaptainSwag101/gba-mus-ripper)) | Faithful Python port of the Sappy/m4a engine-detection logic | Upstream states: "GBAMusRipper is free and open source software. Anyone is free to redistribute it ... but just give me (Bregalad) credit." Credit is given in the file header; no formal upstream license text exists. |

## Patterns (approach credited; no code copied)

| Our file | Pattern from | Note |
|---|---|---|
| `tools/attract_check.py` | [mstan/WarioWareTwistedRecomp](https://github.com/mstan/WarioWareTwistedRecomp) `tools/verify-attract.ps1` (PolyForm NC 1.0.0) | Same workflow — headless fixed-frame run with a pinned frame hash — independently implemented in Python. |
| `src/ffta_ram_dispatch.h` | [mstan/EmeraldRecomp](https://github.com/mstan/EmeraldRecomp) `src/emerald_ram_dispatch.h` (PolyForm NC 1.0.0) | Uses gbarecomp's sanctioned `g_runtime_ram_dispatch_hook` extension point; the FFTA-specific byte-verification logic is original. |

## Reference material (not redistributed)

Community research is used as reference only, with attribution (see
`BRINGUP.md` studies): Data Crystal wiki, LeonarthCG/FFTA_Engine_Hacks,
spiiin/FFTAUtils, charlie-troy/ffta-decomp (**no license** — facts and
addresses referenced; its sources/logs are never ingested), and the
JoKyR / BCROBERT / GameFAQs guide authors (facts and brief attributed
quotes only; full copies are not distributed with this repository).

### Data Crystal pages (the one included exception)

`reference/datacrystal/` holds text extractions of recovered
`datacrystal.romhacking.net` wiki pages, redistributed under the **GNU Free
Documentation License 1.2** — full license text in
`reference/datacrystal/LICENSE-GFDL-1.2.txt`, attribution and source links in
`reference/datacrystal/README.md`. Those files stay under GFDL 1.2; the rest
of the repository is PolyForm Noncommercial 1.0.0. (The recovered
string-tables dump is **not** included — it is ROM-extracted game text,
and is not distributed with this repo.)
