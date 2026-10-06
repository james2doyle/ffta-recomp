#!/usr/bin/env python3
"""framediff.py — native-vs-oracle state comparison for FFTA (Phase 5 harness).

Companion to gbarecomp/oracle/diff_cart.py, hardened for the phase offset
discovered on 2026-10-06:

  * The recomp runner stops at VBlank-START (scanline 159->160) *before* the
    VBlank IRQ handler runs; mGBA's runFrame stops at the VBlank wrap
    (scanline 227->0) *after* the handler ran. Same-index region reads are
    therefore one IRQ-handler apart, which shows up as small standing
    differences (e.g. the BIOS IntrWait flag 0x03007FF8, a per-frame
    countdown at 0x03003B30).
  * Delta mode cancels the phase offset: it compares per-frame *changes*
    (old->new per byte) instead of absolute bytes. A byte whose change set
    and transformation match on both sides is phase noise; a change that
    exists on one side only, or transforms differently, is a candidate
    divergence. Standing value offsets are reported separately as info.

Usage (run from anywhere; spawns both processes itself):
    python3 tools/framediff.py --lo 4 --hi 24                 # scan frames
    python3 tools/framediff.py --lo 4 --hi 24 --region iwram  # one region

Exit code 0 = no divergences found in the scanned window, 1 = divergence.
Output artifacts (JSON report + optional PNGs later) go to --outdir
(default /tmp/ffta_framediff) — never inside the repo (frames are ROM-derived).
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import socket
import subprocess
import sys
import time

REPO = pathlib.Path(__file__).resolve().parent.parent
GBARECOMP = REPO / "gbarecomp"

# name -> (native cmd, oracle cmd, base, len)
REGIONS = {
    "iwram": ("read_iwram", "read_emu_iwram", 0x03000000, 0x8000),
    "ewram": ("read_ewram", "read_emu_ewram", 0x02000000, 0x40000),
    "oam":   ("read_oam",   "read_emu_oam",   0x07000000, 0x400),
    "pal":   ("read_pal",   "read_emu_pal",   0x05000000, 0x400),
    "vram":  ("read_vram",  "read_emu_vram",  0x06000000, 0x18000),
}


class Client:
    def __init__(self, port: int, timeout: float = 30.0):
        deadline = time.time() + timeout
        self.sock = None
        last: Exception | None = None
        while time.time() < deadline:
            try:
                self.sock = socket.create_connection(("127.0.0.1", port), timeout=2.0)
                break
            except OSError as e:
                last = e
                time.sleep(0.2)
        if self.sock is None:
            raise RuntimeError(f"cannot reach 127.0.0.1:{port}: {last}")
        self.sock.settimeout(600.0)
        self.buf = b""

    def call(self, **kw) -> dict:
        self.sock.sendall(json.dumps(kw).encode() + b"\n")
        while b"\n" not in self.buf:
            chunk = self.sock.recv(1 << 20)
            if not chunk:
                raise RuntimeError("peer closed the connection")
            self.buf += chunk
        line, _, self.buf = self.buf.partition(b"\n")
        return json.loads(line.decode())

    def read(self, cmd: str, base: int, ln: int) -> bytes:
        return bytes.fromhex(self.call(cmd=cmd, addr=base, len=ln)["data"])

    def close(self) -> None:
        for fn in (lambda: self.call(cmd="quit"), self.sock.close):
            try:
                fn()
            except Exception:
                pass


def advance(n: Client, o: Client, by: int) -> None:
    if by <= 0:
        return
    n.call(cmd="run_frames", n=by)
    for _ in range(by):
        o.call(cmd="emu_step_to_vblank")


def snapshot(n: Client, o: Client, region: str) -> tuple[bytes, bytes]:
    ncmd, ocmd, base, ln = REGIONS[region]
    return n.read(ncmd, base, ln), o.read(ocmd, base, ln)


def delta(a: bytes, b: bytes) -> dict[int, tuple[int, int]]:
    return {i: (a[i], b[i]) for i in range(min(len(a), len(b))) if a[i] != b[i]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rom", default=str(REPO / "game.gba"))
    ap.add_argument("--bios", default=str(GBARECOMP / "bios" / "gba_bios.bin"))
    ap.add_argument("--native-exe", default=str(REPO / "build" / "FFTARecomp"))
    ap.add_argument("--oracle", default=str(GBARECOMP / "build/oracle/gbarecomp_oracle"))
    ap.add_argument("--lo", type=int, default=4)
    ap.add_argument("--hi", type=int, default=60)
    ap.add_argument("--region", action="append", default=None,
                    help="region name(s); default iwram")
    ap.add_argument("--native-port", type=int, default=19842)
    ap.add_argument("--oracle-port", type=int, default=19843)
    ap.add_argument("--outdir", default="/tmp/ffta_framediff")
    a = ap.parse_args()

    regions = a.region or ["iwram"]
    outdir = pathlib.Path(a.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    procs: list[subprocess.Popen] = []
    n = o = None
    report: dict = {"lo": a.lo, "hi": a.hi, "regions": regions,
                    "mismatches": [], "offsets_info": [], "clean_frames": 0}
    try:
        nenv = os.environ.copy()
        nenv["GBARECOMP_STRICT_STATIC"] = "1"  # no self-heal; deterministic
        procs.append(subprocess.Popen(
            [a.native_exe, "--bios", a.bios, "--rom", a.rom, "--tcp", str(a.native_port)],
            cwd=str(REPO), env=nenv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        procs.append(subprocess.Popen(
            [a.oracle, "--bios", a.bios, "--rom", a.rom, "--port", str(a.oracle_port)],
            cwd=str(GBARECOMP), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        n = Client(a.native_port)
        o = Client(a.oracle_port)

        advance(n, o, a.lo)
        state = {}
        for r in regions:
            na, oo = snapshot(n, o, r)
            state[r] = ([na], [oo])

        for frame in range(a.lo + 1, a.hi + 1):
            advance(n, o, 1)
            frame_bad = False
            for r in regions:
                na, oo = snapshot(n, o, r)
                state[r][0].append(na)
                state[r][1].append(oo)
                dn = delta(state[r][0][-2], na)
                do = delta(state[r][1][-2], oo)
                for k in sorted(set(dn) | set(do)):
                    if k not in dn or k not in do:
                        frame_bad = True
                        side = "native-only" if k not in do else "oracle-only"
                        (old, new) = dn.get(k, do.get(k))
                        report["mismatches"].append(
                            {"frame": frame, "region": r,
                             "addr": REGIONS[r][2] + k, "kind": side,
                             "change": [old, new]})
                    elif dn[k] != do[k]:
                        # same address changed on both sides; equal step(-1/+1/etc)?
                        same_step = (dn[k][1] - dn[k][0]) == (do[k][1] - do[k][0])
                        item = {"frame": frame, "region": r,
                                "addr": REGIONS[r][2] + k,
                                "native": list(dn[k]), "oracle": list(do[k]),
                                "kind": "step-mismatch" if not same_step else "standing-offset"}
                        if same_step:
                            report["offsets_info"].append(item)
                        else:
                            frame_bad = True
                            report["mismatches"].append(item)
                if not frame_bad:
                    report["clean_frames"] += 1

        for m in report["mismatches"][:40]:
            print(f"frame {m['frame']}: {m.get('kind')} @ "
                  f"0x{m['addr']:08x} " + str({k: v for k, v in m.items()
                                               if k not in ('frame', 'region', 'addr', 'kind')}))
        off = len(report["offsets_info"])
        print(f"\nscanned frames {a.lo}..{a.hi}, regions={regions}")
        print(f"clean frames: {report['clean_frames']}, mismatches: "
              f"{len(report['mismatches'])}, standing-offset notes: {off}")
        rep_path = outdir / f"report_{a.lo}_{a.hi}.json"
        rep_path.write_text(json.dumps(report, indent=1))
        print(f"report: {rep_path}")
        return 1 if report["mismatches"] else 0
    finally:
        for c in (n, o):
            if c:
                c.close()
        for p in procs:
            p.terminate()
            try:
                p.wait(timeout=5)
            except Exception:
                p.kill()


if __name__ == "__main__":
    sys.exit(main())
