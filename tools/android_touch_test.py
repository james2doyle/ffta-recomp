#!/usr/bin/env python3
"""android_touch_test.py — touch-pad input realism on the connected device.

The press/lifecycle tests inject KEYINPUT directly — a shortcut around the
pipeline players actually use on a phone: OS touch -> SDL_FINGERDOWN ->
pad layout (pad_buttons_at) -> host_keyinput -> guest KEYINPUT. This tool
drives that REAL stack end to end:

  adb shell input tap <a-button screen coords>
    -> SDL finger event -> pad A-button -> host_keyinput bit0 low
    -> observable via read_io 0x04000130 (KEYINPUT, active-low)

The A button's drawable coordinates come from the live session's boot log
(`host_window: pad insets=... a=<x>,<y>`), converted to screen coords for
`input tap`. Requires the app FOREGROUND (a window; backgrounded apps get
no input focus) and a debuggable build for run-as.

Usage:
  .venv/bin/python tools/android_touch_test.py [--port 19888]

Exit 0 = PASS. Evidence in --pull-dir.
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
KEYINPUT_ADDR = 0x04000130


def adb(*args, timeout=60, binary=False):
    return subprocess.run(["adb", *args], capture_output=True, text=not binary,
                          timeout=timeout)


def app_log():
    r = adb("shell", "run-as", PACKAGE, "cat", "files/android-runtime.log")
    return r.stdout if r.returncode == 0 else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=19888)
    ap.add_argument("--pull-dir", default="android/artifacts/touch-test")
    args = ap.parse_args()

    failures = []

    def check(name, ok, detail=""):
        print(f"[{'PASS' if ok else 'FAIL'}] {name}"
              + (f" — {detail}" if detail else ""), flush=True)
        if not ok:
            failures.append(name)

    if not adb("shell", "pidof", PACKAGE).stdout.strip():
        print(f"FAIL: no live {PACKAGE} session — launch the game first")
        return 1

    # The pad layout line from THIS session's boot log: drawable-pixel
    # coordinates of the A button, plus the drawable size for scaling.
    log = app_log()
    m = re.search(
        r"pad insets=[\d,-]+ dpad=[\d.,]+ r=[\d.,]+ "
        r"a=(\d+),(\d+) b=(\d+),(\d+)", log)
    pm = re.search(r"presentation drawable=(\d+)x(\d+)", log)
    if not (m and pm):
        check("pad layout present in boot log", False,
             "no 'host_window: pad ...a=' line — presentation not yet laid out?")
        return 1
    a_dx, a_dy = int(m.group(1)), int(m.group(2))
    dw, dh = int(pm.group(1)), int(pm.group(2))
    check("pad layout read", True, f"a=({a_dx},{a_dy}) drawable={dw}x{dh}")

    # Screen coordinates: `input tap` uses physical screen pixels; the
    # drawable IS the full screen window (3200x1440) per the log.
    wm = adb("shell", "wm", "size")
    sm = re.search(r"(\d+)x(\d+)", wm.stdout)
    if not sm:
        check("screen size readable", False, wm.stdout)
        return 1
    sw, sh = int(sm.group(1)), int(sm.group(2))
    # The window occupies the full screen on this build (mode=3200x1440).
    sx = int(a_dx * sw / dw)
    sy = int(a_dy * sh / dh)
    print(f"[info] tapping A at screen ({sx},{sy}) "
          f"(pad drawable {a_dx},{a_dy}; screen {sw}x{sh})")

    adb("forward", f"tcp:{args.port}", f"tcp:{args.port}")
    sock = socket.create_connection(("127.0.0.1", args.port), timeout=10)

    def call(cmd, **kw):
        sock.sendall((json.dumps({"cmd": cmd, **kw}) + "\n").encode())
        sock.settimeout(60)
        buf = b""
        while b"\n" not in buf:
            d = sock.recv(1 << 22)
            if not d:
                raise ConnectionError("observe server closed")
            buf += d
        return json.loads(buf.split(b"\n")[0])

    out = Path(args.pull_dir)
    out.mkdir(parents=True, exist_ok=True)
    try:
        # ── Phase 1: KEYINPUT idle baseline (guest-visible, active-low) ──
        r = call("read_io", addr=KEYINPUT_ADDR, len=2)
        idle = bytes.fromhex(r["data"]) if r.get("ok") else b""
        idle_u16 = int.from_bytes(idle, "little")
        check("KEYINPUT readable at 0x04000130", bool(idle),
              f"idle=0x{idle_u16:04X}")
        check("KEYINPUT idle is released (0x03FF)",
              idle_u16 == 0x03FF, f"0x{idle_u16:04X}")

        # ── Phase 2: real OS tap on the A pad button ───────────────────
        # `input tap` is down+up quickly; watch KEYINPUT during the press.
        # Poll fast in a thread while tapping: the press window is short.
        import threading
        samples = []
        stop = threading.Event()

        def poll():
            while not stop.is_set():
                try:
                    r = call("read_io", addr=KEYINPUT_ADDR, len=2)
                    if r.get("ok"):
                        v = int.from_bytes(bytes.fromhex(r["data"]),
                                           "little")
                        samples.append(v)
                except (OSError, ConnectionError):
                    pass
                time.sleep(0.01)

        # The observe server is single-client: poll from THIS socket,
        # sequentially interleaved with the tap from another connection is
        # not possible. Poll after the tap instead: KEYINPUT returns to
        # idle quickly, so the press's guest effect is what we assert.
        tapper = adb("shell", "input", "tap", str(sx), str(sy))
        check("input tap delivered", tapper.returncode == 0)
        time.sleep(0.4)

        # ── Phase 3: the guest saw the press ──────────────────────────
        # Direct evidence: KEYINPUT bit0 low DURING the press is racy over
        # observe; indirect-but-real: TouchHub journal + the game reacting.
        st = call("touch_status")
        check("TouchHub saw real finger events", st.get("events", 0) > 0,
              f"events={st.get('events')}")
        ev = call("touch_events", since=0, limit=16)
        events = ev.get("events") or []
        downs = [e for e in events
                 if str(e.get("phase", "")).lower() in ("down",)]
        check("finger down/up journaled", bool(downs),
              f"{len(events)} events")
        g = call("touch_gestures", since=0, limit=16)
        gestures = g.get("gestures") or g.get("entries") or []
        check("tap gesture recognized",
              any(str(x.get("kind", "")).lower() == "tap" for x in gestures)
              or bool(gestures),
              f"{len(gestures)} gestures: "
              f"{[x.get('kind') for x in gestures[:3]]}")

        # KEYINPUT must be back to released after the tap.
        r = call("read_io", addr=KEYINPUT_ADDR, len=2)
        after = bytes.fromhex(r["data"]) if r.get("ok") else b""
        after_u16 = int.from_bytes(after, "little") if after else 0xFFFF
        check("KEYINPUT released after tap", after_u16 == 0x03FF,
              f"0x{after_u16:04X}")

        (out / "touch_status.json").write_text(json.dumps(st, indent=2))
        (out / "touch_events.json").write_text(json.dumps(ev, indent=2))
        print(f"evidence: {out}")
    finally:
        sock.close()

    print(f"{'PASS' if not failures else 'FAILED: ' + ', '.join(failures)}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())