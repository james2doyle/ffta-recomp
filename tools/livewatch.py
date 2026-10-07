#!/usr/bin/env python3
"""Frame-stall watchdog for a *live* windowed session (--tcp-observe port).

Polls the observe channel every few seconds: registers, state hash, frame
counter. When the frame counter stops advancing (the runner is stuck inside a
frame — a real hang; pc-stalls with advancing frames are legitimate waits),
it snapshots registers + state hash + an IWRAM stack window to /tmp, while
the game is still frozen. Read-only; the observe listener serves few clients,
so use exactly one long-lived watcher per session.

Usage: .venv/bin/python -u tools/livewatch.py <port> [--out-dir /tmp]
"""
import json
import socket
import sys
import time

port = int(sys.argv[1]) if len(sys.argv) > 1 else 19870
out_dir = "/tmp"
if "--out-dir" in sys.argv:
    out_dir = sys.argv[sys.argv.index("--out-dir") + 1]
POLL = 2
STALL_POLLS = 5  # ~10 s without a completed frame


def connect():
    s = socket.create_connection(("127.0.0.1", port), timeout=5)
    s.settimeout(8)
    return s


def call(s, cmd, **kw):
    s.sendall(json.dumps({"cmd": cmd, **kw}).encode() + b"\n")
    buf = b""
    while b"\n" not in buf:
        chunk = s.recv(1 << 20)
        if not chunk:
            raise ConnectionError("closed")
        buf += chunk
    return json.loads(buf.split(b"\n")[0])


def main():
    s = connect()
    last = None
    same = 0
    print(f"livewatch armed on {port} (frame-stall detection)", flush=True)
    while True:
        try:
            regs = call(s, "registers")
            h = call(s, "state_hash")
            f = call(s, "frame")
            frame = f.get("frame")
            pc = regs.get("r15", 0)
            if frame == last:
                same += 1
            else:
                same = 0
                last = frame
            if same >= STALL_POLLS:
                stamp = time.strftime("%H%M%S")
                path = f"{out_dir}/hang_{stamp}"
                with open(path + ".json", "w") as fh:
                    json.dump({"frame": frame, "pc": pc, "registers": regs,
                               "state_hash": h}, fh, indent=1)
                sp = regs.get("r13", 0) & ~3
                try:
                    mem = call(s, "read_iwram",
                               addr=max(sp - 0x80, 0x03000000), len=0x300)
                    with open(path + "_stack.bin", "wb") as fh:
                        fh.write(bytes.fromhex(mem["data"]))
                except Exception:
                    pass
                print(f"STALL frame={frame} pc={pc:#x} "
                      f"hash={h.get('hash')} -> {path}.json", flush=True)
                for i in range(3):
                    time.sleep(POLL)
                    r2 = call(s, "registers")
                    h2 = call(s, "state_hash")
                    f2 = call(s, "frame")
                    print(f"  +{POLL*(i+1)}s: pc={r2.get('r15',0):#x} "
                          f"hash={h2.get('hash')} frame={f2.get('frame')}",
                          flush=True)
                break
            time.sleep(POLL)
        except (ConnectionError, OSError, socket.timeout) as exc:
            print(f"channel lost: {exc}", flush=True)
            break
    print("livewatch done", flush=True)


if __name__ == "__main__":
    main()
