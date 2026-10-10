#!/usr/bin/env bash
# validate_android.sh — device acceptance gate for the FFTARecomp Android port.
#
# Flow: device sanity -> optional APK install -> am force-stop -> crash-buffer
# clear (best effort) -> launch GbaSetupActivity with the AUTOSTART extra ->
# settle -> assertions -> artifact pull -> summary. Exit code is 0 only when
# every assertion passes (a single "GATE PASSED" line ends a good run).
#
# Assertions ([PASS] / [FAIL] lines):
#   1. the package process is running (pidof)
#   2. GbaGameActivity is the resumed activity (dumpsys activity activities)
#   3. files/android-runtime.log is readable via run-as and reports
#      cpu_backend=static-recompiled
#   4. the runtime log has no dispatch misses (no "SELF-HEAL" line and no
#      "missing static coverage" line)
#   5. Android's crash buffer has no entries mentioning "fftarecomp". Only
#      that substring counts: the crash buffer is shared with other apps and
#      other gbarecomp games crash under the same libmain.so name, so a bare
#      Fatal signal line must not be attributed to this package.
#
# Evidence lands in --pull-dir (default android/artifacts/last-run, which is
# gitignored): android-runtime.log (captured while asserting), the on-device
# miss frag + coverage JSON (absent/empty is legitimate when there are no
# misses), crash.log, and a screenshot. Native stdout does not reach logcat,
# so app-private files are read binary-safe via `adb exec-out run-as ... cat`;
# a release (non-debuggable) build fails assertions 3 and 4 with the run-as
# reason. Requires: bash, adb, coreutils/sed/grep. The gate script itself is
# self-tested device-free by `tools/android_static_check.py` (fake `adb`; the
# `android-static` suite in `tools/check.py`, run by CI tier 1).
#
# Usage: tools/validate_android.sh [options]      (see --help for details)
#   tools/validate_android.sh
#   tools/validate_android.sh --serial ABC123 --wait 60
#   tools/validate_android.sh --apk android/app/build/outputs/apk/debug/app-debug.apk
#   tools/validate_android.sh --no-install --no-screenshot

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."   # repo root: default relative paths stay stable

# ---------------------------------------------------------------------------
# Fixed app identity (engine's shared gbarecomp Android shell)
# ---------------------------------------------------------------------------
PACKAGE="org.gbarecomp.fftarecomp"
SETUP_ACTIVITY="org.gbarecomp.GbaSetupActivity"
GAME_ACTIVITY="org.gbarecomp.GbaGameActivity"
AUTOSTART_EXTRA="org.gbarecomp.extra.AUTOSTART"

# App-private files (paths are relative to the app's files/ dir).
RUNTIME_LOG="android-runtime.log"
MISS_FRAG="recomp_master_misses_AFXE.toml.frag"
COVERAGE_JSON="recomp_coverage_AFXE.json"

# ---------------------------------------------------------------------------
# Defaults / options
# ---------------------------------------------------------------------------
DEBUG_APK_DIR="android/app/build/outputs/apk/debug"
WAIT_SECONDS=40
PULL_DIR="android/artifacts/last-run"
APK=""
SERIAL=""
DO_INSTALL=1
DO_SCREENSHOT=1

# ---------------------------------------------------------------------------
# Output / accounting helpers
# ---------------------------------------------------------------------------
usage() {
  cat <<'EOF'
Usage: tools/validate_android.sh [options]

Device acceptance gate for the FFTARecomp Android port: installs an APK,
launches the game through the shared gbarecomp setup activity (AUTOSTART),
asserts process / activity / runtime-log / crash-buffer health, and pulls
evidence files into the pull directory.

Options (paths may be relative to the repo root):
  --apk <path>      APK for `adb install -r`. Default: the newest debug APK
                    under android/app/build/outputs/apk/debug, preferring
                    *-PRIVATE-rom-included.apk builds.
  --serial <s>      adb serial (`adb -s`). Default: the only attached
                    device; fails when several devices are attached.
  --wait <seconds>  Settle time between launch and assertions (default 40).
  --pull-dir <dir>  Evidence directory (default android/artifacts/last-run).
  --no-install      Skip `adb install -r`; gate the installed build.
  --no-screenshot   Do not capture a screenshot.
  --help, -h        Show this help.

Exit codes: 0 = GATE PASSED; 1 = failed check or setup error (device,
install, launch); 2 = usage error.
EOF
}

die_usage() { printf 'error: %s\n' "$1" >&2; usage >&2; exit 2; }

section() { printf '\n== %s ==\n' "$1"; }
info()    { printf '[info] %s\n' "$1"; }
note()    { printf '[note] %s\n' "$1"; }

PASSES=0
FAILURES=0
FAILURE_LIST=""
pass_check() {
  PASSES=$((PASSES + 1))
  printf '[PASS] %s\n' "$1"
}
fail_check() {
  FAILURES=$((FAILURES + 1))
  FAILURE_LIST="${FAILURE_LIST}  - $1"$'\n'
  printf '[FAIL] %s\n' "$1"
}
verdict() {
  if [ "$FAILURES" -eq 0 ]; then
    printf 'GATE PASSED\n'
    exit 0
  fi
  printf 'failures:\n%s' "$FAILURE_LIST"
  printf 'GATE FAILED (%d failures)\n' "$FAILURES"
  exit 1
}
# Setup errors (device/install/launch) abort through the same accounting, so
# every exit path ends with the GATE PASSED / GATE FAILED contract.
abort_gate() { fail_check "$1"; verdict; }

# Collapse arbitrary command output to one trimmed line (for messages).
squeeze() { printf '%s' "$1" | tr '\n' ' ' | tr -s '[:space:]' ' ' | sed -e 's/^ //' -e 's/ $//'; }
bytes_of() { wc -c <"$1" | tr -d '[:space:]'; }

# First N lines of a file matching ERE $2 / text matching fixed string $2,
# joined for one-line failure details. Never aborts under errexit (grep
# exits 1 when nothing matches).
sample_ere()   { grep -aE "$2" "$1" 2>/dev/null | sed -n "1,${3}p" | cut -c1-200 | paste -sd'|' - || true; }
sample_fixed() { printf '%s\n' "$1" | grep -aF "$2" 2>/dev/null | sed -n "1,${3}p" | cut -c1-200 | paste -sd'|' - || true; }

# getprop with the selected device (empty output on failure).
prop() { "${ADB[@]}" shell getprop "$1" 2>/dev/null | tr -d '\r' | sed -n '1p' || true; }

# Newest debug APK, preferring private ROM-embedded builds. Empty if none.
# (Globs are intentional; `-nt` picks the newest without relying on ls.)
discover_apk() {
  local dir="$DEBUG_APK_DIR" newest="" f candidates=()
  [ -d "$dir" ] || return 0
  candidates=("$dir"/*PRIVATE-rom-included.apk)
  [ -e "${candidates[0]}" ] || candidates=("$dir"/*.apk)
  [ -e "${candidates[0]}" ] || return 0
  for f in "${candidates[@]}"; do
    if [ -z "$newest" ] || [ "$f" -nt "$newest" ]; then
      newest="$f"
    fi
  done
  printf '%s' "$newest"
}

# App-private reads go through run-as; a debuggable build is required.
# FETCH_ERR receives the remote stderr; the return status is adb/cat's exit
# status when adb propagates it, so callers must also check that the local
# file is non-empty.
FETCH_ERR=""
fetch_private() { # <path relative to the app files/ dir> <local path>
  local err rc=0
  err=$(mktemp)
  "${ADB[@]}" exec-out run-as "$PACKAGE" cat "$1" >"$2" 2>"$err" || rc=$?
  FETCH_ERR=$(squeeze "$(sed -n '1,3p' "$err" 2>/dev/null || true)")
  rm -f "$err"
  # exec-out folds the remote stderr into the output stream: a missing file
  # arrives as a "cat: <path>: No such file or directory" line with a zero
  # exit status. Treat that as a failed fetch, never as file content.
  if [ "$rc" -eq 0 ] && head -c 5 "$2" 2>/dev/null | grep -q '^cat: '; then
    rc=1
    [ -n "$FETCH_ERR" ] || FETCH_ERR=$(squeeze "$(head -c 200 "$2" 2>/dev/null || true)")
    : >"$2"
  fi
  return "$rc"
}

# PNG magic (89 50 4E 47 0D 0A 1A 0A); screenshots must be real images.
is_png() {
  local magic
  magic=$(head -c 8 "$1" 2>/dev/null | od -An -tx1 | tr -d ' \n' | tr 'A-F' 'a-f' || true)
  case "$magic" in
    89504e470d0a1a0a) return 0 ;;
    *) return 1 ;;
  esac
}

# exec-out first (no on-device temp); fall back to screencap-to-file + pull
# for adb/device combos that mangle the exec-out stream.
capture_screenshot() { # <local png path>
  local dest="$1" remote="/data/local/tmp/ffta_validate_screenshot.png"
  rm -f "$dest"
  if "${ADB[@]}" exec-out screencap -p >"$dest" 2>/dev/null && [ -s "$dest" ] && is_png "$dest"; then
    return 0
  fi
  if "${ADB[@]}" shell screencap -p "$remote" >/dev/null 2>&1 \
     && "${ADB[@]}" pull "$remote" "$dest" >/dev/null 2>&1 \
     && [ -s "$dest" ] && is_png "$dest"; then
    "${ADB[@]}" shell rm -f "$remote" >/dev/null 2>&1 || true
    return 0
  fi
  "${ADB[@]}" shell rm -f "$remote" >/dev/null 2>&1 || true
  rm -f "$dest"
  return 1
}

# One-line view of what `adb devices` showed, for error messages.
attached_summary() {
  printf '%s\n' "$devices_list" \
    | grep -E '^[^[:space:]]+[[:space:]]+(device|unauthorized|offline|no permissions)' \
    | tr '\n' ';' | sed -e 's/;*$//' -e 's/;/; /g' -e 's/[[:space:]]\{1,\}/ /g' || true
}

# ---------------------------------------------------------------------------
# Arguments
# ---------------------------------------------------------------------------
while [ "$#" -gt 0 ]; do
  case "$1" in
    --apk)
      [ "$#" -ge 2 ] || die_usage "--apk requires a path"
      APK="$2"; shift 2 ;;
    --serial)
      [ "$#" -ge 2 ] || die_usage "--serial requires a value"
      SERIAL="$2"; shift 2 ;;
    --wait)
      [ "$#" -ge 2 ] || die_usage "--wait requires a number of seconds"
      WAIT_SECONDS="$2"; shift 2 ;;
    --pull-dir)
      [ "$#" -ge 2 ] || die_usage "--pull-dir requires a path"
      PULL_DIR="$2"; shift 2 ;;
    --no-install)    DO_INSTALL=0; shift ;;
    --no-screenshot) DO_SCREENSHOT=0; shift ;;
    --help|-h)       usage; exit 0 ;;
    --)              shift; break ;;
    -*)              die_usage "unknown option: $1" ;;
    *)               die_usage "unexpected argument: $1" ;;
  esac
done
[ "$#" -eq 0 ] || die_usage "unexpected argument: $1"

case "$WAIT_SECONDS" in
  ''|*[!0-9]*) die_usage "--wait must be a whole number of seconds (got: $WAIT_SECONDS)" ;;
esac

# ---------------------------------------------------------------------------
# Local preflight
# ---------------------------------------------------------------------------
if ! mkdir -p "$PULL_DIR" 2>/dev/null; then
  printf 'error: cannot create pull dir: %s\n' "$PULL_DIR" >&2
  exit 2
fi
# Replace evidence from any previous run (only these known names are touched).
rm -f "$PULL_DIR/$RUNTIME_LOG" \
      "$PULL_DIR/$MISS_FRAG" \
      "$PULL_DIR/$COVERAGE_JSON" \
      "$PULL_DIR/crash.log" \
      "$PULL_DIR/screenshot.png" || true

if ! command -v adb >/dev/null 2>&1; then
  printf 'error: adb not found in PATH\n' >&2
  exit 2
fi

if [ "$DO_INSTALL" -eq 1 ]; then
  if [ -n "$APK" ]; then
    [ -f "$APK" ] || { printf 'error: APK not found: %s\n' "$APK" >&2; exit 2; }
  else
    APK=$(discover_apk)
    if [ -z "$APK" ]; then
      printf 'error: no APK found under %s (build first, pass --apk, or use --no-install)\n' "$DEBUG_APK_DIR" >&2
      exit 2
    fi
  fi
elif [ -n "$APK" ]; then
  note "--no-install: ignoring --apk $APK and gating the installed build"
fi

# ---------------------------------------------------------------------------
# Device sanity
# ---------------------------------------------------------------------------
section "device"

if ! devices_out=$(adb devices 2>&1); then
  abort_gate "adb devices failed: $(squeeze "$devices_out")"
fi
devices_list=$(printf '%s\n' "$devices_out" | sed -n '/^List of devices attached$/,$p' | sed -n '2,$p')

ADB=(adb)
DEVICE_SERIAL=""
if [ -n "$SERIAL" ]; then
  state=$(squeeze "$(adb -s "$SERIAL" get-state 2>&1 || true)")
  case "$state" in
    device)
      ADB=(adb -s "$SERIAL")
      DEVICE_SERIAL="$SERIAL" ;;
    unauthorized)
      abort_gate "device $SERIAL is unauthorized — unlock it and accept the USB debugging prompt" ;;
    offline)
      abort_gate "device $SERIAL is offline — reconnect the USB cable (or adb reconnect) and retry" ;;
    *)
      abort_gate "device $SERIAL is not usable (adb get-state: ${state:-unknown}); attached: $(attached_summary)" ;;
  esac
else
  ready_lines=$(printf '%s\n' "$devices_list" | grep -E '[[:space:]]device$' || true)
  ready_count=$(printf '%s\n' "$ready_lines" | grep -cE '[[:space:]]device$' || true)
  case "$ready_count" in
    1)
      DEVICE_SERIAL=$(printf '%s\n' "$ready_lines" | sed -n '1p' | sed 's/[[:space:]].*//')
      ADB=(adb -s "$DEVICE_SERIAL") ;;
    0)
      if [ -z "$devices_list" ]; then
        abort_gate "no adb devices visible (adb output: $(squeeze "$devices_out"))"
      fi
      abort_gate "no adb device in 'device' state (attached: $(attached_summary)); unlock the phone, accept the USB debugging prompt, and retry" ;;
    *)
      abort_gate "$ready_count adb devices in 'device' state — pass --serial <serial> to pick one (attached: $(attached_summary))" ;;
  esac
fi

MODEL=$(squeeze "$(prop ro.product.model)")
ANDROID_REL=$(squeeze "$(prop ro.build.version.release)")
ANDROID_SDK=$(squeeze "$(prop ro.build.version.sdk)")
DEVICE_ABI=$(squeeze "$(prop ro.product.cpu.abi)")
DEVICE_DESC="${MODEL:-unknown model} [serial $DEVICE_SERIAL, Android ${ANDROID_REL:-?} / API ${ANDROID_SDK:-?}, ${DEVICE_ABI:-?}]"
info "device: $DEVICE_DESC"
info "package: $PACKAGE"

# ---------------------------------------------------------------------------
# Install (optional)
# ---------------------------------------------------------------------------
section "install"
if [ "$DO_INSTALL" -eq 0 ]; then
  APK_STATUS="not installed (--no-install) — gated the build already on the device"
  info "install skipped (--no-install)"
else
  info "installing $APK (adb install -r) ..."
  if install_out=$("${ADB[@]}" install -r "$APK" 2>&1); then
    case "$install_out" in
      *Failure*) abort_gate "adb install reported a failure: $(squeeze "$install_out")" ;;
    esac
    APK_STATUS="$APK (installed)"
    info "install ok: $(squeeze "$install_out")"
  else
    abort_gate "adb install failed: $(squeeze "$install_out")"
  fi
fi

# ---------------------------------------------------------------------------
# Launch
# ---------------------------------------------------------------------------
section "launch"
if ! "${ADB[@]}" shell am force-stop "$PACKAGE" >/dev/null 2>&1; then
  note "am force-stop $PACKAGE returned non-zero (continuing)"
fi

CRASH_CLEAR_OK=0
if "${ADB[@]}" logcat -b crash -c >/dev/null 2>&1; then
  CRASH_CLEAR_OK=1
  info "cleared the crash buffer (adb logcat -b crash -c)"
else
  note "could not clear the crash buffer — the crash scan may include pre-run entries (non-fatal)"
fi

if launch_out=$("${ADB[@]}" shell am start -n "$PACKAGE/$SETUP_ACTIVITY" --ez "$AUTOSTART_EXTRA" true 2>&1); then
  case "$launch_out" in
    *Error:*) abort_gate "am start reported an error: $(squeeze "$launch_out")" ;;
  esac
  info "started $PACKAGE/$SETUP_ACTIVITY with $AUTOSTART_EXTRA=true"
else
  abort_gate "am start failed: $(squeeze "$launch_out")"
fi

# ---------------------------------------------------------------------------
# Wait
# ---------------------------------------------------------------------------
section "wait"
info "waiting ${WAIT_SECONDS}s for the game to settle ..."
sleep "$WAIT_SECONDS"

# ---------------------------------------------------------------------------
# Assertions
# ---------------------------------------------------------------------------
section "assertions"

# 1. process running
pids=$("${ADB[@]}" shell pidof "$PACKAGE" 2>/dev/null | tr -d '\r' | sed -n '1p' || true)
pids=$(squeeze "$pids")
if [ -n "$pids" ]; then
  pass_check "process running (pidof $PACKAGE: $pids)"
else
  fail_check "process running (pidof $PACKAGE returned nothing — crashed or never started?)"
fi

# 2. resumed activity
acts=$("${ADB[@]}" shell dumpsys activity activities 2>/dev/null || true)
resumed_line=$(printf '%s\n' "$acts" | grep -F "$PACKAGE/$GAME_ACTIVITY" | grep -E '(^|[[:space:]])(top|m)?ResumedActivity[=:]' | sed -n '1p' || true)
if [ -n "$resumed_line" ]; then
  pass_check "resumed activity is $GAME_ACTIVITY"
else
  setup_line=$(printf '%s\n' "$acts" | grep -F "$PACKAGE/$SETUP_ACTIVITY" | grep -E '(^|[[:space:]])(top|m)?ResumedActivity[=:]' | sed -n '1p' || true)
  if [ -n "$setup_line" ]; then
    fail_check "resumed activity is $GAME_ACTIVITY (the setup screen is resumed instead — ROM/BIOS not ready, or the game failed to start)"
  else
    any_resumed=$(printf '%s\n' "$acts" | grep -cE '(^|[[:space:]])(top|m)?ResumedActivity[=:]' || true)
    any_resumed=$(squeeze "$any_resumed")
    if [ "${any_resumed:-0}" -eq 0 ]; then
      fail_check "resumed activity is $GAME_ACTIVITY (no ResumedActivity lines in the dumpsys output — device dump format unexpected?)"
    else
      pkg_line=$(printf '%s\n' "$acts" | grep -E '(^|[[:space:]])(top|m)?ResumedActivity[=:]' | grep -F "$PACKAGE" | sed -n '1p' || true)
      if [ -n "$pkg_line" ]; then
        fail_check "resumed activity is $GAME_ACTIVITY (resumed: $(squeeze "$pkg_line"))"
      else
        fail_check "resumed activity is $GAME_ACTIVITY (dumpsys has resumed activities, but none for $PACKAGE)"
      fi
    fi
  fi
fi

# 3./4. runtime log (app-private: only reachable through run-as)
LOG_LOCAL="$PULL_DIR/$RUNTIME_LOG"
LOG_FETCHED=0
RUN_AS_REASON=""
if fetch_private "files/$RUNTIME_LOG" "$LOG_LOCAL" && [ -s "$LOG_LOCAL" ]; then
  LOG_FETCHED=1
else
  if [ -n "$FETCH_ERR" ]; then
    RUN_AS_REASON="app-private read failed: $FETCH_ERR (a debug/private build is required for run-as)"
  elif [ ! -s "$LOG_LOCAL" ]; then
    RUN_AS_REASON="runtime log missing or empty"
  else
    RUN_AS_REASON="app-private read failed"
  fi
  rm -f "$LOG_LOCAL"
fi

if [ "$LOG_FETCHED" -eq 1 ]; then
  if grep -aq 'cpu_backend=static-recompiled' "$LOG_LOCAL"; then
    pass_check "runtime log readable ($(bytes_of "$LOG_LOCAL") bytes) and reports cpu_backend=static-recompiled"
  else
    backend=$(grep -ao 'cpu_backend=[^[:space:]]*' "$LOG_LOCAL" | tr -d '\r' | sed -n '1p' || true)
    fail_check "runtime log readable, but cpu_backend=static-recompiled is missing (found: ${backend:-no cpu_backend line})"
  fi
else
  fail_check "runtime log readable and reporting cpu_backend=static-recompiled (${RUN_AS_REASON})"
fi

if [ "$LOG_FETCHED" -eq 1 ]; then
  miss_count=$(grep -acE 'SELF-HEAL|missing static coverage' "$LOG_LOCAL" || true)
  miss_count=$(squeeze "$miss_count")
  if [ "${miss_count:-0}" -eq 0 ]; then
    pass_check "runtime log has no SELF-HEAL / missing static coverage entries"
  else
    detail=$(sample_ere "$LOG_LOCAL" 'SELF-HEAL|missing static coverage' 2)
    fail_check "runtime log has dispatch-miss entries ($miss_count line(s)): $detail"
  fi
else
  fail_check "runtime log has no dispatch-miss entries (not verifiable: ${RUN_AS_REASON})"
fi

# 5. crash buffer (only lines mentioning this package count — see header)
crash_err=$(mktemp)
CRASH_OK=0
CRASH_ERR=""
if crash_dump=$("${ADB[@]}" logcat -d -b crash 2>"$crash_err"); then
  CRASH_OK=1
else
  CRASH_ERR=$(squeeze "$(sed -n '1,3p' "$crash_err" 2>/dev/null || true)")
fi
rm -f "$crash_err"

CRASH_SAVED=0
if [ "$CRASH_OK" -eq 1 ]; then
  if [ -n "$crash_dump" ]; then
    printf '%s\n' "$crash_dump" > "$PULL_DIR/crash.log"
  else
    : > "$PULL_DIR/crash.log"
  fi
  CRASH_SAVED=1
  crash_hits=$(printf '%s\n' "$crash_dump" | grep -acF 'fftarecomp' || true)
  crash_hits=$(squeeze "$crash_hits")
  if [ "${crash_hits:-0}" -eq 0 ]; then
    pass_check "crash buffer has no fftarecomp entries"
  else
    detail=$(sample_fixed "$crash_dump" 'fftarecomp' 3)
    if [ "$CRASH_CLEAR_OK" -eq 1 ]; then
      fail_check "crash buffer has $crash_hits line(s) mentioning fftarecomp: $detail"
    else
      fail_check "crash buffer has $crash_hits line(s) mentioning fftarecomp (buffer was not cleared pre-launch — some entries may predate this run): $detail"
    fi
  fi
else
  fail_check "crash buffer readable (adb logcat -b crash failed: ${CRASH_ERR:-unknown})"
fi

# ---------------------------------------------------------------------------
# Artifact pull (best effort; --pull-dir is gitignored by default)
# ---------------------------------------------------------------------------
section "artifacts ($PULL_DIR)"
if [ "$LOG_FETCHED" -eq 1 ]; then
  printf '  %-38s %s\n' "$RUNTIME_LOG" "saved ($(bytes_of "$LOG_LOCAL") bytes; captured during assertions)"
else
  printf '  %-38s %s\n' "$RUNTIME_LOG" "not saved (${RUN_AS_REASON:-fetch failed})"
fi

for name in "$MISS_FRAG" "$COVERAGE_JSON"; do
  dest="$PULL_DIR/$name"
  FETCH_ERR=""
  if fetch_private "files/$name" "$dest"; then
    if [ -s "$dest" ]; then
      printf '  %-38s %s\n' "$name" "saved ($(bytes_of "$dest") bytes)"
      if [ "$name" = "$MISS_FRAG" ]; then
        note "non-empty miss frag pulled — review it via the healing loop (tests/README.md)"
      fi
    else
      printf '  %-38s %s\n' "$name" "absent/empty (expected when there are no misses)"
    fi
  else
    rm -f "$dest"
    printf '  %-38s %s\n' "$name" "not present (${FETCH_ERR:-run-as cat: no such file})"
  fi
done

if [ "$CRASH_SAVED" -eq 1 ]; then
  printf '  %-38s %s\n' "crash.log" "saved ($(bytes_of "$PULL_DIR/crash.log") bytes)"
else
  printf '  %-38s %s\n' "crash.log" "not saved (crash buffer unreadable)"
fi

if [ "$DO_SCREENSHOT" -eq 1 ]; then
  if capture_screenshot "$PULL_DIR/screenshot.png"; then
    printf '  %-38s %s\n' "screenshot.png" "saved ($(bytes_of "$PULL_DIR/screenshot.png") bytes)"
  else
    printf '  %-38s %s\n' "screenshot.png" "not saved (screencap failed)"
  fi
else
  printf '  %-38s %s\n' "screenshot.png" "skipped (--no-screenshot)"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
section "summary"
printf 'device:   %s\n' "$DEVICE_DESC"
printf 'apk:      %s\n' "$APK_STATUS"
printf 'wait:     %ss\n' "$WAIT_SECONDS"
printf 'checks:   %d passed, %d failed\n' "$PASSES" "$FAILURES"
printf 'evidence: %s\n' "$PULL_DIR"
verdict
