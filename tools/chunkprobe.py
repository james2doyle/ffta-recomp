#!/usr/bin/env python3
"""Chunked breakpoint probe: drive the native runner over a long trace while
parking on a target PC and logging every hit's registers.

Unlike readseq_probe (1 frame per call, input updates per frame), this runs
frames in chunks between trace events, so a 20k-frame boot route takes
minutes, not an hour. On a park (the yield predicate returns early) it logs
the registers, clears the break, steps one instruction past, and re-arms.

Usage:
  python3 tools/chunkprobe.py <trace.csv> <save.sav> <pc> <limit frames> [out.jsonl]
"""
import json
import os
import pathlib
import socket
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from framediff import Client

REPO = pathlib.Path(__file__).resolve().parents[1]
BIOS = REPO / "gbarecomp/bios/gba_bios.bin"
ROM = REPO / "game.gba"
NATIVE = REPO / "build/FFTARecomp"

trace_path = pathlib.Path(sys.argv[1])
save = pathlib.Path(sys.argv[2])
target = int(sys.argv[3], 0)
limit = int(sys.argv[4])
out_path = pathlib.Path(sys.argv[5] if len(sys.argv) > 5 else "/tmp/chunkprobe.jsonl")
stop_on_hit = len(sys.argv) > 6 and sys.argv[6] == "stop"
stop_min_frame = int(sys.argv[7]) if len(sys.argv) > 7 else 0
arm_at = int(sys.argv[8]) if len(sys.argv) > 8 else 0

events = []
for ln in trace_path.read_text().splitlines():
    ln = ln.strip()
    if not ln or ln.startswith("#"):
        continue
    f, v = ln.split(",")
    events.append((int(f), int(v.strip(), 16)))
events.sort()


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def main():
    env = {k: v for k, v in os.environ.items() if not k.startswith("GBARECOMP_")}
    port = free_port()
    proc = subprocess.Popen(
        [str(NATIVE), "--bios", str(BIOS), "--rom", str(ROM), "--no-window",
         "--save-path", str(save), "--tcp", str(port)],
        cwd=str(REPO), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
    out = open(out_path, "w")
    c = Client(port, timeout=180)
    try:
        frame = 0
        ev_i = 0
        cur_key = None
        hits = 0
        armed = False
        if arm_at <= 0:
            c.call(cmd="set_break_pc", value=target)
            armed = True
        rounds = 0
        while frame < limit and rounds < 4000:
            rounds += 1
            if not armed and frame >= arm_at:
                c.call(cmd="set_break_pc", value=target)
                armed = True
                print(f"break armed at f{frame}", flush=True)
            nxt = events[ev_i][0] if ev_i < len(events) else None
            n = min(64, limit - frame)
            if nxt is not None and nxt > frame:
                n = min(n, nxt - frame)
            elif nxt is not None and nxt <= frame:
                # apply all events due now
                while ev_i < len(events) and events[ev_i][0] <= frame:
                    cur_key = events[ev_i][1]
                    ev_i += 1
                if cur_key is not None:
                    c.call(cmd="set_keyinput", value=cur_key)
                n = min(64, limit - frame)
            try:
                r = c.call(cmd="run_frames", n=n)
            except Exception:
                print(f"(connection lost at frame {frame})", flush=True)
                break
            f2 = int(r.get("frame", frame + n))
            g = c.call(cmd="registers")
            pc = int(g.get("r15", 0)) & ~1
            if pc == target:
                hits += 1
                row = {
                    "frame": f2, "hit": hits,
                    "r0": int(g.get("r0", 0)), "r1": int(g.get("r1", 0)),
                    "r2": int(g.get("r2", 0)), "r3": int(g.get("r3", 0)),
                    "r4": int(g.get("r4", 0)), "r5": int(g.get("r5", 0)),
                    "sp": int(g.get("r13", 0)), "lr": int(g.get("r14", 0)),
                }
                if stop_on_hit and f2 >= stop_min_frame:
                    try:
                        sp = row["sp"]
                        d = c.call(cmd="read_iwram", addr=sp & ~3, len=0x100)
                        row["stack"] = d.get("data")
                    except Exception as e:
                        row["stack_err"] = str(e)
                    out.write(json.dumps(row) + "\n")
                    out.flush()
                    print(f"stop-on-hit at f{f2}: logged and stopping", flush=True)
                    break
                out.write(json.dumps(row) + "\n")
                out.flush()
                c.call(cmd="set_break_pc", value=0)
                c.call(cmd="step_inst")
                c.call(cmd="set_break_pc", value=target)
            if f2 > frame:
                frame = f2
            elif pc != target:
                # no progress and not parked: nudge to avoid spin
                frame += 1
    finally:
        out.close()
        try:
            c.close()
        except Exception:
            pass
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    print(f"done: {hits} hits logged to {out_path}", flush=True)


if __name__ == "__main__":
    main()
