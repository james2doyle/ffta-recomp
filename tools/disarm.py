#!/usr/bin/env python3
"""Disassemble a window of game.gba as ARM or Thumb.

Usage: tools/dis.py START END [arm|thumb]   # START/END in hex or 0x-prefixed
Addresses are absolute GBA ROM addresses (0x08000000-based).
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

    with open(ROM, "rb") as f:
        f.seek(start - ROM_BASE if start >= ROM_BASE else start)
        data = f.read(end - start)

    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM if mode == "arm" else capstone.CS_MODE_THUMB)
    md.detail = False
    for insn in md.disasm(data, start):
        branch = ""
        if insn.group(capstone.x86.X86_GRP_JUMP) if False else False:
            pass
        # capstone arm: op_str contains target for b/bx/bl already; annotate ldr pc
        print(f"{insn.address:08x}: {insn.bytes.hex():<10} {insn.mnemonic:<8} {insn.op_str}")


if __name__ == "__main__":
    main()
