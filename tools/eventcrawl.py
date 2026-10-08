#!/usr/bin/env python3
"""Event/script static walk (Roadmap item 3).

Two evidence sources are mined for code entry points that play has not
reached yet:

1. Script tables (DataCrystal + engine-hacks research): master table at
   0x089A5D54 (62 monotonic u32 offsets, entry0 = table size), each of the 62
   blocks starts with a u32 local-offset-table size (count = size/4), entries
   are block-relative offsets to scripts. Validated; scripts themselves carry
   no code pointers (opcodes only), so this part yields the script inventory
   and the embedded-pointer scan result, not code seeds directly.

2. Code-pointer tables: literal u32 runs inside the event/battle code families
   (targets 0x08100000-0x08130000). Tables whose not-yet-emitted targets
   verify as thumb function prologues are callback/handler tables the walker
   never reached - the "unplayed mission handler" breadth lever. Tables of
   interior switch targets (low verify) are excluded: seeding interiors is
   the speculative-harvest hazard (see BRINGUP, offline push t04).

Output: a reviewable proposal TOML fragment (never auto-edited into
game.toml) plus a stdout summary. Usage:  .venv/bin/python tools/eventcrawl.py
"""
import argparse
import pathlib
import re
import struct
import sys




ROM_BASE = 0x08000000
MASTER_TABLE = 0x089A5D54          # script master table (block table offsets)
SCRIPT_LO, SCRIPT_HI = 0x089A5E4C, 0x089C1480   # script region bounds
FAMILY_LO, FAMILY_HI = 0x08100000, 0x08130000   # event/battle code families
MIN_TABLE = 6                      # min entries for a candidate pointer table
MIN_NEW_VERIFIED = 3               # min new+verified targets to propose a table
VERIFY_RATIO = 0.5                 # min verified/new ratio for a table


def u32(rom, addr):
    return struct.unpack_from("<I", rom, addr - ROM_BASE)[0]


def walk_script_tables(rom):
    """Validate and enumerate the script tables; returns (blocks, scripts)."""
    prev = -1
    n = 0
    while n < 256:
        v = u32(rom, MASTER_TABLE + n * 4)
        if v < prev or v % 4 or v > 0x80000:
            break
        n += 1
        prev = v
    offsets = [u32(rom, MASTER_TABLE + i * 4) for i in range(n)]
    blocks = [MASTER_TABLE + off for off in offsets]
    scripts = []
    for base in blocks:
        size = u32(rom, base)
        if size % 4 or not (4 <= size <= 0x1000):
            continue
        for i in range(size // 4):
            t = base + u32(rom, base + i * 4)
            if SCRIPT_LO <= t < SCRIPT_HI:
                scripts.append(t)
    return blocks, sorted(set(scripts))


def scan_embedded_pointers(rom, scripts, script_hi):
    """Any u32 inside script bytes that looks like an absolute ROM address."""
    out = []
    for i, start in enumerate(scripts):
        end = min(scripts[i + 1], script_hi) if i + 1 < len(scripts) else script_hi
        for fo in range(start, end - 4):
            v = struct.unpack_from("<I", rom, fo - ROM_BASE)[0]
            if 0x08000000 <= (v & ~1) < 0x08140000:
                out.append((fo, v))
    return out


def find_tables(rom):
    """Contiguous u32 runs whose entries are code pointers in FAMILY range."""
    tables = []
    fo = 0
    n = len(rom)
    while fo <= n - MIN_TABLE * 4:
        run = 0
        while fo + run * 4 + 4 <= n:
            v = struct.unpack_from("<I", rom, fo + run * 4)[0]
            if FAMILY_LO <= (v & ~1) < FAMILY_HI:
                run += 1
            else:
                break
        if run >= MIN_TABLE:
            base = ROM_BASE + fo
            targets = [struct.unpack_from("<I", rom, fo + i * 4)[0] & ~1 for i in range(run)]
            tables.append((base, targets))
            fo += run * 4
        else:
            fo += 4
    return tables


def load_corpus(path):
    if not path.exists():
        return set()
    txt = path.read_text()
    return {int(m, 16) for m in re.findall(r"gf_tfunc_(08[0-9A-Fa-f]{6})", txt)}


def load_existing_toml(path):
    if not path.exists():
        return set()
    txt = path.read_text()
    return {int(m, 16) for m in re.findall(r"(?m)^addr = (0x[0-9A-Fa-f]+)", txt)}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rom", default="game.gba")
    ap.add_argument("--corpus", default="generated/dispatch_table.cpp")
    ap.add_argument("--game-toml", default="game.toml")
    ap.add_argument("--proposal", default="logs/eventcrawl_proposal.toml")
    ap.add_argument("--trial-dir", default=None,
                    help="a speculative-harvest regen dir (dispatch_table.cpp inside) giving the "
                         "literal-pool candidate universe; emits walker-missed strict-push starts "
                         "inside the event/battle families (the batch-af lever)")
    args = ap.parse_args()

    rom = pathlib.Path(args.rom).read_bytes()
    corpus = load_corpus(pathlib.Path(args.corpus))
    existing = load_existing_toml(pathlib.Path(args.game_toml))

    blocks, scripts = walk_script_tables(rom)
    print(f"script tables: {len(blocks)} blocks, {len(scripts)} unique scripts "
          f"(0x{scripts[0]:08X}..0x{scripts[-1]:08X})" if scripts else "script tables: none")

    emb = scan_embedded_pointers(rom, scripts, SCRIPT_HI)
    print(f"embedded 0x08xxxxxx u32s in script region: {len(emb)}")
    for fo, v in emb[:10]:
        print(f"   0x{fo:08X}: 0x{v:08X}")
    if emb:
        pathlib.Path("logs/eventcrawl_embedded.txt").write_text(
            "\n".join(f"0x{fo:08X}\t0x{v:08X}" for fo, v in emb) + "\n")

    tables = find_tables(rom)
    cands = {}
    table_stats = []
    for base, targets in tables:
        new = [t for t in targets if t not in corpus and t not in existing]
        if len(new) < MIN_NEW_VERIFIED:
            continue
        # Exact test: the FIRST instruction at t must be `push {..., lr}`.
        # Loose forward scans get fooled by switch-table case bodies (they
        # find the NEXT function's prologue); callbacks/handlers start with a
        # real prologue at the target itself.
        ver = []
        for t in new:
            h = struct.unpack_from("<H", rom, t - ROM_BASE)[0]
            if (h & 0xFF00) == 0xB500:
                ver.append((t, "push {.., lr}"))
        ratio = len(ver) / len(new)
        table_stats.append((base, len(targets), len(new), len(ver), ratio))
        if ratio >= VERIFY_RATIO:
            for t, sig in ver:
                cands.setdefault(t, (base, sig))

    print(f"\ncandidate tables (>= {MIN_NEW_VERIFIED} new, verify ratio >= {VERIFY_RATIO}):")
    for base, n, nnew, nver, ratio in sorted(table_stats, key=lambda r: r[0]):
        mark = "*" if ratio >= VERIFY_RATIO else " "
        print(f" {mark} table 0x{base:08X}: {n:3d} entries, {nnew:3d} new, "
              f"{nver:3d} verified ({ratio:.0%})")

    if args.trial_dir:
        tpath = pathlib.Path(args.trial_dir) / "dispatch_table.cpp"
        if tpath.exists():
            trial = load_corpus(tpath)
            missing_all = trial - corpus - existing
            missing = sorted(a for a in missing_all
                             if FAMILY_LO <= a < FAMILY_HI
                             and (struct.unpack_from("<H", rom, a - ROM_BASE)[0] & 0xFF00) == 0xB500)
            print(f"\ntrial-diff: {len(missing_all)} walker-missed candidates; "
                  f"{len(missing)} strict-push starts in event/battle families (seed batch):")
            for a in missing:
                sites = []
                for pat in (struct.pack("<I", a), struct.pack("<I", a | 1)):
                    fo = rom.find(pat)
                    while fo != -1 and len(sites) < 3:
                        sites.append(fo + ROM_BASE)
                        fo = rom.find(pat, fo + 1)
                print(f"   0x{a:08X}  literal@ " +
                      (", ".join(f"0x{s:08X}" for s in sorted(set(sites))[:3]) or "-"))
            pathlib.Path(args.proposal).with_name("eventcrawl_trial.txt").write_text(
                "\n".join(f"0x{a:08X}" for a in missing) + "\n")
        else:
            print(f"trial-dir {args.trial_dir}: no dispatch_table.cpp found")

    print(f"\nproposed seeds: {len(cands)}")
    lines = ["# Event/script static walk proposal (review before merging!)",
             f"# {len(blocks)} blocks / {len(scripts)} scripts scanned; "
             f"{len(table_stats)} candidate tables; seeds = prologue-verified, not yet emitted.",
             ""]
    for t in sorted(cands):
        base, sig = cands[t]
        lines += ["[[extra_func]]", f"addr = 0x{t:08X}", 'mode = "thumb"',
                  f'note = "event crawl: handler table 0x{base:08X}; start [{sig}]; '
                  f'offline reach for unplayed mission content"', ""]
    out = pathlib.Path(args.proposal)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n")
    print(f"proposal written: {out}")


if __name__ == "__main__":
    main()
