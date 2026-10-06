#!/usr/bin/env python3
"""Regenerate the three-lens function-mapping coverage table for FFTA Recomp.

Lenses (see BRINGUP.md for the methodology):
  1. Executed path  — strict native run (default 1200 frames); 100% means
     FULLY_STATIC with zero dispatch misses / interpreted instructions.
  2. Static reach   — trial config with the aot scan widened to the whole
     ROM; "mapped / total" = current corpus vs. what the walker can find.
  3. Pointer pool   — trial config with speculative_literal_harvest = true;
     "mapped / total" = current corpus vs. the plausible-code-pointer pool.

Usage:
  .venv/bin/python tools/coverage_report.py [--frames N] [--log PATH]
                                           [--json] [--no-run] [--keep-temp]

--log uses an existing native run log instead of running (implies --no-run).
The trials always regenerate from game.toml into a throwaway temp dir with a
cold cache; game.toml and generated/ are never touched. Assumes build/ and
gbarecomp/build/gba_recompile are up to date.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECOMPILER = ROOT / "gbarecomp/build/gba_recompile"
NATIVE = ROOT / "build/FFTARecomp"
GAME_TOML = ROOT / "game.toml"

WHOLE_ROM_SCAN_END = "0x09000000"  # 16 MiB cart: 0x08000000..0x09000000


def parse_toml_path(text: str, section: str, key: str) -> str | None:
    m = re.search(
        rf"(?ms)^\[{re.escape(section)}\]\s*$(.*?)(?=^\[|\Z)", text
    )
    if not m:
        return None
    m2 = re.search(rf"(?m)^\s*{re.escape(key)}\s*=\s*\"([^\"]+)\"", m.group(1))
    return m2.group(1) if m2 else None


def regen(config: Path, out: Path, workdir: Path, rom: Path) -> dict:
    cmd = [
        str(RECOMPILER), "--rom", str(rom), "--config", str(config),
        "--out", str(out), "--max-functions", "65536",
    ]
    res = subprocess.run(
        cmd, cwd=workdir, capture_output=True, text=True, timeout=900
    )
    if res.returncode != 0:
        raise RuntimeError(
            f"recompile failed ({config.name}):\n{res.stdout[-2000:]}\n{res.stderr[-2000:]}"
        )
    out_text = res.stdout + res.stderr
    units = re.search(r"TOTAL emitted:\s+(\d+)", out_text)
    if not units:
        raise RuntimeError(f"no 'TOTAL emitted' in output:\n{out_text[-2000:]}")
    info = {"units": int(units.group(1))}
    seeds = re.search(r"literal_pool_seeds:\s+(\d+) kept / (\d+) PC-rel", out_text)
    if seeds:
        info["literal_seeds_kept"] = int(seeds.group(1))
        info["literals_scanned"] = int(seeds.group(2))
    return info


def run_strict(frames: int, rom: Path, bios: Path, log_path: Path) -> dict:
    env = os.environ | {"GBARECOMP_STRICT_STATIC": "1"}
    cmd = [
        str(NATIVE), "--bios", str(bios), "--rom", str(rom),
        "--frames", str(frames), "--no-window",
    ]
    res = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                         timeout=900, env=env)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(res.stdout + res.stderr)
    return parse_strict_log(res.stdout + res.stderr, frames, log_path)


def parse_strict_log(text: str, frames: int, log_path: Path | None) -> dict:
    m = re.search(
        r"self_heal_coverage=(\S+) dispatch_misses=(\d+) "
        r"interpreted_insns=(\d+) healed_native=(\d+)",
        text,
    )
    if not m:
        raise RuntimeError(
            f"no coverage banner in run log{': ' + str(log_path) if log_path else ''}"
        )
    return {
        "frames": frames,
        "coverage": m.group(1),
        "dispatch_misses": int(m.group(2)),
        "interpreted_insns": int(m.group(3)),
        "healed_native": int(m.group(4)),
        "percent": 100.0 if int(m.group(2)) == 0 else 0.0,
        "log": str(log_path) if log_path else None,
    }


def pct(part: int, total: int) -> float:
    return round(100.0 * part / total, 1) if total else 0.0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--frames", type=int, default=1200,
                    help="frames for the executed-path lens (default 1200)")
    ap.add_argument("--log", type=Path,
                    help="parse an existing native run log instead of running")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of markdown")
    ap.add_argument("--no-run", action="store_true",
                    help="skip the native run (executed-path row from --log only)")
    ap.add_argument("--keep-temp", action="store_true")
    args = ap.parse_args()

    toml_text = GAME_TOML.read_text()
    rom = ROOT / (parse_toml_path(toml_text, "rom", "path") or "game.gba")
    bios = ROOT / (parse_toml_path(toml_text, "bios", "path")
                   or "gbarecomp/bios/gba_bios.bin")
    for p, what in ((rom, "ROM"), (bios, "BIOS")):
        if not p.exists():
            print(f"error: {what} not found: {p}", file=sys.stderr)
            return 2

    if args.log and args.no_run:
        pass
    elif args.log:
        args.no_run = True

    workdir = Path(tempfile.mkdtemp(prefix="ffta_coverage_"))
    try:
        # Trial configs derived from the live game.toml.
        scan_cfg = workdir / "trial_scan.toml"
        scan_cfg.write_text(re.sub(
            r"(?m)^aot_scan_end\s*=\s*0x[0-9A-Fa-f]+",
            f"aot_scan_end = {WHOLE_ROM_SCAN_END}", toml_text))
        spec_text, n_sub = re.subn(
            r"(?m)^speculative_literal_harvest\s*=\s*false",
            "speculative_literal_harvest = true", toml_text)
        spec_cfg = workdir / "trial_spec.toml"
        spec_cfg.write_text(spec_text)
        (workdir / "base.toml").write_text(toml_text)

        if n_sub != 1:
            print("warning: speculative_literal_harvest=false not found in "
                  "game.toml; harvest trial may not differ", file=sys.stderr)

        print("regenerating trials (cold cache, temp dir)...", file=sys.stderr)
        base = regen(workdir / "base.toml", workdir / "gen_base", workdir, rom)
        scan = regen(scan_cfg, workdir / "gen_scan", workdir, rom)
        spec = regen(spec_cfg, workdir / "gen_spec", workdir, rom)

        corpus = base["units"]

        if args.no_run and not args.log:
            executed = None
        elif args.log:
            executed = parse_strict_log(args.log.read_text(), args.frames, args.log)
        else:
            print(f"running strict native for {args.frames} frames...",
                  file=sys.stderr)
            executed = run_strict(
                args.frames, rom, bios,
                ROOT / f"logs/coverage_report_strict_{args.frames}.log")

        report = {
            "corpus_units": corpus,
            "executed": executed,
            "static_reach": {
                "trial_units": scan["units"],
                "percent": pct(corpus, scan["units"]),
            },
            "pointer_pool": {
                "trial_units": spec["units"],
                "literal_seeds_kept": spec.get("literal_seeds_kept"),
                "literals_scanned": spec.get("literals_scanned"),
                "percent": pct(corpus, spec["units"]),
            },
        }

        if args.json:
            print(json.dumps(report, indent=2))
        else:
            ex = executed
            if ex:
                ex_cell = ("everything that ran", "**100%** — FULLY_STATIC, "
                           "zero interpreter fallback"
                           if ex["dispatch_misses"] == 0 else
                           f"**{ex['dispatch_misses']} misses** "
                           f"(interpreted_insns={ex['interpreted_insns']})")
            else:
                ex_cell = ("n/a", "no run")
            print("| Lens | Mapped / Total | % |")
            print("|---|---|---|")
            print(f"| **Executed path** (strict {ex['frames'] if ex else '-'}"
                  f"-frame run) | {ex_cell[0]} | {ex_cell[1]} |")
            print(f"| **Walker's static reach** (trial config scanning whole ROM) "
                  f"| **{corpus:,} / {scan['units']:,}** emitted units "
                  f"| **~{report['static_reach']['percent']}%** |")
            print(f"| **Pointer-pool reach** (trial with "
                  f"`speculative_literal_harvest = true`) | **{corpus:,} / "
                  f"{spec['units']:,}** | **~{report['pointer_pool']['percent']}%** |")
            print()
            if ex and ex.get("log"):
                print(f"- Executed-path log: `{Path(ex['log']).relative_to(ROOT)}`")
            print(f"- Corpus units (current config): {corpus:,} "
                  f"(TOTAL emitted; includes interior split units + IWRAM code-copy).")
            if spec.get("literal_seeds_kept") is not None:
                print(f"- Harvest trial kept {spec['literal_seeds_kept']:,} "
                      f"plausible pointers out of {spec['literals_scanned']:,} "
                      f"PC-relative literals (trial only; `false` in game.toml "
                      f"by policy).")
            print("- Rows 2-3 are proxies with different denominators; "
                  "no ground-truth function inventory exists.")
        return 0
    finally:
        if args.keep_temp:
            print(f"temp kept: {workdir}", file=sys.stderr)
        else:
            shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
