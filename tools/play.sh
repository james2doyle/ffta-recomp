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
# through tools/misspack.py -> game.toml seeds.
#
# Controls: arrows = D-pad, X = A, Z = B, Enter = Start, Backspace = Select,
#           C = L, V = R. Close the window (or Ctrl-C the terminal) to quit.
#
# Extras:  tools/play.sh --fullscreen            windowed fullscreen
#          tools/play.sh --tcp-observe 19850     window + live debug port;
#              inspect from another terminal: .venv/bin/python tools/keyprobe.py
#              19850   NOTE: plain --tcp is structurally headless (the TCP
#              branch returns before window init) — never combine it with a
#              window.
#          tools/play.sh --launcher       run the settings UI first
#          tools/play.sh --view-width 720 wider window
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
exec env -u GBARECOMP_STRICT_STATIC \
  GBARECOMP_INPUT_RECORD="$PWD/logs/playthrough.csv" \
  GBARECOMP_MISS_FRAG="$PWD/logs/playtest_misses.frag" \
  ./build/FFTARecomp --bios gbarecomp/bios/gba_bios.bin --rom game.gba \
  --save-path saves/playtest.sav "$@"
