#!/usr/bin/env python3
"""Fresh-clone bootstrap: from a clone to a running build/FFTARecomp.

Wraps the newcomer setup (README § Setup) into one idempotent script:

  1. submodules         git submodule update --init --recursive (two-pass)
  2. dumps              game.gba + BIOS present and SHA-1-verified
  3. python env         .venv with the pinned capstone (uv, else venv + pip)
  4. framework patches  tools/patches/*.patch onto the pinned gbarecomp
  5. framework tools    build gba_recompile + gba_scan
  6. BIOS recompile     named-function corpus for the LLE BIOS
  7. corpus regen       game.gba + game.toml + symbols -> generated/
  8. host build         build/FFTARecomp (mods enabled, widescreen ready)
  9. smoke              strict 2400-frame headless run, expects FULLY_STATIC

Runs on the system python3 (stdlib only — it exists before .venv does).
Re-running is cheap: every step detects whether it is already done.
Flags: --force (redo BIOS + corpus), --no-smoke, --jobs N.
"""
import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent
ROM = REPO / "game.gba"
ROM_SHA1 = "4ac05441f4de70a4ec3dd932116346c61b8783d9"
BIOS = REPO / "gbarecomp/bios/gba_bios.bin"
BIOS_SHA1 = "300c20df6731a33952ded8c436f7f186d25d3492"
CAPSTONE_PIN = "5.0.7"
BIOS_OUT = REPO / "gbarecomp/src/runtime/generated_bios/bios_recompiled.cpp"
PATCH_DIR = REPO / "tools/patches"
GENERATED = REPO / "generated"
REGEN_INPUTS = [
    REPO / "game.toml",
    REPO / "symbols/ffta_symbols.tsv",
    REPO / "symbols/ffta_data_symbols.tsv",
    REPO / "gbarecomp/build/gba_recompile",
]
SUBMODULE_MARKERS = [
    REPO / "gbarecomp/CMakeLists.txt",
    REPO / "recomp-ui/CMakeLists.txt",
    REPO / "gbarecomp/external/arm-recomp-core/CMakeLists.txt",
    REPO / "gbarecomp/external/rbengine/CMakeLists.txt",
    REPO / "gbarecomp/external/recomp-net/CMakeLists.txt",
]
N_STEPS = 9


class Fail(Exception):
    def __init__(self, msg, hint=None):
        super().__init__(msg)
        self.msg = msg
        self.hint = hint


def die(msg, hint=None):
    raise Fail(msg, hint)


def sha1_file(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def run(cmd, cwd=REPO, capture=True, env=None, timeout=1800):
    try:
        return subprocess.run([str(c) for c in cmd], cwd=str(cwd), env=env,
                              capture_output=capture, text=True, timeout=timeout)
    except FileNotFoundError:
        die(f"command not found: {cmd[0]}",
            hint="install the build dependencies (README § Requirements)")


def run_ok(cmd, cwd=REPO):
    return run(cmd, cwd=cwd).returncode == 0


def tail(proc, n=20):
    text = (proc.stdout or "") + (proc.stderr or "")
    return "\n".join(text.strip().splitlines()[-n:])


# --- steps -----------------------------------------------------------------

def submodule_drift():
    r = run(["git", "submodule", "status", "--recursive"])
    if r.returncode != 0:
        return 0
    return sum(1 for line in r.stdout.splitlines()
               if line[:1] in ("+", "-"))


def step_submodules():
    if not all(p.exists() for p in SUBMODULE_MARKERS):
        r = run(["git", "submodule", "update", "--init", "--recursive"],
                capture=False)
        if r.returncode != 0:
            die("submodule checkout failed (see output above)",
                hint="git needs network access here; retry "
                     "`git submodule update --init --recursive`")
        if not all(p.exists() for p in SUBMODULE_MARKERS):
            r = run(["git", "submodule", "update", "--checkout",
                     "--recursive"], capture=False)
            if r.returncode != 0:
                die("submodule checkout failed (see output above)",
                    hint="retry "
                         "`git submodule update --checkout --recursive`")
        if not all(p.exists() for p in SUBMODULE_MARKERS):
            missing = [str(p.relative_to(REPO)) for p in SUBMODULE_MARKERS
                       if not p.exists()]
            die("submodule worktrees still incomplete: " + ", ".join(missing),
                hint="check network access; retry "
                     "`git submodule update --checkout --recursive`")
        detail = "cloned"
    else:
        detail = "already present"
    drift = submodule_drift()
    if drift:
        return (detail + f" — warning: {drift} submodule(s) off-pin "
                         "(check `git submodule status --recursive`)")
    return detail


def step_dumps():
    checks = [
        (ROM, ROM_SHA1, 16777216, "ROM", "game.gba",
         "place your own legally-dumped FFTA (USA) ROM at game.gba "
         "(never commit or download it)"),
        (BIOS, BIOS_SHA1, 16384, "BIOS", "gbarecomp/bios/gba_bios.bin",
         "place your own GBA BIOS dump at gbarecomp/bios/gba_bios.bin "
         "(do not download a BIOS)"),
    ]
    for path, want, size, label, where, hint in checks:
        if not path.exists():
            die(f"{label} missing: {where}", hint=hint)
        got_size = path.stat().st_size
        if got_size != size:
            die(f"{label} has the wrong size: {got_size} bytes (expected "
                f"{size}) — truncated or corrupt file?", hint=hint)
        got = sha1_file(path)
        if got != want:
            die(f"{label} SHA-1 mismatch: got {got[:12]}..., want "
                f"{want[:12]}... — wrong or corrupt dump?", hint=hint)
    return "ROM + BIOS present, size + SHA-1 verified"


def step_venv():
    py = REPO / ".venv/bin/python"
    if py.exists() and run_ok([py, "-c", "import capstone"]):
        return "already ready"
    if shutil.which("uv"):
        r = run(["uv", "venv", ".venv"], capture=False)
        if r.returncode != 0:
            die("could not create .venv with uv (see output above)")
        r = run(["uv", "pip", "install", "--python", ".venv",
                 f"capstone=={CAPSTONE_PIN}"])
    else:
        r = run([sys.executable, "-m", "venv", ".venv"])
        if r.returncode != 0 or not (REPO / ".venv/bin/pip").exists():
            die("uv not found and `python3 -m venv` failed",
                hint="install uv (https://docs.astral.sh/uv/) or your "
                     "distro's python venv/pip packages")
        r = run([REPO / ".venv/bin/pip", "install", f"capstone=={CAPSTONE_PIN}"])
    if r.returncode != 0:
        die("capstone install failed", hint=tail(r))
    if not run_ok([py, "-c", "import capstone"]):
        die("capstone still not importable from .venv")
    return f"capstone {CAPSTONE_PIN}"


def step_patches():
    if not (REPO / "gbarecomp/.git").exists():
        return "not a git submodule — skipped"
    patches = sorted(PATCH_DIR.glob("*.patch"))
    if not patches:
        die("no framework patches found in tools/patches/",
            hint="incomplete checkout — the patches ship with this repo")
    applied, in_place = [], 0
    for patch in patches:
        if run_ok(["git", "-C", "gbarecomp", "apply", "--check", "--reverse",
                   patch]):
            in_place += 1
            continue
        if not run_ok(["git", "-C", "gbarecomp", "apply", "--check", patch]):
            die(f"patch does not apply: {patch.name}",
                hint="the submodule likely drifted from its pin — check "
                     "`git -C gbarecomp status`; see README § Troubleshooting")
        r = run(["git", "-C", "gbarecomp", "apply", patch])
        if r.returncode != 0:
            die(f"failed to apply {patch.name}", hint=tail(r))
        applied.append(patch.name)
    if applied:
        return f"{len(applied)} applied, {in_place} already in place"
    return f"all {in_place} already in place"


def step_tools(jobs):
    r = run(["cmake", "-S", "gbarecomp", "-B", "gbarecomp/build", "-G",
             "Ninja", "-DCMAKE_BUILD_TYPE=Release"], capture=False)
    if r.returncode != 0:
        die("framework cmake configure failed (see output above)")
    r = run(["cmake", "--build", "gbarecomp/build", "--target",
             "gba_recompile", "gba_scan", "--parallel", jobs], capture=False)
    if r.returncode != 0:
        die("framework tools build failed (see output above)")
    for binary in ("gba_recompile", "gba_scan"):
        if not (REPO / "gbarecomp/build" / binary).exists():
            die(f"framework build produced no {binary}")
    return "gba_recompile + gba_scan ready"


def step_bios(force):
    if (not force and BIOS_OUT.exists()
            and BIOS_OUT.stat().st_mtime >= BIOS.stat().st_mtime):
        return "up to date"
    r = run(["./build/gba_recompile", "--bios", "bios/gba_bios.bin",
             "--config", "bios/gba_bios.toml"], cwd=REPO / "gbarecomp")
    if r.returncode != 0:
        die("BIOS recompile failed", hint=tail(r))
    if not BIOS_OUT.exists() or BIOS_OUT.stat().st_size == 0:
        die("BIOS recompile produced no output",
            hint="it must run with cwd = gbarecomp/ (see README § Setup)")
    m = re.search(r"discovered (\d+) function", r.stdout)
    return f"{m.group(1)} functions" if m else "done"


def step_regen(force):
    missing = [str(p.relative_to(REPO)) for p in (
        REPO / "game.toml", REPO / "symbols/ffta_symbols.tsv",
        REPO / "symbols/ffta_data_symbols.tsv",
        REPO / "gbarecomp/build/gba_recompile") if not p.exists()]
    if missing:
        die("missing required files: " + ", ".join(missing),
            hint="incomplete checkout — re-clone, or re-run "
                 "`python3 build.py` to rebuild the framework tools")
    if not force and GENERATED.exists():
        newest = max((p.stat().st_mtime for p in GENERATED.rglob("*")
                      if p.is_file()), default=0)
        stale = [p for p in REGEN_INPUTS if p.exists()
                 and p.stat().st_mtime > newest]
        if not stale:
            return "up to date"
    r = run(["./gbarecomp/build/gba_recompile", "--rom", "game.gba",
             "--config", "game.toml",
             "--symbols", "symbols/ffta_symbols.tsv",
             "--data-symbols", "symbols/ffta_data_symbols.tsv",
             "--out", "generated", "--max-functions", "65536"])
    if r.returncode != 0:
        die("corpus regeneration failed", hint=tail(r))
    if not (GENERATED / "dispatch_table.cpp").exists():
        die("regeneration produced no generated/dispatch_table.cpp")
    m = re.search(r"TOTAL emitted:?\s+(\d+)", r.stdout)
    return f"{m.group(1)} units" if m else "done"


def step_host(jobs):
    r = run(["cmake", "-S", ".", "-B", "build", "-G", "Ninja",
             "-DCMAKE_BUILD_TYPE=Release", "-DGBARECOMP_ENABLE_MODS=ON"],
            capture=False)
    if r.returncode != 0:
        die("host cmake configure failed (see output above)")
    r = run(["cmake", "--build", "build", "--target", "FFTARecomp",
             "--parallel", jobs], capture=False)
    if r.returncode != 0:
        die("host build failed (see output above)")
    if not (REPO / "build/FFTARecomp").exists():
        die("host build produced no build/FFTARecomp")
    return "build/FFTARecomp ready"


def step_smoke():
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("GBARECOMP_")}
    env["GBARECOMP_STRICT_STATIC"] = "1"
    r = run(["./build/FFTARecomp", "--bios", "gbarecomp/bios/gba_bios.bin",
             "--rom", "game.gba", "--frames", "2400", "--no-window"], env=env)
    line = next((l.strip() for l in r.stdout.splitlines()
                 if "self_heal_coverage" in l), "")
    if r.returncode != 0 or "FULLY_STATIC" not in line:
        die("strict smoke did not reach FULLY_STATIC",
            hint=line or tail(r))
    return line


# --- main ------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Fresh-clone bootstrap for FFTA Recomp (idempotent).")
    ap.add_argument("--force", action="store_true",
                    help="redo BIOS recompile + corpus even when up to date")
    ap.add_argument("--no-smoke", action="store_true",
                    help="skip the strict 2400-frame smoke at the end")
    ap.add_argument("--jobs", type=int, default=min(8, os.cpu_count() or 4),
                    help="build parallelism (default: min(8, cpus))")
    a = ap.parse_args()

    if (not (REPO / "game.toml").exists()
            or not (REPO / "CMakeLists.txt").exists()):
        die("this does not look like the ffta-recompiled repo",
            hint="run `python3 build.py` from the repo root")

    print(f"build.py — {REPO}")
    print("first run: framework + host builds (minutes); later runs are "
          "near-instant.\n")
    t0 = time.time()
    steps = [
        ("submodules", lambda: step_submodules()),
        ("dumps", lambda: step_dumps()),
        ("python env", lambda: step_venv()),
        ("framework patches", lambda: step_patches()),
        ("framework tools", lambda: step_tools(str(a.jobs))),
        ("BIOS recompile", lambda: step_bios(a.force)),
        ("corpus regen", lambda: step_regen(a.force)),
        ("host build", lambda: step_host(str(a.jobs))),
        ("smoke", None if a.no_smoke else lambda: step_smoke()),
    ]
    for i, (title, fn) in enumerate(steps, 1):
        print(f"[{i}/{N_STEPS}] {title} ... ", end="", flush=True)
        if fn is None:
            print("skip (--no-smoke)")
            continue
        try:
            detail = fn()
        except Fail as e:
            print("FAIL")
            print(f"    {e.msg}")
            if e.hint:
                print(f"    hint: {e.hint}")
            return 1
        print(f"ok — {detail}" if detail else "ok")

    dur = time.time() - t0
    print(f"\nbuild.py: DONE in {dur:.1f}s — build/FFTARecomp is ready")
    print("  play:      tools/play.sh")
    print("  gate:      .venv/bin/python tools/check.py")
    print("  optional:  mGBA oracle build — see README § Setup")
    return 0


if __name__ == "__main__":
    sys.exit(main())
