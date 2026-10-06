#!/usr/bin/env python3
"""misspack.py — turn a self-heal miss fragment into per-PC evidence packs.

Input: a fragment written by GBARECOMP_MISS_FRAG during a NON-STRICT run
(logs/miss*.frag; the framework's own header says a human reviews these and
merges genuine ones — this tool only gathers evidence, it never writes
game.toml).

For each miss PC it reports:
  * classification: ROM code / RAM (needs [[code_copy]] + IWRAM dump) / BIOS;
  * disassembly window around the PC (mode taken from the fragment);
  * candidate function starts from a backward prologue scan (cited bounds,
    not assertions);
  * thumb-pointer occurrences of the PC in the ROM, and — when a run of
    regular code-pointer words surrounds a hit — a [[jump_table]] proposal
    (remember: entries_mode MUST be "auto" for raw interworking pointers);
  * the nearest entry in generated/dispatch_table.cpp (interior alias vs gap);
  * a ready-to-paste, clearly-marked PROPOSED TOML stub.

Usage:
  .venv/bin/python tools/misspack.py logs/miss480b.frag            # report
  .venv/bin/python tools/misspack.py logs/miss480b.frag --stubs    # stubs only
  .venv/bin/python tools/misspack.py logs/miss480b.frag --pc 0x08144A0C
  .venv/bin/python tools/misspack.py logs/miss480b.frag --out logs/pack.md

Harvest a fresh fragment first (repo root):
  GBARECOMP_MISS_FRAG=logs/missN.frag ./build/FFTARecomp --bios \
    gbarecomp/bios/gba_bios.bin --rom game.gba --frames N --no-window
"""
from __future__ import annotations

import argparse
import pathlib
import re
import struct
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
ROM_PATH = REPO / "game.gba"
DISPATCH_PATH = REPO / "generated/dispatch_table.cpp"
ROM_BASE = 0x08000000

import capstone  # noqa: E402  (run via .venv/bin/python)

MD_THUMB = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
MD_ARM = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM)


def parse_frag(path: pathlib.Path):
    text = path.read_text(errors="replace")
    blocks = []
    for m in re.finditer(r"(?m)^\[\[(\w+)\]\](.*?)(?=^\[\[|\Z)", text,
                         re.S | re.M):
        section, body = m.group(1), m.group(2)
        item = {"section": section}
        for key, pat in (("addr", r'(?m)^addr\s*=\s*(0x[0-9A-Fa-f]+)'),
                         ("mode", r'(?m)^mode\s*=\s*"(.*)"'),
                         ("note", r'(?m)^note\s*=\s*"(.*)"')):
            mm = re.search(pat, body)
            if mm:
                item[key] = mm.group(1)
        if "addr" not in item:
            continue
        item["addr"] = int(item["addr"], 16)
        mm = re.search(r"bridged x(\d+)", item.get("note", ""))
        item["bridged"] = int(mm.group(1)) if mm else None
        blocks.append(item)
    return blocks


def load_dispatch():
    if not DISPATCH_PATH.exists():
        return []
    rows = []
    for m in re.finditer(
            r"\{0x([0-9A-Fa-f]+)u,\s*(\d)u,\s*(\d)u,\s*(\w+)\}",
            DISPATCH_PATH.read_text(errors="replace")):
        rows.append((int(m.group(1), 16), int(m.group(2)), int(m.group(3)),
                     m.group(4)))
    rows.sort()
    return rows


def nearest(rows, pc):
    lo, hi = 0, len(rows)
    while lo < hi:
        mid = (lo + hi) // 2
        if rows[mid][0] <= pc:
            lo = mid + 1
        else:
            hi = mid
    below = rows[lo - 1] if lo else None
    above = rows[lo] if lo < len(rows) else None
    exact = below if below and below[0] == pc else None
    return exact, below, above


def decode_one(rom: bytes, off: int, mode: str):
    """Decode one instruction at GBA address `off`."""
    fo = off - ROM_BASE
    if fo < 0 or fo + 8 > len(rom):
        return None
    md = MD_THUMB if mode == "thumb" else MD_ARM
    try:
        for insn in md.disasm(rom[fo:fo + 8], off):
            return f"{insn.mnemonic} {insn.op_str}"
    except Exception:
        pass
    return None


def prologue_scan(rom: bytes, pc: int, mode: str, limit: int = 0x200):
    """Backward scan for plausible function prologues (GBA addresses out).

    Also checks `pc` itself — misses are often function starts.
    """
    hits = []
    if mode == "thumb":
        base = pc & ~1
        bfo = base - ROM_BASE
        if 0 <= bfo and bfo + 2 <= len(rom) and \
                (struct.unpack_from("<H", rom, bfo)[0] & 0xFF00) == 0xB500:
            hits.append(base)
        for off in range(base - 2, max(base - limit, ROM_BASE), -2):
            fo = off - ROM_BASE
            if fo < 0 or fo + 2 > len(rom):
                break
            hw = struct.unpack_from("<H", rom, fo)[0]
            if (hw & 0xFF00) == 0xB500:  # push {..., lr}
                hits.append(off)
                if len(hits) == 3:
                    break
        return [(off, decode_one(rom, off, mode)) for off in hits]
    for off in range(pc - 4, max(pc - limit, ROM_BASE), -4):
        insn = decode_one(rom, off, mode)
        if insn and (insn.startswith("push") or
                     ("stmdb" in insn and "sp!" in insn)):
            hits.append(off)
            if len(hits) == 3:
                break
    return [(off, decode_one(rom, off, mode)) for off in hits]


def pointer_scan(rom: bytes, pc: int, mode: str):
    """Occurrences of the PC as a pointer word; returns FILE offsets."""
    needles = [(pc | 1, "pc|1")]
    if mode == "arm":
        needles.append((pc & ~1, "pc"))
    hits = []
    for value, kind in needles:
        needle = struct.pack("<I", value)
        start = 0
        while True:
            off = rom.find(needle, start)
            if off < 0:
                break
            hits.append((off, value, kind))
            start = off + 1
    return hits


def table_run(rom: bytes, fo_hit: int):
    """Largest run of regular code-pointer words around a FILE offset."""
    if fo_hit % 4:
        return None

    def plausible(fo):
        if fo < 0 or fo + 4 > len(rom):
            return False
        v = struct.unpack_from("<I", rom, fo)[0]
        return 0x08000000 <= (v & ~1) < 0x09000000

    if not plausible(fo_hit):
        return None
    s = fo_hit
    while s - 4 >= 0 and plausible(s - 4):
        s -= 4
    e = fo_hit
    while e + 4 <= len(rom) - 4 and plausible(e + 4):
        e += 4
    return (s, (e - s) // 4 + 1)


def classify(pc):
    if pc < 0x4000:
        return "BIOS"
    if 0x02000000 <= pc < 0x04000000:
        return "RAM"
    if 0x08000000 <= pc < 0x0A000000:
        return "ROM"
    return "unknown"


def report_block(rom, rows, item, stubs_only):
    pc, mode = item["addr"], item.get("mode", "thumb")
    bridged = item.get("bridged")
    cls = classify(pc)
    lines = []
    stub = []
    add = lines.append
    add(f"### {pc:#010x} ({mode}, {cls}"
        + (f", bridged x{bridged}" if bridged else "") + ")")
    if cls == "ROM":
        win = 0x20
        fo, fo2 = pc - ROM_BASE, min(pc - ROM_BASE + win, len(rom))
        add(f"disasm [{pc - 4:#x}..{pc + win:#x}]:")
        md = MD_THUMB if mode == "thumb" else MD_ARM
        try:
            for insn in md.disasm(rom[fo:fo2], pc):
                add(f"  {insn.address:08x}: {insn.mnemonic} {insn.op_str}")
        except Exception:
            add("  (undecodable)")
        cands = prologue_scan(rom, pc, mode)
        if cands:
            add("prologue candidates (nearest first): " +
                ", ".join(f"{off:#x} `{text}`" for off, text in cands))
        else:
            add("prologue candidates: none within 0x200 (check pool/bx-lr "
                "boundaries or a mid-function resume point)")
        hits = pointer_scan(rom, pc, mode)
        if hits:
            add(f"pointer occurrences of {pc:#x} in ROM: {len(hits)}")
            best = None
            for off, value, kind in hits[:12]:
                run = table_run(rom, off)
                extra = ""
                if run:
                    extra = (f"  [table run: start {run[0] + ROM_BASE:#x}, "
                             f"count {run[1]}]")
                    if run[1] >= 8 and (best is None or run[1] > best[2]):
                        best = (run[0], off, run[1])
                add(f"  @ {off + ROM_BASE:#x} value {value:#010x} ({kind}){extra}")
            if best:
                add(f"TABLE CANDIDATE: code-pointer run at "
                    f"{best[0] + ROM_BASE:#x} (count {best[2]}) containing "
                    f"the hit — likely a jump table; propose [[jump_table]] "
                    f"with entries_mode=\"auto\"")
                stub.append(
                    f"# PROPOSED jump_table (review extent/evidence first!)\n"
                    f"[[jump_table]]\naddr = {best[0] + ROM_BASE:#x}\nstride = 4\n"
                    f"count = {best[2]}\nformat = \"abs32\"\n"
                    f"entries_mode = \"auto\"\n"
                    f"name = \"proposed_from_{pc:x}\"\n"
                    f"note = \"PROPOSED by tools/misspack.py: pointer {pc:#x} "
                    f"found @{best[1] + ROM_BASE:#x} inside a {best[2]}-entry "
                    f"code-pointer run @{best[0] + ROM_BASE:#x}; entries_mode "
                    f"must be 'auto' (raw interworking pointers, bit0 masked)\"")
        else:
            add(f"pointer occurrences of {pc:#x} in ROM: none (runtime "
                f"registration / computed target?)")
        exact, below, above = nearest(rows, pc) if rows else (None, None, None)
        if exact:
            add(f"dispatch: exact entry exists: {exact[3]} (resume={exact[2]}) "
                f"— why did dispatch miss? check mode/thumb bit")
        elif below:
            add(f"dispatch: nearest below {below[0]:#x} {below[3]} "
                f"(+{pc - below[0]:#x}); next above "
                + (f"{above[0]:#x} {above[3]} (+{above[0] - pc:#x})"
                   if above else "none"))
            if below[2] == 1 and pc - below[0] < 0x1000:
                add("  note: inside an existing host's resume range — a "
                    "strict regen may already cover this via "
                    "static_resume_all; verify before adding an entry")
        else:
            add("dispatch: table empty/missing")
        note_bits = ["misspack evidence: prologue "
                     + (f"@{cands[0][0]:#x}" if cands else "not found")]
        if hits:
            note_bits.append(f"ptr@{hits[0][0] + ROM_BASE:#x}")
        note_bits.append(f"bridged x{bridged}" if bridged else "bridged")
        stub.append(f"# PROPOSED extra_func (review before merging)\n"
                    f"[[extra_func]]\naddr = {pc:#x}\nmode = \"{mode}\"\n"
                    f"note = \"PROPOSED: " + "; ".join(note_bits) + "\"")
    elif cls == "RAM":
        add("RAM region — needs [[code_copy]] evidence, not [[extra_func]]:")
        add("  1) re-run with GBARECOMP_MISS_IWRAM_DUMP to capture IWRAM at "
            "the miss point")
        add("  2) locate the ROM source of the copied blob (forward+backward "
            "byte match)")
        add("  3) declare [[code_copy]] iwram_lo, rom_lo, len with the match "
            "as note evidence")
    elif cls == "BIOS":
        add("BIOS PC — belongs in the BIOS fragment/config, not game.toml")
    add("")
    if stubs_only:
        return "\n".join(stub) + ("\n" if stub else ""), stub
    return "\n".join(lines), stub


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("frag", type=pathlib.Path)
    ap.add_argument("--pc", default=None, help="report only this PC (hex)")
    ap.add_argument("--stubs", action="store_true", help="TOML stubs only")
    ap.add_argument("--out", type=pathlib.Path, default=None)
    args = ap.parse_args()

    if not args.frag.exists():
        print(f"error: no such fragment: {args.frag}", file=sys.stderr)
        return 2
    rom = ROM_PATH.read_bytes()
    rows = load_dispatch()
    items = parse_frag(args.frag)
    if args.pc:
        want = int(args.pc, 16)
        items = [i for i in items if i.get("addr") == want]
        if not items:
            print(f"error: PC {args.pc} not in fragment "
                  f"(parsed {len(parse_frag(args.frag))} PCs)", file=sys.stderr)
            return 2

    out_lines = [f"# misspack — {args.frag} ({len(items)} PCs, "
                 f"{len(rows)} dispatch rows)", ""]
    stubs = []
    for item in items:
        text, stub = report_block(rom, rows, item, args.stubs)
        out_lines.append(text)
        stubs.extend(stub)
    report = "\n".join(out_lines)
    if args.stubs:
        report = ("\n".join(stubs) + "\n") if stubs else \
            "# (no stubs generated — PCs were RAM/BIOS class; see full report)\n"
    if args.out:
        args.out.write_text(report)
        print(f"wrote {args.out}")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
