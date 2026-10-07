#!/usr/bin/env python3
"""Capture the save-driver read-call sequence (pc=0x08141BA0) on both engines.

Native breakpoint mechanics: set_break_pc arms a yield; on hit -> clear (0),
step_inst past, re-arm. Oracle: emu_run_until_pc chunks + emu_step_inst.
Inputs from the trace are applied stickily by frame on both sides.
"""
import os, pathlib, shutil, socket, subprocess, sys, tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "tools"))
from framediff import Client

REPO = pathlib.Path("/home/james/Git/ffta-recompiled")
BIOS = REPO / "gbarecomp/bios/gba_bios.bin"
ROM = REPO / "game.gba"
NATIVE = REPO / "build/FFTARecomp"
ORACLE = REPO / "gbarecomp/build/oracle/gbarecomp_oracle"
SAVE = REPO / "saves/found_save.mGBA.sav"
TRACE = REPO / "saves/trace_prev_20261007_114607.csv"
CALL_PC = 0x08141BA0
WARM = 850
LIMIT = 1300

if len(sys.argv) > 3:
    SAVE = pathlib.Path(sys.argv[2])
    WARM = int(sys.argv[3])
if len(sys.argv) > 4:
    LIMIT = int(sys.argv[4])
if len(sys.argv) > 5:
    CALL_PC = int(sys.argv[5], 0)

trace = {}
for ln in TRACE.read_text().splitlines():
    ln = ln.strip()
    if not ln or ln.startswith("#"):
        continue
    f, v = ln.split(",", 1)
    trace[int(f)] = int(v.strip(), 16)

events = sorted(trace.items())


def key_at(frame: int) -> int | None:
    best = None
    for f, v in events:
        if f <= frame:
            best = v
        else:
            break
    return best


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def native_seq():
    env = {k: v for k, v in os.environ.items() if not k.startswith("GBARECOMP_")}
    port = free_port()
    proc = subprocess.Popen(
        [str(NATIVE), "--bios", str(BIOS), "--rom", str(ROM), "--no-window",
         "--save-path", str(SAVE), "--tcp", str(port)],
        cwd=str(REPO), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
    c = Client(port, timeout=120)
    out = []
    try:
        frame = 0
        while frame < WARM:
            f = frame + 1
            if f in trace:
                c.call(cmd="set_keyinput", value=trace[f])
            r = c.call(cmd="run_frames", n=1)
            frame = int(r.get("frame", frame + 1))
        c.call(cmd="set_break_pc", value=CALL_PC)
        guard = 0
        while frame < LIMIT and len(out) < 300 and guard < 6000:
            guard += 1
            v = key_at(frame + 1)
            if v is not None:
                c.call(cmd="set_keyinput", value=v)
            try:
                r = c.call(cmd="run_frames", n=1)
            except Exception:
                print("  (native stalled / connection lost)", flush=True)
                break
            g = c.call(cmd="registers")
            pc = int(g.get("r15", 0)) & ~1
            if pc == CALL_PC:
                out.append((frame, int(g["r0"]), int(g["r1"]), int(g["r2"]),
                            int(g.get("r3", 0)), int(g.get("r13", 0)),
                            int(g.get("r14", 0)), int(g.get("r4", 0)),
                            int(g.get("r5", 0)), int(g.get("r6", 0)),
                            int(g.get("r7", 0))))
                c.call(cmd="set_break_pc", value=0)      # clear
                c.call(cmd="step_inst")                  # past the call
                c.call(cmd="set_break_pc", value=CALL_PC)  # re-arm
                continue
            fr = int(r.get("frame", frame))
            if fr > frame:
                frame = fr
    finally:
        try:
            c.close()
        except Exception:
            pass
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    return out


def oracle_seq():
    tmp = tempfile.mkdtemp(prefix="probe_orc_")
    (pathlib.Path(tmp) / "game.gba").symlink_to(ROM)
    shutil.copy(str(SAVE), str(pathlib.Path(tmp) / "game.sav"))
    port = free_port()
    proc = subprocess.Popen(
        [str(ORACLE), "--bios", str(BIOS), "--rom", str(pathlib.Path(tmp) / "game.gba"),
         "--port", str(port)],
        cwd=str(REPO / "gbarecomp"), stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL)
    c = Client(port, timeout=120)
    out = []
    try:
        frame = 0
        while frame < WARM:
            f = frame + 1
            if f in trace:
                c.call(cmd="emu_set_keys", keys=(~trace[f]) & 0x03FF)
            c.call(cmd="emu_step")
            frame = f
        guard = 0
        while frame < LIMIT and len(out) < 300 and guard < 3000:
            guard += 1
            v = key_at(frame + 1)
            if v is not None:
                c.call(cmd="emu_set_keys", keys=(~v) & 0x03FF)
            r = c.call(cmd="emu_run_until_pc", target=CALL_PC, max_steps=300000)
            if r.get("found"):
                g = c.call(cmd="emu_registers")
                out.append((frame, int(g["r0"]), int(g["r1"]), int(g["r2"]),
                            int(g.get("r3", 0)), int(g.get("r13", 0)),
                            int(g.get("r14", 0)), int(g.get("r4", 0)),
                            int(g.get("r5", 0)), int(g.get("r6", 0)),
                            int(g.get("r7", 0))))
                c.call(cmd="emu_step_inst")
                continue
            frame = int(c.call(cmd="emu_vblank_count").get("vblank", frame + 1))
    finally:
        try:
            c.close()
        except Exception:
            pass
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)
    return out


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "both"
    if which in ("native", "both"):
        seq = native_seq()
        print(f"=== NATIVE calls ({len(seq)}) ===", flush=True)
        for row in seq:
            fr, r0, r1, r2, r3, sp, lr = row[:7]
            r4, r5, r6, r7 = row[7:11]
            print(f"  f{fr}: src={r0:#010x} dst={r1:#010x} n={r2:#05x} "
                  f"r3={r3:#010x} sp={sp:#010x} lr={lr:#010x} | "
                  f"r4={r4:#x} r5={r5:#010x} r6={r6:#x} r7={r7:#010x}", flush=True)
    if which in ("oracle", "both"):
        seq = oracle_seq()
        print(f"=== ORACLE calls ({len(seq)}) ===", flush=True)
        for row in seq:
            fr, r0, r1, r2, r3, sp, lr = row[:7]
            r4, r5, r6, r7 = row[7:11]
            print(f"  f{fr}: src={r0:#010x} dst={r1:#010x} n={r2:#05x} "
                  f"r3={r3:#010x} sp={sp:#010x} lr={lr:#010x} | "
                  f"r4={r4:#x} r5={r5:#010x} r6={r6:#x} r7={r7:#010x}", flush=True)
