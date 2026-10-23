#!/usr/bin/env python3
"""make_appimage.py — build the Steam-Deck-friendly AppImage.

The AppImage wraps the same allowlisted Linux payload as the portable zip
(tools/make_release.py) in the standard AppImage runtimes. Two details are
specific to this game:

* **Writable sidecars.** The runtime stores ``rom.cfg``, ``config.ini``,
  ``keybinds.ini`` and ``saves/`` beside the executable. An AppImage mount
  is read-only, so ``AppRun`` unpacks the payload once to
  ``$XDG_DATA_HOME/ffta-recomp/app`` (default ``~/.local/share/...``) and
  runs it there. Updates copy the new payload over that directory without
  deleting the player's files.

* **Steam Deck defaults.** When ``SteamDeck=1`` is set (Game Mode / Deck
  Desktop), ``AppRun`` adds ``--fullscreen=1 --resize-view`` unless the
  player already passed a display flag. ``FFTA_APPIMAGE_NO_DECK_DEFAULTS=1``
  disables that.

The compatibility floor is the binary's, not this script's: release cuts
pass ``--binary build-compat/FFTARecomp`` (glibc 2.36, Debian 12 container).
The AppImage is smoke-tested after packaging with a strict 2400-frame run.

Usage:
  .venv/bin/python tools/compat_build.py
  .venv/bin/python tools/make_appimage.py --version v1.7 \
      --binary build-compat/FFTARecomp

Output:
  release-stage/FFTARecomp-<version>-linux-x86_64.AppImage
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import make_release as mr  # noqa: E402

OUT_DIR = REPO / "release-stage"
ICON = REPO / "recomp" / "launcher" / "appimage-icon.png"
ROM = REPO / "game.gba"
BIOS = REPO / "bios" / "emibios_gba_bios.bin"

# appimagetool 1.9.1 (AppImage/appimagetool). The asset is identified by
# SHA-256 because it is a downloaded executable that runs in the release
# job; a changed/moved asset must fail loudly, not silently execute.
APPIMAGETOOL_URL = (
    "https://github.com/AppImage/appimagetool/releases/download/1.9.1/"
    "appimagetool-x86_64.AppImage")
APPIMAGETOOL_SHA256 = (
    "ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0")
APPIMAGE_RUNTIME_URL = (
    "https://github.com/AppImage/type2-runtime/releases/download/continuous/"
    "runtime-x86_64")
APPIMAGE_RUNTIME_SHA256 = (
    "617aa77314d57c8b8e4fae9c3f0b35af7b30d5529cb69e98f64f92510ed98a46")

APPIMAGE_README = """
## AppImage

This is the portable AppImage build. On first run it unpacks the game
beside your user data at:

    ${XDG_DATA_HOME:-~/.local/share}/ffta-recomp/app

and runs it from there — the game stores `rom.cfg`, menu settings and
`saves/` beside the executable, and the AppImage mount is read-only.
Updating to a newer AppImage refreshes the game files in that directory but
keeps your ROM pick, settings and saves.

### Steam Deck

In Desktop Mode, add the AppImage as a non-Steam game (or launch it from
the file manager). In Game Mode it defaults to borderless fullscreen with
the resize-driven widescreen view; pass `--window`, `--scale`, or
`--view-width` to override, or set `FFTA_APPIMAGE_NO_DECK_DEFAULTS=1`.

The launch screen's **Select ROM** uses the system file dialog (zenity or
kdialog on SteamOS). If no dialog provider is available, add this as a
Steam launch option once:

    --rom /path/to/Final_Fantasy_Tactics_Advance_USA.gba

The pick is remembered in `rom.cfg`. The clean-room launch BIOS is bundled;
no Nintendo BIOS dump is needed.

If the system does not provide FUSE, run the AppImage with
`APPIMAGE_EXTRACT_AND_RUN=1` or `--appimage-extract-and-run`.
"""


class Fail(Exception):
    pass


def die(msg, hint=None):
    raise Fail(msg + (f"\nhint: {hint}" if hint else ""))


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def cache_root():
    base = os.environ.get("XDG_CACHE_HOME")
    return (Path(base) if base else Path.home() / ".cache") / "ffta-recomp"


def ensure_appimagetool(override=None):
    if override:
        tool = Path(override).resolve()
        if not tool.is_file():
            die(f"appimagetool not found: {tool}")
        return tool
    tool = cache_root() / "appimagetool-x86_64.AppImage"
    if tool.is_file() and sha256_file(tool) == APPIMAGETOOL_SHA256:
        return tool
    tool.parent.mkdir(parents=True, exist_ok=True)
    tmp = tool.with_suffix(".download")
    print(f"appimage: fetching appimagetool 1.9.1 -> {tool}", flush=True)
    req = urllib.request.Request(
        APPIMAGETOOL_URL, headers={"User-Agent": "ffta-recomp-appimage/1"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r, open(tmp, "wb") as f:
            shutil.copyfileobj(r, f)
    except Exception as exc:  # network/HTTP errors are all fatal here
        tmp.unlink(missing_ok=True)
        die(f"could not download appimagetool: {exc}",
            hint="install it manually and pass --appimagetool PATH")
    got = sha256_file(tmp)
    if got != APPIMAGETOOL_SHA256:
        tmp.unlink(missing_ok=True)
        die(f"appimagetool sha256 mismatch: got {got}, "
            f"want {APPIMAGETOOL_SHA256}")
    tmp.chmod(0o755)
    tmp.replace(tool)
    return tool


def ensure_runtime(override=None):
    """Pinned AppImage type-2 runtime.

    appimagetool 1.9.1 downloads a *moving* `continuous` runtime when
    --runtime-file is omitted. Pin it so a release cannot silently change
    its launcher/runtime bytes.
    """
    if override:
        runtime = Path(override).resolve()
        if not runtime.is_file():
            die(f"AppImage runtime not found: {runtime}")
        return runtime
    runtime = cache_root() / "runtime-x86_64"
    if runtime.is_file() and sha256_file(runtime) == APPIMAGE_RUNTIME_SHA256:
        return runtime
    runtime.parent.mkdir(parents=True, exist_ok=True)
    tmp = runtime.with_suffix(".download")
    print(f"appimage: fetching type-2 runtime -> {runtime}", flush=True)
    req = urllib.request.Request(
        APPIMAGE_RUNTIME_URL, headers={"User-Agent": "ffta-recomp-appimage/1"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r, open(tmp, "wb") as f:
            shutil.copyfileobj(r, f)
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        die(f"could not download the AppImage runtime: {exc}",
            hint="install it manually and pass --runtime-file PATH")
    got = sha256_file(tmp)
    if got != APPIMAGE_RUNTIME_SHA256:
        tmp.unlink(missing_ok=True)
        die(f"AppImage runtime sha256 mismatch: got {got}, "
            f"want {APPIMAGE_RUNTIME_SHA256}")
    tmp.chmod(0o644)
    tmp.replace(runtime)
    return runtime


def payload_id(payload):
    """Stable short id for this exact payload (names + bytes)."""
    h = hashlib.sha1()
    for p in sorted((q for q in Path(payload).rglob("*") if q.is_file()),
                    key=lambda q: q.relative_to(payload).as_posix()):
        h.update(p.relative_to(payload).as_posix().encode())
        h.update(b"\0")
        h.update(mr.sha1_file(p).encode())
        h.update(b"\n")
    return h.hexdigest()[:12]


def apprun_script(app_id):
    return f"""#!/bin/sh
# Generated by tools/make_appimage.py — FFTA Recomp AppImage entry point.
set -eu

if [ -z "${{APPDIR:-}}" ]; then
    APPDIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
fi

APP_ID='{app_id}'
if [ -n "${{XDG_DATA_HOME:-}}" ]; then
    DATA_ROOT="$XDG_DATA_HOME/ffta-recomp"
elif [ -n "${{HOME:-}}" ]; then
    DATA_ROOT="$HOME/.local/share/ffta-recomp"
else
    DATA_ROOT="${{TMPDIR:-/tmp}}/ffta-recomp-$(id -u)"
fi
DEST="$DATA_ROOT/app"

first_run=0
if [ ! -x "$DEST/FFTARecomp" ]; then
    first_run=1
fi
if [ "$first_run" -eq 1 ] || \\
   [ "$(cat "$DEST/.appimage-id" 2>/dev/null || true)" != "$APP_ID" ]; then
    mkdir -p "$DEST"
    # Copy the new payload over the old one; player files (rom.cfg,
    # config.ini, keybinds.ini, saves/) are never deleted by an update.
    cp -a "$APPDIR/usr/bin/." "$DEST/"
    printf '%s\\n' "$APP_ID" > "$DEST/.appimage-id"
    if [ "$first_run" -eq 1 ]; then
        echo "FFTA Recomp: unpacked to $DEST" >&2
    fi
fi

# Steam Deck / Game Mode: fill the 1280x720 panel unless the player chose.
if [ "${{SteamDeck:-0}}" = "1" ] && \\
   [ "${{FFTA_APPIMAGE_NO_DECK_DEFAULTS:-0}}" != "1" ]; then
    case " $* " in
        *" --fullscreen"*|*" --window"*|*" --no-window"*|*" --scale"*|\\
        *" --resize-view"*|*" --view-width"*)
            ;;
        *)
            set -- --fullscreen=1 --resize-view "$@"
            ;;
    esac
fi

cd "$DEST"
exec "$DEST/FFTARecomp" "$@"
"""


def desktop_entry(version):
    return f"""[Desktop Entry]
Type=Application
Name=FFTA Recomp
GenericName=Game
Comment=Final Fantasy Tactics Advance static recompilation
Exec=FFTARecomp
Icon=ffta-recomp
Terminal=false
Categories=Game;
Keywords=FFTA;Final Fantasy Tactics;GBA;recomp;
StartupWMClass=FFTARecomp
X-AppImage-Version={version}
"""


def build_appdir(payload, version, appdir):
    if appdir.exists():
        shutil.rmtree(appdir)
    (appdir / "usr" / "bin").mkdir(parents=True)
    shutil.copytree(payload, appdir / "usr" / "bin", dirs_exist_ok=True)

    app_id = payload_id(payload)
    apprun = appdir / "AppRun"
    apprun.write_text(apprun_script(app_id), encoding="utf-8")
    apprun.chmod(0o755)

    if not ICON.is_file():
        die(f"missing AppImage icon: {ICON}")
    shutil.copy2(ICON, appdir / "ffta-recomp.png")
    shutil.copy2(ICON, appdir / ".DirIcon")
    icon_dir = appdir / "usr" / "share" / "icons" / "hicolor" / \
        "512x512" / "apps"
    icon_dir.mkdir(parents=True)
    shutil.copy2(ICON, icon_dir / "ffta-recomp.png")

    desktop = desktop_entry(version)
    (appdir / "ffta-recomp.desktop").write_text(desktop, encoding="utf-8")
    apps_dir = appdir / "usr" / "share" / "applications"
    apps_dir.mkdir(parents=True)
    (apps_dir / "ffta-recomp.desktop").write_text(desktop, encoding="utf-8")
    return app_id


def source_epoch():
    r = subprocess.run(["git", "-C", str(REPO), "log", "-1", "--format=%ct"],
                       capture_output=True, text=True)
    if r.returncode == 0 and r.stdout.strip().isdigit():
        return r.stdout.strip()
    return "0"


def run_appimagetool(tool, runtime, appdir, output):
    if output.exists():
        output.unlink()
    env = dict(os.environ)
    env.update({
        "ARCH": "x86_64",
        "APPIMAGE_EXTRACT_AND_RUN": "1",
        "SOURCE_DATE_EPOCH": source_epoch(),
    })
    # Absolute paths: appimagetool extracts itself to a temp dir when
    # APPIMAGE_EXTRACT_AND_RUN is set, so relative paths are ambiguous.
    r = subprocess.run([str(tool), "--no-appstream",
                        "--runtime-file", str(runtime),
                        str(appdir), str(output)], cwd=str(OUT_DIR), env=env,
                       capture_output=True, text=True)
    if r.returncode != 0:
        tail = "\n".join((r.stdout + r.stderr).strip().splitlines()[-20:])
        die("appimagetool failed:\n" + tail)
    if not output.is_file() or output.stat().st_size == 0:
        die("appimagetool reported success but produced no AppImage")


def guard_appimage(output):
    """Extract the finished AppImage and run the same private-material sweep."""
    with tempfile.TemporaryDirectory(prefix="ffta-appimage-guard-") as td:
        r = subprocess.run([str(output), "--appimage-extract"], cwd=td,
                           capture_output=True, text=True)
        if r.returncode != 0:
            tail = "\n".join((r.stdout + r.stderr).strip().splitlines()[-20:])
            die("AppImage self-extract failed:\n" + tail)
        root = Path(td) / "squashfs-root"
        payload = root / "usr" / "bin"
        if not payload.is_dir():
            die("extracted AppImage has no usr/bin payload")
        violations = mr.sweep_stage(payload)
        if violations:
            die("AppImage payload rejected:\n  " + "\n  ".join(violations))
        if not (root / "ffta-recomp.desktop").is_file():
            die("AppImage has no desktop entry")
        if not (root / "ffta-recomp.png").is_file():
            die("AppImage has no icon")


def smoke_appimage(output, frames):
    """Boot the packaged AppImage from a fresh data dir, then reuse it."""
    if not ROM.is_file():
        die(f"missing {ROM} — the AppImage smoke needs the ROM")
    with tempfile.TemporaryDirectory(prefix="ffta-appimage-smoke-") as td:
        data = Path(td) / "data"
        env = {k: v for k, v in os.environ.items()
               if not k.startswith("GBARECOMP_")}
        env.update({
            "XDG_DATA_HOME": str(data),
            "APPIMAGE_EXTRACT_AND_RUN": "1",
            "GBARECOMP_STRICT_STATIC": "1",
        })

        def run(n):
            return subprocess.run(
                [str(output), "--bios", str(BIOS), "--rom", str(ROM),
                 "--frames", str(n), "--no-window"],
                cwd=td, env=env, capture_output=True, text=True, timeout=600)

        r = run(frames)
        out = r.stdout + r.stderr
        line = next((l.strip() for l in out.splitlines()
                     if "self_heal_coverage" in l), "")
        if r.returncode != 0 or "FULLY_STATIC" not in line:
            tail = "\n".join(out.strip().splitlines()[-20:])
            die("AppImage smoke did not reach FULLY_STATIC: "
                + (line or tail))
        app = data / "ffta-recomp" / "app"
        stamp = app / ".appimage-id"
        if not stamp.is_file():
            die("AppImage did not unpack its payload into the data dir")
        before = stamp.stat().st_mtime_ns
        r2 = run(120)
        if r2.returncode != 0:
            tail = (r2.stdout + r2.stderr).strip().splitlines()[-20:]
            die("AppImage second run failed:\n" + "\n".join(tail))
        if stamp.stat().st_mtime_ns != before:
            die("AppImage re-unpacked on the second run (cache stamp moved)")
        return line, app


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Build the Steam-Deck-friendly FFTA Recomp AppImage.")
    ap.add_argument("--version", default=None,
                    help="release version (default: git describe)")
    default_binary = REPO / "build-compat" / "FFTARecomp"
    if not default_binary.is_file():
        default_binary = mr.BINARY
    ap.add_argument("--binary", default=str(default_binary),
                    help="Linux executable to package (default: "
                         "build-compat/FFTARecomp, else build/FFTARecomp)")
    ap.add_argument("--appimagetool", default=None,
                    help="use a local appimagetool instead of the pinned "
                         "download")
    ap.add_argument("--runtime-file", default=None,
                    help="use a local AppImage type-2 runtime instead of the "
                         "pinned download")
    ap.add_argument("--no-strip", action="store_true",
                    help="do not strip the staged executable")
    ap.add_argument("--frames", type=int, default=2400,
                    help="strict smoke frame count (default 2400)")
    ap.add_argument("--no-smoke", action="store_true",
                    help="skip the packaged-AppImage boot (dev only; never "
                         "use for a release)")
    ap.add_argument("--clean", action="store_true",
                    help="remove the payload/AppDir after a successful build")
    a = ap.parse_args(argv)

    binary = Path(a.binary).resolve()
    if binary == mr.BINARY.resolve():
        print("appimage: warning: using the host build; pass "
              "--binary build-compat/FFTARecomp for the SteamOS glibc floor",
              flush=True)
    mr.check_freshness(binary)
    version = a.version or mr.git_version()
    version = version.replace("/", "-")
    OUT_DIR.mkdir(exist_ok=True)

    payload_dir = OUT_DIR / f"FFTARecomp-{version}-appimage-payload"
    mods = REPO / "build-compat" / "mods"
    if not mods.is_dir():
        mods = None
    payload, _ = mr.stage_release(
        version, strip=not a.no_strip, binary=binary, out_dir=OUT_DIR,
        folder=payload_dir.name, mods_dir=mods)
    violations = mr.sweep_stage(payload)
    if violations:
        die("AppImage stage rejected:\n  " + "\n  ".join(violations))
    readme = payload / "README.md"
    readme.write_text(readme.read_text(encoding="utf-8") + APPIMAGE_README,
                      encoding="utf-8")

    appdir = OUT_DIR / f"FFTARecomp-{version}.AppDir"
    app_id = build_appdir(payload, version, appdir)
    print(f"appimage: payload {payload.name} id={app_id}", flush=True)

    tool = ensure_appimagetool(a.appimagetool)
    runtime = ensure_runtime(a.runtime_file)
    output = OUT_DIR / f"FFTARecomp-{version}-linux-x86_64.AppImage"
    run_appimagetool(tool, runtime, appdir, output)
    guard_appimage(output)

    smoke = "skipped"
    if not a.no_smoke:
        smoke, app = smoke_appimage(output, a.frames)
        print(f"appimage: data dir {app}", flush=True)

    digest = sha256_file(output)
    print(f"appimage: {output.name} sha256={digest} "
          f"size={output.stat().st_size} "
          f"(guard: sweep+squashfs, smoke: "
          f"{'FULLY_STATIC' if 'FULLY_STATIC' in smoke else 'skipped'})")
    if a.clean:
        shutil.rmtree(payload, ignore_errors=True)
        shutil.rmtree(appdir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Fail as exc:
        print(f"make_appimage: {exc}", file=sys.stderr)
        sys.exit(1)
