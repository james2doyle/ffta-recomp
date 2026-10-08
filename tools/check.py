#!/usr/bin/env python3
"""One-command regression gate for the FFTA recomp worktree.

Runs: host unit tests (C++ + Python) -> patch validity -> attract golden
gate -> strict route replays (user save-load repro, session G, session K)
against the frozen fixtures in saves/regress/.

The checks are independent processes, so they run concurrently by default
(--jobs; auto = min(8, cpus)). Each game run gets isolated outputs — its own
battery-save copy and its own GBARECOMP_COVERAGE_JSON path in the temp dir —
so concurrent runs can't race on the shared fixture save or the repo-root
coverage file. Use --jobs 1 for the old serial order.

Every check prints PASS/FAIL with a one-line summary; exit 0 only if all
pass. Fixtures are local-only (gitignored, like all saves/traces). The save
fixture is sha-verified so an accidental overwrite fails loudly instead of
silently redefining the baseline.

Usage:
  .venv/bin/python tools/check.py            # everything (~1.5-2 min)
  .venv/bin/python tools/check.py --fast     # unit tests + attract only
  .venv/bin/python tools/check.py --jobs 1   # serial
  .venv/bin/python tools/check.py --only NAME
"""
import argparse
import concurrent.futures
import hashlib
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

REPO = pathlib.Path(__file__).resolve().parent.parent
EXE = REPO / "build/FFTARecomp"
BIOS = REPO / "gbarecomp/bios/gba_bios.bin"
ROM = REPO / "game.gba"
REG = REPO / "saves/regress"
FIXTURE_SAVE = REG / "skyemu_20261007.sav"
FIXTURE_SHA_PREFIX = "65742af1"


def clean_env():
    return {k: v for k, v in os.environ.items() if not k.startswith("GBARECOMP_")}


def run(cmd, env=None, timeout=600):
    return subprocess.run(cmd, cwd=str(REPO), env=env or clean_env(),
                          capture_output=True, text=True, timeout=timeout)


def check_unit_cpp():
    b = run(["cmake", "--build", "build", "--target", "ffta_unit_tests",
             "--parallel", "8"])
    if b.returncode != 0:
        return False, "build failed: " + b.stderr.strip()[-160:]
    r = run([str(REPO / "build/ffta_unit_tests")])
    line = (r.stdout.strip().splitlines() or [""])[-1]
    return r.returncode == 0 and "PASS" in line, line


def check_unit_py():
    r = run([sys.executable, "tests/python/test_tools.py"])
    line = (r.stdout.strip().splitlines() or [""])[-1]
    return r.returncode == 0, line


def check_attract():
    r = run([sys.executable, "tools/attract_check.py"], timeout=900)
    line = next((l for l in r.stdout.splitlines() if "attract_verify" in l), "")
    return r.returncode == 0 and "PASS" in line, line or f"exit {r.returncode}"


def strict_route(trace, frames):
    if not trace.exists():
        return False, f"missing fixture {trace.name}"
    env = clean_env()
    env["GBARECOMP_STRICT_STATIC"] = "1"
    env["GBARECOMP_INPUT_REPLAY"] = str(trace)
    # Parallel safety: each run gets its own save copy (the runner flushes
    # "<save>.tmp" then renames; runs sharing one path would race) and its own
    # coverage-json path (runs otherwise clobber recomp_coverage_*.json in the
    # repo root).
    save = FIXTURE_SAVE
    if FIXTURE_SAVE.exists():
        save = pathlib.Path(tempfile.gettempdir()) / f"ffta_check_{trace.stem}.sav"
        shutil.copyfile(FIXTURE_SAVE, save)
    env["GBARECOMP_COVERAGE_JSON"] = str(
        pathlib.Path(tempfile.gettempdir()) / f"ffta_check_{trace.stem}_cov.json")
    r = run([str(EXE), "--bios", str(BIOS), "--rom", str(ROM),
             "--save-path", str(save), "--frames", str(frames),
             "--no-window"], env=env, timeout=1800)
    cov = next((l for l in r.stdout.splitlines()
                if "self_heal_coverage" in l), "")
    return r.returncode == 0 and "FULLY_STATIC" in cov, cov or f"exit {r.returncode}"


def check_savecheck():
    r = run([sys.executable, "tools/savecheck.py", str(FIXTURE_SAVE)], timeout=120)
    line = (r.stdout.strip().splitlines() or [""])[-1]
    return r.returncode == 0 and "savecheck: OK" in line, line


def check_patches():
    """tools/patches/*.patch must be real diffs matching the pinned submodule:
    apply-able forward to a pristine gbarecomp, or reversible from the patched
    dev tree. Catches mangled/empty exports (2026-10-08 regression)."""
    details = []
    ok = True
    for name in ("oracle-save-autoload.patch",
                 "selfheal-journal-close-hardening.patch"):
        p = REPO / "tools/patches" / name
        if not p.exists():
            ok = False
            details.append(f"{name}: missing")
            continue
        fwd = run(["git", "-C", "gbarecomp", "apply", "--check", str(p)])
        if fwd.returncode == 0:
            details.append(f"{name}: forward-ok")
            continue
        rev = run(["git", "-C", "gbarecomp", "apply", "--check",
                   "--reverse", str(p)])
        if rev.returncode == 0:
            details.append(f"{name}: reverse-ok (applied)")
        else:
            ok = False
            details.append(f"{name}: INVALID")
    return ok, " ".join(details)


CHECKS = {
    "unit-cpp": check_unit_cpp,
    "unit-py": check_unit_py,
    "savecheck": check_savecheck,
    "patches": check_patches,
    "attract": check_attract,
    "user_load": lambda: strict_route(REG / "user_load_trace.csv", 1600),
    "route_G": lambda: strict_route(REG / "sessionG_trace.csv", 19400),
    "route_K": lambda: strict_route(REG / "sessionK_trace.csv", 29884),
}
FAST = ["unit-cpp", "unit-py", "savecheck", "patches", "attract"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true")
    ap.add_argument("--only", choices=sorted(CHECKS))
    ap.add_argument("--jobs", type=int, default=0,
                    help="concurrent checks (default: auto = min(8, cpus); "
                         "1 = serial)")
    a = ap.parse_args()
    if not EXE.exists():
        print(f"check: {EXE} missing - build the game first (see AGENTS.md)")
        return 1
    if FIXTURE_SAVE.exists():
        h = hashlib.sha256(FIXTURE_SAVE.read_bytes()).hexdigest()
        if not h.startswith(FIXTURE_SHA_PREFIX):
            print(f"check: regress save sha256 {h[:12]}... != frozen "
                  f"{FIXTURE_SHA_PREFIX} - regenerate fixtures deliberately "
                  "before trusting results")
            return 1
    names = [a.only] if a.only else (FAST if a.fast else list(CHECKS))
    jobs = a.jobs if a.jobs > 0 else min(8, os.cpu_count() or 4)
    jobs = max(1, min(jobs, len(names)))
    print(f"check: {len(names)} check(s), jobs={jobs}", flush=True)

    def run_one(name):
        t0 = time.time()
        try:
            ok, detail = CHECKS[name]()
        except Exception as exc:  # keep the gate summarizing on crashes/timeouts
            ok, detail = False, f"exception: {exc}"
        return name, ok, detail, time.time() - t0

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = [pool.submit(run_one, n) for n in names]
        for fut in concurrent.futures.as_completed(futures):
            n, ok, detail, dt = fut.result()
            print(f"[{'PASS' if ok else 'FAIL'}] {n:9s} {dt:6.1f}s  {detail}",
                  flush=True)
            results.append((n, ok))
    failed = [n for n, ok in results if not ok]
    print(f"check: {'ALL PASS' if not failed else 'FAILED: ' + ', '.join(failed)} "
          f"({len(results) - len(failed)}/{len(results)})")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
