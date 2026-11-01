#!/usr/bin/env bash
# play.sh — interactive desktop playtest of FFTA Recomp.
#
# Launches the windowed build with the audit instrumentation already on:
#   * input recording  -> logs/playthrough.csv        (replayable keystate trace)
#   * miss logging     -> logs/playtest_misses.frag   (self-heal proposals)
#   * persistent save  -> saves/playtest.sav          (flash image)
#
# Self-heal is ON (not strict): unmapped code is bridged instead of aborting,
# so the session never hard-stops; every miss is recorded and later runs
# through gbarecompx/tools/misspack.py -> game.toml seeds.
#
# Controls: arrows = D-pad, X = A, Z = B, Enter = Start, Backspace = Select,
#           C = L, V = R. Close the window (or Ctrl-C the terminal) to quit.
#           (Or your keybinds.ini rebinds — config is read from the exe's
#           directory, so each build dir has its own copy.)
#
# Backend: raylib (`build/FFTARecomp`) — the product backend since Phase 4c;
# a plain `cmake -S . -B build` selects it. The old SDL build is gone (--sdl
# was retired) and the OFF configuration is a headless stub compile-check, not
# playable. Everything else passes through to the game.
#
# Extras:  tools/play.sh --fullscreen            windowed fullscreen
#          tools/play.sh --tcp-observe 19850     window + live debug port;
#              inspect from another terminal: .venv/bin/python tools/keyprobe.py
#              19850   NOTE: plain --tcp is structurally headless (the TCP
#              branch returns before window init) — never combine it with a
#              window.
#          tools/play.sh --scale 8        bigger window: Nx240 x Nx160
#              pixels (scale 1-8; 8 = 1920x1280 on a 4K-class display)
#          tools/play.sh --fullscreen     borderless desktop fullscreen
#              NOTE: --view-width is the widescreen *view* feature, NOT
#              window size; see reference/widescreen.md.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p logs saves
# Preserve the previous session's savestates + input trace before they get
# overwritten (states are destructive across sessions; the trace is replay
# evidence for the last session's route).
ts=$(date +%Y%m%d_%H%M%S)
for slot in game.state1 game.state2; do
  n="${slot#game.state}"
  [ -f "$slot" ] && cp "$slot" "saves/state${n}_prev_${ts}.state" || true
done
[ -f logs/playthrough.csv ] && cp logs/playthrough.csv "saves/trace_prev_${ts}.csv" || true
# The miss proposal is journaled live while the session runs (durable across
# unclean closes) and rewritten with final counts on a clean exit — archive
# it too, so back-to-back sessions can't clobber the previous proposals.
[ -f logs/playtest_misses.frag ] && cp logs/playtest_misses.frag "saves/frag_prev_${ts}.frag" || true
# The product build (raylib; Phase 4c made it the default). --sdl is retired:
# fail loudly rather than pass a dead flag through to the game.
EXE=./build/FFTARecomp
ARGS=()
for a in "$@"; do
  if [ "$a" = "--sdl" ]; then
    echo "play.sh: --sdl was retired in Phase 4c (raylib is the only window backend)." >&2
    exit 2
  fi
  ARGS+=("$a")
done
if [ ! -x "$EXE" ]; then
  echo "play.sh: $EXE missing. Build it first:" >&2
  echo "  cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release" >&2
  echo "  cmake --build build --target FFTARecomp --parallel 8" >&2
  exit 1
fi
exec env -u GBARECOMP_STRICT_STATIC \
  GBARECOMP_INPUT_RECORD="$PWD/logs/playthrough.csv" \
  GBARECOMP_MISS_FRAG="$PWD/logs/playtest_misses.frag" \
  "$EXE" --bios bios/emibios_gba_bios.bin --rom game.gba \
  --save-path saves/playtest.sav "${ARGS[@]}"
