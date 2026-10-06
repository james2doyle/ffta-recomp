#!/usr/bin/env python3
"""ringscan.py — query a GBARECOMP_FP_SAVE instruction ring.

Ring format (framework): 16-byte header {u32 magic, u32 entry_size, u64
count}; entries {u64 cyc, u32 pc, u32 cpsr, r0..r15} (80 bytes). The window
is the last ~8.4 M instructions — size --frames so the event is in-window.

Capture one (repo root):
  GBARECOMP_STRICT_STATIC=1 GBARECOMP_INSN_TRACE=1 GBARECOMP_FP_SAVE=/tmp/fp.bin \
    ./build/FFTARecomp --bios gbarecomp/bios/gba_bios.bin --rom game.gba \
    --frames N --no-window

Queries (filters combine with AND; output capped by --max):
  .venv/bin/python tools/ringscan.py --file /tmp/fp.bin --reg 0x030034B0
  .venv/bin/python tools/ringscan.py --file /tmp/fp.bin --pc 0x08002810 --max 5
  .venv/bin/python tools/ringscan.py --file /tmp/fp.bin --cyc 336000000 336600000 --context 4
  .venv/bin/python tools/ringscan.py --file /tmp/fp.bin \
      --reg-range 0x01F00000 0x01FFFFFF --max 10

Notes: parsing ~8.4 M entries takes ~10-30 s; addresses are printed in GBA
space; instructions are decoded from game.gba via capstone (thumb/arm from
CPSR bit 5).
"""
from __future__ import annotations

import argparse
import mmap
import struct
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ROM_PATH = REPO / "game.gba"
FRAME_CYCLES = 280896  # GBA frame = 228 scanlines * 1232 cycles


def load_rom():
    return ROM_PATH.read_bytes()


def decode(rom, pc, cpsr):
    try:
        import capstone
    except ImportError:
        return ""
    mode = (capstone.CS_MODE_THUMB if cpsr & 0x20
            else capstone.CS_MODE_ARM)
    md = capstone.Cs(capstone.CS_ARCH_ARM, mode)
    fo = pc - 0x08000000
    if not (0 <= fo < len(rom)):
        return ""
    try:
        for insn in md.disasm(rom[fo:fo + 8], pc):
            return f"{insn.mnemonic} {insn.op_str}"
    except Exception:
        pass
    return ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file", required=True, type=Path)
    ap.add_argument("--pc", default=None, help="match this pc (hex)")
    ap.add_argument("--reg", default=None, help="match if any reg == value")
    ap.add_argument("--reg-range", nargs=2, default=None, metavar=("LO", "HI"))
    ap.add_argument("--cyc", nargs=2, default=None, metavar=("LO", "HI"))
    ap.add_argument("--context", type=int, default=0,
                    help="entries of context around each match")
    ap.add_argument("--max", type=int, default=20,
                    help="max matches to print (default 20; 0 = all)")
    args = ap.parse_args()

    want_pc = int(args.pc, 16) if args.pc else None
    want_reg = int(args.reg, 16) if args.reg else None
    reg_lo, reg_hi = ((int(args.reg_range[0], 16), int(args.reg_range[1], 16))
                      if args.reg_range else (None, None))
    cyc_lo, cyc_hi = ((int(args.cyc[0]), int(args.cyc[1]))
                      if args.cyc else (None, None))

    f = open(args.file, "rb")
    mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
    magic, esize, count = struct.unpack_from("<IIQ", mm, 0)
    nregs = (esize - 16) // 4
    fmt = f"<QII{nregs}I"
    mv = memoryview(mm)[16:16 + count * esize]
    print(f"ring: {args.file} — entries={count} entry_size={esize}")

    def unpack(i):
        return struct.unpack_from(fmt, mv, i * esize)

    def matches_fields(cyc, pc, regs):
        if want_pc is not None and pc != want_pc:
            return False
        if cyc_lo is not None and not (cyc_lo <= cyc <= cyc_hi):
            return False
        if want_reg is not None and want_reg not in regs:
            return False
        if reg_lo is not None and not any(reg_lo <= v <= reg_hi
                                          for v in regs):
            return False
        return True

    hit_idxs = []
    first_cyc = last_cyc = None
    for i in range(count):
        cyc, pc, cpsr = struct.unpack_from("<QII", mv, i * esize)
        if first_cyc is None:
            first_cyc = cyc
        last_cyc = cyc
        regs = struct.unpack_from(f"{nregs}I", mv, i * esize + 16)
        if matches_fields(cyc, pc, regs):
            hit_idxs.append(i)
            if args.max and len(hit_idxs) >= args.max:
                break

    print(f"cyc {first_cyc}..{last_cyc} (~frames "
          f"{first_cyc // FRAME_CYCLES}..{last_cyc // FRAME_CYCLES}), "
          f"matches shown: {len(hit_idxs)}"
          + (f" (stopped at --max {args.max})" if
             args.max and len(hit_idxs) >= args.max else ""))
    rom = load_rom()
    shown = set()
    for i in hit_idxs:
        lo = max(0, i - args.context)
        hi = min(count - 1, i + args.context)
        for j in range(lo, hi + 1):
            if j in shown:
                continue
            shown.add(j)
            cyc, pc, cpsr, *regs = unpack(j)
            mark = ">" if j == i else " "
            regtxt = " ".join(f"r{k}={v:08x}" for k, v in enumerate(regs)
                              if v in (0x030034B0,) or reg_lo is not None
                              and reg_lo <= v <= reg_hi or
                              (want_reg is not None and v == want_reg))
            print(f"{mark} cyc={cyc} pc={pc:08x} {regtxt} | "
                  f"{decode(rom, pc, cpsr)}")
    try:
        mv.release()
    except Exception:
        pass
    mm.close()
    f.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
