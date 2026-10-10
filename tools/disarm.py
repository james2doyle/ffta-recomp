#!/usr/bin/env/python3
"""Disassemble a window of game.gba as ARM or Thumb.

Usage: tools/disarm.py START END [arm|thumb]   # START/END in hex or 0x-prefixed
Addresses are absolute GBA ROM addresses (0x08000000-based); a ROM address
(>= 0x08000000) is used as a file offset, a bare value as an offset directly.

Examples:
  .venv/bin/python tools/disarm.py 0x0800543C 0x08005460 thumb
  .venv/bin/python tools/disarm.py 800543C 8005460 thumb
"""
import sys

import capstone

ROM = "game.gba"
ROM_BASE = 0x08000000


def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(2)
    start = int(sys.argv[1], 16) & 0xFFFFFFFF
    end = int(sys.argv[2], 16) & 0xFFFFFFFF
    mode = (sys.argv[3] if len(sys.argv) > 3 else "arm").lower()
    if mode not in ("arm", "thumb"):
        raise SystemExit(f"bad mode: {mode}")
    if end <= start:
        raise SystemExit(f"end must be after start ({start:#x} >= {end:#x})")

    with open(ROM, "rb") as f:
        f.seek(start - ROM_BASE if start >= ROM_BASE else start)
        data = f.read(end - start)
    if len(data) != end - start:
        raise SystemExit(f"short read: ROM ended before {end:#x}")

    md = capstone.Cs(capstone.CS_ARCH_ARM,
                     capstone.CS_MODE_ARM if mode == "arm"
                     else capstone.CS_MODE_THUMB)
    md.detail = False
    for insn in md.disasm(data, start):
        # capstone ARM: op_str already carries the target for b/bx/bl;
        # pc-relative loads of the literal pool are annotated inline.
        print(f"{insn.address:08x}: {insn.bytes.hex():<10} "
              f"{insn.mnemonic:<8} {insn.op_str}")


if __name__ == "__main__":
    main()