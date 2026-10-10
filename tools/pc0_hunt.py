#!/usr/bin/env python3
"""pc0_hunt.py — catch the anomalous pc=0 transfer in the windowed press flow.

Per iteration: launch the windowed game on the full TCP surface with the
instruction ring armed, load game.state3, set a breakpoint at pc=0, press A
(ydotool), and poll run_status. When the flow reaches pc=0 the break parks it
BEFORE executing, so fp_save captures a ring whose last record is the
transferring instruction (full r0-r15 + cpsr). Saves evidence under
logs/desktop_accept/pc0/iterN/ and stops on the first hit.
"""
import json, os, pathlib, shutil, signal, socket, subprocess, time

REPO = str(pathlib.Path(__file__).resolve().parent.parent)
STATE = f"{REPO}/game.state3"
CARD_SRC = f"{REPO}/saves/playtest.sav"

def call(sock, cmd, timeout=30, **kw):
    sock.sendall((json.dumps({"cmd": cmd, **kw}) + "\n").encode())
    sock.settimeout(timeout)
    buf = b""
    while b"\n" not in buf:
        d = sock.recv(1 << 22)
        if not d:
            raise ConnectionError("peer closed")
        buf += d
    return json.loads(buf.split(b"\n")[0])

def main():
    for it in range(1, 17):
        work = f"{REPO}/logs/desktop_accept/pc0/iter{it}"
        os.makedirs(work, exist_ok=True)
        shutil.copyfile(CARD_SRC, f"{work}/card.sav")
        port = 19930 + it
        env = dict(os.environ)
        env["GBARECOMP_WS_WIP"] = "1"
        env["GBARECOMP_INSN_TRACE"] = "1"
        env["GBARECOMP_BREAK_FP"] = "/tmp/pc0_fp.bin"
        env["GBARECOMP_BRIDGE_ENTRY_FP"] = "/tmp/pc0_entry_fp.bin"
        logf = open(f"{work}/run.log", "wb")
        proc = subprocess.Popen(
            [f"{REPO}/build/FFTARecomp",
             "--bios", f"{REPO}/gbarecomp/bios/gba_bios.bin",
             "--rom", f"{REPO}/game.gba",
             "--save-path", f"{work}/card.sav",
             "--scale", "2", "--view-width", "320",
             "--tcp-observe", str(port)],
            cwd=REPO, env=env, stdout=logf, stderr=subprocess.STDOUT,
            start_new_session=True)
        hit = False
        try:
            sock = None
            for _ in range(50):
                try:
                    sock = socket.create_connection(("127.0.0.1", port), timeout=2)
                    break
                except OSError:
                    time.sleep(0.2)
            if sock is None:
                print(f"iter{it}: no port"); continue
            call(sock, "savestate_load", timeout=60, path=STATE)
            call(sock, "set_break_pc", value=0)
            time.sleep(3.0)
            subprocess.Popen(["ydotool", "key", "45:1"])
            time.sleep(0.15)
            subprocess.run(["ydotool", "key", "45:0"])
            t0 = time.time()
            while time.time() - t0 < 90:
                try:
                    rs = call(sock, "run_status", timeout=10)
                except (ConnectionError, OSError) as e:
                    print(f"iter{it}: conn lost at t={time.time()-t0:.1f}s: {e}")
                    tail = subprocess.run(
                        ["grep", "-c", "0x00000", f"{work}/run.log"],
                        capture_output=True, text=True).stdout.strip()
                    break
                pc = str(rs.get("pc", ""))
                if pc.lower() in ("0x0", "0x00000000") or rs.get("parked"):
                    print(f"iter{it}: PARKED pc={pc} cpsr={rs.get('cpsr')} "
                          f"t={time.time()-t0:.1f}s", flush=True)
                    time.sleep(2)
                    for src, dst in (("/tmp/pc0_fp.bin", "pc0_fp.bin"),
                                     ("/tmp/pc0_entry_fp.bin", "entry_fp.bin")):
                        try:
                            shutil.copyfile(src, f"{work}/{dst}")
                            print(f"iter{it}: copied {dst}", flush=True)
                        except FileNotFoundError:
                            print(f"iter{it}: {src} missing", flush=True)
                    # stack + sp-adjacent IWRAM for context
                    for a in (0x03007D80, 0x03007E00, 0x03007F00, 0x03007FE0):
                        try:
                            m = call(sock, "read_iwram", addr=a, len=16)
                            print(f"  iw[{a:#x}] {m.get('data')}", flush=True)
                        except Exception:
                            pass
                    hit = True
                    break
                time.sleep(0.03)
            else:
                print(f"iter{it}: no park in 90s")
        finally:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass
            logf.close()
            time.sleep(1)
        if hit:
            print(f"PCOHIT iter{it}")
            return 0
    print("PCO-NOHIT")
    return 1

if __name__ == "__main__":
    raise SystemExit(main())
