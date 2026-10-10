#!/usr/bin/env python3
"""Read-only hang probe for the --tcp-observe channel.

Captures WHY a gbarecomp title is spinning without progressing: guest
registers, the GBA interrupt state (IF/IE/IME), the FFTA vblank wake flag in
IWRAM, the user IRQ vector, and the live miss report.

Read-only by design: NEVER sends savestate_save / pause / step. The observe
server serves one client and its savestate request is queued for "the next
present" — a stalled guest never presents, so the server wedges (learned the
hard way, 2026-10-08). These reads are always safe.

Usage: .venv/bin/python tools/hangprobe.py <port> [--repeat N] [--interval S]
"""
import argparse
import json
import socket
import time

FFTA_VBLANK_FLAG_IWRAM = 0x03000E10
FFTA_IRQ_VECTOR_IWRAM = 0x03007FF0  # covers the 0x03007FFC vector pointer
GBA_IO_if_ie_ime = 0x04000200       # IF(2) pad(2) IE(2) pad(2) IME(2)


def call(s, cmd, **kw):
    s.sendall((json.dumps({"cmd": cmd, **kw}) + "\n").encode())
    buf = b""
    while b"\n" not in buf:
        chunk = s.recv(1 << 20)
        if not chunk:
            raise ConnectionError("closed")
        buf += chunk
    return buf.split(b"\n")[0].decode()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("port", type=int)
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--interval", type=float, default=1.0)
    a = ap.parse_args()

    s = socket.create_connection(("127.0.0.1", a.port), timeout=5)
    s.settimeout(9)
    for i in range(a.repeat):
        print(f"--- sample {i} at {time.strftime('%H:%M:%S')} ---")
        print("registers:", call(s, "registers"))
        time.sleep(a.interval)
    print("counters:", call(s, "counters"))
    print("state_hash:", call(s, "state_hash"))
    print("misses:", call(s, "misses"))
    print("io@0x04000200 (IF,IE,IME):", call(s, "read_io", addr=GBA_IO_if_ie_ime, len=12))
    print("iwram@0x03000E10 (vblank wake flag):", call(s, "read_iwram", addr=FFTA_VBLANK_FLAG_IWRAM, len=16))
    print("iwram@0x03007FF0 (irq vector):", call(s, "read_iwram", addr=FFTA_IRQ_VECTOR_IWRAM, len=16))
    s.close()


if __name__ == "__main__":
    main()
