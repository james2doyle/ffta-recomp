#!/usr/bin/env python3
"""Device-free Android checks for FFTARecomp (check.py suite: `android-static`).

Validates the game-repo Android surface without a phone, an SDK, or a Gradle
build, and self-tests the device gate script against a fake `adb`:

  identity  applicationId / variant / ROM / BIOS / save pins consistent
            across android/app/build.gradle, android/game_android.toml,
            game.toml, the gate script constants and the engine default
  payload   android/payload/mods/state.toml keeps the widescreen feature
            enabled (the second-launch fix) and matches the preloaded catalog
  hygiene   no ROM/save/APK/binary artifacts tracked; android build outputs
            stay gitignored
  gate      tools/validate_android.sh passes a clean fake-device run (evidence
            pulled) and fails SELF-HEAL / missing-log / crash-buffer /
            setup-still-resumed runs; usage errors exit 2

Usage: tools/android_static_check.py        (stdlib only; runs from any cwd)
Exit codes: 0 = all checks pass, 1 = at least one failure.
"""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

try:
    import tomllib as _tomllib
except ModuleNotFoundError:  # Python 3.10 (tomllib landed in 3.11)
    _tomllib = None

# Standard GBA BIOS dump hash, mirrored by the engine template's default.
BIOS_SHA1 = "300c20df6731a33952ded8c436f7f186d25d3492"


# ---------------------------------------------------------------------------
# Minimal TOML reading (tomllib when available, subset fallback for 3.10)
# ---------------------------------------------------------------------------

def _strip_comment(line):
    out = []
    in_string = False
    escaped = False
    for ch in line:
        if escaped:
            out.append(ch)
            escaped = False
            continue
        if in_string and ch == "\\":
            out.append(ch)
            escaped = True
            continue
        if ch == '"':
            in_string = not in_string
            out.append(ch)
            continue
        if ch == "#" and not in_string:
            break
        out.append(ch)
    return "".join(out)


def _parse_scalar(text):
    text = text.strip()
    if len(text) >= 2 and text.startswith('"') and text.endswith('"'):
        return text[1:-1]
    if text == "true":
        return True
    if text == "false":
        return False
    try:
        return int(text, 0)
    except ValueError:
        return text


def _mini_load(path):
    """Subset reader for the shapes this repo's Android TOMLs use: flat
    [tables], [[arrays of tables]], string/bool/int scalars, comments."""
    root = {}
    current = root
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = _strip_comment(raw).strip()
        if not line:
            continue
        if line.startswith("[[") and line.endswith("]]"):
            current = {}
            root.setdefault(line[2:-2].strip(), []).append(current)
            continue
        if line.startswith("[") and line.endswith("]"):
            current = root.setdefault(line[1:-1].strip(), {})
            continue
        key, sep, value = line.partition("=")
        if not sep:
            raise ValueError("%s:%d: unsupported line: %s"
                             % (path, lineno, raw.strip()))
        current[key.strip()] = _parse_scalar(value)
    return root


def load_toml(rel):
    path = REPO / rel
    if _tomllib is not None:
        with path.open("rb") as handle:
            return _tomllib.load(handle)
    return _mini_load(path)


def read_text(rel):
    return (REPO / rel).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Check plumbing
# ---------------------------------------------------------------------------

class CheckFailure(Exception):
    pass


def need(condition, message):
    if not condition:
        raise CheckFailure(message)


def one(pattern, text, what, flags=0):
    match = re.search(pattern, text, flags)
    need(match is not None, "could not find %s" % what)
    return match.group(1)


class Suite:
    def __init__(self):
        self.results = []  # (name, ok, detail)

    def run(self, name, fn):
        try:
            fn()
        except CheckFailure as exc:
            self.results.append((name, False, str(exc)))
        except Exception as exc:  # keep the suite summarizing on bugs too
            self.results.append(
                (name, False, "%s: %s" % (type(exc).__name__, exc)))
        else:
            self.results.append((name, True, ""))


def tail(completed, limit=300):
    text = (completed.stdout or "") + "\n" + (completed.stderr or "")
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return "(no output)"
    return " | ".join(lines[-2:])[:limit]


# ---------------------------------------------------------------------------
# Identity checks
# ---------------------------------------------------------------------------

def check_package_constants():
    gradle = read_text("android/app/build.gradle")
    package = one(r'applicationId\s*:\s*"([^"]+)"', gradle, "applicationId")
    gate = read_text("tools/validate_android.sh")
    gate_package = one(r'^PACKAGE="([^"]+)"', gate, "PACKAGE", re.M)
    need(package == gate_package,
         "applicationId %r != gate PACKAGE %r" % (package, gate_package))
    setup = one(r'^SETUP_ACTIVITY="([^"]+)"', gate, "SETUP_ACTIVITY", re.M)
    game = one(r'^GAME_ACTIVITY="([^"]+)"', gate, "GAME_ACTIVITY", re.M)
    need(setup.endswith(".GbaSetupActivity") and game.endswith(".GbaGameActivity"),
         "gate activity constants look renamed: %s / %s" % (setup, game))


def check_variant():
    gradle = read_text("android/app/build.gradle")
    gradle_variant = one(r'^\s*variant\s*:\s*"([^"]+)"', gradle,
                         "gbaGame variant", re.M)
    game = load_toml("game.toml")["game"]["short_name"]
    android = load_toml("android/game_android.toml")["game"]["short_name"]
    need(len({gradle_variant, game, android}) == 1,
         "variant/short_name mismatch: build.gradle=%r game.toml=%r "
         "game_android.toml=%r" % (gradle_variant, game, android))


def check_rom_pins():
    gradle = read_text("android/app/build.gradle")
    gradle_sha = one(r'romSha1\s*:\s*\["([0-9a-f]{40})"\]', gradle, "romSha1")
    gradle_size = int(one(r'romSize\s*:\s*(\d+)', gradle, "romSize"))
    gradle_file = one(r'romFile\s*:\s*"([^"]+)"', gradle, "romFile")
    game = load_toml("game.toml")
    android = load_toml("android/game_android.toml")
    shas = {gradle_sha, game["identity"]["sha1"], game["rom"]["sha1"],
            android["rom"]["sha1"]}
    need(len(shas) == 1, "ROM sha1 mismatch across build.gradle / game.toml "
                         "[identity] / game.toml [rom] / game_android.toml: %s"
                         % sorted(shas))
    need(game["program"]["size"] == gradle_size,
         "game.toml [program].size %d != build.gradle romSize %d"
         % (game["program"]["size"], gradle_size))
    android_file = Path(android["rom"]["path"]).name
    need(android_file == gradle_file,
         "game_android.toml [rom].path basename %r != romFile %r"
         % (android_file, gradle_file))


def check_bios_pins():
    game = load_toml("game.toml")
    android = load_toml("android/game_android.toml")
    need(android["bios"]["sha1"] == game["bios"]["sha1"],
         "BIOS sha1 mismatch: game.toml %s != game_android.toml %s"
         % (game["bios"]["sha1"], android["bios"]["sha1"]))
    need(android["bios"]["hle"] is False,
         "game_android.toml must keep [bios].hle = false (LLE)")
    need(Path(android["bios"]["path"]).name == Path(game["bios"]["path"]).name,
         "BIOS filename mismatch: %r vs %r"
         % (android["bios"]["path"], game["bios"]["path"]))
    template = REPO / "gbarecomp/platform/android/gbarecomp-app.gradle"
    need(template.is_file(),
         "%s missing — initialize the gbarecomp submodule"
         % template.relative_to(REPO))
    default = one(r'gbaBiosSha1:\s*g\.biosSha1\s*\?:\s*"([0-9a-f]{40})"',
                  template.read_text(encoding="utf-8"),
                  "engine biosSha1 default")
    need(default == android["bios"]["sha1"], "engine template default %s != "
         "game_android.toml [bios].sha1 %s" % (default, android["bios"]["sha1"]))


def check_save_config():
    game = load_toml("game.toml")
    android = load_toml("android/game_android.toml")
    need(android["save"]["type"] == game["save"]["type"],
         "save type mismatch: game.toml %r != game_android.toml %r"
         % (game["save"]["type"], android["save"]["type"]))
    need(android["save"]["size"] == game["save"]["size"],
         "save size mismatch: game.toml %d != game_android.toml %d"
         % (game["save"]["size"], android["save"]["size"]))


# ---------------------------------------------------------------------------
# Payload checks
# ---------------------------------------------------------------------------

def check_state_toml():
    state = load_toml("android/payload/mods/state.toml")
    packages = state.get("package", [])
    need(len(packages) == 1,
         "expected one [[package]] in state.toml, found %d" % len(packages))
    package = packages[0]
    need(package.get("id") == "ffta.enhancement.widescreen",
         "unexpected default package %r — update this check and the docs if "
         "the default selection is deliberate" % package.get("id"))
    matches = [f for f in state.get("feature", [])
               if f.get("package_id") == package.get("id")
               and f.get("id") == "widescreen"]
    need(matches and matches[0].get("enabled") is True,
         "state.toml must ship enabled = true for the widescreen feature: the "
         "engine persists raw false for never-touched features from the "
         "second launch on (see android/README.md § Mods state)")


def check_state_catalog():
    state = load_toml("android/payload/mods/state.toml")
    package = state["package"][0]
    package_id = package["id"]
    version = package["version"]
    manifest_path = (REPO / "mods/preloaded/packages" / package_id / version
                     / "manifest.toml")
    need(manifest_path.is_file(),
         "catalog manifest missing: %s" % manifest_path.relative_to(REPO))
    manifest = load_toml(str(manifest_path.relative_to(REPO)))
    need(manifest.get("id") == package_id
         and manifest.get("version") == version,
         "state.toml package %s/%s != catalog manifest %s/%s"
         % (package_id, version, manifest.get("id"), manifest.get("version")))
    catalog_features = {f.get("id") for f in manifest.get("feature", [])}
    state_features = {f.get("id") for f in state.get("feature", [])}
    unknown = state_features - catalog_features
    need(not unknown,
         "state.toml enables feature(s) the catalog does not declare: %s"
         % ", ".join(sorted(unknown)))


def check_payload_wiring():
    for rel in ("mods/preloaded/packages", "android/payload/mods"):
        path = REPO / rel
        need(path.is_dir() and any(path.iterdir()),
             "%s missing or empty" % rel)
    gradle = read_text("android/app/build.gradle")
    need('"mods/preloaded"' in gradle and '"payload/mods"' in gradle,
         "build.gradle payloadDirs no longer stages both mods sources")


def check_resize_view():
    android = load_toml("android/game_android.toml")
    need(android["video"].get("resize_view") is True,
         "game_android.toml must keep [video] resize_view = true — the "
         "Android expanded-view opt-in (deliberate change? update "
         "android/README.md § Decisions and this check)")


# ---------------------------------------------------------------------------
# Hygiene checks
# ---------------------------------------------------------------------------

def check_tracked_artifacts():
    completed = subprocess.run(["git", "ls-files"], cwd=str(REPO),
                               capture_output=True, text=True, timeout=60)
    need(completed.returncode == 0,
         "git ls-files failed: %s" % tail(completed))
    offenders = []
    for name in completed.stdout.splitlines():
        base = name.rsplit("/", 1)[-1].lower()
        if base == "gba_bios.bin" or re.search(
                r"\.(gba|sav|apk|aab|state\d*)$", base):
            offenders.append(name)
    need(not offenders,
         "tracked private/binary artifacts: %s" % ", ".join(offenders[:5]))


def check_ignored_outputs():
    paths = [
        "android/artifacts/last-run/screenshot.png",
        "android/app/build/outputs/apk/debug/app-debug.apk",
        "android/local.properties",
        "android/signing.local.properties",
        "android/.gradle/file-system.probe",
        "sample.apk",
    ]
    missing = []
    for rel in paths:
        completed = subprocess.run(["git", "check-ignore", "-q", rel],
                                   cwd=str(REPO), capture_output=True,
                                   text=True, timeout=60)
        if completed.returncode != 0:
            missing.append(rel)
    need(not missing, "path(s) no longer gitignored: %s" % ", ".join(missing))


# ---------------------------------------------------------------------------
# Gate self-test (fake adb)
# ---------------------------------------------------------------------------

FAKE_ADB = '''\
#!/usr/bin/env bash
# Fake `adb` for tools/android_static_check.py — not a device tool.
# FADB_SCENARIO selects the canned behavior: clean | selfheal | missing-log |
# crash | setup-resumed. Outputs mimic a device just closely enough for
# tools/validate_android.sh to walk its normal code paths.
set -u

scenario="${FADB_SCENARIO:-clean}"

args=("$@")
if [ "${args[0]:-}" = "devices" ]; then
  printf 'List of devices attached\\nFADB123\\tdevice\\n'
  exit 0
fi
if [ "${args[0]:-}" = "-s" ]; then
  args=("${args[@]:2}")
fi
cmd="${args[0]:-}"
sub="${args[1]:-}"

case "$cmd" in
  get-state)
    printf 'device\\n' ;;
  install)
    printf 'Success\\n' ;;
  shell)
    case "$sub" in
      getprop)
        case "${args[2]:-}" in
          ro.product.model) printf 'FakePhone\\n' ;;
          ro.build.version.release) printf '14\\n' ;;
          ro.build.version.sdk) printf '34\\n' ;;
          ro.product.cpu.abi) printf 'arm64-v8a\\n' ;;
          *) printf '\\n' ;;
        esac ;;
      pidof)
        printf '4242\\n' ;;
      am)
        if [ "${args[2]:-}" = "start" ]; then
          printf 'Starting: Intent { cmp=org.gbarecomp.fftarecomp/org.gbarecomp.GbaSetupActivity }\\n'
        fi ;;
      dumpsys)
        if [ "$scenario" = "setup-resumed" ]; then
          printf '    topResumedActivity=ActivityRecord{1 u0 org.gbarecomp.fftarecomp/org.gbarecomp.GbaSetupActivity t1}\\n'
        else
          printf '    topResumedActivity=ActivityRecord{1 u0 org.gbarecomp.fftarecomp/org.gbarecomp.GbaGameActivity t1}\\n'
        fi ;;
      *) : ;;
    esac ;;
  exec-out)
    # exec-out run-as <pkg> cat <path>
    path="${args[4]:-}"
    case "$path" in
      files/android-runtime.log)
        case "$scenario" in
          selfheal)
            printf 'gbarecomp: cpu_backend=static-recompiled\\n'
            printf 'runtime: SELF-HEAL dispatch miss pc=0x08001234\\n' ;;
          missing-log)
            printf 'cat: files/android-runtime.log: No such file or directory\\n' ;;
          *)
            printf 'gbarecomp: cpu_backend=static-recompiled\\n'
            printf 'gbarecomp: frames=2400 self_heal_coverage=FULLY_STATIC\\n' ;;
        esac ;;
      *)
        # Every other app-private read (miss frag, coverage json) is absent.
        # `exec-out` folds the remote stderr into stdout; the gate must
        # tolerate that instead of treating "cat: ..." as file content.
        printf 'cat: %s: No such file or directory\\n' "$path" ;;
    esac ;;
  logcat)
    if [ "${args[2]:-}" = "crash" ] && [ "${args[3]:-}" = "-c" ]; then
      exit 0
    fi
    if [ "$scenario" = "crash" ]; then
      printf 'F DEBUG   : Fatal signal 11 (SIGSEGV), code 1, fault addr 0x0 in tid 4242 (fftarecomp)\\n'
      printf 'F DEBUG   : pid: 4242, tid: 4242, name: fftarecomp  >>> org.gbarecomp.fftarecomp <<<\\n'
    fi ;;
  *) : ;;
esac
exit 0
'''


def run_gate(scenario, extra_args=()):
    """Run tools/validate_android.sh with the fake adb; returns the completed
    process plus a name->bytes snapshot of the pulled evidence."""
    with tempfile.TemporaryDirectory(prefix="ffta_android_static_") as tmp:
        tmp_path = Path(tmp)
        bindir = tmp_path / "bin"
        bindir.mkdir()
        adb = bindir / "adb"
        adb.write_text(FAKE_ADB, encoding="utf-8")
        adb.chmod(0o755)
        evidence = tmp_path / "evidence"
        env = dict(os.environ)
        env["PATH"] = str(bindir) + os.pathsep + env.get("PATH", "")
        env["FADB_SCENARIO"] = scenario
        cmd = ["bash", str(REPO / "tools/validate_android.sh"),
               "--no-install", "--wait", "0", "--no-screenshot",
               "--pull-dir", str(evidence)]
        cmd.extend(extra_args)
        completed = subprocess.run(cmd, cwd=str(REPO), env=env,
                                   capture_output=True, text=True, timeout=180)
        pulled = {}
        if evidence.is_dir():
            for item in sorted(evidence.iterdir()):
                pulled[item.name] = item.read_bytes()
        return completed, pulled


def run_gate_cli(*args):
    return subprocess.run(
        ["bash", str(REPO / "tools/validate_android.sh"), *args],
        cwd=str(REPO), capture_output=True, text=True, timeout=60)


def check_gate_clean():
    completed, pulled = run_gate("clean")
    need(completed.returncode == 0,
         "clean fake-device run should pass (rc=%d): %s"
         % (completed.returncode, tail(completed)))
    out = completed.stdout
    need("GATE PASSED" in out, "no GATE PASSED line: %s" % tail(completed))
    counts = re.search(r"(\d+) passed, (\d+) failed", out)
    need(counts is not None and counts.group(2) == "0",
         "clean run reported failures: %s" % tail(completed))
    log = pulled.get("android-runtime.log", b"").decode("utf-8", "replace")
    need("cpu_backend=static-recompiled" in log,
         "evidence runtime log lacks the backend line")
    need("crash.log" in pulled, "crash.log evidence was not pulled")
    need("screenshot.png" not in pulled,
         "--no-screenshot must not produce a screenshot")
    need("recomp_master_misses_AFXE.toml.frag" not in pulled,
         "an absent miss frag must not appear in the evidence dir")


def check_gate_selfheal():
    completed, _ = run_gate("selfheal")
    need(completed.returncode == 1,
         "SELF-HEAL log should fail the gate (rc=%d)" % completed.returncode)
    out = completed.stdout
    need("GATE FAILED" in out and "dispatch-miss entries" in out,
         "expected the dispatch-miss assertion to fail: %s" % tail(completed))


def check_gate_missing_log():
    completed, _ = run_gate("missing-log")
    need(completed.returncode == 1,
         "missing runtime log should fail the gate (rc=%d)"
         % completed.returncode)
    need("app-private read failed" in completed.stdout,
         "expected the app-private read reason: %s" % tail(completed))


def check_gate_crash():
    completed, _ = run_gate("crash")
    need(completed.returncode == 1,
         "crash-buffer entry should fail the gate (rc=%d)"
         % completed.returncode)
    need("crash buffer has" in completed.stdout,
         "expected the crash assertion to fail: %s" % tail(completed))


def check_gate_setup_resumed():
    completed, _ = run_gate("setup-resumed")
    need(completed.returncode == 1,
         "setup-still-resumed should fail the gate (rc=%d)"
         % completed.returncode)
    need("the setup screen is resumed instead" in completed.stdout,
         "expected the resumed-activity assertion to fail: %s"
         % tail(completed))


def check_gate_usage():
    helped = run_gate_cli("--help")
    need(helped.returncode == 0 and "Usage:" in helped.stdout,
         "--help should print usage and exit 0: %s" % tail(helped))
    bad_wait = run_gate_cli("--wait", "nope")
    need(bad_wait.returncode == 2,
         "bad --wait should exit 2 (got %d)" % bad_wait.returncode)
    bad_flag = run_gate_cli("--bogus")
    need(bad_flag.returncode == 2,
         "unknown option should exit 2 (got %d)" % bad_flag.returncode)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

CHECKS = [
    ("identity: applicationId and gate package/activity constants",
     check_package_constants),
    ("identity: variant matches [game] short_name (3 files)", check_variant),
    ("identity: ROM sha1/size/file consistent (build.gradle, game.toml, "
     "game_android.toml)", check_rom_pins),
    ("identity: BIOS sha1 consistent (game.toml, game_android.toml, engine "
     "default)", check_bios_pins),
    ("identity: save type/size mirror the desktop config", check_save_config),
    ("payload: state.toml keeps the widescreen feature enabled",
     check_state_toml),
    ("payload: state.toml matches the preloaded catalog manifest",
     check_state_catalog),
    ("payload: mods catalog + payload dirs staged", check_payload_wiring),
    ("payload: resize_view opt-in present", check_resize_view),
    ("hygiene: no ROM/save/APK/bin artifacts tracked", check_tracked_artifacts),
    ("hygiene: android outputs stay gitignored", check_ignored_outputs),
    ("gate: clean fake-device run passes and pulls evidence", check_gate_clean),
    ("gate: SELF-HEAL runtime log fails the gate", check_gate_selfheal),
    ("gate: missing runtime log fails the gate", check_gate_missing_log),
    ("gate: crash-buffer entry fails the gate", check_gate_crash),
    ("gate: setup-still-resumed fails the gate", check_gate_setup_resumed),
    ("gate: usage contract (--help 0, bad --wait 2, unknown option 2)",
     check_gate_usage),
]


def main():
    suite = Suite()
    for name, fn in CHECKS:
        suite.run(name, fn)
    passed = 0
    for name, ok, detail in suite.results:
        print("[%s] %s%s" % ("PASS" if ok else "FAIL", name,
                             "" if ok else " — " + detail))
        if ok:
            passed += 1
    total = len(suite.results)
    if passed == total:
        print("android-static: OK (%d checks passed)" % total)
        return 0
    failing = ", ".join(name for name, ok, _ in suite.results if not ok)
    print("android-static: FAILED (%d/%d passed; failing: %s)"
          % (passed, total, failing))
    return 1


if __name__ == "__main__":
    sys.exit(main())
