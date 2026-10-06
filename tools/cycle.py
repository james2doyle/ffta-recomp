#!/usr/bin/env python3
"""cycle.py — the standard change cycle: cold regen → dispatch sanity → build
→ attract gate (+ optional non-strict miss harvest).

Run after ANY game.toml / src change (AGENTS.md § "Validation discipline"):

  .venv/bin/python tools/cycle.py                  # regen + build + gate
  .venv/bin/python tools/cycle.py --harvest 2400   # + miss fragment harvest
  .venv/bin/python tools/cycle.py --frames 2400    # gate horizon (must match
                                                   # the pitch pin; --repin first)
  .venv/bin/python tools/cycle.py --skip-regen --skip-build

Sanity check baked in (the entries_mode lesson, BRINGUP § "Reference-repo
study"): every dispatch-table row must have an aligned address — thumb rows
even, ARM rows 4-aligned. Odd addresses mean raw interworking pointers were
not masked and the odd-pc dispatch ladder is back.

Exit code 0 only if every enabled stage passes.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RECOMPILER = REPO / "gbarecomp/build/gba_recompile"
NATIVE = REPO / "build/FFTARecomp"
BIOS = REPO / "gbarecomp/bios/gba_bios.bin"
ROM = REPO / "game.gba"
DISPATCH = REPO / "generated/dispatch_table.cpp"
LOGS = REPO / "logs"


def run(cmd, **kw):
    return subprocess.run([str(c) for c in cmd], cwd=str(REPO),
                          capture_output=True, text=True, **kw)


def stage_regen():
    shutil.rmtree(REPO / "recomp_cache", ignore_errors=True)
    res = run([RECOMPILER, "--rom", ROM, "--config", REPO / "game.toml",
               "--out", REPO / "generated", "--max-functions", "65536"],
              timeout=900)
    out = res.stdout + res.stderr
    if res.returncode != 0:
        print("regen: FAIL")
        print(out[-1500:])
        return False
    m = re.search(r"==> discovered (\d+) functions", out)
    t = re.search(r"TOTAL emitted:\s+(\d+)", out)
    print(f"regen: OK — discovered {m.group(1) if m else '?'} functions, "
          f"TOTAL emitted {t.group(1) if t else '?'}")
    return True


def stage_dispatch_sanity():
    if not DISPATCH.exists():
        print("dispatch sanity: SKIP (no generated/dispatch_table.cpp)")
        return True
    bad = []
    for line in DISPATCH.read_text(errors="replace").splitlines():
        mm = re.match(
            r"\s*\{0x([0-9A-Fa-f]+)u,\s*(\d)u,\s*(\d)u,\s*(\w+)\}", line)
        if not mm:
            continue
        addr, thumb = int(mm.group(1), 16), int(mm.group(2))
        if (thumb and addr & 1) or (not thumb and addr & 3):
            bad.append((addr, mm.group(4)))
    if bad:
        print(f"dispatch sanity: FAIL — {len(bad)} misaligned "
              f"entr{'y' if len(bad) == 1 else 'ies'} (thumb bit masked? "
              f"see BRINGUP entries_mode lesson):")
        for a, host in bad[:10]:
            print(f"   {a:#010x} {host}")
        return False
    print("dispatch sanity: OK (all entries aligned)")
    return True


def stage_build():
    res = run(["cmake", "--build", "build", "--target", "FFTARecomp",
               "--parallel", "8"], timeout=1800)
    out = res.stdout + res.stderr
    if res.returncode != 0:
        print("build: FAIL")
        print(out[-1500:])
        return False
    print("build: OK")
    return True


def stage_gate(frames):
    cmd = [sys.executable, REPO / "tools/attract_check.py"]
    if frames:
        cmd += ["--frames", str(frames)]
    res = run(cmd, timeout=1200)
    out = (res.stdout + res.stderr).strip().splitlines()
    print(f"attract gate: {'OK' if res.returncode == 0 else 'FAIL'} "
          f"(exit {res.returncode})")
    for line in out[-3:]:
        print(f"   {line}")
    return res.returncode == 0


def stage_harvest(frames):
    LOGS.mkdir(exist_ok=True)
    frag = LOGS / "cycle_harvest.frag"
    if frag.exists():
        frag.unlink()
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("GBARECOMP_")}
    env["GBARECOMP_MISS_FRAG"] = str(frag)
    res = subprocess.run(
        [str(NATIVE), "--bios", str(BIOS), "--rom", str(ROM),
         "--frames", str(frames), "--no-window"],
        cwd=str(REPO), capture_output=True, text=True, timeout=1800, env=env)
    out = res.stdout + res.stderr
    pcs = set()
    if frag.exists():
        pcs = {int(m, 16) for m in
               re.findall(r"(?m)^addr = 0x([0-9A-Fa-f]+)", frag.read_text())}
    cov = re.search(r"self_heal_coverage=(\S+)", out)
    print(f"harvest: {len(pcs)} distinct miss PCs → "
          f"{frag.relative_to(REPO)} (coverage={cov.group(1) if cov else '?'})")
    if pcs:
        print("   next: .venv/bin/python tools/misspack.py "
              "logs/cycle_harvest.frag")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--frames", type=int, default=None,
                    help="gate horizon (default: the pin in attract_check.py)")
    ap.add_argument("--harvest", type=int, default=None, metavar="N",
                    help="also run a non-strict N-frame miss harvest")
    ap.add_argument("--skip-regen", action="store_true")
    ap.add_argument("--skip-build", action="store_true")
    ap.add_argument("--skip-gate", action="store_true")
    args = ap.parse_args()

    ok = True
    if not args.skip_regen:
        ok &= stage_regen()
        ok &= stage_dispatch_sanity()
    if not args.skip_build and ok is not False:
        ok &= stage_build()
    if not args.skip_gate and ok:
        ok &= stage_gate(args.frames)
    if args.harvest:
        ok &= stage_harvest(args.harvest)
    print(f"cycle: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
