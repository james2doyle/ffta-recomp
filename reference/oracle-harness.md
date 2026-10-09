# Oracle & frame diff — the validation harness

Moved out of `AGENTS.md` on 2026-10-08. The harness compares our runner
against gbarecomp's **own** mGBA oracle (the framework's mGBA 0.10.5
checkout — distinct from the system mGBA install used for manual eyeballing).
History: BRINGUP § Phase 5. Framework-side docs: `gbarecomp/oracle/README.md`
and `gbarecomp/CLAUDE.md` § SYNC RULES.

## Build the oracle (one-time; needs network for the mGBA clone)

Re-run only after framework/submodule changes:

```sh
cd gbarecomp
bash oracle/setup-mgba.sh           # clones mGBA 0.10.5 -> third_party/mgba,
                                    # builds libmgba.a (~25 s)
cmake -B build -S . -DGBARECOMP_BUILD_ORACLE=ON
cmake --build build --target gbarecomp_oracle --parallel 8
```

## The server

`gbarecomp/build/oracle/gbarecomp_oracle` — TCP server, default port 19843;
args `--bios <real bios> --rom <rom> --port N`; run with cwd=`gbarecomp/`
(default BIOS path is cwd-relative). Key JSON-line commands: `emu_step`/
`emu_step_to_vblank` (one runFrame = one PPU frame), `emu_vblank_count`,
`emu_screenshot` (240x160 RGB888 hex), `read_emu_{iwram,ewram,vram,pal,oam,
rom,io}`, `emu_set_keys`, plus `emu_step_inst`/`emu_registers`/
`emu_run_until_pc`/`emu_write` for register-level captures.

The oracle **autoloads `<rom>.sav`** (patch:
`tools/patches/oracle-save-autoload.patch`, applied in the working tree —
re-apply after submodule updates); put a save copy next to a symlinked ROM
to drive save/load flows (`tools/dualrun.py probe saveflow` does this).

## Save-flow note (corrected 2026-10-07)

`--tcp` (and `--window`) set `quiet = true`, which hides the `!quiet`-guarded
boot prints (`save_loaded`, `rom_loaded`, `bios_loaded`, `input_replay`, …) —
the save **does** still load via `--save-path`. Do not use missing log lines
to infer state in these modes. (An earlier caveat claimed the serve mode
skipped the save; that was a probe artifact — BRINGUP § "Correction: two
retracted claims".)

## Comparison protocol (learned the hard way)

- Both engines park at **VBlank-start** (source-verified; the old "mGBA
  stops at the wrap" note was wrong). The real phase difference is CPU-side:
  our runner executes the VBlank IRQ handler before parking (post-handler);
  mGBA raises the IRQ and vectors it at the start of the next step
  (pre-handler). Same-index **state** reads are therefore offset by exactly
  one handler's effects (native ahead — e.g. snow RNG Δ=13 chain steps/frame
  during the title animation; BRINGUP § "park-phase semantics"). **Pixels**
  compare fine same-index (latched completed frames; static stretches
  byte-exact; bounded band diffs on mid-frame-animated content). Keep
  per-frame deltas for memory-divergence detection; use stable frames for
  golden hashes.
- Framework-ready tools: `gbarecomp/oracle/diff_cart.py` (absolute
  PAL/OAM/VRAM/IWRAM byte compare; `--native-exe ../build/FFTARecomp
  --rom ../game.gba --bios bios/gba_bios.bin`), `diff_frame.py`,
  `gba_tcp.py` (manual driver). Our wrapper: `tools/framediff.py --lo 4
  --hi 300` (spawns both engines, delta mode, JSON report to
  `/tmp/ffta_framediff/`, exit 1 on divergence).
- **Sync on hardware events** (VBlank counts), never raw frame indexes
  (gbarecomp/CLAUDE.md § SYNC RULES); debug region **writes**, not screen
  pixels, until memory matches.
- Frame dumps/saves are ROM-derived: write to `/tmp/` or `logs/`
  (gitignored) only — never commit them. Recomp-side capture envs:
  `GBARECOMP_FRAMEDUMP_DIR/_START/_COUNT` (windowed path; one PNG per guest
  frame), `--dump-png` (single frame, works `--no-window`), TCP
  `screenshot`.
