#!/usr/bin/env python3
"""keyprobe.py — live KEYINPUT monitor for a running FFTARecomp instance.

Connects to the game's TCP debug surface and polls the guest KEYINPUT
register (0x04000130) once per 100 ms, printing every change. Use it to
verify that HOST keyboard input reaches the guest:

  # terminal 1 — click the game window once (focus!), then:
  tools/play.sh --tcp 19850

  # terminal 2:
  .venv/bin/python tools/keyprobe.py 19850

Press X / Z / arrows / Enter. Values print active-low (0x3FF = no keys).
If the value never changes while you press keys, host input is not reaching
the guest (window focus / SDL video driver), not a game-phase issue.
"""
from __future__ import annotations

import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from framediff import Client  # noqa: E402


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 19850
    dur = float(sys.argv[2]) if len(sys.argv) > 2 else 30.0
    c = Client(port)
    print(f"connected to :{port} — monitoring KEYINPUT for {dur:.0f}s "
          f"(0x3FF = nothing pressed)")
    prev = None
    end = time.time() + dur
    try:
        while time.time() < end:
            kb = int.from_bytes(c.read("read_io", 0x04000130, 2), "little")
            if kb != prev:
                names = []
                for bit, name in ((0, "A"), (1, "B"), (2, "Select"),
                                  (3, "Start"), (4, "Right"), (5, "Left"),
                                  (6, "Up"), (7, "Down"), (8, "R"), (9, "L")):
                    if not (kb >> bit) & 1:
                        names.append(name)
                print(f"KEYINPUT=0x{kb:03x}  pressed: {'+'.join(names) or '-'}")
                prev = kb
            time.sleep(0.1)
    finally:
        try:
            c.close()
        except Exception:
            pass
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
