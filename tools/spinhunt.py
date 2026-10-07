#!/usr/bin/env python3
"""spinhunt.py — drive a route via TCP in chunks and detect a silent spin.

Steps frames in 64-frame chunks (inputs applied per trace), reads the PC each
chunk, and when the PC repeats for several consecutive chunks (a spin) dumps
registers + guest stack + nearby IWRAM, then stops.

Respects GBARECOMP_STRICT_STATIC from the parent environment if set.

Usage: spinhunt.py <trace.csv> <save.sav> <limit frames> [repeat-threshold]
"""
import os
import pathlib
import socket
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from framediff import Client

REPO = pathlib.Path("/home/james/Git/ffta-recompiled")
BIOS = REPO / "gbarecomp/bios/gba_bios.bin"
ROM = REPO / "game.gba"
NATIVE = REPO / "build/FFTARecomp"

trace_path = pathlib.Path(sys.argv[1])
save = pathlib.Path(sys.argv[2])
limit = int(sys.argv[3])
threshold = int(sys.argv[4]) if len(sys.argv) > 4 else 3
shrink_at = int(sys.argv[5]) if len(sys.argv) > 5 else 0

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
    if "GBARECOMP_STRICT_STATIC" in os.environ:
        env["GBARECOMP_STRICT_STATIC"] = os.environ["GBARECOMP_STRICT_STATIC"]
    port = free_port()
    proc = subprocess.Popen(
        [str(NATIVE), "--bios", str(BIOS), "--rom", str(ROM), "--no-window",
         "--save-path", str(save), "--tcp", str(port)],
        cwd=str(REPO), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
    c = Client(port, timeout=240)
    try:
        frame = 0
        ev_i = 0
        cur_key = None
        last_pc = None
        last_frame = None
        same = 0
        rounds = 0
        while frame < limit and rounds < 2000:
            rounds += 1
            nxt = events[ev_i][0] if ev_i < len(events) else None
            n = min(64, limit - frame)
            if shrink_at and frame >= shrink_at:
                n = 1
            if nxt is not None and nxt > frame:
                n = min(n, nxt - frame)
            elif nxt is not None and nxt <= frame:
                while ev_i < len(events) and events[ev_i][0] <= frame:
                    cur_key = events[ev_i][1]
                    ev_i += 1
                if cur_key is not None:
                    c.call(cmd="set_keyinput", value=cur_key)
                n = min(1 if (shrink_at and frame >= shrink_at) else 64, limit - frame)
            if shrink_at and frame >= shrink_at:
                print(f"  f{frame} pc={last_pc and hex(last_pc)}", flush=True)
            try:
                r = c.call(cmd="run_frames", n=n)
            except Exception:
                print(f"(timeout at frame {frame}, pc={last_pc and hex(last_pc)})",
                      flush=True)
                break
            f2 = int(r.get("frame", frame + n))
            g = c.call(cmd="registers")
            pc = int(g.get("r15", 0)) & ~1
            if pc == last_pc and f2 == last_frame:
                same += 1
            else:
                same = 0
                last_pc = pc
            last_frame = f2
            if same >= threshold:
                print(f"SPIN at {pc:#010x} (frame {f2}, x{same+1})")
                for k in ("r0", "r1", "r2", "r3", "r4", "r5", "r6", "r7",
                          "r8", "r9", "r10", "r11", "r12", "r13", "r14"):
                    print(f"  {k}={int(g.get(k, 0)):#010x}")
                sp = int(g.get("r13", 0))
                try:
                    d = c.call(cmd="read_iwram", addr=sp & ~3, len=0x80)
                    b = bytes.fromhex(d["data"])
                    print("  stack:")
                    for i in range(0, 0x80, 16):
                        w = [int.from_bytes(b[i+j:i+j+4], "little") for j in (0, 4, 8, 12)]
                        print("   ", " ".join(f"{v:08x}" for v in w))
                except Exception as e:
                    print(f"  (stack read failed: {e})")
                break
            if f2 > frame:
                frame = f2
            elif same == 0:
                frame += 1
            if rounds % 16 == 0:
                print(f"  ... f{frame} pc={pc:#010x}", flush=True)
    finally:
        try:
            c.close()
        except Exception:
            pass
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    main()
