#!/usr/bin/env python3
"""APK content guard for FFTARecomp (check.py suite: `android-apk`).

Static, device-free verification of a built APK — unzip + aapt2, no phone:
the payload it would install must byte-match the staging sources, a private
test build must embed the pinned ROM (and BIOS when present), a public build
must embed neither, native libraries and manifest facts must match the build
config, and the zip must be free of duplicate / stray / oversized entries
(the incremental-repackaging junk-blob class, android/README.md § Known
behavior).

Run after `./gradlew :app:assembleDebug` (android/README.md § Build):

    tools/android_apk_check.py                      # newest APK under android/
    tools/android_apk_check.py --apk <path> [--expect public|private]

The default check.py gate skips it (a desktop worktree may have no APK);
select it explicitly with `--only android-apk` after an Android build.

Exit codes: 0 = all checks pass, 1 = at least one failure, 2 = setup error
(no APK / no aapt2 / unreadable zip).
"""
import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from android_static_check import (  # noqa: E402 - sibling tool plumbing
    REPO,
    CheckFailure,
    Suite,
    load_toml,
    need,
    one,
    tail,
)

APK_DIR = REPO / "android/app/build/outputs/apk"
PRIVATE_MARKER = "-PRIVATE-rom-included.apk"
ALLOWED_ABIS = {"arm64-v8a", "x86_64"}
EXPECTED_LIBS = {"libmain.so", "libSDL2.so", "libc++_shared.so"}
MAX_STRAY_ENTRY = 1024 * 1024
SENSOR_LANDSCAPE = 6
ALLOWED_ENTRY = re.compile(
    r"^(AndroidManifest\.xml|classes\d*\.dex|resources\.arsc"
    r"|res/.+|lib/.+|assets/.+|META-INF/.+)$")


# ---------------------------------------------------------------------------
# Inputs: build config, aapt2, the APK
# ---------------------------------------------------------------------------

def build_config():
    gradle = (REPO / "android/app/build.gradle").read_text(encoding="utf-8")
    template = (REPO / "gbarecomp/platform/android/gbarecomp-app.gradle")
    template_text = template.read_text(encoding="utf-8")
    android_toml = load_toml("android/game_android.toml")
    return {
        "application_id": one(r'applicationId\s*:\s*"([^"]+)"', gradle,
                              "applicationId"),
        "variant": one(r'^\s*variant\s*:\s*"([^"]+)"', gradle, "variant",
                       re.M),
        "rom_file": one(r'romFile\s*:\s*"([^"]+)"', gradle, "romFile"),
        "rom_sha1": one(r'romSha1\s*:\s*\["([0-9a-f]{40})"\]', gradle,
                        "romSha1"),
        "rom_size": int(one(r'romSize\s*:\s*(\d+)', gradle, "romSize")),
        "min_sdk": one(r'minSdk\s+(\d+)', template_text, "minSdk"),
        "target_sdk": one(r'targetSdk\s+(\d+)', template_text, "targetSdk"),
        "bios_sha1": android_toml["bios"]["sha1"],
        "bios_size": 16 * 1024,
    }


def _version_key(name):
    return tuple(int(part) for part in re.findall(r"\d+", name))


def find_aapt2():
    """Newest SDK build-tools aapt2, then whatever is on PATH."""
    for env in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        root = os.environ.get(env)
        if not root:
            continue
        build_tools = Path(root) / "build-tools"
        if not build_tools.is_dir():
            continue
        for candidate in sorted(build_tools.iterdir(), reverse=True,
                                key=lambda p: _version_key(p.name)):
            exe = candidate / "aapt2"
            if exe.is_file() and os.access(exe, os.X_OK):
                return exe
    found = shutil.which("aapt2")
    return Path(found) if found else None


def discover_apk():
    if not APK_DIR.is_dir():
        return None
    candidates = sorted(APK_DIR.rglob("*.apk"),
                        key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def _dump(aapt2, apk, *args):
    completed = subprocess.run([str(aapt2), "dump", *args, str(apk)],
                               capture_output=True, text=True, timeout=180)
    if completed.returncode != 0:
        return None, tail(completed)
    return completed.stdout, None


def parse_activities(xmltree_text):
    """[{name, orientation}] from `aapt2 dump xmltree` (indent-aware)."""
    activities = []
    current = None
    current_indent = None
    for raw in xmltree_text.splitlines():
        indent = len(raw) - len(raw.lstrip(" "))
        line = raw.strip()
        if line.startswith("E: activity ("):
            if current is not None:
                activities.append(current)
            current = {"name": None, "orientation": None}
            current_indent = indent
            continue
        if current is None:
            continue
        if line.startswith("E: ") and indent <= current_indent:
            activities.append(current)
            current = None
            current_indent = None
            continue
        if line.startswith("A: "):
            if current["name"] is None and "name(" in line and '"' in line:
                match = re.search(r'name\(0x[0-9a-f]+\)="([^"]+)"', line)
                if match:
                    current["name"] = match.group(1)
            if "screenOrientation(" in line:
                match = re.search(r'screenOrientation\(0x[0-9a-f]+\)=(\d+)',
                                  line)
                if match:
                    current["orientation"] = int(match.group(1))
    if current is not None:
        activities.append(current)
    return activities


class Context:
    def __init__(self, apk_path, expect):
        self.apk_path = apk_path
        self.expect = expect
        self.config = build_config()
        self.aapt2 = find_aapt2()
        need(self.aapt2 is not None,
             "aapt2 not found — install Android build-tools or set "
             "ANDROID_HOME")
        need(apk_path.is_file(), "APK not found: %s" % apk_path)
        try:
            self.zf = zipfile.ZipFile(apk_path)
        except zipfile.BadZipFile as exc:
            raise CheckFailure("not a readable zip: %s" % exc) from None
        self.infos = {info.filename: info for info in self.zf.infolist()}
        self.names = [info.filename for info in self.zf.infolist()]
        self.private = apk_path.name.endswith(PRIVATE_MARKER)
        self.badging, self.badging_err = _dump(self.aapt2, apk_path,
                                               "badging")
        self.xmltree, self.xmltree_err = _dump(
            self.aapt2, apk_path, "xmltree", "--file", "AndroidManifest.xml")
        self.activities = parse_activities(self.xmltree or "")
        self.libs = {}
        for name in self.names:
            if name.startswith("lib/"):
                parts = name.split("/")
                if len(parts) == 3:
                    self.libs.setdefault(parts[1], []).append(parts[2])

    def mode(self):
        return "private" if self.private else "public"

    def rom_asset(self):
        return "assets/payload/roms/%s" % self.config["rom_file"]

    def bios_asset(self):
        return "assets/payload/bios/gba_bios.bin"

    def sha1_of(self, entry):
        digest = hashlib.sha1()
        with self.zf.open(entry) as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()


def expected_payload():
    """asset path -> source file, mirroring gbarecomp-app.gradle staging
    (variant TOML renamed, both mods sources folded into payload/mods)."""
    config = build_config()
    expected = {
        "assets/payload/variants/%s/game.toml" % config["variant"]:
            REPO / "android/game_android.toml",
    }
    for source in (REPO / "mods/preloaded", REPO / "android/payload/mods"):
        for path in sorted(source.rglob("*")):
            if path.is_file():
                rel = path.relative_to(source).as_posix()
                expected["assets/payload/mods/" + rel] = path
    return expected


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def check_identity(ctx):
    need(ctx.badging is not None,
         "aapt2 dump badging failed: %s" % ctx.badging_err)
    config = ctx.config
    package = one(r"package: name='([^']+)'", ctx.badging, "package in badging")
    need(package == config["application_id"],
         "package %s != build.gradle applicationId %s"
         % (package, config["application_id"]))
    min_sdk = one(r"minSdkVersion:'(\d+)'", ctx.badging, "minSdkVersion")
    target_sdk = one(r"targetSdkVersion:'(\d+)'", ctx.badging, "targetSdkVersion")
    need(min_sdk == config["min_sdk"],
         "minSdk %s != engine template minSdk %s" % (min_sdk, config["min_sdk"]))
    need(target_sdk == config["target_sdk"],
         "targetSdk %s != engine template targetSdk %s"
         % (target_sdk, config["target_sdk"]))
    launcher = one(r"launchable-activity: name='([^']+)'", ctx.badging,
                   "launchable-activity")
    need(launcher.endswith(".GbaSetupActivity"),
         "launchable activity %s is not the setup activity" % launcher)


def check_markers(ctx):
    has_rom = any(n.startswith("assets/payload/roms/") for n in ctx.names)
    has_bios = any(n.startswith("assets/payload/bios/") for n in ctx.names)
    if ctx.private:
        need(has_rom or has_bios,
             "private-named APK embeds nothing — built without "
             "-PprivateRom/-PprivateBios?")
    else:
        offenders = [n for n in ctx.names
                     if n.startswith(("assets/payload/roms/",
                                      "assets/payload/bios/"))]
        need(not offenders,
             "a distributable-named APK contains private assets: %s"
             % ", ".join(offenders))
    if ctx.expect:
        need((ctx.expect == "private") == ctx.private,
             "APK is %s but --expect %s was given" % (ctx.mode(), ctx.expect))


def check_payload(ctx):
    config = ctx.config
    expected = expected_payload()
    rom_asset = ctx.rom_asset()
    bios_asset = ctx.bios_asset()
    payload = [n for n in ctx.names if n.startswith("assets/payload/")]
    private_assets = {n for n in payload
                      if n.startswith("assets/payload/roms/")
                      or n.startswith("assets/payload/bios/")}
    stray_private = sorted(private_assets - {rom_asset, bios_asset})
    need(not stray_private,
         "unexpected private-asset paths: %s" % ", ".join(stray_private))
    core = sorted(set(payload) - private_assets)
    missing = sorted(set(expected) - set(core))
    extra = sorted(set(core) - set(expected))
    need(not missing and not extra,
         "payload does not match staging sources (missing: %s; extra: %s)"
         % (", ".join(missing) or "-", ", ".join(extra) or "-"))
    for asset, source in sorted(expected.items()):
        need(ctx.zf.read(asset) == source.read_bytes(),
             "%s does not byte-match %s" % (asset, source.relative_to(REPO)))


def check_embeds(ctx):
    config = ctx.config
    rom_asset = ctx.rom_asset()
    bios_asset = ctx.bios_asset()
    if not ctx.private:
        offenders = [n for n in ctx.names
                     if n in (rom_asset, bios_asset)
                     or n.startswith(("assets/payload/roms/",
                                      "assets/payload/bios/"))]
        need(not offenders, "public APK embeds private assets: %s"
             % ", ".join(offenders))
        return
    need(rom_asset in ctx.infos,
         "private build is missing the embedded ROM (%s)" % rom_asset)
    info = ctx.infos[rom_asset]
    need(info.file_size == config["rom_size"],
         "embedded ROM is %d bytes, expected %d"
         % (info.file_size, config["rom_size"]))
    digest = ctx.sha1_of(rom_asset)
    need(digest == config["rom_sha1"],
         "embedded ROM sha1 %s != pinned %s" % (digest, config["rom_sha1"]))
    if bios_asset in ctx.infos:
        bios = ctx.infos[bios_asset]
        need(bios.file_size == config["bios_size"],
             "embedded BIOS is %d bytes, expected %d"
             % (bios.file_size, config["bios_size"]))
        digest = ctx.sha1_of(bios_asset)
        need(digest == config["bios_sha1"],
             "embedded BIOS sha1 %s != pinned %s" % (digest, config["bios_sha1"]))


def check_native_libs(ctx):
    need(ctx.libs, "no lib/ entries in the APK")
    for abi, files in sorted(ctx.libs.items()):
        need(abi in ALLOWED_ABIS, "unexpected ABI %s" % abi)
        need(files.count("libmain.so") == 1,
             "libmain.so missing or duplicated for %s" % abi)
        unexpected = sorted(set(files) - EXPECTED_LIBS)
        need(not unexpected,
             "unexpected libraries for %s: %s (deliberate? update this check)"
             % (abi, ", ".join(unexpected)))
    if ctx.badging:
        match = re.search(r"native-code:\s*(.+)", ctx.badging)
        if match:
            from_badging = set(re.findall(r"'([^']+)'", match.group(1)))
            need(from_badging == set(ctx.libs),
                 "badging native-code %s != lib/ ABIs %s"
                 % (sorted(from_badging), sorted(ctx.libs)))


def check_manifest(ctx):
    need(ctx.xmltree is not None,
         "aapt2 dump xmltree failed: %s" % ctx.xmltree_err)
    acts = {a["name"]: a["orientation"] for a in ctx.activities
            if a.get("name")}
    for cls in ("org.gbarecomp.GbaSetupActivity",
                "org.gbarecomp.GbaGameActivity"):
        need(cls in acts, "activity %s missing from the manifest" % cls)
        need(acts[cls] == SENSOR_LANDSCAPE,
             "%s orientation %s != sensorLandscape (%d)"
             % (cls, acts[cls], SENSOR_LANDSCAPE))
    build_type = re.search(r"-(debug|release)(?=[.-])", ctx.apk_path.name)
    if build_type:
        expected = build_type.group(1) == "debug"
        match = re.search(r":debuggable\(0x[0-9a-f]+\)=(\w+)", ctx.xmltree)
        actual = bool(match) and match.group(1) == "true"
        need(actual == expected,
             "debuggable=%s but the name says %s"
             % (actual, build_type.group(1)))


def check_no_debug_args(ctx):
    offenders = [n for n in ctx.names
                 if os.path.basename(n) == "debug-args.txt"]
    need(not offenders,
         "debug-args.txt must never be packaged: %s" % ", ".join(offenders))


def check_packaging(ctx):
    bad = ctx.zf.testzip()
    need(bad is None, "zip CRC check failed at %s" % bad)
    duplicates = sorted({n for n in ctx.names if ctx.names.count(n) > 1})
    need(not duplicates,
         "duplicate zip entries: %s" % ", ".join(duplicates))
    stray = [n for n in ctx.names if not ALLOWED_ENTRY.match(n)]
    need(not stray, "unexpected zip entries: %s" % ", ".join(stray))
    stray_assets = [n for n in ctx.names
                    if n.startswith("assets/")
                    and not n.startswith("assets/payload/")]
    need(not stray_assets,
         "assets/ outside the payload tree: %s" % ", ".join(stray_assets))
    rom_asset = ctx.rom_asset()
    big = []
    for info in ctx.zf.infolist():
        if info.file_size <= MAX_STRAY_ENTRY:
            continue
        if info.filename.startswith("lib/") or info.filename == rom_asset:
            continue
        big.append("%s (%d bytes)" % (info.filename, info.file_size))
    need(not big,
         "unexpected large entries — the incremental-repackaging junk-blob "
         "class (android/README.md § Known behavior): %s" % ", ".join(big))
    # Slack form of the same class (observed 2026-10-09): stale bytes between
    # the last entry and the signing block — invisible to infolist(). The APK
    # file size must be within local-header/central-directory/signing-block
    # overhead of the sum of the compressed entries; ~1 MiB covers thousands
    # of headers (our ~15-entry APK uses <2 KB) — 30 MB of slack failed here.
    import os
    apk_bytes = os.path.getsize(ctx.apk_path)
    entries_bytes = sum(i.compress_size for i in ctx.zf.infolist())
    overhead = sum(30 + len(i.filename) + 16 + 46 + len(i.filename)
                    for i in ctx.zf.infolist()) + 1024 + (1 << 20)
    need(apk_bytes <= entries_bytes + overhead,
         "APK is %d bytes but its %d entries compress to %d — %.1f MB of "
         "unaccounted slack between entries (the incremental-repackaging "
         "junk class: stale bytes from a prior build, invisible to "
         "infolist). Clean `android/app/build` and rebuild"
         % (apk_bytes, len(ctx.names), entries_bytes,
            (apk_bytes - entries_bytes) / (1024 * 1024)))


CHECKS = [
    ("apk: identity (package, sdk levels, launcher)", check_identity),
    ("apk: public/private markers consistent", check_markers),
    ("apk: payload matches staging sources", check_payload),
    ("apk: embedded ROM/BIOS verified (private) / absent (public)",
     check_embeds),
    ("apk: native libs per ABI", check_native_libs),
    ("apk: manifest activities + debuggable flag", check_manifest),
    ("apk: no debug-args.txt packaged", check_no_debug_args),
    ("apk: packaging sanity (CRC, duplicates, strays, oversize)",
     check_packaging),
]


def main():
    parser = argparse.ArgumentParser(
        description="Static content guard for a built FFTARecomp APK.")
    parser.add_argument("--apk", help="APK path (default: newest under %s)"
                        % APK_DIR.relative_to(REPO))
    parser.add_argument("--expect", choices=("public", "private"),
                        help="require this build mode")
    args = parser.parse_args()

    apk = Path(args.apk) if args.apk else discover_apk()
    if apk is None:
        print("android-apk: no APK under %s — build one first "
              "(android/README.md § Build)" % APK_DIR.relative_to(REPO))
        return 2
    try:
        ctx = Context(apk, args.expect)
    except CheckFailure as exc:
        print("android-apk: setup error — %s" % exc)
        return 2

    print("android-apk: checking %s" % apk)
    suite = Suite()
    for name, fn in CHECKS:
        suite.run(name, lambda fn=fn: fn(ctx))
    passed = 0
    for name, ok, detail in suite.results:
        print("[%s] %s%s" % ("PASS" if ok else "FAIL", name,
                             "" if ok else " — " + detail))
        if ok:
            passed += 1
    total = len(suite.results)
    size_mib = apk.stat().st_size / (1024 * 1024)
    if passed == total:
        print("android-apk: OK (%d checks passed; %s, %s, %s, %.1f MiB)"
              % (total, apk.name, ctx.mode(),
                 ",".join(sorted(ctx.libs)) or "no ABIs", size_mib))
        return 0
    failing = ", ".join(name for name, ok, _ in suite.results if not ok)
    print("android-apk: FAILED (%d/%d passed; failing: %s)"
          % (passed, total, failing))
    return 1


if __name__ == "__main__":
    sys.exit(main())
