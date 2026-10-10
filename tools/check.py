#!/usr/bin/env python3
"""One-command regression gate for the FFTA recomp worktree.

Runs: host unit tests (C++ + Python) -> patch validity -> device-free
Android checks -> attract golden gate -> widescreen smoke (margin census /
center-crop / stale guard, needs the local game.state1/state2 fixtures) ->
strict route replays (user save-load repro, session G, session K) against
the frozen fixtures in saves/regress/.

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
  .venv/bin/python tools/check.py --fast     # unit tests + android checks + attract
  .venv/bin/python tools/check.py --jobs 1   # serial
  .venv/bin/python tools/check.py --only NAME[,NAME...]

CI tier 1 runs the no-private-material subset (no ROM/BIOS/savestates
needed): `--only unit-cpp,unit-py,patches,android-static` — see
tests/README.md § Continuous integration.

Opt-in suite (not in the default run): `android-apk` — the content guard for
a built APK (`tools/android_apk_check.py`); it needs an Android build, so
select it explicitly with `--only android-apk`.
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
    if r.returncode != 0 and not line.strip():
        # unittest reports and import tracebacks go to stderr; without this
        # fallback the table shows an empty detail for those failures.
        err = [l for l in r.stderr.strip().splitlines() if l.strip()]
        line = next((l for l in reversed(err) if "error" in l.lower()),
                    err[-1] if err else f"exit {r.returncode}")
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


def check_ws_smoke():
    # Inner --jobs stays small: this check runs inside the outer pool, so
    # 8x8 nested engine runs would oversubscribe the machine.
    r = run([sys.executable, "tools/ws_check.py", "--jobs", "4"], timeout=1800)
    line = (r.stdout.strip().splitlines() or [""])[-1]
    if r.returncode == 2:
        # Missing or sha-changed local savestate fixtures; the tool's SKIP
        # line carries the reason (fresh clones have no states by design).
        return False, line or "fixtures missing (saves/ws_fixtures)"
    return r.returncode == 0, line or f"exit {r.returncode}"


def check_savecheck():
    r = run([sys.executable, "tools/savecheck.py", str(FIXTURE_SAVE)], timeout=120)
    line = (r.stdout.strip().splitlines() or [""])[-1]
    return r.returncode == 0 and "savecheck: OK" in line, line


def check_patches():
    """tools/patches/*.patch must be real diffs matching the pinned submodules:
    apply-able forward to a pristine tree, or reversible from the patched dev
    tree. Catches mangled/empty exports (2026-10-08 regression). Patches named
    arm-recomp-core-* target the nested external/arm-recomp-core repo; all
    others target gbarecomp itself."""
    details = []
    ok = True
    names = sorted(p.name for p in (REPO / "tools" / "patches").glob("*.patch"))
    if not names:
        return False, "no *.patch files found"
    for name in names:
        p = REPO / "tools/patches" / name
        if not p.exists():
            ok = False
            details.append(f"{name}: missing")
            continue
        root = ("gbarecomp/external/arm-recomp-core"
                if name.startswith("arm-recomp-core") else "gbarecomp")
        fwd = run(["git", "-C", root, "apply", "--check", str(p)])
        if fwd.returncode == 0:
            details.append(f"{name}: forward-ok")
            continue
        rev = run(["git", "-C", root, "apply", "--check",
                   "--reverse", str(p)])
        if rev.returncode == 0:
            details.append(f"{name}: reverse-ok (applied)")
        else:
            ok = False
            details.append(f"{name}: INVALID")
    # Replay integrity: pin + the consolidated patch must byte-match the dev
    # tree. This catches submodule drift (unrecorded edits) and any mangling
    # the per-file forward/reverse checks would miss. The per-feature files
    # are reference diffs and deliberately are NOT stacked here (their
    # contexts interleave after historical re-exports; the consolidated
    # patch is the canonical re-apply unit). Same for the nested
    # arm-recomp-core repo with its own consolidated patch.
    for root, cons_name, label in (
            ("gbarecomp", "gbarecomp-local.patch", "gbarecomp-local"),
            ("gbarecomp/external/arm-recomp-core",
             "arm-recomp-core-local.patch", "arm-recomp-core-local")):
        cons = REPO / "tools" / "patches" / cons_name
        if not cons.exists():
            continue
        with tempfile.TemporaryDirectory(prefix="gbpatch.") as td:
            arch = subprocess.run(
                ["bash", "-c", f"git -C {root} archive HEAD | tar -x -C {td}"],
                cwd=str(REPO), capture_output=True, text=True)
            app = subprocess.run(
                ["patch", "-p1", "-s", "-f", "--no-backup-if-mismatch",
                 "-i", str(cons)], cwd=td, capture_output=True, text=True)
            if arch.returncode != 0 or app.returncode != 0:
                ok = False
                details.append(f"{label} replay: apply FAILED")
            else:
                # The byte-compare below is a LOCAL-dev-tree guarantee: pin+
                # patch must equal the submodule tree that carries the
                # uncommitted framework edits. A pristine checkout (CI) has
                # no local edits — its tree IS the pin, so the clean apply
                # above already proved patch<->pin fidelity and the compare
                # would false-red on every patched file. Skip it there.
                # Tracked modifications only (-uno): untracked build junk
                # must not force the compare.
                pristine = not run(
                    ["git", "-C", root, "status", "--porcelain", "-uno"]
                ).stdout.strip()
                if pristine:
                    details.append(
                        f"{label} replay: apply-ok (pristine submodule)")
                    continue
                tracked = run(["git", "-C", root, "ls-files"]).stdout.split()
                bad = []
                for f in tracked:
                    dev = REPO / root / f
                    if not dev.is_file():
                        continue  # gitlinks and directories
                    rep = pathlib.Path(td) / f
                    if not rep.exists() or rep.read_bytes() != dev.read_bytes():
                        bad.append(f)
                if bad:
                    ok = False
                    details.append(
                        f"{label} replay: {len(bad)} file(s) differ "
                        f"(e.g. {', '.join(bad[:3])})")
                else:
                    details.append(
                        f"{label} replay: {len(tracked)}-file tree matches")
    return ok, " ".join(details)


def _acceptance_lock():
    """Cross-process lock so concurrent check runs never race two acceptance
    games (they share evidence paths and would collide regardless of port)."""
    import fcntl
    lock_dir = REPO / "logs" / "desktop_accept"
    lock_dir.mkdir(parents=True, exist_ok=True)
    f = open(lock_dir / ".lock", "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    return f


def check_desktop_accept():
    """Opt-in TCP-observed free-run acceptance of the suspend-save press
    (tools/desktop_accept.py --mode tcp). Skips without game.state3 /
    saves/playtest.sav, or while another acceptance holds the lock."""
    if not (REPO / "game.state3").exists() or not (REPO / "saves" / "playtest.sav").exists():
        return True, "skipped (needs game.state3 + saves/playtest.sav)"
    lock = _acceptance_lock()
    if lock is None:
        return True, "skipped (another acceptance running)"
    try:
        r = run([sys.executable, "tools/desktop_accept.py", "--mode", "tcp",
                 "--port", "19878", "--work", "logs/desktop_accept/tcp",
                 "--observe", "60"], timeout=300)
    finally:
        lock.close()
    if r.returncode == 77:
        return True, "skipped (prerequisites missing)"
    if r.returncode == 0:
        return True, "PASS: desktop acceptance (tcp free-run)"
    return False, f"FAIL: desktop acceptance rc={r.returncode}"


def check_desktop_accept_window():
    """Opt-in WINDOWED acceptance (present-in-place path): play.sh +
    --tcp-observe + ydotool press, scored identically. This is the path
    where the abandon-resume one-unwind hook and mode coherence matter
    (present-in-place never unwinds on VBlank by design). Skips (rc 77)
    without a display / ydotool / state3 / playtest.sav."""
    if not (REPO / "game.state3").exists() or not (REPO / "saves" / "playtest.sav").exists():
        return True, "skipped (needs game.state3 + saves/playtest.sav)"
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return True, "skipped (needs a display)"
    if shutil.which("ydotool") is None:
        return True, "skipped (needs ydotool)"
    lock = _acceptance_lock()
    if lock is None:
        return True, "skipped (another acceptance running)"
    try:
        r = run([sys.executable, "tools/desktop_accept.py", "--mode", "window",
                 "--port", "19879", "--work", "logs/desktop_accept/window",
                 "--observe", "60"], timeout=300)
    finally:
        lock.close()
    if r.returncode == 77:
        return True, "skipped (prerequisites missing)"
    if r.returncode == 0:
        return True, "PASS: desktop acceptance (windowed present-in-place)"
    return False, f"FAIL: windowed desktop acceptance rc={r.returncode}"


def check_hangrepro():
    """Opt-in deterministic press repro (tools/hangrepro.py): the state3
    suspend->A hang must stay bounded (pre-guard it SIGSEGV'd at ~+26 steps;
    now the process survives with host-stack guard unwinds). Needs the
    gitignored game.state3 + saves/playtest.sav; reports skipped otherwise."""
    r = run([sys.executable, "tools/hangrepro.py"], timeout=600)
    line = (r.stdout.strip().splitlines() or [""])[-1]
    if r.returncode == 77:
        return True, "skipped (no game.state3 / saves/playtest.sav)"
    return r.returncode == 0, line or f"exit {r.returncode}"


def check_android_static():
    """Device-free Android checks (tools/android_static_check.py): identity
    pin consistency, the mods payload contract, tracked-file hygiene, and a
    fake-adb self-test of the device gate script. Needs only the checkout —
    no SDK, no device, no private material."""
    r = run([sys.executable, "tools/android_static_check.py"], timeout=300)
    line = (r.stdout.strip().splitlines() or [""])[-1]
    return r.returncode == 0, line or f"exit {r.returncode}"


def check_android_apk():
    """Content guard for a built APK (tools/android_apk_check.py): payload
    vs staging sources, private-embed pins, per-ABI libs, manifest facts,
    duplicate/stray/oversize zip entries. Opt-in — it needs a built APK
    (--only android-apk; build first: android/README.md § Build)."""
    r = run([sys.executable, "tools/android_apk_check.py"], timeout=600)
    line = (r.stdout.strip().splitlines() or [""])[-1]
    return r.returncode == 0, line or f"exit {r.returncode}"


CHECKS = {
    "unit-cpp": check_unit_cpp,
    "unit-py": check_unit_py,
    "savecheck": check_savecheck,
    "patches": check_patches,
    "android-static": check_android_static,
    "hangrepro": check_hangrepro,
    "desktop-accept": check_desktop_accept,
    "desktop-accept-window": check_desktop_accept_window,
    "android-apk": check_android_apk,
    "attract": check_attract,
    "ws_smoke": check_ws_smoke,
    "user_load": lambda: strict_route(REG / "user_load_trace.csv", 1600),
    "route_G": lambda: strict_route(REG / "sessionG_trace.csv", 19400),
    "route_K": lambda: strict_route(REG / "sessionK_trace.csv", 29884),
}
FAST = ["unit-cpp", "unit-py", "savecheck", "patches", "android-static",
        "attract"]
# Opt-in suites, left out of the default run (they need local artifacts a
# desktop-only worktree may not have); --only NAME runs them explicitly.
OPTIONAL = {"android-apk"}
# Checks that execute the game binary (require it to exist); the others run
# on a fresh clone without the ROM (CI tier 1: unit-cpp, unit-py, patches).
NEEDS_EXE = {"attract", "ws_smoke", "user_load", "route_G", "route_K"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true")
    ap.add_argument("--only",
                    help="comma-separated subset, e.g. "
                         "unit-cpp,unit-py,patches,android-static")
    ap.add_argument("--jobs", type=int, default=0,
                    help="concurrent checks (default: auto = min(8, cpus); "
                         "1 = serial)")
    a = ap.parse_args()
    names = []
    if a.only:
        names = [n.strip() for n in a.only.split(",") if n.strip()]
        unknown = [n for n in names if n not in CHECKS]
        if unknown:
            print("check: unknown check(s): " + ", ".join(unknown) +
                  " (known: " + ", ".join(sorted(CHECKS)) + ")")
            return 1
    needs_exe = [n for n in names if n in NEEDS_EXE]
    if needs_exe and not EXE.exists():
        print(f"check: {EXE} missing - build the game first "
              f"(needed by: {', '.join(needs_exe)}; see AGENTS.md)")
        return 1
    if FIXTURE_SAVE.exists():
        h = hashlib.sha256(FIXTURE_SAVE.read_bytes()).hexdigest()
        if not h.startswith(FIXTURE_SHA_PREFIX):
            print(f"check: regress save sha256 {h[:12]}... != frozen "
                  f"{FIXTURE_SHA_PREFIX} - regenerate fixtures deliberately "
                  "before trusting results")
            return 1
    names = names if a.only else (
        FAST if a.fast else [n for n in CHECKS if n not in OPTIONAL])
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
