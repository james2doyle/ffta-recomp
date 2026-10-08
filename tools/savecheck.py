#!/usr/bin/env python3
"""Structural + checksum validation for FFTA flash saves (.sav).

Two external formats are recognized:
  - raw 64 KiB flash image (mGBA exports, our runtime --save-path)
  - Retro5.net "RTN5" container (24-byte header + zlib payload + CRC32)

Raw images: scan the 16 sectors for `FFTEX000` header sectors; for a header
sector h the group is sectors [h, h-1, h-2, h-3] concatenated (header
sector first). The stored u32 at group+0x0C must equal the game's own
checksum (save_checksum @ ROM 0x0813ADF0, table @ ROM 0x08393318):

  crc24(group, length=0x2FC4, seed=0) with group[0x0C:0x10] and
  group[0x12:0x17] zeroed first; algorithm: r2 = ~seed;
  for b: idx = (b ^ r2) & 0xFF; r2 = (r2>>8) & 0xFFFFFF; r2 ^= table[idx];
  return ~r2 (32-bit arithmetic throughout).

The length 0x2FC4 was verified empirically against all three known-good
groups (user save + both groups of the found save), 2026-10-08.

Exit: 0 = every input has >=1 valid group (and container CRC32 OK);
      1 = problems; 2 = usage / game.gba missing (checksum needs its table).
"""
import argparse
import pathlib
import struct
import sys
import zlib

REPO = pathlib.Path(__file__).resolve().parent.parent
ROM = REPO / "game.gba"
ROM_BASE = 0x08000000
CRC_TABLE_ROM = 0x08393318
CRC_LEN = 0x2FC4
SECTOR = 0x1000
N_SECTORS = 16
MAGIC = b"FFTEX000"

crc_tab = []


def load_crc_table():
    rom = ROM.read_bytes()
    base = CRC_TABLE_ROM - ROM_BASE
    return [struct.unpack_from("<I", rom, base + 4 * i)[0] for i in range(256)]


def crc24(buf, length, seed=0):
    r2 = (seed ^ 0xFFFFFFFF) & 0xFFFFFFFF
    for i in range(length):
        idx = (buf[i] ^ r2) & 0xFF
        r2 = (r2 >> 8) & 0x00FFFFFF
        r2 ^= crc_tab[idx]
    return (~r2) & 0xFFFFFFFF


def group_checksum(g):
    b = bytearray(g)
    b[0x0C:0x10] = b"\0\0\0\0"
    b[0x12:0x17] = b"\0" * 5
    return crc24(b, CRC_LEN)


def check_container(d):
    """RTN5 container -> (problems, payload or None); None if not a container."""
    if len(d) < 24:
        return None
    magic, fmtver, flags, orig, packed, off, crc = struct.unpack_from("<IHHIIII", d, 0)
    if magic != 0x354E5452:  # "RTN5" little-endian
        return None
    problems = []
    if fmtver != 1:
        problems.append(f"RTN5: unexpected format version {fmtver}")
    payload = d[off:off + packed]
    if flags & 1:
        try:
            raw = zlib.decompress(payload)
        except zlib.error as e:
            return problems + [f"RTN5: zlib decompress failed: {e}"], None
    else:
        raw = payload
    if len(raw) != orig:
        problems.append(f"RTN5: unpacked {len(raw)} != origSize {orig}")
    if (zlib.crc32(raw) & 0xFFFFFFFF) != crc:
        problems.append("RTN5: CRC32 mismatch (payload corrupt)")
    return problems, raw


def check_raw(d):
    """-> (problems, [(header_sector, counter, stamp, stored, calc, ok), ...])"""
    problems = []
    if len(d) != SECTOR * N_SECTORS:
        problems.append(f"size {len(d)} != {SECTOR * N_SECTORS} (64 KiB)")
        return problems, []
    headers = [h for h in range(N_SECTORS) if d[h * SECTOR:h * SECTOR + 8] == MAGIC]
    if not headers:
        problems.append("no FFTEX000 header sector found (erased or not a save)")
        return problems, []
    results = []
    for h in headers:
        if h < 3:
            problems.append(f"header sector {h} has no 3 preceding sectors")
            continue
        g = b"".join(d[s * SECTOR:(s + 1) * SECTOR] for s in (h, h - 1, h - 2, h - 3))
        stored = struct.unpack_from("<I", g, 0x0C)[0]
        counter = struct.unpack_from("<I", g, 0x08)[0]
        stamp = g[0x12:0x16]
        calc = group_checksum(g)
        ok = calc == stored
        results.append((h, counter, stamp, stored, calc, ok))
        if not ok:
            problems.append(
                f"group@{h}: checksum {stored:#010x} != computed {calc:#010x}")
    return problems, results


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("saves", nargs="+")
    a = ap.parse_args()
    if not ROM.exists():
        print(f"savecheck: {ROM} missing - checksum validation unavailable")
        return 2
    global crc_tab
    crc_tab = load_crc_table()
    rc = 0
    for p in a.saves:
        path = pathlib.Path(p)
        d = path.read_bytes()
        print(f"== {path} ({len(d)} bytes)")
        cont = check_container(d)
        if cont is not None:
            cprob, raw = cont
            for m in cprob:
                print("   container:", m)
            if cprob:
                rc = 1
            if raw is None:
                continue
            if not cprob:
                print(f"   container: RTN5, payload {len(raw)} bytes, CRC32 OK")
            d = raw
        prob, results = check_raw(d)
        for (h, counter, stamp, stored, calc, ok) in results:
            print(f"   group@ sectors {h - 3}..{h}: counter={counter} "
                  f"stamp={stamp.hex(' ')} checksum={stored:#010x} "
                  f"{'OK' if ok else 'MISMATCH'}")
        for m in prob:
            print("   problem:", m)
        if prob or not results:
            rc = 1
    print("savecheck:", "OK" if rc == 0 else "PROBLEMS")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
