#!/usr/bin/env python3
"""build_apk.py — Android bootstrap: from a working checkout to a device-ready APK.

Mirrors build.py's step pattern for the Android target. The public app shell
imports the ROM/BIOS through the phone's SAF picker at first run; until that
UI exists in this game's shell, the practical path is the **private test
build** (ROM+BIOS embedded, debug-signed), which this script drives:

  1. preflight     JDK 21 on PATH or JAVA_HOME (Gradle 8.11.1 rejects 27),
                   ANDROID SDK platform+build-tools+NDK, engine SDL submodule
                   checked out (the Gradle CMake needs it), `generated/`
                   corpus present and fresh (regenerate with build.py /
                   tools/cycle.py on desktop — an Android build cannot)
  2. gradle        ./gradlew :app:assembleDebug -PgbaAbis=<abi>
                   -PprivateRom/-PprivateBios (paths relative to android/)
  3. content guard tools/android_apk_check.py --expect private
                   (payload matches staging, embedded ROM/BIOS hash-verified
                   against the pins, packaging sanity)
  4. install+gate  optional (default on with a device attached): adb install
                   and the boot-health gate tools/validate_android.sh

Flags: --abi <abi> (default arm64-v8a), --jobs N (native compile parallelism),
       --install/--no-install (default: install when exactly one device is
       attached), --skip-check (skip the content guard), --no-gate (install
       without the device gate).

The private APK is debug-signed and named *-PRIVATE-rom-included.apk —
never commit or distribute it (.gitignore covers *.apk). Public builds
(drop the -Pprivate* flags) embed nothing; ROM/BIOS arrive via the phone UI.
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
ANDROID = REPO / "android"
ROM = REPO / "game.gba"
ROM_SHA1 = "4ac05441f4de70a4ec3dd932116346c61b8783d9"
BIOS = REPO / "gbarecomp/bios/gba_bios.bin"
BIOS_SHA1 = "300c20df6731a33952ded8c436f7f186d25d3492"
ROM_SIZE = 16777216
BIOS_SIZE = 16384
GRADLE_MIN_JDK = (21, 21)  # Gradle 8.11.1: JDK 21 works; JDK 27 is too new
SDL_SUBMODULE = REPO / "gbarecomp/platform/android/third_party/SDL/Android.mk"
APK_DIR = ANDROID / "app/build/outputs/apk/debug"
PRIVATE_MARKER = "-PRIVATE-rom-included.apk"


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


def run(cmd, cwd=REPO, capture=True, timeout=3600):
    try:
        return subprocess.run([str(c) for c in cmd], cwd=str(cwd),
                              capture_output=capture, text=True,
                              timeout=timeout)
    except FileNotFoundError:
        die(f"command not found: {cmd[0]}",
            hint="install the build dependencies (android/README.md § Build)")


def run_ok(cmd, cwd=REPO):
    return run(cmd, cwd=cwd).returncode == 0


def tail(proc, n=20):
    text = (proc.stdout or "") + (proc.stderr or "")
    return "\n".join(text.strip().splitlines()[-n:])


# --- preflight ---------------------------------------------------------------

def find_java():
    """JDK >= 17 & < 27: JAVA_HOME first, then the `java` on PATH, then common
    distro locations. Gradle 8.11.1 caps at 23 in practice (21 verified)."""
    candidates = []
    if os.environ.get("JAVA_HOME"):
        candidates.append(Path(os.environ["JAVA_HOME"]))
    which = shutil.which("java")
    if which:
        candidates.append(Path(which).resolve().parent.parent)
    candidates += [Path(p) for p in (
        "/usr/lib/jvm/java-21-openjdk",
        "/usr/lib/jvm/java-17-openjdk",
    )]
    for home in candidates:
        java = home / "bin/java"
        if not java.exists():
            continue
        r = run([java, "-version"])
        m = re.search(r'version "(\d+)', r.stderr or r.stdout)
        if not m:
            continue
        major = int(m.group(1))
        if major > 26:
            continue  # too new for Gradle 8.11.1
        return java, major
    return None, 0


def adb_devices_ready():
    r = run(["adb", "devices"], timeout=30)
    if r.returncode != 0:
        return -1
    lines = [l for l in r.stdout.splitlines()
             if l.strip() and not l.startswith("List of")]
    ready = [l for l in lines if l.split()[-1] == "device"]
    return len(ready)


def step_preflight():
    java, major = find_java()
    if java is None:
        die("no usable JDK found (need >= 17 and <= 26 for Gradle 8.11.1)",
            hint="install JDK 21 (android/README.md § Build prerequisites) "
                 "or set JAVA_HOME")
    details = [f"JDK {major} ({java})"]
    sdk = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    if not sdk:
        # auto-discover the sdk
        for p in (Path.home() / "Android/Sdk", Path("/opt/android-sdk")):
            if p.is_dir():
                sdk = str(p)
                break
    if not sdk or not Path(sdk).is_dir():
        die("ANDROID SDK not found",
            hint="set ANDROID_HOME (android/README.md § Build prerequisites)")
    ndk = Path(sdk) / "ndk"
    if not ndk.is_dir() or not any(ndk.iterdir()):
        die(f"no NDK under {ndk}",
            hint="install an NDK via sdkmanager (android/README.md)")
    details.append(f"SDK {sdk}")
    # engine SDL submodule (Gradle's CMake needs its sources)
    if not SDL_SUBMODULE.exists():
        r = run(["git", "-C", REPO / "gbarecomp", "submodule", "update",
                 "--init", "platform/android/third_party/SDL"])
        if r.returncode != 0 or not SDL_SUBMODULE.exists():
            die("gbarecomp SDL submodule not checked out",
                hint="git -C gbarecomp submodule update --init "
                     "platform/android/third_party/SDL")
    details.append("SDL submodule ok")
    # dumps (re-checked by Gradle too, but fail early and clear)
    for path, want, label in ((ROM, ROM_SHA1, "ROM"),
                               (BIOS, BIOS_SHA1, "BIOS")):
        if not path.exists():
            die(f"{label} missing: {path}", hint="run build.py first "
                "(README § Setup) — the private build embeds these dumps")
        if path.stat().st_size != (ROM_SIZE if label == "ROM" else BIOS_SIZE):
            die(f"{label} has the wrong size: {path}")
        if sha1_file(path) != want:
            die(f"{label} SHA-1 mismatch: {path}")
    details.append("dumps verified")
    # corpus freshness: an APK embeds the corpus via libmain.so's build;
    # generated/ must exist and not be older than game.toml
    generated = REPO / "generated/dispatch_table.cpp"
    if not generated.exists():
        die("no generated/ corpus", hint="run build.py (or tools/cycle.py) "
            "on desktop first — an Android build consumes it, cannot "
            "produce it")
    if generated.stat().st_mtime < (REPO / "game.toml").stat().st_mtime:
        die("generated/ corpus is stale", hint="re-run build.py "
            "(game.toml is newer than generated/)")
    details.append("corpus present")
    return ", ".join(details)


# --- build -------------------------------------------------------------------

def step_gradle(abi, jobs):
    gradle = ANDROID / "gradlew"
    cmd = [gradle, ":app:assembleDebug",
           f"-PgbaAbis={abi}", f"-PgbaNativeJobs={jobs}",
           f"-PprivateRom={ROM}", f"-PprivateBios={BIOS}"]
    r = run(cmd, cwd=ANDROID, capture=False)
    if r.returncode != 0:
        die("gradle assembleDebug failed (see output above)",
            hint="android/README.md § Build — JDK 21, SDK platform 35, "
                 "NDK, and the SDL submodule are the usual suspects")
    # An up-to-date Gradle build does not rewrite the APK; presence is enough.
    apk = newest_apk()
    if not apk:
        die("gradle reported success but no APK found under "
            f"{APK_DIR.relative_to(REPO)}")
    return apk


def newest_apk():
    if not APK_DIR.is_dir():
        return None
    apks = sorted(APK_DIR.rglob(f"*{PRIVATE_MARKER}"),
                  key=lambda p: p.stat().st_mtime, reverse=True)
    return apks[0] if apks else None


def step_check(apk):
    tool = REPO / "tools/android_apk_check.py"
    venv_py = REPO / ".venv/bin/python"
    py = venv_py if venv_py.exists() else sys.executable
    r = run([py, tool, "--apk", apk, "--expect", "private"], timeout=300)
    last = (r.stdout.strip().splitlines() or [""])[-1]
    if r.returncode != 0:
        die("APK content guard failed", hint=last or tail(r))
    return last


def step_install_gate(apk, gate):
    ready = adb_devices_ready()
    if ready != 1:
        die(f"{ready} adb device(s) ready (need exactly 1 for --install)",
            hint="connect exactly one phone (or --no-install), "
                 "and accept the USB debugging prompt")
    r = run(["adb", "install", "-r", str(apk)], timeout=600)
    if r.returncode != 0:
        die("adb install failed", hint=tail(r))
    detail = f"installed {apk.name}"
    if gate:
        r = run([str(REPO / "tools/validate_android.sh"),
                 "--no-install"], timeout=600)
        if r.returncode != 0:
            die("device gate failed", hint=tail(r))
        detail += " — GATE PASSED"
    else:
        detail += " (--no-gate)"
    return detail


# --- main --------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Android bootstrap: private test APK (ROM embedded) "
                    "→ content guard → install + device gate. Public "
                    "builds (ROM via phone UI) use gradlew directly.")
    ap.add_argument("--abi", default="arm64-v8a",
                    help="target ABI (default arm64-v8a; x86_64 for emulator)")
    ap.add_argument("--jobs", type=int,
                    default=min(12, os.cpu_count() or 4),
                    help="native compile parallelism (default min(12, cpus))")
    ap.add_argument("--no-install", action="store_true",
                    help="build + check only; skip install + gate")
    ap.add_argument("--no-gate", action="store_true",
                    help="install without running the device gate")
    ap.add_argument("--skip-check", action="store_true",
                    help="skip the APK content guard")
    a = ap.parse_args()

    print(f"build_apk.py — {REPO}")
    print("private test build: ROM+BIOS embedded, debug-signed. Never "
          "commit or distribute the *-PRIVATE-rom-included.apk.\n")
    t0 = time.time()
    # The plan runs sequentially; later steps receive the previous step's
    # result (the gradle step's APK path flows into the guard and install).
    plan = []

    def run_step(i, total, title, fn, *args):
        print(f"[{i}/{total}] {title} ... ", end="", flush=True)
        try:
            detail = fn(*args)
        except Fail as e:
            print("FAIL")
            print(f"    {e.msg}")
            if e.hint:
                print(f"    hint: {e.hint}")
            return None
        print(f"ok — {detail}")
        return detail

    total = 3 if a.no_install else 4
    if a.skip_check:
        total -= 1
    i = 0

    i += 1
    run_step(i, total, "preflight", step_preflight)

    i += 1
    apk = run_step(i, total, "gradle assembleDebug (private)",
                   step_gradle, a.abi, a.jobs)
    if apk is None:
        return 1
    mi = apk.stat().st_size / (1 << 20)
    print(f"      -> {apk.name} ({mi:.1f} MiB)")

    if not a.skip_check:
        i += 1
        if run_step(i, total, "APK content guard",
                    step_check, apk) is None:
            return 1

    if not a.no_install:
        i += 1
        if run_step(i, total, "install + device gate",
                    step_install_gate, apk, not a.no_gate) is None:
            return 1

    dur = time.time() - t0
    print(f"\nbuild_apk.py: DONE in {dur:.1f}s — {apk.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())