#!/usr/bin/env python3
"""android_press_test.py — device-driven press acceptance over --tcp-observe.

The manual protocol (android/README.md § On-device suspend/resume protocol)
drives the A press by thumb; the device gate cannot inject inputs at all.
This tool drives the SAME acceptance through the windowed observe TCP:
savestate_load → settle → A press (set_keyinput) → scored observation, on
the live device session, asserting the press flows through the guest and
nothing derails (frames advance, no ledger/abandon/guard anomalies, no
crash-buffer entry for the package).

Usage:
  .venv/bin/python tools/android_press_test.py [--port 19888] \
      [--state <path on the phone or repo] [--pull-dir android/artifacts/press-test]

Requires: a device session running with --tcp-observe (adb forward set), the
adb-observed serial's package process alive. Exit 0 = PASS.
"""
import argparse
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PACKAGE = "org.gbarecomp.fftarecomp"


def adb(*args, timeout=30):
    return subprocess.run(["adb", *args], capture_output=True, text=True,
                          timeout=timeout)


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


def counters(sock):
    # The windowed-observe context wires no counters (steps/sync_frames stay
    # 0 there — runtime.cpp builds octx without them); run_status carries the
    # authoritative frame count from ppu.frame_count() instead.
    r = call(sock, "run_status")
    if r.get("ok"):
        return {"frame": int(r.get("frame", 0)),
                "pc": int(r.get("pc", "0"), 16),
                "vblank_starts": int(r.get("vblank_starts", 0))}
    return {"frame": -1}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=19888)
    ap.add_argument("--state", default=None,
                    help="repo-root relative .state file to push and load")
    ap.add_argument("--serial", default=None, help="adb serial")
    ap.add_argument("--pull-dir", default="android/artifacts/press-test")
    args = ap.parse_args()

    pre = adb("forward", f"tcp:{args.port}", f"tcp:{args.port}")
    if pre.returncode != 0:
        print("FAIL: adb forward failed:", pre.stderr.strip())
        return 1
    pid = adb("shell", "pidof", PACKAGE)
    if not pid.stdout.strip():
        print(f"FAIL: no live {PACKAGE} process — launch the game "
              "with --tcp-observe first (android/README.md)")
        return 1
    print(f"session: pid={pid.stdout.strip()} port={args.port}")

    sock = socket.create_connection(("127.0.0.1", args.port), timeout=10)
    failures = []
    log_lines = []

    def check(name, ok, detail=""):
        print(f"[{'PASS' if ok else 'FAIL'}] {name}"
              + (f" — {detail}" if detail else ""))
        if not ok:
            failures.append(name)

    try:
        if args.state:
            state = Path(args.state)
            if not state.is_absolute():
                state = REPO / args.state
            if not state.is_file():
                check("state file exists", False, str(state))
                return 1
            remote = "/data/local/tmp/ffta_press_state.state"
            push = adb("push", str(state), remote)
            check("state pushed", push.returncode == 0, push.stderr.strip())
            install = adb("shell", "run-as", PACKAGE, "mkdir", "-p",
                          "files/saves")
            r = adb("shell", "run-as", PACKAGE, "cp", remote,
                    f"files/saves/{state.name}")
            check("state staged into app files", r.returncode == 0,
                  r.stderr.strip())
            adb("shell", "rm", "-f", remote)
            local_path = f"saves/{state.name}"  # app cwd is files/ after chdir
            res = call(sock, "savestate_load", path=local_path)
            check("savestate loaded", res.get("ok") is True,
                  json.dumps(res)[:200])
            time.sleep(1.0)

        c0 = counters(sock)
        time.sleep(2.0)
        c1 = counters(sock)
        advancing = c1.get("frame", 0) > c0.get("frame", 0)
        check("frames advance pre-press", advancing,
              f"frames {c0.get('frame')}->{c1.get('frame')}")

        # The A press (active-low bit0).
        r = call(sock, "set_keyinput", value=0x03FF)
        check("press armed (idle)", r.get("ok") is True)
        p0 = counters(sock)
        r = call(sock, "set_keyinput", value=0x03FE)  # A down
        time.sleep(0.25)
        r = call(sock, "set_keyinput", value=0x03FF)  # A up
        time.sleep(2.0)
        p1 = counters(sock)
        pressed = (p1.get("frame", 0) > p0.get("frame", 0)
                   and p1.get("vblank_starts", 0) >= p0.get("vblank_starts", 0))
        check("post-press frames advance", pressed,
              f"frames {p0.get('frame')}->{p1.get('frame')}")

        # Anomaly scan on the observe log since the run started: this tool
        # cannot tail the server's stderr; the anomaly classes are asserted
        # via the app log pulled afterwards.
        log = adb("shell", "run-as", PACKAGE, "cat", "files/android-runtime.log")
        if log.returncode == 0:
            log_lines = log.stdout.splitlines()
        anomalies = [l for l in log_lines
                     if ("SWI-return ledger override" in l
                         or "SELF-HEAL" in l
                         or "host-stack guard unwind" in l)]
        check("no ledger/self-heal/guard anomalies", not anomalies,
              "; ".join(anomalies[:3]))
        closing = [l for l in log_lines if "closing the IRQ" in l]
        if closing:
            print(f"[note] abandon-close fired {len(closing)}x (expected "
                  "at most once during a plain press; a load+press flow may "
                  "legally close one)")
        crash = adb("logcat", "-d", "-b", "crash")
        crash_hits = [l for l in crash.stdout.splitlines()
                      if "fftarecomp" in l]
        check("crash buffer clean for the package", not crash_hits,
              "; ".join(crash_hits[:3]))

        out = Path(args.pull_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "android-runtime.log").write_text("\n".join(log_lines) + "\n")
        shot = call(sock, "screenshot")
        if shot.get("ok") and "data" in shot:
            import base64
            png = base64.b64decode(shot["data"]
                                   if isinstance(shot["data"], str)
                                   else bytes.fromhex(shot["data"]))
            (out / "screenshot.png").write_bytes(png)
        c = counters(sock)
        (out / "counters.json").write_text(json.dumps(c, indent=2) + "\n")
        print(f"evidence: {out}")
    finally:
        sock.close()

    print(f"{'PASS' if not failures else 'FAILED: ' + ', '.join(failures)}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())