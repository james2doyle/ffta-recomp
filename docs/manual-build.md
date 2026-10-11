# Manual build (what `build.py` automates)

Prefer `python3 build.py` (see the [Quick start](../README.md#quick-start)) —
it runs every step below idempotently and stops with an actionable hint when
something is off. This page is the reference + troubleshooting route: what the
script does, in order, so a broken step can be run by hand.

The sequence was verified end-to-end from a fresh clone on 2026-10-08
(submodules → tools → patches → BIOS → corpus → build → strict smoke +
attract gate).

**1. Clone with submodules.**
```sh
git clone <repo-url> ffta-recompiled && cd ffta-recompiled
git submodule update --init --recursive
# If a submodule worktree comes up empty, re-run with --checkout --recursive
```

**2. Place your dumps** — `game.gba` at the repo root (FFTA USA) and
`gbarecomp/bios/gba_bios.bin` (your own BIOS dump). Launch verifies both
hashes (SHA-1s in the root README) and fails loudly if either is wrong or
missing.

**3. Python venv for the tooling** (disassembler, audit harness):
```sh
uv venv .venv && uv pip install --python .venv capstone
#   (or: python3 -m venv .venv && .venv/bin/pip install capstone)
```

**4. Apply the local framework patches** (recommended — the tooling below
assumes them; the two **consolidated** `*-local.patch` files are the
canonical re-apply units — per-feature files are reference diffs whose
contexts interleave, so apply them only onto a pristine submodule, before
the consolidated ones, and only if you need the attribution history):

```sh
cd gbarecomp
git apply ../tools/patches/gbarecomp-local.patch
cd external/arm-recomp-core && git apply ../../../tools/patches/arm-recomp-core-local.patch && cd ../..
cd ..
```

`tools/check.py --only patches` guards their validity — each file must be
apply-able forward against the pristine pin (the CI condition) and
reverse against the patched tree, and the replay must byte-match the dev
tree (`tools/patches/README.md`).

**5. Build the framework tools** (one-time; re-run only after submodule
changes):
```sh
cmake -S gbarecomp -B gbarecomp/build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build gbarecomp/build --target gba_recompile gba_scan --parallel 8
```

**6. Recompile the BIOS (one-time).** Run it *from `gbarecomp/`* so the
output lands in `gbarecomp/src/runtime/generated_bios/`, and pass the
project's BIOS config — it seeds the 770 named BIOS functions and
identity-checks the dump (without it only 666 are discovered and strict
runs abort on a miss at pc `0x300`):
```sh
cd gbarecomp && ./build/gba_recompile --bios bios/gba_bios.bin \
  --config bios/gba_bios.toml && cd ..
```

**7. Generate the game's static code corpus** (also after every `game.toml`
change — `tools/cycle.py` wraps this with the sanity checks and the attract
gate):
```sh
./gbarecomp/build/gba_recompile --rom game.gba --config game.toml \
  --symbols symbols/ffta_symbols.tsv --data-symbols symbols/ffta_data_symbols.tsv \
  --out generated --max-functions 65536
```

**8. Configure and build the game binary:**
```sh
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DGBARECOMP_ENABLE_MODS=ON
cmake --build build --target FFTARecomp --parallel 8
```

(`GBARECOMP_ENABLE_MODS=ON` links the framework's mod lifecycle APIs —
activation/reset plugins, view-width requests — used by the game's
widescreen hooks; verified gate-neutral.)

**9. Sanity.** Strict, headless, no input — expect `FULLY_STATIC` in the
banner:
```sh
GBARECOMP_STRICT_STATIC=1 ./build/FFTARecomp \
  --bios gbarecomp/bios/gba_bios.bin --rom game.gba --frames 2400 --no-window
```
And optionally the attract gate, which pins the exact frame hash:
```sh
.venv/bin/python tools/attract_check.py    # PASS + exit 0 expected
```

Then play — `tools/play.sh` (guide: `tests/README.md`).

## Troubleshooting

- `build.py` stops at **dumps** → the ROM/BIOS is missing or has the wrong
  hash (expected SHA-1s in the root README); it never downloads them.
- `build.py` stops at **framework patches** → the submodule drifted from
  its pin; check `git -C gbarecomp status`.
- `gba_recompile: command not found` → step 5 was not run in this checkout.
- `generated_bios/` stays empty / BIOS never loads → step 6 was run from the
  wrong directory (`cd gbarecomp` first). If strict runs instead abort with
  a dispatch miss near pc `0x300`, step 6 ran without
  `--config bios/gba_bios.toml`.
- Launch aborts with an identity/hash error → wrong or missing dump; compare
  the SHA-1s listed in the root README.
- CMake cannot find SDL2 → install the dev package (see root README
  Requirements in Quick start).
- `import capstone` fails in tools → step 3's venv (use
  `.venv/bin/python tools/...`).
- A submodule directory is empty after cloning → step 1's retry line.
- Window refuses to close, or a session wedges → `tools/quit.py <port>`; see
  `tests/README.md` § Playtesting & debugging.
- After `game.toml` edits: regenerate (step 7) → rebuild → attract gate, i.e.
  `.venv/bin/python tools/cycle.py`.

## mGBA oracle (optional)

The mGBA oracle used by the frame-diff harness (needs network
once; distinct from a system mGBA):

```sh
cd gbarecomp && bash oracle/setup-mgba.sh \
  && cmake -B build -S . -DGBARECOMP_BUILD_ORACLE=ON \
  && cmake --build build --target gbarecomp_oracle --parallel 8
```
