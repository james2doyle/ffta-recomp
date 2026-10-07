#!/usr/bin/env python3
# Strict-replay a recorded session to FULLY_STATIC: seed each miss, rebuild,
# repeat. Accumulated seeds go to a proposal file; game.toml is never
# auto-edited. Merge the proposal, then run tools/cycle.py.
# Usage: tools/resolve.py --trace logs/playthrough.csv [--load-state saves/x.state]
#        [--frames 120000] [--iters 16] [--max-scan 0x800]
import argparse
import os
import pathlib
import re
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import misspack  # noqa: E402


def game_addrs(text):
    return {int(x, 16) for x in re.findall(r"(?m)^addr = (0x[0-9A-Fa-f]+)", text)}


def code_copy_spans(text):
    spans = []
    for m in re.finditer(r"(?ms)^\[\[code_copy\]\].*?(?=^\[|\Z)", text):
        block = m.group(0)
        ram = re.search(r"(?m)^ram\s*=\s*(0x[0-9A-Fa-f]+)", block)
        size = re.search(r"(?m)^size\s*=\s*(0x[0-9A-Fa-f]+)", block)
        if ram and size:
            base = int(ram.group(1), 16)
            spans.append((base, base + int(size.group(1), 16)))
    return spans


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--trace", required=True, help="input replay csv")
    ap.add_argument("--load-state", help="start from a savestate instead of boot")
    ap.add_argument("--frames", type=int, default=120000)
    ap.add_argument("--iters", type=int, default=16)
    ap.add_argument("--max-scan", type=lambda s: int(s, 0), default=0x800)
    ap.add_argument("--proposal-out", default="logs/resolve_proposal.toml")
    a = ap.parse_args()
    os.chdir(REPO)

    rom = (REPO / "game.gba").read_bytes()
    text = (REPO / "game.toml").read_text()
    identity = re.search(r"(?ms)^\[identity\]\s*$(.*?)(?=^\[|\Z)", text).group(0)
    existing = game_addrs(text)
    spans = code_copy_spans(text)
    overlay = pathlib.Path(tempfile.gettempdir()) / "resolve_overlay.toml"
    seeds, seen, direct = [], set(), set()

    def write_overlay():
        body = identity + "\n\n"
        for addr, mode, note in seeds:
            body += f'[[extra_func]]\naddr = 0x{addr:08X}\nmode = "{mode}"\nnote = "{note}"\n\n'
        overlay.write_text(body)

    def regen_build():
        cmd = ["./gbarecomp/build/gba_recompile", "--rom", "game.gba",
               "--config", "game.toml"]
        if seeds:
            cmd += ["--config", str(overlay)]
        cmd += ["--out", "generated", "--max-functions", "65536"]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        if r.returncode != 0:
            print("REGEN FAIL:", (r.stdout + r.stderr)[-800:])
            return False
        b = subprocess.run(
            ["cmake", "--build", "build", "--target", "FFTARecomp", "--parallel", "8"],
            capture_output=True, text=True, timeout=3600)
        if b.returncode != 0:
            print("BUILD FAIL:", (b.stdout + b.stderr)[-800:])
            return False
        return True

    def strict_run():
        env = {k: v for k, v in os.environ.items() if not k.startswith("GBARECOMP_")}
        env.update({"GBARECOMP_STRICT_STATIC": "1", "GBARECOMP_INPUT_REPLAY": a.trace})
        cmd = ["./build/FFTARecomp", "--bios", "gbarecomp/bios/gba_bios.bin",
               "--rom", "game.gba", "--frames", str(a.frames), "--no-window"]
        if a.load_state:
            cmd += ["--load-state", a.load_state]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800, env=env)
        out = r.stdout + r.stderr
        m = re.search(
            r"STRICT_STATIC dispatch miss for pc=(0x[0-9a-fA-F]+) \((thumb|arm)\)",
            out)
        if m:
            return int(m.group(1), 16), m.group(2)
        if "FULLY_STATIC" in out:
            return None, None
        print("unexpected run outcome; tail:")
        print("\n".join(out.splitlines()[-8:]))
        return "unknown", "unknown"

    result = "stopped"
    for it in range(a.iters):
        write_overlay()
        if not regen_build():
            result = "build-failure"
            break
        pc, mode = strict_run()
        if pc is None:
            print(f"iter {it}: STRICT replay PASSED end-to-end")
            result = "passed"
            break
        if pc == "unknown":
            result = "unknown-failure"
            break
        if pc >= 0x09000000 or 0x04000000 <= pc < 0x08000000:
            print(f"iter {it}: FATAL miss pc={pc:#x} outside addressable code — "
                  "replay diverged (behavioral bug, not a coverage gap); stopping")
            result = "diverged"
            break
        if pc in seen:
            if pc in direct:
                print(f"iter {it}: repeat miss {pc:#x} after direct seed — stopping")
                result = "no-progress"
                break
            direct.add(pc)
            seeds.append((pc, mode, f"resolve: direct seed for {pc:#x}"))
            print(f"iter {it}: {pc:#x} -> direct seed")
            continue
        seen.add(pc)
        if (pc >> 24) == 0x03:
            if any(lo <= pc < hi for lo, hi in spans):
                seeds.append((pc, mode, f"resolve: RAM island in code_copy span {pc:#x}"))
                print(f"iter {it}: {pc:#x} RAM island -> seed")
                continue
            print(f"iter {it}: {pc:#x} RAM outside mapped spans: MANUAL stop")
            result = "manual"
            break
        cands = misspack.prologue_scan(rom, pc, mode, limit=a.max_scan)
        if not cands:
            direct.add(pc)
            seeds.append((pc, mode, f"resolve: direct seed (no prologue) {pc:#x}"))
            print(f"iter {it}: {pc:#x} -> direct seed")
            continue
        start = cands[0][0]
        if start >= 0x08500000 or start in existing or any(s[0] == start for s in seeds):
            direct.add(pc)
            seeds.append((pc, mode, f"resolve: direct seed {pc:#x} (start {start:#x} rejected)"))
            print(f"iter {it}: {pc:#x} -> direct seed")
            continue
        seeds.append((start, mode, f"resolve: covers miss {pc:#x}; push @0x{start:08X}"))
        print(f"iter {it}: {pc:#x} -> seed {start:#x} (total {len(seeds)})")

    write_overlay()
    print(f"resolve {result}: {len(seeds)} seed(s); overlay at {overlay}")
    if seeds:
        lines = [f"# resolve proposal ({a.trace}) — review before merging into game.toml", ""]
        for addr, mode, note in seeds:
            lines += ["[[extra_func]]", f"addr = 0x{addr:08X}",
                      f'mode = "{mode}"', f'note = "{note}"', ""]
        pathlib.Path(a.proposal_out).write_text("\n".join(lines) + "\n")
        print(f"proposal written: {a.proposal_out}")
    return 0 if result == "passed" else 2


if __name__ == "__main__":
    sys.exit(main())
