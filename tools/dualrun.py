#!/usr/bin/env python3
"""dualrun.py — lockstep native-vs-oracle probes for FFTA (Phase 5 harness).

Replaces the hand-rolled probe scripts of 2026-10-06 (see BRINGUP
§ "park-phase semantics" for the model this tool encodes):

  * Both engines park at VBlank-start. The native runner executes the VBlank
    IRQ handler before parking (post-handler); mGBA raises it and vectors it
    at the start of the next step (pre-handler). Same-index STATE reads are
    therefore one handler apart (native ahead; e.g. snow RNG delta = 13
    chain steps/frame). PIXELS compare same-index — both sides return the
    latched completed frame.

Commands (run from anywhere; .venv has capstone but this tool needs no deps):
  .venv/bin/python tools/dualrun.py dump --frames 620 --out /tmp/dr
  .venv/bin/python tools/dualrun.py probe regions --frames 600 \
      [--regions iwram,ewram,oam,pal,vram,io]
  .venv/bin/python tools/dualrun.py probe pixels --lo 600 --hi 640 \
      [--every 2] [--shifts] [--save-worst /tmp/dr]
  .venv/bin/python tools/dualrun.py probe cells --lo 300 --hi 330 \
      --addrs 0x030034B0,0x03000088
  .venv/bin/python tools/dualrun.py probe saveflow \
      --trace logs/playthrough.csv --save saves/playtest.sav \
      --checkpoints 400,600,900,1200,1500,1700 --dump-dir /tmp/sf

PNG artifacts are ROM-derived: write them to /tmp or logs/ (gitignored),
never into the repo tree.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import zlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from framediff import Client, REGIONS as _REGIONS  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parent.parent
BIOS = REPO / "gbarecomp/bios/gba_bios.bin"
ROM = REPO / "game.gba"
NATIVE = REPO / "build/FFTARecomp"
ORACLE = REPO / "gbarecomp/build/oracle/gbarecomp_oracle"

REGIONS = dict(_REGIONS)
REGIONS["io"] = ("read_io", "read_emu_io", 0x04000000, 0x60)


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Dual:
    """Lockstep pair of engine TCP clients (use as a context manager)."""

    def __init__(self, strict: bool = True, env_extra: dict | None = None,
                 timeout: float = 30.0, trace: str | None = None,
                 save: str | None = None):
        self.nat_port = free_port()
        self.orc_port = free_port()
        env = {k: v for k, v in os.environ.items()
               if not k.startswith("GBARECOMP_")}
        if strict:
            env["GBARECOMP_STRICT_STATIC"] = "1"
        if env_extra:
            env.update(env_extra)
        self.trace: dict[int, int] = {}
        if trace:
            for ln in pathlib.Path(trace).read_text().splitlines():
                ln = ln.strip()
                if not ln or ln.startswith("#"):
                    continue
                f, v = ln.split(",", 1)
                self.trace[int(f)] = int(v.strip(), 16)
        self.frame = 0
        nat_argv = [str(NATIVE), "--bios", str(BIOS), "--rom", str(ROM),
                    "--tcp", str(self.nat_port)]
        if save:
            nat_argv += ["--save-path", str(save)]
        self.nat = subprocess.Popen(
            nat_argv, cwd=str(REPO), stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, env=env)
        orc_rom = str(ROM)
        self._tmpdirs: list[str] = []
        if save:
            # Give the oracle a save file via its standard "<rom>.sav"
            # autoload (oracle supports it since the 2026-10-07 rebuild):
            # symlink the ROM + copy the battery save into a temp dir.
            tmp = tempfile.mkdtemp(prefix="dualrun_save_")
            self._tmpdirs.append(tmp)
            t = pathlib.Path(tmp)
            (t / "game.gba").symlink_to(ROM)
            shutil.copy(str(save), str(t / "game.sav"))
            orc_rom = str(t / "game.gba")
        self.orc = subprocess.Popen(
            [str(ORACLE), "--bios", str(BIOS), "--rom", orc_rom,
             "--port", str(self.orc_port)],
            cwd=str(REPO / "gbarecomp"), stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL)
        try:
            self.n = Client(self.nat_port, timeout=timeout)
            self.o = Client(self.orc_port, timeout=timeout)
        except Exception:
            self.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def step(self, count: int = 1) -> None:
        if count <= 0:
            return
        self.n.call(cmd="run_frames", n=count)
        for _ in range(count):
            self.o.call(cmd="emu_step")
        self.frame += count

    def step_traced(self, target: int) -> None:
        """Step frame-by-frame to absolute frame `target`, applying input
        events from the trace just before the frame they belong to."""
        while self.frame < target:
            f = self.frame + 1
            if f in self.trace:
                v = self.trace[f]
                self.n.call(cmd="set_keyinput", value=v)
                self.o.call(cmd="emu_set_keys", keys=(~v) & 0x03FF)
            self.n.call(cmd="run_frames", n=1)
            self.o.call(cmd="emu_step")
            self.frame = f

    def read(self, region: str, addr: int | None = None, ln: int | None = None):
        ncmd, ocmd, base, default_len = REGIONS[region]
        a = base if addr is None else addr
        l = default_len if ln is None else ln
        return self.n.read(ncmd, a, l), self.o.read(ocmd, a, l)

    def screenshot(self):
        return (bytes.fromhex(self.n.call(cmd="screenshot")["data"]),
                bytes.fromhex(self.o.call(cmd="emu_screenshot")["data"]))

    def close(self):
        for c in (getattr(self, "n", None), getattr(self, "o", None)):
            if c is not None:
                try:
                    c.close()
                except Exception:
                    pass
        for p in (getattr(self, "nat", None), getattr(self, "orc", None)):
            if p is None:
                continue
            p.terminate()
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
        for tmp in getattr(self, "_tmpdirs", []) or []:
            shutil.rmtree(tmp, ignore_errors=True)


def write_png(path: pathlib.Path, w: int, h: int, rgb: bytes) -> None:
    raw = b"".join(b"\x00" + rgb[y * w * 3:(y + 1) * w * 3]
                   for y in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n" +
        chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) +
        chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def diff_count(a: bytes, b: bytes) -> int:
    return sum(1 for x, y in zip(a, b) if x != y)


def first_diffs(a: bytes, b: bytes, limit: int = 5):
    out = []
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            out.append(i)
            if len(out) >= limit:
                break
    return out


def make_dual(args) -> Dual:
    env_extra = dict(kv.split("=", 1) for kv in args.env)
    return Dual(strict=not args.no_strict, env_extra=env_extra,
                timeout=args.timeout)


def cmd_dump(args) -> int:
    with make_dual(args) as d:
        d.step(args.frames)
        n_rgb, o_rgb = d.screenshot()
        out = pathlib.Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        write_png(out / f"native_f{args.frames}.png", 240, 160, n_rgb)
        write_png(out / f"oracle_f{args.frames}.png", 240, 160, o_rgb)
        print(f"frames={args.frames} pixel-diff={diff_count(n_rgb, o_rgb)} bytes "
              f"— wrote native_f{args.frames}.png / oracle_f{args.frames}.png to {out}")
    return 0


def cmd_regions(args) -> int:
    with make_dual(args) as d:
        d.step(args.frames)
        for name in args.regions.split(","):
            nb, ob = d.read(name)
            first = [hex(REGIONS[name][2] + i) for i in first_diffs(nb, ob)]
            print(f"{name}: diff={diff_count(nb, ob)}/{len(nb)} first={first}")
    return 0


def cmd_pixels(args) -> int:
    with make_dual(args) as d:
        d.step(args.lo)
        nbufs, obufs, frames = [], [], []
        worst = (0, None, None, None)
        for i, f in enumerate(range(args.lo + 1, args.hi + 1)):
            d.step(1)
            if i % args.every:
                continue
            nb, ob = d.screenshot()
            nbufs.append(nb)
            obufs.append(ob)
            frames.append(f)
            dd = diff_count(nb, ob)
            if dd > worst[0]:
                worst = (dd, f, nb, ob)
            print(f"f{f}: diff={dd} bytes ({100.0 * dd / len(nb):.2f}%)")
        if args.shifts and len(nbufs) > 2:
            print("shift table (total diff bytes):")
            for s in (-2, -1, 0, 1, 2):
                tot = cnt = 0
                for i in range(len(nbufs)):
                    j = i + s
                    if 0 <= j < len(obufs):
                        tot += diff_count(nbufs[i], obufs[j])
                        cnt += 1
                if cnt:
                    print(f"  nat[i] vs orc[i{s:+d}]: avg {tot / cnt:.0f} bytes")
        if args.save_worst and worst[1] is not None:
            dd, f, nb, ob = worst
            out = pathlib.Path(args.save_worst)
            out.mkdir(parents=True, exist_ok=True)
            mask = bytearray()
            for px in range(240 * 160):
                if nb[px * 3:px * 3 + 3] != ob[px * 3:px * 3 + 3]:
                    mask += bytes((255, 0, 0))
                else:
                    mask += bytes((nb[px * 3] // 3, nb[px * 3 + 1] // 3,
                                   nb[px * 3 + 2] // 3))
            write_png(out / f"native_f{f}.png", 240, 160, nb)
            write_png(out / f"oracle_f{f}.png", 240, 160, ob)
            write_png(out / f"diff_f{f}.png", 240, 160, bytes(mask))
            print(f"worst frame f{f} ({dd} bytes) saved to {out}")
    return 0


def cmd_cells(args) -> int:
    addrs = [int(a, 16) for a in args.addrs.split(",")]
    regions = []
    for a in addrs:
        top = a >> 24
        if top == 0x03:
            regions.append("iwram")
        elif top == 0x02:
            regions.append("ewram")
        else:
            print(f"error: only IWRAM/EWRAM cells supported (got {a:#x})",
                  file=sys.stderr)
            return 2
    with make_dual(args) as d:
        d.step(args.lo)
        seq = {"n": [[], []], "o": [[], []]}
        for _i in range(args.lo + 1, args.hi + 1):
            d.step(1)
            for k, a in enumerate(addrs):
                nb, ob = d.read(regions[k], a, 4)
                seq["n"][k].append(nb)
                seq["o"][k].append(ob)
        total = sum(len(v) for v in (seq["n"] + seq["o"]))
        n_samples = len(seq["n"][0]) if addrs else 0
        print(f"samples={n_samples} cells={len(addrs)}")
        for k, a in enumerate(addrs):
            print(f"cell {a:#010x}:")
            for s in range(-2, 3):
                m = t = 0
                for i in range(n_samples):
                    j = i + s
                    if 0 <= j < n_samples:
                        t += 1
                        m += seq["n"][k][i] == seq["o"][k][j]
                if t:
                    print(f"  nat[i] vs orc[i{s:+d}]: {m}/{t}")
    return 0


def cmd_saveflow(args) -> int:
    env_extra = dict(kv.split("=", 1) for kv in args.env)
    d = Dual(strict=not args.no_strict, env_extra=env_extra,
             timeout=args.timeout, trace=args.trace, save=args.save)
    dumpdir = pathlib.Path(args.dump_dir) if args.dump_dir else None
    if (dumpdir or args.png_at):
        dumpdir = dumpdir or pathlib.Path("/tmp/dualrun_saveflow")
        dumpdir.mkdir(parents=True, exist_ok=True)
    pngs = {int(x) for x in (args.png_at or "").split(",") if x}
    checks = [int(x) for x in args.checkpoints.split(",") if x]
    rc = 0
    try:
        for ck in checks:
            d.step_traced(ck)
            if ck in pngs and dumpdir:
                nr, orr = d.screenshot()
                write_png(dumpdir / f"native_f{ck}.png", 240, 160, nr)
                write_png(dumpdir / f"oracle_f{ck}.png", 240, 160, orr)
            parts = [f"f{ck}"]
            for name in args.regions.split(","):
                nb, ob = d.read(name)
                dd = diff_count(nb, ob)
                parts.append(f"{name}:diff={dd}")
                if dd:
                    fd = [hex(REGIONS[name][2] + i)
                          for i in first_diffs(nb, ob)]
                    parts.append("first=" + "+".join(fd))
                    if dumpdir:
                        tag = f"f{ck}_{name}"
                        (dumpdir / f"native_{tag}.bin").write_bytes(nb)
                        (dumpdir / f"oracle_{tag}.bin").write_bytes(ob)
            print(" ".join(parts), flush=True)
    except Exception as e:
        print(f"saveflow stopped at f~{d.frame}: {e}", flush=True)
        rc = 1
    finally:
        d.close()
    return rc


def main() -> int:
    std = argparse.ArgumentParser(add_help=False)
    std.add_argument("--no-strict", action="store_true",
                     help="run the native side without STRICT_STATIC")
    std.add_argument("--env", action="append", default=[], metavar="K=V",
                     help="extra environment (repeatable); GBARECOMP_* from "
                          "the shell are always stripped first")
    std.add_argument("--timeout", type=float, default=30.0)

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 parents=[std])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("dump", help="boot both engines, dump PNG pair")
    p.add_argument("--frames", type=int, default=1200)
    p.add_argument("--out", default="/tmp/dualrun")
    p.set_defaults(fn=cmd_dump)

    pp = sub.add_parser("probe", help="lockstep probes")
    psub = pp.add_subparsers(dest="probe_cmd", required=True)

    r = psub.add_parser("regions", help="region diff at a frame")
    r.add_argument("--frames", type=int, required=True)
    r.add_argument("--regions", default="iwram,ewram,oam,pal,vram")
    r.set_defaults(fn=cmd_regions)

    px = psub.add_parser("pixels", help="per-frame pixel diff trajectory")
    px.add_argument("--lo", type=int, required=True)
    px.add_argument("--hi", type=int, required=True)
    px.add_argument("--every", type=int, default=1)
    px.add_argument("--shifts", action="store_true",
                    help="print shift table (-2..+2)")
    px.add_argument("--save-worst", default=None,
                    help="directory for worst-frame PNG triple")
    px.set_defaults(fn=cmd_pixels)

    c = psub.add_parser("cells", help="cell value alignment probe")
    c.add_argument("--lo", type=int, required=True)
    c.add_argument("--hi", type=int, required=True)
    c.add_argument("--addrs", required=True,
                   help="comma-separated hex addresses (IWRAM/EWRAM)")
    c.set_defaults(fn=cmd_cells)

    sf = psub.add_parser("saveflow",
                         help="region diff across an input trace, "
                              "optionally with a battery save")
    sf.add_argument("--trace", required=True, help="input trace CSV")
    sf.add_argument("--save", default=None,
                    help="battery save for the native side; a copy is "
                         "placed next to a symlinked ROM for the oracle")
    sf.add_argument("--checkpoints", required=True,
                    help="comma-separated absolute frame numbers")
    sf.add_argument("--regions", default="iwram,ewram,io")
    sf.add_argument("--dump-dir", default=None,
                    help="write region dumps (and PNGs) here")
    sf.add_argument("--png-at", default=None,
                    help="comma-separated frames to also save a PNG pair")
    sf.set_defaults(fn=cmd_saveflow)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
