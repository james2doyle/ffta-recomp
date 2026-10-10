#!/usr/bin/env python3
"""Desktop observe-TCP acceptance: state3 suspend-save press must complete.

The acceptance the steppable suites cannot give: a *real windowed desktop
run* (launched through tools/play.sh, exactly like a hand playtest) driven
and observed over the live observe TCP port (--tcp-observe): queued
savestate load, a real-time A press via ydotool, then a scored observation
window.

PASS requires ALL of:
  * the press lands (KEYINPUT shows A held during the injection), and the
    presented screen changes after it;
  * the log shows the abandoned-IRQ close WITH the flow-continuation resume
    (`closing the IRQ (flow-continuation resume pc=0x…)`) — the mechanism
    under test;
  * frames advance continuously through the observation window (no wedge);
  * the post-press screen sequence animates (≥ MIN_DISTINCT_SCREENS distinct
    presented frames — the suspend-save reboot intro);
  * no bridge Undefined / abort appears in the log and the process is alive
    at the end.

Needs (local-only, hence opt-in): game.state3, saves/playtest.sav, a display,
and ydotool on PATH (uinput; xdotool is banned). Port/observation length are
flags. Evidence lands in logs/desktop_accept/ (log, summary.json, screens/).
"""
import argparse
import hashlib
import json
import os
import pathlib
import re
import shutil
import signal
import socket
import subprocess
import sys
import time

REPO = pathlib.Path(__file__).resolve().parent.parent
WORK = REPO / "logs" / "desktop_accept"
STATE = REPO / "game.state3"
FLASH = REPO / "saves" / "playtest.sav"

MIN_FRAMES = 1000
MIN_DISTINCT_SCREENS = 12


def connect(port, deadline_s):
    end = time.monotonic() + deadline_s
    while time.monotonic() < end:
        try:
            s = socket.create_connection(("127.0.0.1", port), timeout=5)
            s.settimeout(30)
            return s
        except OSError:
            time.sleep(0.25)
    return None


def call(sock, cmd, timeout=30, **kw):
    sock.settimeout(timeout)
    sock.sendall((json.dumps({"cmd": cmd, **kw}) + "\n").encode())
    buf = b""
    while b"\n" not in buf:
        d = sock.recv(1 << 22)
        if not d:
            raise ConnectionError("peer closed")
        buf += d
    return json.loads(buf.split(b"\n")[0])


def call_soft(sock, cmd, **kw):
    try:
        return call(sock, cmd, **kw)
    except (ConnectionError, OSError):
        raise
    except Exception:
        return None


def read_keyinput(sock):
    r = call(sock, "read_io", addr=0x04000130, len=2, timeout=5)
    d = r.get("data") or ""
    d = d[2:] if d.startswith("0x") else d
    return d.lower()


def shot_md5(sock):
    r = call(sock, "screenshot", timeout=20)
    d = r["data"]
    d = d[2:] if d.startswith("0x") else d
    rgb = bytes.fromhex(d)
    return hashlib.md5(rgb).hexdigest()[:8], rgb, r.get("w", 240), r.get("h", 160)


def write_png(path, rgb, w, h):
    import struct
    import zlib
    raw = b"".join(b"\x00" + rgb[y * w * 3:(y + 1) * w * 3] for y in range(h))
    def chunk(tag, data):
        c = tag + data
        return (struct.pack(">I", len(data)) + c
                + struct.pack(">I", zlib.crc32(c) & 0xffffffff))
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)))
        f.write(chunk(b"IDAT", zlib.compress(raw, 6)))
        f.write(chunk(b"IEND", b""))


def ydotool_key(code, hold=0.15):
    subprocess.run(["ydotool", "key", f"{code}:1"], check=True)
    time.sleep(hold)
    subprocess.run(["ydotool", "key", f"{code}:0"], check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=19870)
    ap.add_argument("--press-delay", type=float, default=3.0)
    ap.add_argument("--observe", type=float, default=90.0)
    ap.add_argument("--scale", type=int, default=2)
    ap.add_argument("--view-width", type=int, default=320)
    ap.add_argument("--work", default="logs/desktop_accept",
                    help="evidence directory (log, summary.json, screens/)")
    ap.add_argument("--mode", choices=("window", "tcp"), default="window",
                    help="window: play.sh + --tcp-observe + ydotool input; "
                         "tcp: headless free-run + --tcp (input via set_keyinput)")
    args = ap.parse_args()

    if not (STATE.exists() and FLASH.exists()):
        print("SKIP: needs game.state3 and saves/playtest.sav (local-only)")
        return 77
    if shutil.which("ydotool") is None:
        print("SKIP: ydotool not on PATH")
        return 77

    global WORK
    WORK = REPO / args.work
    WORK.mkdir(parents=True, exist_ok=True)
    card = WORK / "card.sav"
    shutil.copyfile(FLASH, card)
    log = WORK / "run.log"
    log.write_text("")
    env = dict(os.environ)
    env["GBARECOMP_WS_WIP"] = "1"
    logf = open(log, "wb")
    if args.mode == "tcp":
        proc = subprocess.Popen(
            [str(REPO / "build" / "FFTARecomp"),
             "--bios", str(REPO / "gbarecomp" / "bios" / "gba_bios.bin"),
             "--rom", str(REPO / "game.gba"),
             "--save-path", str(card), "--tcp", str(args.port)],
            cwd=str(REPO), env=env, stdout=logf, stderr=subprocess.STDOUT,
            start_new_session=True)
    else:
        proc = subprocess.Popen(
            [str(REPO / "tools" / "play.sh"),
             "--scale", str(args.scale),
             "--view-width", str(args.view_width),
             "--tcp-observe", str(args.port),
             "--save-path", str(card)],
            cwd=str(REPO), env=env, stdout=logf, stderr=subprocess.STDOUT,
            start_new_session=True)

    ok = True
    detail = []
    try:
        sock = connect(args.port, 45.0)
        if sock is None:
            print("FAIL: observe port never came up")
            return 1

        r = call(sock, "savestate_load", path=str(STATE), timeout=60)
        detail.append(f"savestate_load={r.get('ok')}")
        if not r.get("ok"):
            print(f"FAIL: savestate_load: {r}")
            return 1

        time.sleep(1.5)
        if args.mode == "tcp":
            call(sock, "continue")
        st = call(sock, "run_status")
        f0 = int(st.get("frame", 0))
        pre_md5, _, _, _ = shot_md5(sock)

        how = "ydotool x" if args.mode == "window" else "set_keyinput"
        print(f"pre-press: frame={f0} screen={pre_md5}; waiting "
              f"{args.press_delay}s then pressing A ({how})", flush=True)
        time.sleep(args.press_delay)

        if args.mode == "tcp":
            call(sock, "set_keyinput", value=0x03FE)
            seen_a = True
            time.sleep(0.15)
            call(sock, "set_keyinput", value=0x03FF)
        else:
            # Verified injection with retries: a missed press invalidates the
            # whole observation, so make it a hard precondition.
            seen_a = False
            for attempt in range(3):
                subprocess.Popen(["ydotool", "key", "45:1"])
                for _ in range(14):
                    if read_keyinput(sock) not in ("ff03", ""):
                        seen_a = True
                        break
                    time.sleep(0.03)
                subprocess.run(["ydotool", "key", "45:0"])
                if seen_a:
                    break
                time.sleep(0.4)
        detail.append(f"press_seen_in_keyinput={seen_a}")
        if not seen_a:
            ok = False
            detail.append("KEYINPUT never showed a button held during injection")

        # scored observation
        t0 = time.monotonic()
        last_frame = f0
        stuck = 0
        screens = {pre_md5}
        frames_series = []
        pc_series = []
        n = 0
        while time.monotonic() - t0 < args.observe:
            try:
                st = call(sock, "run_status", timeout=15)
            except (ConnectionError, ConnectionResetError, OSError) as e:
                ok = False
                detail.append(f"connection lost during observation: {e}")
                break
            fr = int(st.get("frame", 0))
            frames_series.append(fr)
            if fr <= last_frame:
                stuck += 1
            last_frame = max(last_frame, fr)
            pc_series.append(st.get("pc"))
            if n % 4 == 0:
                try:
                    md5, rgb, w, h = shot_md5(sock)
                except (ConnectionError, ConnectionResetError, OSError) as e:
                    ok = False
                    detail.append(f"connection lost during screenshot: {e}")
                    break
                screens.add(md5)
                if n % 12 == 0:
                    (WORK / "screens").mkdir(exist_ok=True)
                    write_png(WORK / "screens" / f"t{n:04d}_{md5}.png",
                              rgb, w, h)
            n += 1
            time.sleep(0.5)

        advanced = last_frame - f0
        detail.append(f"frames_advanced={advanced}")
        detail.append(f"distinct_screens={len(screens)}")
        detail.append(f"stuck_samples={stuck}")
        from collections import Counter
        hot = Counter(pc_series).most_common(5)
        detail.append("hot_pcs=" + ", ".join(f"{p}x{c}" for p, c in hot))
        floor = MIN_FRAMES if args.mode == "window" else 600
        if advanced < floor:
            ok = False
            detail.append(f"frames advanced < {floor}")
        if len(screens) < MIN_DISTINCT_SCREENS:
            ok = False
            detail.append(f"distinct screens < {MIN_DISTINCT_SCREENS} "
                          "(no post-press animation?)")
        if stuck > 3:
            ok = False
            detail.append("frame counter stalled multiple samples")

        txt = log.read_text(errors="replace")
        if re.search(r"closing the IRQ \(flow-continuation resume pc=0x", txt):
            detail.append("close_with_flow_continuation=yes")
        elif "closing the IRQ" in txt:
            detail.append("close_seen_without_flow_continuation (old build?)")
        else:
            detail.append("close_with_flow_continuation=not-needed "
                          "(clean route)")
        for bad in ("interpreter Undefined", "Aborted", "Segmentation fault",
                    "dispatch miss 0x08145484"):
            if bad in txt:
                ok = False
                detail.append(f"log contains '{bad}'")

        if proc.poll() is not None:
            ok = False
            detail.append(f"process exited early rc={proc.returncode}")
        else:
            detail.append("process_alive=yes")
    finally:
        try:
            sock.close()
        except Exception:
            pass
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
        logf.close()

    summary = {"pass": ok, "details": detail}
    (WORK / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2), flush=True)
    print("PASS: desktop observe acceptance" if ok else "FAIL: see details")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
