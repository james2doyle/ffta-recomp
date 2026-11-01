# Building from source

This is the source-build reference. If you only want to play, use a
[release artifact](../README.md#quick-start) — no build tools are needed.

`python3 build.py` is the one-command route: it runs every step below
idempotently and stops with an actionable hint when something is off. This
page documents the requirements, what the script does in order, the manual
pipeline, and troubleshooting.

The sequence was verified end-to-end from a fresh clone on 2026-10-08
(submodules → tools → BIOS → corpus → build → strict smoke + attract gate).

## Requirements

- Linux x86-64 host for the desktop build. The static Windows release is
  cross-compiled from the same tree (MinGW-w64; see Troubleshooting).
- CMake ≥ 3.20, Ninja, GCC or Clang with C++20, git, and Python 3.10+.
- OpenGL + X11 development headers. Debian/Ubuntu:

  ```sh
  sudo apt install libgl-dev libx11-dev libxrandr-dev libxinerama-dev \
    libxcursor-dev libxi-dev libxkbcommon-dev
  ```

- Network access on the first configure: CMake fetches pinned `raylib` and
  `toml++` sources. No system UI toolkit beyond OpenGL/X11 is required.
- `uv` (recommended) or `python3 -m venv` for the harness venv.
- The supported ROM revision: *Final Fantasy Tactics Advance* (USA, AFXE),
  SHA-1 `4ac05441f4de70a4ec3dd932116346c61b8783d9`, 16,777,216 bytes —
  pinned in [`game.toml`](../game.toml).
- The launch BIOS is the bundled clean-room
  [emibios](../bios/README.md) build; no Nintendo BIOS dump is needed.

Android builds additionally need JDK 21, Android SDK platform 35,
build-tools 35, CMake 3.30.3, NDK 28.2.13676358, and `adb`. See
[`android/README.md`](../android/README.md) § Build.

## Quick source build

1. Clone with submodules and place your legally obtained ROM dump at the
   repo root:

   ```sh
   git clone --recurse-submodules https://github.com/james2doyle/ffta-recomp.git
   cd ffta-recomp
   cp /path/to/ffta-usa.gba game.gba
   ```

2. Run the bootstrap:

   ```sh
   python3 build.py
   ```

   It installs the Python tooling, builds the framework tools and BIOS
   corpus, recompiles the game, builds `build/FFTARecomp`, and finishes
   with a strict headless smoke test.

3. Run the self-built binary:

   ```sh
   ./build/FFTARecomp
   ```

   With no arguments it opens the launch screen; the first boot opens the
   file picker. Pick **Final Fantasy Tactics Advance (USA)** and select
   **Play**. Pass the paths directly — or run with any headless flag
   (`--no-window`, `--frames`, `--load-state`, `--tcp`) — to start without
   the launch screen:

   ```sh
   ./build/FFTARecomp --bios bios/emibios_gba_bios.bin --rom game.gba
   ```

   Running and display options are listed in
   [`docs/README.md`](README.md) § Display options.

## Manual pipeline (what `build.py` automates)

**1. Clone with submodules.**
```sh
git clone https://github.com/james2doyle/ffta-recomp.git ffta-recomp
cd ffta-recomp
git submodule update --init --recursive
# If a submodule worktree comes up empty, re-run with --checkout --recursive
```

**2. Place your ROM dump** — `game.gba` at the repo root (FFTA USA). Launch
verifies the ROM hash (SHA-1 `4ac05441f4de70a4ec3dd932116346c61b8783d9`)
and fails loudly if it is wrong or missing. No BIOS dump is needed: the
launch BIOS is the bundled clean-room emibios at
`bios/emibios_gba_bios.bin` (issue #17; pin in `bios/README.md`). The
Windows release build needs the **same** ROM for its corpus translation
(the ROM is never embedded — the packaged sweep proves it); it
cross-compiles from this tree, it does not rerun these steps on a second
machine.

**3. Python venv for the tooling** (the harness scripts):
```sh
uv venv .venv
#   (or: python3 -m venv .venv)
```

**4. Build the framework tools** (one-time; re-run only after submodule
changes):
```sh
cmake -S gbarecompx -B gbarecompx/build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build gbarecompx/build --target gba_recompile gba_scan --parallel 8
```

**5. Recompile the BIOS (one-time).** Run it *from `gbarecompx/`* so the
output lands in `gbarecompx/src/runtime/generated_bios/`, and pass the
project's BIOS config — it seeds the named emibios functions from the build
ELF (plus the two statically-unreachable fragments: the `after_interrupt`
trampoline epilogue and the runtime-installed `.vc_irqh` boot handler) and
identity-checks the committed clean-room BIOS (issue #17):
```sh
cd gbarecompx && ./build/gba_recompile \
  --bios ../bios/emibios_gba_bios.bin \
  --config ../bios/emibios_gba_bios.toml && cd ..
```

**6. Generate the game's static code corpus** (also after every `game.toml`
change — `tools/cycle.py` wraps this with the sanity checks and the attract
gate):
```sh
./gbarecompx/build/gba_recompile --rom game.gba --config game.toml \
  --symbols symbols/ffta_symbols.tsv --data-symbols symbols/ffta_data_symbols.tsv \
  --out generated --max-functions 65536
```

**7. Configure and build the game binary:**
```sh
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DGBARECOMP_ENABLE_MODS=ON
cmake --build build --target FFTARecomp --parallel 8
```

(`GBARECOMP_ENABLE_MODS=ON` links the framework's mod lifecycle APIs —
activation/reset plugins, view-width requests — used by the game's
widescreen hooks; verified gate-neutral.)

**8. Sanity.** Strict, headless, no input — expect `FULLY_STATIC` in the
banner:
```sh
GBARECOMP_STRICT_STATIC=1 ./build/FFTARecomp \
  --bios bios/emibios_gba_bios.bin --rom game.gba --frames 2400 --no-window
```
And optionally the attract gate, which pins the exact frame hash:
```sh
.venv/bin/python tools/attract_check.py    # PASS + exit 0 expected
```

Then play — run the built binary (`./build/FFTARecomp`; running and display
options: [`docs/README.md`](README.md) § Display options). For an
*instrumented playtest session* use `tools/play.sh` (guide:
[`tests/README.md`](../tests/README.md)).

## Android build

The APK consumes the desktop-generated corpus, so complete the desktop
build first. Then:

```sh
python3 build_apk.py
```

With a device attached the script installs the APK and runs the boot-health
gate. The full local-build, install, signing, and device-validation guide is
[`android/README.md`](../android/README.md).

The public release APK is built separately by `tools/make_release.py --apk`
and contains no ROM; players import their dump through the Android setup
screen.

## Contributing

The `gbarecompx` submodule **is** the framework:
[james2doyle/gbarecompx](https://github.com/james2doyle/gbarecompx), the
fork carrying the raygui launch screen, the tinyfiledialogs picker, the
emibios default BIOS, and every former local patch as committed history. A
plain `--recurse-submodules` clone builds everything; there are no
working-tree patches to apply. Framework changes land as fork commits, then
the game repo's gitlink moves — see
[`reference/dev-gotchas.md`](../reference/dev-gotchas.md) § Submodules.

Testing, debugging, coverage, and CI workflows live in
[`tests/README.md`](../tests/README.md); the repository map is in
[`docs/README.md`](README.md); project rules are in
[`AGENTS.md`](../AGENTS.md).

## Troubleshooting

- `build.py` stops at **dumps** → the ROM is missing or has the wrong hash
  (SHA-1 above); it never downloads one. BIOS pin: `bios/README.md`.
- `gba_recompile: command not found` → step 4 was not run in this checkout.
- `generated_bios/` stays empty / BIOS never loads → step 5 was run from the
  wrong directory (`cd gbarecompx` first). If strict runs instead abort with
  a dispatch miss near pc `0x300`, step 5 ran without
  `--config ../bios/emibios_gba_bios.toml`.
- Launch aborts with an identity/hash error → wrong or missing dump; compare
  against the pinned SHA-1 above (BIOS: `bios/README.md`).
- CMake cannot find OpenGL/X11 development headers → install the
  Debian/Ubuntu set in [Requirements](#requirements).
- MinGW cross (static Windows build, R2): the toolchain is
  `mingw-w64-toolchain` from pacman (`x86_64-w64-mingw32-gcc` — check with
  `command -v`); the dependency prefix is built from pinned sources, not
  packages (`tools/win_cross_deps.py build` — Arch ships no mingw binary
  library packages, MSYS2 is Windows-only). A dynamic third-party DLL
  import in the exe (libstdc++/winpthread/…) means the prefix leaked a
  DLL and the objdump guard will say so — rebuild the prefix after
  pruning, then the exe.
- a tool fails to import its deps → step 3's venv (use
  `.venv/bin/python tools/...`).
- A submodule directory is empty after cloning → step 1's retry line.
- Window refuses to close, or a session wedges → `gbarecompx/tools/quit.py <port>`; see
  `tests/README.md` § Playtesting & debugging.
- After `game.toml` edits: regenerate (step 6) → rebuild → attract gate, i.e.
  `.venv/bin/python tools/cycle.py`.

## mGBA oracle (optional)

The mGBA oracle used by the frame-diff harness (needs network
once; distinct from a system mGBA):

```sh
cd gbarecompx && bash oracle/setup-mgba.sh \
  && cmake -B build -S . -DGBARECOMP_BUILD_ORACLE=ON \
  && cmake --build build --target gbarecomp_oracle --parallel 8
```
