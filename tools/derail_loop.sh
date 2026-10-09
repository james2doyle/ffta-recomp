#!/usr/bin/env bash
# derail_loop.sh — hunt the rare windowed-only press-path derail into BIOS
# 0x0FF8 (bridge runaway abort). Each iteration runs the full windowed
# acceptance (state3 + verified press + 75 s observation) with the
# instruction ring ARMED and the runaway-abort ring dump ENABLED, then
# checks for the fingerprint. Stops on first hit (or ring dump present).
# Evidence: logs/desktop_accept/loop<N>/{run.log,summary.json,screens/}
#           /tmp/bridge_abort_fp.bin (the fp ring at the abort)
set -u
cd /home/james/Git/ffta-recompiled
MAX_ITERS="${1:-12}"
for i in $(seq 1 "$MAX_ITERS"); do
  W="logs/desktop_accept/loop$i"
  rm -rf "$W"; rm -f /tmp/bridge_abort_fp.bin /tmp/bridge_entry_fp.bin
  pkill -9 -x FFTARecomp 2>/dev/null; sleep 1
  echo "=== iter $i/$MAX_ITERS ($(date +%H:%M:%S)) ==="
  GBARECOMP_BRIDGE_ABORT_FP=/tmp/bridge_abort_fp.bin \
  GBARECOMP_BRIDGE_ENTRY_FP=/tmp/bridge_entry_fp.bin \
  GBARECOMP_INSN_TRACE=1 \
    timeout 220 .venv/bin/python tools/desktop_accept.py --mode window \
      --port "$((19900 + i))" --work "$W" --observe 75 2>&1 | tail -14
  if grep -qE "SELF-HEAL bridge|bridge entry pc=" "$W/run.log" 2>/dev/null; then
    cp /tmp/bridge_abort_fp.bin /tmp/bridge_entry_fp.bin logs/savehang/ 2>/dev/null
    echo "HIT: 0x0FF8 derail at iter=$i"; exit 0
  fi
  if [ -f /tmp/bridge_abort_fp.bin ] || [ -f /tmp/bridge_entry_fp.bin ]; then
    cp /tmp/bridge_abort_fp.bin /tmp/bridge_entry_fp.bin logs/savehang/ 2>/dev/null
    echo "HIT: ring dumped at iter=$i"; exit 0
  fi
  if grep -q "bridge entry pc=" "$W/run.log" 2>/dev/null; then
    cp /tmp/bridge_abort_fp.bin /tmp/bridge_entry_fp.bin logs/savehang/ 2>/dev/null
    echo "HIT(entry-only): bridge entry at iter=$i"; exit 0
  fi
done
echo "NO HIT after $MAX_ITERS iterations"
