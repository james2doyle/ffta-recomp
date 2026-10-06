#!/usr/bin/env python3
# Recover self-heal cache units as a reviewable TOML proposal fragment.
# Crash-session fallback: the runtime .frag never flushes on SIGABRT, but each
# completed heal left <PC>_<hash>_<mode>.{c,dll,log} in recomp_cache/.
import argparse
import pathlib
import re
import sys


def collect(repo):
    units = {}
    for f in (repo / "recomp_cache").rglob("*.c"):
        m = re.match(r"^([0-9A-Fa-f]{8})_[0-9A-Fa-f]{8}_([ta])\.c$", f.name)
        if m:
            units[int(m.group(1), 16)] = m.group(2)
    return units


def game_addrs(repo):
    t = (repo / "game.toml").read_text()
    return {int(x, 16) for x in re.findall(r"(?m)^addr = (0x[0-9A-Fa-f]+)", t)}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default=".")
    ap.add_argument("--out", help="write proposal fragment here")
    ap.add_argument("--new", action="store_true",
                    help="only addresses not already in game.toml")
    a = ap.parse_args()
    repo = pathlib.Path(a.repo).resolve()
    units = collect(repo)
    if not units:
        print("no cache units found")
        return 1
    skip = game_addrs(repo) if a.new else set()
    items = sorted((p, m) for p, m in units.items() if p not in skip)
    print(f"cache units: {len(units)} total, {len(items)} to propose")
    for p, m in items:
        print(f"  0x{p:08X} {m}")
    if a.out and items:
        lines = ["# cache-harvest proposal - review before merging into game.toml", ""]
        for p, m in items:
            mode = "thumb" if m == "t" else "arm"
            lines += [
                "[[extra_func]]",
                f"addr = 0x{p:08X}",
                f'mode = "{mode}"',
                f'note = "cache-harvest: live-completed heal unit {p:08X}_{m}"',
                "",
            ]
        pathlib.Path(a.out).write_text("\n".join(lines) + "\n")
        print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
