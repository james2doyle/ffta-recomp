# reference/ — study notes, sources, and credits

The research layer of the project: engine studies, harness gotchas, the
oracle protocol, and the community research this recompilation builds on —
with attribution. Redistribution terms for anything included in the repo
live in [THIRD_PARTY_ATTRIBUTION.md](../THIRD_PARTY_ATTRIBUTION.md).

## Study notes

| Note | What |
|---|---|
| [dev-gotchas.md](dev-gotchas.md) | Harness traps: run modes, capture envs, close handling, RAM dispatch, saves, submodule pins, fork sync, Android device forensics |
| [oracle-harness.md](oracle-harness.md) | The mGBA frame-diff oracle: park phase, sync rules, builds |
| [widescreen.md](widescreen.md) | Widescreen internals + validation |
| [upscale-shaders.md](upscale-shaders.md) | Upscale-shader rationale: sharp scaling, pixel grid, and the >3× crossover |
| [event-vm.md](event-vm.md) | The event interpreter (VM) + scripts |
| [gba-bios-boot-and-spsr.md](gba-bios-boot-and-spsr.md) | BIOS boot/SoftReset/System-SPSR semantics, validated vs GBATEK + mGBA source |
| [ffta-decomp.md](ffta-decomp.md), [fergusson-mechanics.md](fergusson-mechanics.md), [bcrobert-notes.md](bcrobert-notes.md), [jokyr-hack-guide.md](jokyr-hack-guide.md), [ffta-gamefaqs-code-guides.md](ffta-gamefaqs-code-guides.md) | Community source summaries (decomp, engine hacks, FAQs, notes) |
| [datacrystal/](datacrystal/) | Recovered Data Crystal wiki pages, redistributed under GFDL 1.2 — see [datacrystal/README.md](datacrystal/README.md) |

## Sources used (reference only, with attribution)

- [mstan/gbarecomp](https://github.com/mstan/gbarecomp) — the
  recompilation framework (read its `PRINCIPLES.md`, `DEBUG.md`,
  `docs/TOML_SCHEMA.md`); the pre-boot launch screen is the framework
  fork's ([james2doyle/gbarecompx](https://github.com/james2doyle/gbarecompx))
  raygui launcher.
- [mstan/EmeraldRecomp](https://github.com/mstan/EmeraldRecomp) and
  [mstan/WarioWareTwistedRecomp](https://github.com/mstan/WarioWareTwistedRecomp) —
  reference implementations for the widescreen margin/UI-anchoring model
  (studied for [widescreen.md](widescreen.md)).
- [Data Crystal wiki](https://datacrystal.tcrf.net/) — FFTA ROM/RAM maps,
  scripting and compression pages (via the Wayback Machine).
- [LeonarthCG/FFTA_Engine_Hacks](https://github.com/LeonarthCG/FFTA_Engine_Hacks) —
  the address index behind the engine studies.
- [spiiin/FFTAUtils](https://github.com/spiiin/FFTAUtils) — map-data
  formats, verified data regions.
- [charlie-troy/ffta-decomp](https://github.com/charlie-troy/ffta-decomp) —
  revision-exact partial decompilation, used for naming and cross-checks
  (**no license — its sources/logs are never ingested; reference only**).
- [FFHacktics](https://ffhacktics.com/) forum — long-running FFTA research.

Every ROM claim in the project is re-verified with `gbarecompx/tools/disarm.py`
disassembly and cited; community sources are the map, never the evidence.

## Thanks

Nothing here would exist without work other people shared:

- **[mstan](https://github.com/mstan)** — the
  [gbarecomp](https://github.com/mstan/gbarecomp) framework (and the
  recomp-ui runtime UI it shipped through most of this project's life),
  plus the reference-game recompilations and the R.A.I.D. community
  around them.
- **Bregalad and loveemu** — "GBA Mus Ripper" / `sappy_detector.c` behind
  the m4a engine detection ([berg8793](https://github.com/berg8793/gba-mus-ripper)
  and [CaptainSwag101](https://github.com/CaptainSwag101/gba-mus-ripper)
  forks for cross-checking).
- **The [Data Crystal](https://datacrystal.tcrf.net/) contributors** —
  FFTA ROM/RAM maps, scripting and compression pages.
- **[LeonarthCG](https://github.com/LeonarthCG)** —
  [FFTA_Engine_Hacks](https://github.com/LeonarthCG/FFTA_Engine_Hacks), the
  address index behind the engine studies.
- **[charlie-troy](https://github.com/charlie-troy)** —
  [ffta-decomp](https://github.com/charlie-troy/ffta-decomp), used for
  naming and cross-checks.
- **[spiiin](https://github.com/spiiin)** —
  [FFTAUtils](https://github.com/spiiin/FFTAUtils): map-data formats,
  verified data regions.
- **BCROBERT, JoKyR, Terence Fergusson, and the GameFAQs code-guide authors
  (Adrammelech, labmaster, TetrisTheMovie, Vegikachu)** — structures and
  formulas.
- **The [FFHacktics](https://ffhacktics.com/) community** — long-running
  FFTA research that made all of this findable.
- **The [mGBA](https://mgba.io/) project** — the differential-testing
  oracle.
