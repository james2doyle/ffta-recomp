#!/usr/bin/env python3
"""android_lifecycle_test.py — the OS suspend/kill/relaunch lifecycle gate.

The engine's mobile contract (runtime.cpp): on background/terminate the app
flushes the battery save, writes a suspend state + a .suspend.pending marker;
if the OS kills the process in the background the marker survives, and the
next launch (resume_suspend_state_on_launch, main.cpp) auto-resumes exactly
where the player left. This is mobile-only machinery — it CANNOT exist on
desktop — and it shares the suspend-save flow with the historical worst bug
class (the suspend→A phantom chain), so it belongs on the device gate list.

Driven entirely over adb on a live device: play → KEYCODE_HOME (background) →
assert flush+state+marker → force-stop (the OS kill) → relaunch via
AUTOSTART → assert resume + frames advance → marker gone. Evidence pulled
into --pull-dir.

Usage:
  .venv/bin/python tools/android_lifecycle_test.py [--pull-dir android/artifacts/lifecycle-test]

Requires: adb device with the app installed (debuggable — private build
carries the ROM), the game NOT currently mid-suspend. Exit 0 = PASS.
"""
import argparse
import json
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PACKAGE = "org.gbarecomp.fftarecomp"
SETUP_ACTIVITY = "org.gbarecomp.GbaSetupActivity"
AUTOSTART_EXTRA = "org.gbarecomp.extra.AUTOSTART"
ROM_BASE = "files/roms/ffta_usa"
OBSERVE_PORT = 19888


def adb(*args, timeout=60, binary=False):
    return subprocess.run(["adb", *args],
                          capture_output=True, text=not binary,
                          timeout=timeout)


def app_log():
    r = adb("shell", "run-as", PACKAGE, "cat", "files/android-runtime.log")
    return r.stdout if r.returncode == 0 else ""


def file_exists(remote_rel):
    # run-as ls prints the name on stdout for a present file; empty otherwise.
    r = adb("shell", "run-as", PACKAGE, "ls", remote_rel)
    return r.returncode == 0 and bool(r.stdout.strip())


def call(sock, cmd, **kw):
    sock.sendall((json.dumps({"cmd": cmd, **kw}) + "\n").encode())
    sock.settimeout(60)
    buf = b""
    while b"\n" not in buf:
        d = sock.recv(1 << 22)
        if not d:
            raise ConnectionError("observe server closed the connection")
        buf += d
    return json.loads(buf.split(b"\n")[0])


def frames(sock):
    r = call(sock, "run_status")
    if not r.get("ok"):
        return -1
    return int(r.get("frame", 0))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pull-dir", default="android/artifacts/lifecycle-test")
    ap.add_argument("--port", type=int, default=OBSERVE_PORT)
    args = ap.parse_args()

    failures = []

    def check(name, ok, detail=""):
        print(f"[{'PASS' if ok else 'FAIL'}] {name}"
              + (f" — {detail}" if detail else ""), flush=True)
        if not ok:
            failures.append(name)

    # ── Phase 0: preconditions ─────────────────────────────────────────
    pid = adb("shell", "pidof", PACKAGE)
    if not pid.stdout.strip():
        print(f"FAIL: no live {PACKAGE} session — launch the game first")
        return 1
    # A stale suspend marker would make the launch-under-test resume an old
    # session: clear the precondition explicitly.
    if file_exists(ROM_BASE + ".suspend.pending"):
        check("stale suspend marker cleared", False,
              "clear it before testing (let the app foreground once)")
        return 1

    adb("forward", f"tcp:{args.port}", f"tcp:{args.port}")
    sock = socket.create_connection(("127.0.0.1", args.port), timeout=10)
    out = Path(args.pull_dir)
    out.mkdir(parents=True, exist_ok=True)

    try:
        # ── Phase 1: playing baseline ────────────────────────────────
        f0 = frames(sock)
        check("session live pre-background", f0 >= 0, f"frame={f0}")

        # ── Phase 2: OS background (HOME) ───────────────────────────
        adb("shell", "input", "keyevent", "KEYCODE_HOME")
        deadline = time.time() + 15
        bg_line = ""
        while time.time() < deadline:
            log = app_log()
            m = re.search(r"(?:entering background|terminating): "
                          r"save=(\w+) suspend_state=(\S+)", log)
            if m:
                bg_line = m.group(0)
                break
            time.sleep(0.5)
        check("background: save flushed + suspend state written",
              "save=flushed" in bg_line and "suspend_state=" in bg_line
              and ".suspend.state" in bg_line,
              bg_line or "no background log line within 15 s")
        check("background: suspend state file exists",
              file_exists(ROM_BASE + ".suspend.state"))
        check("background: suspend marker exists",
              file_exists(ROM_BASE + ".suspend.pending"))
        (out / "background_android-runtime.log").write_text(app_log())

        # ── Phase 3: the OS kill (force-stop) ─────────────────────────
        adb("shell", "am", "force-stop", PACKAGE)
        time.sleep(2.0)
        pid2 = adb("shell", "pidof", PACKAGE)
        check("kill: process dead", not pid2.stdout.strip())
        # The marker SURVIVES the kill — that is the whole resume contract.
        check("kill: suspend marker survived",
              file_exists(ROM_BASE + ".suspend.pending"))
        save_before = adb("exec-out", "run-as", PACKAGE, "cat",
                          "files/saves/ffta_us.sav", binary=True)
        save_bytes = len(save_before.stdout) \
            if save_before.returncode == 0 else -1
        check("kill: battery save present", save_bytes > 0,
              f"{save_bytes} bytes")

        # ── Phase 4: relaunch (AUTOSTART) ─────────────────────────────
        r = adb("shell", "am", "start", "-n",
                f"{PACKAGE}/{SETUP_ACTIVITY}",
                "--ez", AUTOSTART_EXTRA, "true")
        check("relaunch: am start ok", r.returncode == 0, r.stderr.strip())
        deadline = time.time() + 40
        resumed_line = ""
        while time.time() < deadline:
            log = app_log()
            m = re.search(r"suspend_resumed path=\"[^\"]+\" frame=(\d+)", log)
            if m:
                resumed_line = m.group(0)
                break
            time.sleep(0.5)
        check("relaunch: suspend_resumed logged",
              bool(resumed_line), resumed_line or "no resume line within 40 s")
        marker_cleared = False
        deadline = time.time() + 10
        while time.time() < deadline:
            marker_cleared = not file_exists(ROM_BASE + ".suspend.pending")
            if marker_cleared:
                break
            time.sleep(0.5)
        check("relaunch: marker cleared after resume", marker_cleared)

        # ── Phase 5: post-resume liveness ─────────────────────────────
        # The kill closed the observe socket; the relaunched process listens
        # on the same device port. Re-forward and reconnect with a FRESH
        # socket per attempt.
        sock.close()
        sock = None
        f1 = -1
        deadline = time.time() + 30
        while time.time() < deadline and f1 < 0:
            try:
                adb("forward", f"tcp:{args.port}", f"tcp:{args.port}")
                sock = socket.create_connection(("127.0.0.1", args.port),
                                                timeout=10)
                f1 = frames(sock)
                sock.close()
            except (OSError, ConnectionError):
                sock = None
            time.sleep(2.0)
        time.sleep(3.0)
        f2 = -1
        try:
            adb("forward", f"tcp:{args.port}", f"tcp:{args.port}")
            sock = socket.create_connection(("127.0.0.1", args.port), timeout=10)
            f2 = frames(sock)
        except (OSError, ConnectionError):
            sock = None
        check("post-resume: observe reconnected + frames advance",
              f1 >= 0 and f2 > f1, f"frames {f1}->{f2}")
        log_now = app_log()
        anomalies = [l for l in log_now.splitlines()
                     if ("SWI-return ledger override" in l
                         or "SELF-HEAL" in l
                         or "host-stack guard unwind" in l)]
        check("post-resume: no ledger/self-heal/guard anomalies",
              not anomalies, "; ".join(anomalies[:3]))
        crash = adb("logcat", "-d", "-b", "crash")
        crash_hits = [l for l in crash.stdout.splitlines()
                      if "fftarecomp" in l]
        check("post-resume: crash buffer clean", not crash_hits,
              "; ".join(crash_hits[:3]))
        (out / "post-resume_android-runtime.log").write_text(log_now)
        if sock is not None:
            shot = call(sock, "screenshot")
        if sock is not None and shot.get("ok") and "data" in shot:
            import base64
            raw = shot["data"]
            png = base64.b64decode(raw) if isinstance(raw, str) \
                else bytes.fromhex(raw)
            (out / "post-resume_screenshot.png").write_bytes(png)
        print(f"evidence: {out}")
    finally:
        if sock is not None:
            sock.close()

    print(f"{'PASS' if not failures else 'FAILED: ' + ', '.join(failures)}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())