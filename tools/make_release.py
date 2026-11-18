#!/usr/bin/env python3
"""make_release.py — assemble the distributable desktop zip (issue #3, R1).

The stage is built from an ALLOWLIST, never by copying a tree: every file
that enters the release is named here, so nothing can leak in by accident.
After staging, sweep_stage() rejects private material, and the zip writer
produces a deterministic, portable archive (fixed timestamps, sorted
entries, forward-slash names, permissions preserved).

Layout — everything resolves beside the executable at runtime
(GBARECOMP_DEFAULT_GAME_CONFIG="game.toml"; the pre-boot launch screen and
the asset picker use the same sidecar chain):

    FFTARecomp-<version>-linux-x64/
      FFTARecomp                    stripped copy of build/FFTARecomp
      assets/img/boxart.png         launch-screen box art
      mods/                         preloaded mod catalog (default-enabled)
      game.toml
      recomplauncher.json           RecompLauncher setup + settings profile
      bios/emibios_gba_bios.bin     committed clean-room BIOS (LGPL)
      bios/README.md
      README.md                     generated, self-contained (no dead links)
      LICENSE, LICENSES/, THIRD_PARTY_ATTRIBUTION.md

rom.cfg (the ROM pick's cache), config.ini/keybinds.ini (in-game menu
state) and saves/ are created beside the executable at runtime — extract
to a writable folder.

Sweep (sweep_stage, unit-tested in tests/python/test_tools.py):
  - forbidden extensions .gba/.agb/.sav/.srm/.apk
  - .bin allowed only at the emibios SHA-1 pin (a retail dump fails)
  - no staged file may hash to the ROM SHA-1 or the retail BIOS SHA-1
    under ANY name
  - no symlinks (a staged link could point outside the tree)
  - the required set present: binary (+ exec bit), config, pinned BIOS,
    box art, mod manifest, README, LICENSE, LICENSES/LGPL, THIRD_PARTY

Refuses a stale artifact (the build_apk.py gate, mirrored): no regen stamp
→ refuse; any regen input newer than generated/.regen_stamp → refuse (a
pull that rewrites unchanged files lands here too — one cycle.py run
clears it, and the gate never packages a maybe-stale tree); binary older
than the corpus → refuse.

Usage:
  .venv/bin/python tools/make_release.py [--version V] [--no-strip] [--clean]
  .venv/bin/python tools/make_release.py --binary build-compat/FFTARecomp
  .venv/bin/python tools/make_release.py --apk   # + the public Android APK

``--binary`` selects the Linux executable to stage (default
``build/FFTARecomp``). Release cuts pass ``build-compat/FFTARecomp`` so
the portable zip shares the AppImage's SteamOS-compatible glibc floor.

Output (release-stage/, gitignored):
  FFTARecomp-<version>-linux-x64.zip    deterministic portable zip
  FFTARecomp-<version>-android-arm64-v8a.apk     (--apk; ROM-less, debug-signed)

The last stdout line is "release: <name> sha1=<sha1> ..." for check.py.
"""
import argparse
import hashlib
import os
import shutil
import stat
import subprocess
import sys
import time
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BUILD = REPO / "build"
BINARY = BUILD / "FFTARecomp"
OUT_DIR = REPO / "release-stage"

ROM_SHA1 = "4ac05441f4de70a4ec3dd932116346c61b8783d9"
EMIBIOS_SHA1 = "0c0d404d16c6b55b3071aba714f82077da132f14"
RETAIL_BIOS_SHA1 = "300c20df6731a33952ded8c436f7f186d25d3492"

FORBIDDEN_EXTS = {".gba", ".agb", ".sav", ".srm", ".apk"}

REQUIRED_FILES = [
    "FFTARecomp",
    "game.toml",
    "recomplauncher.json",
    "bios/emibios_gba_bios.bin",
    "bios/README.md",
    "README.md",
    "LICENSE",
    "LICENSES/LGPL-3.0-or-later.txt",
    "LICENSES/ZLIB-raylib.txt",
    "LICENSES/ZLIB-tinyfiledialogs.txt",
    "LICENSES/ZLIB-raygui.txt",
    "THIRD_PARTY_ATTRIBUTION.md",
    "mods/packages/ffta.enhancement.widescreen/1.0.1/manifest.toml",
]
REQUIRED_DIRS = [
]


def exe_name(platform):
    """The staged executable's name: bare on POSIX, suffixed on Windows."""
    return "FFTARecomp.exe" if platform == "windows" else "FFTARecomp"


def licenses_required():
    """Every license document required in every staged artifact (module
    helper so the sweep AND the unit test read the same contract)."""
    return ["LICENSE", "LICENSES/LGPL-3.0-or-later.txt",
            "LICENSES/ZLIB-raylib.txt",
            "LICENSES/ZLIB-tinyfiledialogs.txt",
            "LICENSES/ZLIB-raygui.txt"]


def required_files(platform):
    """The staged required set, per target platform (same layout, the
    executable's name differs)."""
    return [exe_name(platform) if rel == "FFTARecomp" else rel
            for rel in REQUIRED_FILES]

# The zip README: self-contained (no links into repo folders that do not
# ship). The repo README § "Using a release binary" is the same story for
# users browsing the repository.
README_TEMPLATE = """# Final Fantasy Tactics Advance — Recomp (desktop release)

A static recompilation of *Final Fantasy Tactics Advance* (USA): the GBA
machine code was translated ahead-of-time into a native Linux binary. This
is not an emulator. **No game data is included** — you provide your own
legally obtained ROM.

## Requirements

Linux x86-64, plus system libraries (packages):

| Distro | Packages |
|---|---|
| Debian/Ubuntu | `libgl1 libglu1-mesa libx11-6` (any desktop install already has these) |
| Fedora | `mesa-libGL mesa-libGLU` |
| Arch | `mesa` (OpenGL; the X11 client libs are part of every desktop install) |

## Run

1. Extract the folder anywhere **writable** — your ROM pick, menu
   settings, and saves are kept beside the executable.
2. Run `./FFTARecomp` — the launch screen opens; the first boot opens the
   native file picker right away.
3. Pick your legally obtained *Final Fantasy Tactics Advance* (USA) ROM,
   then **Play**. The pick is remembered (`rom.cfg`), so later boots open
   ready to play; **Select ROM** re-picks, and passing `--rom <file>`
   skips the screen entirely.

The launch BIOS is bundled (`bios/emibios_gba_bios.bin` — a clean-room,
freely redistributable build, LGPL-3.0-or-later). You never need a Nintendo
BIOS dump.

The ROM is hash-verified at launch (SHA-1 `{rom_sha1}`). A mismatch error
means the file is not the expected USA dump — re-dump your own cartridge.

## Widescreen (validated)

`./FFTARecomp --view-width 448` (240–448 px) or `--resize-view` for a
window-aspect-driven view; `--scale N` sets the window size
(N×240 × N×160 px). The default stays faithful 240×160.

## Where files land (beside the executable)

- `rom.cfg` — the ROM pick's sidecar cache (created on first run)
- `config.ini`, `keybinds.ini` — in-game menu settings and key bindings
- `saves/ffta_us.sav` — the cartridge battery save

## Legal

Unofficial, non-commercial preservation project — PolyForm Noncommercial
1.0.0, see `LICENSE`. Not affiliated with or endorsed by Square Enix or
Nintendo. No ROM or Nintendo BIOS data ships in this archive; the bundled
BIOS is clean-room (`bios/README.md`). Third-party terms and credits:
`THIRD_PARTY_ATTRIBUTION.md`, `LICENSES/`.
"""


class Fail(Exception):
    def __init__(self, msg, hint=None):
        super().__init__(msg)
        self.msg = msg
        self.hint = hint


# --- windows cross-release (issue #3, R2) ------------------------------------

WIN_BUILD = REPO / "build-win"
TOOLCHAIN = REPO / "tools" / "mingw-x64.cmake"
CROSS_PREFIX = REPO / "cross-prefix"
WINE_FRAMES = 240

# System DLLs are the only legal imports of a static release exe. Anything
# mingw-runtime or third-party here = the "static" build silently fell back
# to dynamic (the exact regression D. static-release machinery exists to
# prevent — and it fails silently at configure/link, so this is the gate).
STATIC_FORBIDDEN_DLLS = frozenset({
"LIBSTDC++-6.DLL", "LIBGCC_S_SEH-1.DLL",
    "LIBWINPTHREAD-1.DLL", "FREETYPE-6.DLL", "HARFBUZZ-0.DLL",
    "ZLIB1.DLL",
})


def parse_import_dlls(objdump_text):
    """Pure core of the static-link guard (unit-tested): DLL names the PE
    imports, upper-cased."""
    import re
    return {m.group(1).upper() for m in re.finditer(
        r"DLL Name:\s*(\S+)", objdump_text)}


def static_link_violations(dlls):
    """Third-party DLL imports in a static release exe (empty = clean)."""
    return sorted(set(dlls) & STATIC_FORBIDDEN_DLLS)


def win_configure_needed():
    """Why build-win/ must be (re)configured: None = usable as is."""
    cache = WIN_BUILD / "CMakeCache.txt"
    if not cache.exists():
        return "no build-win/ (fresh tree)"
    text = cache.read_text(errors="ignore")
    for needle in ("mingw-x64.cmake", "GBARECOMP_STATIC_RELEASE:BOOL=ON",
                   "CMAKE_BUILD_TYPE:STRING=Release",
                   "--no-insert-timestamp -s"):
        if needle not in text:
            return f"cache lacks {needle} (flags changed)"
    return None


def win_build_exe(jobs, strip):
    """Configure (if needed) + build the static release exe."""
    marker = CROSS_PREFIX / ".done"
    missing = [d for d in ("raylib",) if not any(marker.glob(f"{d}-*"))]
    if missing:
        die("cross prefix incomplete: " + ", ".join(missing),
            hint="run .venv/bin/python tools/win_cross_deps.py build "
                 "(tools/win_cross_deps.py status shows the gaps)")
    reason = win_configure_needed()
    env = dict(**os.environ)
    env["PKG_CONFIG_PATH"] = str(CROSS_PREFIX / "lib" / "pkgconfig")
    if reason:
        print(f"windows: (re)configuring build-win/ ({reason})")
        if WIN_BUILD.exists():
            shutil.rmtree(WIN_BUILD)
        # -static-libgcc/-static-libstdc++: engine rule (the framework
        # CMakeLists — add_link_options in the subdir cannot reach the
        # parent exe target, so it comes via CMAKE_EXE_LINKER_FLAGS).
        # -s: strip at LINK time, not post-link (binutils strip rewrites
        # the PE TimeDateStamp on every run — R2 determinism lesson);
        # --no-strip drops it. --no-insert-timestamp epochs the link
        # stamp so the -s'd output stays deterministic to the zip.
        linker = ("-static -static-libgcc -static-libstdc++ "
                  "-Wl,--no-insert-timestamp"
                  + (" -s" if strip else ""))
        r = subprocess.run(
            ["cmake", "-S", str(REPO), "-B", str(WIN_BUILD), "-G", "Ninja",
             f"-DCMAKE_TOOLCHAIN_FILE={TOOLCHAIN}",
             "-DCMAKE_BUILD_TYPE=Release",
             f"-DCMAKE_TOOLCHAIN_FILE={TOOLCHAIN}",
             "-DCMAKE_BUILD_TYPE=Release",
             f"-DCMAKE_EXE_LINKER_FLAGS={linker}",
             "-DGBARECOMP_STATIC_RELEASE=ON",
             "-DFFTA_BUILD_TESTS=OFF"], env=env)
        if r.returncode != 0:
            die("windows cmake configure failed",
                hint="tools/win_cross_deps.py status — is the prefix "
                     "complete? See BRINGUP § R2 for the cross-build notes")
    r = subprocess.run(["cmake", "--build", str(WIN_BUILD), "--target",
                        "FFTARecomp", "--parallel", str(jobs)], env=env)
    if r.returncode != 0:
        die("windows build failed (see output above)",
            hint="build-win/ is preserved for inspection")
    exe = WIN_BUILD / "FFTARecomp.exe"
    if not exe.is_file():
        die("windows build produced no build-win/FFTARecomp.exe")
    return exe


def check_static_link(exe):
    """objdump the PE import table: third-party DLLs forbidden."""
    r = subprocess.run(["x86_64-w64-mingw32-objdump", "-p", str(exe)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        die("objdump failed on " + str(exe),
            hint="mingw-w64-binutils provides x86_64-w64-mingw32-objdump")
    bad = static_link_violations(parse_import_dlls(r.stdout))
    if bad:
        die("static release exe imports third-party DLLs: "
            + ", ".join(bad),
            hint="GBARECOMP_STATIC_RELEASE=ON fell back to dynamic "
                 "linking — see the prune_dynamic() rule in "
                 "tools/win_cross_deps.py")
    return len(parse_import_dlls(r.stdout))


def wine_smoke(zip_path, folder):
    """Boot the packaged exe from a bare extraction under wine: config
    files beside the binary, --no-window headless, strict FULLY_STATIC
    assertion (mirrors the desktop_accept acceptance shape).

    The run passes the ROM explicitly (--rom/--bios): under wine there is
    no native file dialog provider (no zenity/GetOpenFileName provider is
    guaranteed), so a bare-extraction run would hard-fail at the picker's
    fail-fast probe, not block — that is the designed behavior, not a
    regression. Seeding rom.cfg into the extraction would also work; the
    explicit flags are the simpler seed.
    """
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="win-smoke-"))
    try:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmp)
        root = tmp / folder
        env = {k: v for k, v in os.environ.items()
               if not k.startswith("GBARECOMP_")}
        env["GBARECOMP_STRICT_STATIC"] = "1"
        env["WINEDEBUG"] = "-all"
        env["WINEARCH"] = "win64"
        env["WINEPREFIX"] = str(tmp / "winehome")
        env["WINEDLLOVERRIDES"] = "mscoree,mshtml="
        r = subprocess.run(
            ["wine", str(root / "FFTARecomp.exe"),
             "--bios", "bios/emibios_gba_bios.bin",
             "--rom", str(REPO / "game.gba"),
             "--frames", str(WINE_FRAMES), "--no-window"],
            cwd=str(root), env=env, capture_output=True, text=True,
            timeout=600)
        out = r.stdout + r.stderr
        line = next((l.strip() for l in out.splitlines()
                     if "self_heal_coverage" in l), "")
        detail = line or (out.strip().splitlines() or ["<no output>"])[-1]
        if r.returncode != 0 or "FULLY_STATIC" not in line:
            die("wine smoke did not reach FULLY_STATIC: " + detail,
                hint="the static exe booted but a miss fired under wine "
                     "(Windows divergences are real bugs — heal loop them)")
        return line
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def die(msg, hint=None):
    raise Fail(msg, hint)


def sha1_file(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def git_version():
    r = subprocess.run(["git", "describe", "--tags", "--always", "--dirty"],
                       cwd=str(REPO), capture_output=True, text=True)
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip()
    return "untagged"


def newest_mtime(paths):
    """Newest mtime under the given roots (files only, symlink-safe)."""
    newest = 0.0
    for root in paths:
        root = Path(root)
        if root.is_file():
            newest = max(newest, root.stat().st_mtime)
            continue
        for dirpath, _dirnames, filenames in os.walk(root):
            for name in filenames:
                p = Path(dirpath) / name
                if p.is_symlink():
                    continue
                try:
                    newest = max(newest, p.stat().st_mtime)
                except OSError:
                    pass
    return newest


def _check_corpus_fresh():
    """Corpus freshness (rules 1-2 of the stamp gate): the stamp exists and
    no regen input is newer. Platform-independent."""
    stamp = REPO / "generated/.regen_stamp"
    if not stamp.is_file():
        die("generated/ corpus has no regen stamp",
            hint="run tools/cycle.py (cold regen + build) before packaging")
    symbols = sorted((REPO / "symbols").glob("*.tsv"))
    src = [p for p in (REPO / "src").rglob("*") if p.is_file()]
    inputs = ([REPO / "game.toml", REPO / "CMakeLists.txt", REPO / "generated",
               REPO / "gbarecompx/build/gba_recompile"]
              + symbols + src)
    missing = [str(p) for p in inputs if not p.exists()]
    if missing:
        die("regen inputs missing: " + ", ".join(missing),
            hint="run tools/cycle.py (cold regen) first")
    stamp_mtime = stamp.stat().st_mtime
    for source in inputs:
        if newest_mtime([source]) > stamp_mtime:
            die(f"regen input {source} is newer than the last regen stamp",
                hint="re-run tools/cycle.py (regen + build), then package — "
                     "the gate never ships a maybe-stale tree (a pull that "
                     "rewrites files lands here too; one cycle clears it)")


def check_freshness(binary=None):
    """Refuse to package a stale artifact (mirrors build_apk.py's gate).

    Three rules:
      1. generated/.regen_stamp exists — no stamp = never regen'd here;
      2. no regen input (game.toml, symbols/, src/, CMakeLists.txt,
         generated/) is newer than the stamp — an input newer than the
         last regen means the corpus predates it. Git checkouts smudge
         mtimes on unchanged files (branch switches/pulls) and that
         lands here too — deliberately: a cycle.py run clears it, and
         the gate never packages a maybe-stale tree;
      3. the binary is newer than the newest corpus file — the
         recompiler preserves mtimes for byte-identical output, so a
         no-op regen moves nothing and this stays true; a real corpus
         change is only linked by a rebuild, which moves the binary.
    """
    binary = Path(binary) if binary else BINARY
    if not binary.is_file():
        die(f"missing {binary}",
            hint="build first: python3 build.py (or AGENTS.md § Commands)")
    _check_corpus_fresh()
    corpus_newest = newest_mtime([REPO / "generated"])
    if binary.stat().st_mtime < corpus_newest:
        die(f"{binary} is older than the generated/ corpus",
            hint="re-run tools/cycle.py (rebuild), then package")


def check_freshness_windows():
    """The cross build compiles the (host-independent) corpus fresh, but a
    stale corpus is still a stale corpus: rules 1-2 only (no binary rule —
    build-win/ may not exist yet)."""
    _check_corpus_fresh()


def sweep_stage(stage, platform="linux"):
    """Return the list of private-material / completeness violations.

    Empty list = clean. Pure function of the staged tree: unit-tested
    directly (tests/python/test_tools.py) with synthetic stages.
    The platform selects the staged executable's name (FFTARecomp vs
    FFTARecomp.exe); all hash and extension rules are identical.
    """
    stage = Path(stage)
    exe = exe_name(platform)
    violations = []

    # 1. Required set present (and the binary carries its exec bit — on a
    # POSIX stage; on the Windows platform the bit is meaningless to the
    # player but still enforced here as a staging invariant).
    for rel in required_files(platform):
        p = stage / rel
        if not p.is_file():
            violations.append(f"missing required file: {rel}")
    for rel in REQUIRED_DIRS:
        p = stage / rel
        if not (p.is_dir() and any(p.iterdir())):
            violations.append(f"missing required (non-empty) dir: {rel}")
    bin_mode = (stage / exe).stat().st_mode \
        if (stage / exe).is_file() else 0
    if bin_mode and not (bin_mode & stat.S_IXUSR):
        violations.append(f"{exe} lost its exec bit")

    # 2. Forbidden material — walk everything staged.
    for dirpath, dirnames, filenames in os.walk(stage):
        for name in dirnames + filenames:
            p = Path(dirpath) / name
            if p.is_symlink():
                violations.append(f"symlink in stage: {p.relative_to(stage)}")
        for name in filenames:
            p = Path(dirpath) / name
            rel = p.relative_to(stage).as_posix()
            ext = p.suffix.lower()
            if ext in FORBIDDEN_EXTS:
                violations.append(f"forbidden extension: {rel}")
                continue
            try:
                digest = sha1_file(p)
            except OSError as exc:
                violations.append(f"unreadable file: {rel} ({exc})")
                continue
            if digest == ROM_SHA1:
                violations.append(f"ROM material under disguised name: {rel}")
            if digest == RETAIL_BIOS_SHA1:
                violations.append(f"retail BIOS dump material: {rel}")
            if ext == ".bin" and digest != EMIBIOS_SHA1:
                violations.append(
                    f".bin that is not the pinned clean-room BIOS: {rel}")
    return violations


README_NOTE = """
*(This README is generated by tools/make_release.py at packaging time; the
canonical project README lives in the source repository.)*
"""


def readme_for(platform):
    if platform == "windows":
        def rep(body, old, new):
            if old not in body:
                die(f"windows README template pattern missed: {old[:60]}...",
                    hint="README_TEMPLATE changed — update the windows "
                         "rewrites to match")
            return body.replace(old, new)
        body = README_TEMPLATE
        body = rep(body,
            "machine code was translated ahead-of-time into a native Linux "
            "binary. This\nis not an emulator.",
            "machine code was translated ahead-of-time into a native "
            "Windows binary. This\nis not an emulator.")
        body = rep(body,
            "Linux x86-64, plus system libraries (packages):",
            "Windows 10+ x86-64. Everything is statically linked — no "
            "runtime DLLs to install (the bundled BIOS sits in `bios/`).")
        body = rep(body,
            """| Distro | Packages |
|---|---|
| Debian/Ubuntu | `libgl1 libglu1-mesa libx11-6` (any desktop install already has these) |
| Fedora | `mesa-libGL mesa-libGLU` |
| Arch | `mesa` (OpenGL; the X11 client libs are part of every desktop install) |
""",
            "")
        body = rep(body, "./FFTARecomp", "FFTARecomp.exe")
        return body.format(rom_sha1=ROM_SHA1) + README_NOTE
    return README_TEMPLATE.format(rom_sha1=ROM_SHA1) + README_NOTE


def stage_windows(version, strip=True, jobs=8):
    """Cross-configure (if needed) + build the static release exe, guard it,
    strip it in-stage, and stage the Windows layout (issue #3, R2).

    The launch screen boots from game.toml beside the exe; the ROM pick is
    the player's own dump (issue #3 "bring your own ROM"). No ROM is
    embedded —
    the sweep below proves it. build-win/ is preserved for inspection.
    """
    exe = win_build_exe(jobs, strip)
    n_imports = check_static_link(exe)

    folder = f"FFTARecomp-{version}-windows-x64"
    stage = OUT_DIR / folder
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)

    def cp_file(src, rel):
        dst = stage / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    # The exe ships straight from build-win/ (link-time stripped by
    # default); nothing post-processes it, so the staged bytes are exactly
    # the linked bytes.
    cp_file(exe, "FFTARecomp.exe")
    os.chmod(stage / "FFTARecomp.exe", 0o755)

    # Runtime layout beside the exe (mods land in build-win/ via
    # PostBuild staging).
    for sub in ("mods",):
        src = WIN_BUILD / sub
        if not src.is_dir():
            die(f"windows build produced no {sub}/ beside the exe",
                hint="build-win/ is preserved for inspection")
        shutil.copytree(src, stage / sub)

    cp_file(REPO / "game.toml", "game.toml")
    cp_file(REPO / "recomplauncher.json", "recomplauncher.json")
    cp_file(REPO / "bios/emibios_gba_bios.bin", "bios/emibios_gba_bios.bin")
    cp_file(REPO / "bios/README.md", "bios/README.md")
    cp_file(REPO / "LICENSE", "LICENSE")
    shutil.copytree(REPO / "LICENSES", stage / "LICENSES")
    cp_file(REPO / "THIRD_PARTY_ATTRIBUTION.md", "THIRD_PARTY_ATTRIBUTION.md")
    (stage / "README.md").write_text(readme_for("windows"),
                                     encoding="utf-8")

    # Launch-screen box art — the raygui launcher loads assets/img/boxart.png
    # beside the exe via GetApplicationDirectory() (the dev build stages the
    # same file from the same source via CMake's stage_boxart target).
    cp_file(REPO / "recomp/launcher/boxart.png", "assets/img/boxart.png")

    violations = sweep_stage(stage, platform="windows")
    if violations:
        shutil.rmtree(stage)
        die("windows release stage rejected:\n  " + "\n  ".join(violations),
            hint="nothing private may enter a public artifact "
                 "(AGENTS.md § Public-repo hygiene)")
    zip_path = OUT_DIR / f"{folder}.zip"
    if zip_path.exists():
        zip_path.unlink()
    count = write_portable_zip(stage, folder, zip_path)
    problems = verify_zip(zip_path, count)
    if problems:
        die("zip verification failed:\n  " + "\n  ".join(problems))

    smoke = wine_smoke(zip_path, folder)
    digest = sha1_file(zip_path)
    print(f"release: {zip_path.name} sha1={digest} "
          f"size={zip_path.stat().st_size} "
          f"(static imports={n_imports}, smoke: {smoke.split(',')[0]})")
    return zip_path


def stage_apk(version):
    """Build, guard, and stage the public (ROM-less) Android APK artifact.

    Gradle without -PprivateRom embeds no ROM: the app boots into the SAF
    setup flow (issue #3 "bring your own ROM"). Reuses build_apk.py's
    preflight (JDK/SDK/NDK discovery + the raylib Android scaffold + dump
    verification — the release runner carries the ROM for the bootstrap
    anyway), but its
    own gradle call: build_apk.step_gradle bakes in -PprivateRom.

    The artifact passes tools/android_apk_check.py --expect public (the
    same 8-check gate the private build answers, ROM-presence inverted:
    bundled BIOS hash-verified, embedded ROM forbidden) BEFORE staging, and
    is copied under the distributable name (public builds keep AGP's
    app-debug.apk — only private builds get the engine's
    *-PRIVATE-rom-included.apk rename, so they can't be mistaken for
    releases; this name can't be mistaken either way).

    assembleDebug is debug-signed. Shipping the DEBUG key is the open R5
    decision (a release key via -PgbaKeystore lets sideloaded updates
    install over earlier installs); until then the artifact stays
    debug-signed and that stays flagged.
    """
    sys.path.insert(0, str(REPO))  # build_apk.py lives at the repo root
    import build_apk  # noqa: E402 (local import: zip-only runs need no SDK)
    print("preflight: " + build_apk.step_preflight())
    abi = "arm64-v8a"
    jobs = max(1, min(16, os.cpu_count() or 8))
    # The APK manifest versionName follows the release version (engine
    # gradle: -PgbaVersionName), so the installed app shows the release it
    # came from. Strip the tag's "v" (manifest convention: 1.5, not v1.5).
    version_name = version.lstrip("v")
    # A release artifact is ALWAYS a clean package: gradle's incremental
    # repackaging strands slack from prior builds between zip entries (the
    # junk class android_apk_check's packaging-sanity check exists for —
    # 29 MB of it on the first attempt here). Native objects live under
    # android/app/.cxx, which is NOT touched: the native compile stays
    # cached, only the packaging restarts from scratch.
    app_build = REPO / "android/app/build"
    if app_build.is_dir():
        shutil.rmtree(app_build)
    gradlew = REPO / "android" / "gradlew"
    r = subprocess.run([str(gradlew), ":app:assembleDebug",
                        f"-PgbaAbis={abi}", f"-PgbaNativeJobs={jobs}",
                        f"-PgbaVersionName={version_name}"],
                       cwd=str(REPO / "android"))
    if r.returncode != 0:
        die("gradle assembleDebug (public) failed",
            hint="android/README.md § Build — JDK 21, SDK platform 35, NDK, "
                 "and the gbarecompx scaffold are the usual suspects")
    # AGP's debug output path; the engine's *-PRIVATE-rom-included rename
    # only applies to private builds, and build_apk.newest_apk() globs that
    # PRIVATE marker only — a public build is always right here.
    apk = REPO / "android/app/build/outputs/apk/debug/app-debug.apk"
    if not (apk.is_file() and apk.stat().st_size > 0):
        die(f"gradle reported success but no APK at {apk.relative_to(REPO)}")
    guard = subprocess.run(
        [sys.executable, str(REPO / "tools/android_apk_check.py"),
         "--apk", str(apk), "--expect", "public"],
        capture_output=True, text=True)
    if guard.returncode != 0:
        tail = "\n".join((guard.stdout + guard.stderr).strip().splitlines()[-12:])
        die(f"APK guard rejected the artifact ({apk.name}):\n{tail}",
            hint="a public release artifact may not contain ROM material — "
                 "see tools/android_apk_check.py")
    name = f"FFTARecomp-{version}-android-{abi}.apk"
    dst = OUT_DIR / name
    shutil.copy2(apk, dst)
    print(f"release: {name} sha1={sha1_file(dst)} "
          f"size={dst.stat().st_size} (guard: --expect public)")


def stage_release(version, strip=True, binary=None, out_dir=None, folder=None,
                  mods_dir=None):
    """Build the allowlisted stage. Returns (stage_dir, folder_name).

    ``binary``/``out_dir``/``folder``/``mods_dir`` let the AppImage builder
    reuse the same allowlist + README staging for a compat-built executable
    in its own output directory.
    """
    binary = Path(binary) if binary else BINARY
    out_dir = Path(out_dir) if out_dir else OUT_DIR
    folder = folder or f"FFTARecomp-{version}-linux-x64"
    mods_dir = Path(mods_dir) if mods_dir else BUILD / "mods"
    stage = out_dir / folder
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)

    def cp_file(src, rel):
        dst = stage / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    # Binary (stripped in-stage; the source binary keeps its symbols for
    # dev-side addr2line crash triage).
    cp_file(binary, "FFTARecomp")
    if strip:
        r = subprocess.run(["strip", str(stage / "FFTARecomp")],
                           capture_output=True, text=True)
        if r.returncode != 0:
            die("strip failed: " + r.stderr.strip(), hint="--no-strip skips it")
    os.chmod(stage / "FFTARecomp", 0o755)

    if not mods_dir.is_dir():
        die(f"missing mods directory: {mods_dir}",
            hint="build with -DGBARECOMP_ENABLE_MODS=ON (build.py does)")
    shutil.copytree(mods_dir, stage / "mods")

    # Launch-screen box art — the raygui launcher loads assets/img/boxart.png
    # beside the exe via GetApplicationDirectory() (the dev build stages the
    # same file from the same source via CMake's stage_boxart target).
    cp_file(REPO / "recomp/launcher/boxart.png", "assets/img/boxart.png")

    cp_file(REPO / "game.toml", "game.toml")
    cp_file(REPO / "recomplauncher.json", "recomplauncher.json")
    cp_file(REPO / "bios/emibios_gba_bios.bin", "bios/emibios_gba_bios.bin")
    cp_file(REPO / "bios/README.md", "bios/README.md")
    cp_file(REPO / "LICENSE", "LICENSE")
    shutil.copytree(REPO / "LICENSES", stage / "LICENSES")
    cp_file(REPO / "THIRD_PARTY_ATTRIBUTION.md", "THIRD_PARTY_ATTRIBUTION.md")

    readme =(README_TEMPLATE.format(rom_sha1=ROM_SHA1) + README_NOTE)
    (stage / "README.md").write_text(readme, encoding="utf-8")
    return stage, folder


def write_portable_zip(stage, folder, zip_path):
    """Deterministic zip: fixed timestamps, sorted entries, '/' names.

    Two packaging runs over the same tree produce byte-identical archives
    (unit-tested), so CI can hash and users can diff releases.
    """
    files = sorted((p for p in stage.rglob("*") if p.is_file() and
                    not p.is_symlink()),
                   key=lambda p: p.relative_to(stage).as_posix())
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED,
                         compresslevel=9) as zf:
        for p in files:
            rel = p.relative_to(stage).as_posix()
            zi = zipfile.ZipInfo(f"{folder}/{rel}",
                                date_time=(1980, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.create_system = 3  # unix, so external_attr carries the mode
            mode = 0o755 if rel in ("FFTARecomp", "FFTARecomp.exe") else 0o644
            zi.external_attr = (0o100000 | mode) << 16
            zf.writestr(zi, p.read_bytes())
    return len(files)


def verify_zip(zip_path, expected_count):
    """Read back: portable names, count match, exec bit survived."""
    problems = []
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        if len(names) != expected_count:
            problems.append(f"entry count {len(names)} != {expected_count}")
        for info in zf.infolist():
            name = info.filename
            if "\\" in name or name.startswith("/") or ".." in name.split("/"):
                problems.append(f"non-portable entry name: {name}")
            if name.rsplit("/", 1)[-1] in ("FFTARecomp", "FFTARecomp.exe"):
                mode = (info.external_attr >> 16) & 0o777
                if mode & stat.S_IXUSR != stat.S_IXUSR:
                    problems.append(
                        f"{name.rsplit('/', 1)[-1]} lost exec bit in zip: "
                        f"{mode:o}")
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Assemble the distributable desktop release zip.")
    ap.add_argument("--version", default=None,
                    help="override the version (default: git describe)")
    ap.add_argument("--no-strip", action="store_true",
                    help="ship the binary with symbols")
    ap.add_argument("--binary", default=None,
                    help="Linux executable to stage (default: "
                         "build/FFTARecomp; release cuts pass "
                         "build-compat/FFTARecomp)")
    ap.add_argument("--clean", action="store_true",
                    help="remove the stage dir after zipping")
    ap.add_argument("--apk", action="store_true",
                    help="also build + guard + stage the public Android "
                         "APK (ROM-less; needs the Android SDK/NDK/JDK — "
                         "android/README.md § Build)")
    ap.add_argument("--windows", action="store_true",
                    help="cross-compile + guard + stage the static Windows "
                         "exe (issue #3, R2 — MinGW cross on a Linux box; "
                         "the corpus regen consumes the repo's game.gba, "
                         "but no ROM bytes enter the artifact — the sweep "
                         "proves it; needs mingw-w64-toolchain + "
                         "tools/win_cross_deps.py prefix)")
    a = ap.parse_args(argv)

    t0 = time.time()
    if a.windows:
        check_freshness_windows()
        version = a.version or git_version()
        OUT_DIR.mkdir(exist_ok=True)
        stage_windows(version, strip=not a.no_strip, jobs=8)
        return 0
    check_freshness(a.binary)
    version = a.version or git_version()
    OUT_DIR.mkdir(exist_ok=True)

    stage, folder = stage_release(version, strip=not a.no_strip,
                                  binary=a.binary)
    violations = sweep_stage(stage)
    if violations:
        shutil.rmtree(stage)
        die("release stage rejected:\n  " + "\n  ".join(violations),
            hint="nothing private may enter a public artifact "
                 "(AGENTS.md § Public-repo hygiene)")

    zip_path = OUT_DIR / f"{folder}.zip"
    if zip_path.exists():
        zip_path.unlink()
    count = write_portable_zip(stage, folder, zip_path)
    problems = verify_zip(zip_path, count)
    if problems:
        die("zip verification failed:\n  " + "\n  ".join(problems))

    if a.clean:
        shutil.rmtree(stage)
    digest = sha1_file(zip_path)
    print(f"staged {count} files, zip {zip_path}")
    print(f"release: {zip_path.name} sha1={digest} "
          f"size={zip_path.stat().st_size} "
          f"({time.time() - t0:.1f}s)")
    if a.apk:
        stage_apk(version)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Fail as exc:
        print(f"make_release: {exc.msg}", file=sys.stderr)
        if exc.hint:
            print(f"hint: {exc.hint}", file=sys.stderr)
        sys.exit(1)