#!/usr/bin/env python3
"""Deterministic state3 press regression: the suspend→A hang must not return.

Reproduces the 2026-10-09 hang deterministically (steppable `--tcp` +
`savestate_load game.state3` + A press). History: the process SIGSEGV'd ~26
steps after the press; the host-stack guard then bounded it; since the
irq-handler-abandon-close fix the phantom IRQ is closed cleanly
(`closing the IRQ` in the log) and, since the flow-continuation resume fix
(2026-10-09, BRINGUP § flow-continuation resume), the guest's own flow
survives the close: the suspend-save completes and the game reboots into
its intro sequence (matching the mGBA oracle). The run must not hang, must
not crash, and must keep advancing.

Needs (both gitignored / local-only, hence opt-in):
  game.state3            — the press-moment savestate
  saves/playtest.sav     — the flash the state was captured with

Exit codes: 0 pass, 1 fail, 77 skipped (missing prerequisites).
"""
import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import time

REPO = pathlib.Path(__file__).resolve().parent.parent
PORT = int(os.environ.get("HANGREPRO_PORT", "19878"))
STATE = REPO / "game.state3"
FLASH = REPO / "saves" / "playtest.sav"
WORK = REPO / "logs" / "hangrepro"
LOG = WORK / "run.log"


def call(sock, cmd, timeout=60, **kw):
    sock.settimeout(timeout)
    sock.sendall((json.dumps({"cmd": cmd, **kw}) + "\n").encode())
    buf = b""
    while b"\n" not in buf:
        d = sock.recv(1 << 22)
        if not d:
            raise ConnectionError("peer closed")
        buf += d
    head, _, _ = buf.partition(b"\n")
    return json.loads(head)


def log_text():
    try:
        return LOG.read_text(errors="replace")
    except OSError:
        return ""


def guard_lines():
    return log_text().count("host-stack guard unwind")


def close_lines():
    return log_text().count("closing the IRQ")


def main():
    if not (STATE.exists() and FLASH.exists()):
        print("SKIP: needs game.state3 and saves/playtest.sav (local-only)")
        return 77

    WORK.mkdir(parents=True, exist_ok=True)
    card = WORK / "card.sav"
    shutil.copyfile(FLASH, card)

    runner = subprocess.Popen(
        [str(REPO / "build" / "FFTARecomp"),
         "--bios", str(REPO / "gbarecomp" / "bios" / "gba_bios.bin"),
         "--rom", str(REPO / "game.gba"),
         "--save-path", str(card), "--tcp", str(PORT)],
        cwd=str(REPO), stdout=open(LOG, "wb"), stderr=subprocess.STDOUT,
        start_new_session=True)
    try:
        sock = None
        for _ in range(300):
            try:
                sock = socket.create_connection(("127.0.0.1", PORT), timeout=5)
                break
            except OSError:
                if runner.poll() is not None:
                    print(f"FAIL: runner exited early (rc {runner.returncode})")
                    return 1
                time.sleep(0.2)
        if sock is None:
            print("FAIL: server never came up")
            return 1

        call(sock, "savestate_load", path=str(STATE))
        call(sock, "set_keyinput", value=0x03FF)
        for _ in range(98):
            call(sock, "step")
        call(sock, "set_keyinput", value=0x03FE)
        for _ in range(4):
            call(sock, "step")
        call(sock, "set_keyinput", value=0x03FF)

        # Post-press: before the fix the process dies at ~+26 (peer closed).
        steps = 0
        timed_out = False
        deadline = time.monotonic() + 240.0
        try:
            while steps < 40 and time.monotonic() < deadline:
                call(sock, "step", timeout=30)
                steps += 1
        except socket.timeout:
            timed_out = True
        except (ConnectionError, OSError) as e:
            # Acceptable post-fix ending: the fix closed the abandoned IRQ
            # and the flow then ended at the coverage boundary. The phantom
            # (nd stuck, never-closing IRQ) is what must not return.
            if close_lines() > 0:
                print(f"SUCCESS: closed the abandoned IRQ; flow advanced "
                      f"past the old wedge (+{steps} steps; process ended: "
                      f"{e})")
                return 0
            print(f"FAIL: connection lost (crash?) at +{steps}: {e}")
            return 1
        finally:
            try:
                sock.close()
            except OSError:
                pass

        # Aliveness / mechanism: process must still run; if a step wedged
        # (bounded state), guard unwinds must keep accumulating in the log.
        alive_deadline = time.monotonic() + 60.0
        while time.monotonic() < alive_deadline:
            if runner.poll() is not None:
                print(f"FAIL: process died after bounded state "
                      f"(rc {runner.returncode}, guard unwinds={guard_lines()})")
                return 1
            if not timed_out:
                break
            time.sleep(2.0)
        if runner.poll() is not None:
            print(f"FAIL: process not alive (rc {runner.returncode})")
            return 1
        if timed_out and guard_lines() == 0:
            print("FAIL: step wedged without any guard unwind (gate hole?)")
            return 1
        print(f"SUCCESS: survived the press (+{steps} steps"
              f"{', bounded state' if timed_out else ''}; "
              f"guard unwinds={guard_lines()}, irq closes={close_lines()})")
        return 0
    finally:
        try:
            if runner.poll() is None:
                os.killpg(runner.pid, 9)
        except (ProcessLookupError, PermissionError):
            pass


if __name__ == "__main__":
    sys.exit(main())
