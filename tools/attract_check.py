#!/usr/bin/env python3
"""attract_check.py — attract-corridor regression gate for FFTA.

Pattern copied from WarioWareTwistedRecomp tools/verify-attract.ps1: run the
native runner headless for a fixed frame count with a throwaway save, assert
the strict-static banner, and compare the SHA-256 of the dumped frame against
a value pinned right here (hash string only — never a committed image; frames
are ROM-derived).

The attract corridor covers BIOS + title animation and is FULLY_STATIC from
2026-10-06 (strict 2400 verified). Any game.toml / generated / build change
that alters it flips the hash. Deliberate visual changes are adopted with
--repin (updates EXPECTED_SHA256 / EXPECTED_FRAMES in this file itself).

Usage (repo root):
  .venv/bin/python tools/attract_check.py              # verify (exit 0 = PASS)
  .venv/bin/python tools/attract_check.py --repin      # adopt current output
  .venv/bin/python tools/attract_check.py --frames 2400

Exit codes: 0 PASS, 1 FAIL (banner/hash/exit-code problem), 2 not pinned or
frames mismatch with the pin.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# ── pinned golden (updated only by --repin, review the diff on commit) ──────
EXPECTED_SHA256 = "1EF4C118A8438CADE6E5847DC6716A7A800D157A568DECB272F2F7052EF321C1"
EXPECTED_FRAMES = 1200
# ────────────────────────────────────────────────────────────────────────────

BANNER_PATTERNS = (
    "self_heal_coverage=FULLY_STATIC",
    "dispatch_misses=0",
    "interpreted_insns=0",
    "unmapped=0",
    "io_unhandled=0",
)


def repin(sha: str, frames: int) -> None:
    path = Path(__file__).resolve()
    text = path.read_text()
    text = re.sub(r'(?m)^EXPECTED_SHA256 = ".*"$',
                  f'EXPECTED_SHA256 = "{sha}"', text, count=1)
    text = re.sub(r"(?m)^EXPECTED_FRAMES = \d+$",
                  f"EXPECTED_FRAMES = {frames}", text, count=1)
    path.write_text(text)
    print(f"repinned: frames={frames} sha256={sha}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--frames", type=int, default=None,
                    help=f"frames for the gate (default: pinned {EXPECTED_FRAMES})")
    ap.add_argument("--repin", action="store_true",
                    help="adopt the current run's frame hash as the new pin")
    ap.add_argument("--exe", default=str(REPO / "build/FFTARecomp"))
    ap.add_argument("--bios", default=str(REPO / "gbarecomp/bios/gba_bios.bin"))
    ap.add_argument("--rom", default=str(REPO / "game.gba"))
    args = ap.parse_args()
    frames = args.frames if args.frames is not None else EXPECTED_FRAMES

    if not args.repin and not EXPECTED_SHA256:
        print("not pinned yet — run: tools/attract_check.py --repin",
              file=sys.stderr)
        return 2
    if not args.repin and frames != EXPECTED_FRAMES:
        print(f"frames={frames} differs from pinned frames={EXPECTED_FRAMES}; "
              f"run --repin --frames {frames} to adopt", file=sys.stderr)
        return 2

    env = {k: v for k, v in __import__("os").environ.items()
           if not k.startswith("GBARECOMP_")}
    env["GBARECOMP_STRICT_STATIC"] = "1"
    env["GBARECOMP_HANG_WATCHDOG"] = "0"

    problems: list[str] = []
    with tempfile.TemporaryDirectory(prefix="ffta_attract_") as td:
        png = Path(td) / "attract_frame.png"
        sav = Path(td) / "throwaway.sav"
        env["GBARECOMP_COVERAGE_JSON"] = str(Path(td) / "coverage.json")
        cmd = [args.exe, "--config", str(REPO / "game.toml"),
               "--bios", args.bios, "--rom", args.rom,
               "--frames", str(frames), "--no-window",
               "--dump-png", str(png), "--save-path", str(sav)]
        res = subprocess.run(cmd, cwd=str(REPO), capture_output=True,
                             text=True, timeout=900, env=env)
        out = res.stdout + res.stderr
        log_path = REPO / "logs" / f"attract_check_{frames}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(out)

        if res.returncode != 0:
            problems.append(f"exit code {res.returncode}")
        for pat in BANNER_PATTERNS + (f"ppu_frames={frames}",):
            if pat not in out:
                problems.append(f"banner missing {pat!r}")
        if not png.exists():
            problems.append("no frame dumped")
        sha = (hashlib.sha256(png.read_bytes()).hexdigest().upper()
               if png.exists() else None)
        if png.exists():
            shutil.copy(png, REPO / "logs" / "attract_check_last.png")

    if args.repin:
        if sha is None:
            print("repin failed: no frame produced (see log)", file=sys.stderr)
            return 1
        repin(sha, frames)
        if problems:
            print("warning: banner problems during repin: " + "; ".join(problems),
                  file=sys.stderr)
        return 0

    if sha is not None and sha != EXPECTED_SHA256:
        problems.append(f"frame sha256 mismatch (got {sha}, "
                        f"expected {EXPECTED_SHA256})")

    if problems:
        print(f"attract_verify=FAIL frames={frames}")
        for p in problems:
            print(f"  - {p}")
        print(f"  log: {log_path}")
        print(f"  frame: logs/attract_check_last.png")
        if any("sha256 mismatch" in p for p in problems):
            print("  if the visual change is deliberate: tools/attract_check.py --repin")
        return 1
    print(f"attract_verify=PASS frames={frames} sha256={sha}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
