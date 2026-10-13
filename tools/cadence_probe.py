#!/usr/bin/env python3
"""Per-frame update-cadence probe for the guest render path.

Answers "does any guest state update every other frame?" — the
compute-at-60/read-at-30 signature (an every-other-frame render consumer,
the Mario Kart: Super Circuit affine-track shape, whose 60 fps mod exists
precisely because that game renders its track every *other* frame) — plus
the scheduler invariants of the render staging double buffer (symbols
§ 23 / § 22): the frame_step parities must toggle every VBlank and
gVblankCounter must advance one per step.

The game is run headless on the --tcp debug surface, the pacer is paused,
an optional savestate fixture is loaded, and the guest is then stepped
EXACTLY one VBlank at a time (run_frames n=1) with a held keyinput,
snapshotting the requested memory regions after every step. Per region it
reports the per-address update-cadence histogram, every EVERY-OTHER-FRAME
address (strictly alternating change steps — the real 30 Hz gate
signature; a ~0.5 change ratio alone is not, since static-then-live
transitions mimic it), and the parity/vblank rates. Alternation is judged
per scope: on the PRESENTED surfaces (io/oam/pal/vram + the display-reg
shadow, all fully rewritten every frame) it is a 30 Hz read gate and is
gated; inside IWRAM staging it is the healthy double-buffer slot write
(slot A on even steps, slot B on odd) and is only reported.

Background: BRINGUP § 2026-10-12 (late 12) audited ffta's render path for
that split and found none — parities toggle every VBlank, BG scroll moves
0x12 px/frame monotonic during pans, and a full IWRAM/OAM/PAL/VRAM sweep
found zero exact-half cadences. This tool keeps that verdict checkable.

Usage:
  tools/cadence_probe.py                       # gate: invariants + iwram/oam/pal
  tools/cadence_probe.py --state game.state1 --keyinput right --frames 160
  tools/cadence_probe.py --replay saves/regress/battle_move_trace.csv \
      --state saves/regress/battle_move_start.state   # drive a recorded flow
  tools/cadence_probe.py --script "0:a,4:none,14:right" --watch 0x02002FD8:0x80
  tools/cadence_probe.py --regions vram --frames 120
  tools/cadence_probe.py --strict              # every-other-frame fails the run
  tools/cadence_probe.py --table --traces 8    # per-frame table + more traces
  tools/cadence_probe.py --json /tmp/cad.json

Exit: 0 pass, 1 cadence/invariant failure, 2 setup error.
Gate rules: parities equal and toggling on >=95% of steps, gVblankCounter
+1 per step on >=95% of steps; with --strict, additionally zero SUSTAINED
every-other-frame addresses (>=6 alternating changes) on the PRESENTED
surfaces (io/oam/pal/vram + the display-reg shadow) — internal IWRAM
staging alternation is the double-buffer slot write and is reported, not
gated; short alternating runs are reported as transient candidates (OAM
slot recycling mimics strict alternation over short windows), never gated.
"""
import argparse
import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import tempfile
import time

REPO = pathlib.Path(__file__).resolve().parent.parent
EXE = REPO / "build/FFTARecomp"
BIOS = REPO / "bios/emibios_gba_bios.bin"
ROM = REPO / "game.gba"

REGIONS = {
    "iwram": (0x03000000, 32 * 1024, "read_iwram"),
    "ewram": (0x02000000, 256 * 1024, "read_ewram"),
    "oam": (0x07000000, 1024, "read_oam"),
    "pal": (0x05000000, 1024, "read_pal"),
    "vram": (0x06000000, 96 * 1024, "read_vram"),
    "io": (0x04000008, 0x4E, "read_io"),
}
# Presented surfaces: the hardware-visible output, fully rewritten every
# frame (staging double buffers live in IWRAM and may legitimately
# alternate slot writes; OAM/PAL/VRAM/IO do not). The IWRAM display-reg
# shadow is presented-equivalent: DMA0 commits it verbatim per VBlank.
PRESENTED = {"oam", "pal", "vram", "io"}
SHADOW = (0x03000942, 0x03000942 + 0x4E)  # gDisplayRegShadow window
PARITY_A = 0x03000028  # gOamStageParityA (symbols § 22)
PARITY_B = 0x03002F58  # gOamStageParityB
TICK = 0x03000E10      # vblank scheduler tick flag
VBCOUNT = 0x03000EB4   # gVblankCounter (+1 per vblank_callback)

# KEYINPUT is active-low; set_keyinput takes the raw register value.
KEY_BITS = {"a": 0x001, "b": 0x002, "select": 0x004, "start": 0x008,
            "right": 0x010, "left": 0x020, "up": 0x040, "down": 0x080,
            "r": 0x100, "l": 0x200}


def parse_keyinput(spec):
    if not spec:
        return 0x03FF
    mask = 0
    for tok in spec.split(","):
        tok = tok.strip().lower()
        if not tok:
            continue
        if tok in KEY_BITS:
            mask |= KEY_BITS[tok]
        else:
            mask |= int(tok, 0) & 0x03FF
    return 0x03FF & ~mask


def find_free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def parse_script(spec):
    """--script "0:a,4:none,14:right,24:a" -> per-step keyinput schedule.

    Step i uses the last entry whose frame <= i; missing schedule = the
    --keyinput default. Buttons use the KEY_BITS names, '+' to chord.
    """
    if not spec:
        return []
    out = []
    for item in spec.split(","):
        fr, btn = item.split(":", 1)
        out.append((int(fr), parse_keyinput(btn)))
    out.sort()
    return out


def parse_watch(spec):
    """--watch 0x02002C10:0x20,0x02002FD8:0x20 -> [(addr, len), ...]"""
    out = []
    for item in spec.split(",") if spec else []:
        item = item.strip()
        if not item:
            continue
        addr, ln = item.split(":")
        out.append((int(addr, 0), int(ln, 0)))
    return out


def parse_trace(path, leadin):
    """Replay a gbarecomp-keyinput-v1 trace (frame,keyinput_active_low) as
    a per-step schedule. The recorded session's absolute frames are
    re-anchored so its FIRST non-idle input lands at probe step `leadin`
    (the state is quiescent while idle, so the boot offset is inert).
    """
    events = []
    for line in pathlib.Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        fr, keys = line.split(",", 1)
        events.append((int(fr), int(keys, 0)))
    if not events:
        raise SystemExit(f"cadence_probe: empty trace {path}")
    first = next((f for f, k in events if k != 0x03FF), events[0][0])
    shift = first - leadin
    return [(max(0, f - shift), k) for f, k in events if f - shift >= 0]


def connect(port, deadline_s=45.0):
    end = time.monotonic() + deadline_s
    while time.monotonic() < end:
        try:
            s = socket.create_connection(("127.0.0.1", port), timeout=5)
            s.settimeout(60)
            return s
        except OSError:
            time.sleep(0.25)
    raise SystemExit(2)


def call(sock, cmd, **kw):
    sock.sendall((json.dumps({"cmd": cmd, **kw}) + "\n").encode())
    buf = b""
    while b"\n" not in buf:
        d = sock.recv(1 << 22)
        if not d:
            raise ConnectionError("peer closed")
        buf += d
    return json.loads(buf.split(b"\n")[0])


def read_mem(sock, cmd, addr, ln):
    r = call(sock, cmd, addr=addr, len=ln)
    d = r.get("data") or "0x"
    d = d[2:] if d.startswith("0x") else d
    return bytes.fromhex(d)


def clean_env():
    return {k: v for k, v in os.environ.items()
            if not k.startswith("GBARECOMP_")}


def read_cmd_for(addr):
    for name, (base, size, cmd) in REGIONS.items():
        if base <= addr < base + size:
            return cmd
    raise SystemExit(f"cadence_probe: no read command for {addr:#x}")


def collect(sock, frames, keyinput, targets, script):
    """Step one VBlank at a time; return per-step snapshots."""
    out = []
    for i in range(frames):
        if i and i % 100 == 0:
            print(f"cadence_probe: step {i}/{frames} ...", file=sys.stderr,
                  flush=True)
    for i in range(frames):
        keys = keyinput
        for fr, kv in script:
            if fr <= i:
                keys = kv
        fr = call(sock, "run_frames", n=1, keyinput=keys)
        pa = read_mem(sock, "read_iwram", PARITY_A, 1)[0]
        pb = read_mem(sock, "read_iwram", PARITY_B, 1)[0]
        tick = int.from_bytes(read_mem(sock, "read_iwram", TICK, 2), "little")
        vb = int.from_bytes(read_mem(sock, "read_iwram", VBCOUNT, 2), "little")
        blobs = []
        for name, base, size, cmd in targets:
            blobs.append(read_mem(sock, cmd, base, size))
        out.append({"frame": fr.get("frame"), "pa": pa, "pb": pb,
                    "tick": tick, "vb": vb, "blobs": blobs})
    return out


def analyze(targets, rows, trace_n):
    """Per-target cadence stats + scheduler invariants.

    The every-other-frame signature is STRICT ALTERNATION of change steps
    (gaps of exactly 2 between consecutive change frames), not merely a
    ~0.5 change ratio: a byte that is static for half the run and then
    updates every frame also lands near 0.5 without being a 30 Hz gate.

    OAM confounder (2026-10-13, route-B replay): a recycled OAM slot can
    fake strict alternation over a SHORT window — the whole entry is
    reassigned to a different sprite every step during scene recomposition
    while one byte happens to take pairwise-equal values across consecutive
    sprites (e.g. entry 70 byte3 = 50,50,10,10,11,11 over steps 73-79 while
    bytes 0,1,2,4,5 jump discontinuously every step). Gating therefore
    requires a SUSTAINED run (>=6 alternating changes); shorter runs are
    reported as transient candidates for human review, not gated.

    Dilution caveat (2026-10-13, totema 2600-step replay): full-history
    alternation misses a LOCALIZED burst (e.g. a 20-step palette fade)
    when the same byte changes again anywhere later in a long run — the
    totema fade flagged 8 palette bytes over 1800 steps and zero over
    2600. Maximal gap-2 subruns (>=6 changes) are therefore reported
    separately as burst_alternating with their step window (reported, not
    gated); long measurement runs must be read through bursts, not just
    the gate.
    """
    n = len(rows) - 1
    sched = {"steps": n, "parity_toggles": 0, "parity_disagreements": 0,
             "vblank_steps": 0}
    for a, b in zip(rows, rows[1:]):
        sched["parity_toggles"] += int(a["pa"] != b["pa"])
        sched["parity_disagreements"] += int(a["pa"] != a["pb"])
        sched["vblank_steps"] += int(b["vb"] - a["vb"] == 1)
    sched["parity_rate"] = sched["parity_toggles"] / max(1, n)
    sched["vblank_rate"] = sched["vblank_steps"] / max(1, n)

    out = {}
    for ti, (name, base, size, cmd) in enumerate(targets):
        changed_at = {}
        for si, (a, b) in enumerate(zip(rows, rows[1:])):
            pa, pb = a["blobs"][ti], b["blobs"][ti]
            if pa == pb:
                continue
            for off in range(len(pa)):
                if pa[off] != pb[off]:
                    changed_at.setdefault(off, []).append(si)
        hist = {}
        alt_steps = {}
        bursts = []
        near = []
        for off, steps in changed_at.items():
            cad = len(steps) / max(1, n)
            hist[round(cad * 20) / 20] = hist.get(round(cad * 20) / 20, 0) + 1
            gaps = [b - x for x, b in zip(steps, steps[1:])]
            if len(steps) >= 4 and all(g == 2 for g in gaps):
                # Sustained runs gate; short runs (OAM slot-recycling
                # transients) are reported separately, never gated.
                bucket = "sust" if len(steps) >= 6 else "tran"
                alt_steps.setdefault((bucket, tuple(steps)), []).append(
                    base + off)
            # Burst runs: maximal consecutive gap-2 subruns. Full-history
            # alternation dilutes when a localized burst (e.g. a 20-step
            # palette fade) is followed by later changes to the same byte
            # anywhere in a long run — the subrun still counts.
            run = [steps[0]]
            for prev_, cur in zip(steps, steps[1:]):
                if cur - prev_ == 2:
                    run.append(cur)
                else:
                    if len(run) >= 6:
                        bursts.append((base + off, run[0], run[-1], len(run)))
                    run = [cur]
            if len(run) >= 6:
                bursts.append((base + off, run[0], run[-1], len(run)))
            if abs(cad - 0.5) <= 0.1:
                near.append((cad, base + off, ti, off))
        # Every-other-frame signature = strictly alternating change steps.
        # On a PRESENTED surface that is a 30 Hz gate; in IWRAM staging it
        # is the normal double-buffer slot write (slot A written on even
        # steps, slot B on odd ones) — report it, don't gate it.
        alt = []
        transient = []
        for (bucket, steps), addrs in alt_steps.items():
            for x in addrs:
                (alt if bucket == "sust" else transient).append(
                    (x, steps[0] % 2, len(steps)))
        phases = {}
        for _, ph, _cnt in alt + transient:
            phases[ph] = phases.get(ph, 0) + 1

        def presented(x):
            if name in PRESENTED:
                return True
            if name == "iwram" and SHADOW[0] <= x < SHADOW[1]:
                return True
            return name.startswith("watch@") and (
                (0x04000008 <= x < 0x04000056) or
                (0x05000000 <= x < 0x05000400) or
                (0x06000000 <= x < 0x06018000) or
                (0x07000000 <= x < 0x07000400))

        gate_addrs = sorted(f"{x:#010x}" for x, _, _ in alt if presented(x))
        transient_addrs = sorted(f"{x:#010x}" for x, _, _ in transient
                                 if presented(x))
        internal = sum(1 for x, _, _ in alt if not presented(x))
        internal += sum(1 for x, _, _ in transient if not presented(x))
        near.sort(key=lambda t: abs(t[0] - 0.5))
        # Traces: gated alternating addresses first (always), then the
        # nearest-to-0.5 movers.
        traces = []
        for x, _ph, cnt in sorted(alt + transient):
            if presented(x):
                vals = [r["blobs"][ti][x - base] for r in rows[:120]]
                traces.append({"addr": f"{x:#010x}",
                               "cadence": round(cnt / max(1, n), 3),
                               "changes": cnt,
                               "values": [f"{v:02x}" for v in vals]})
        for x, start, end, cnt in sorted(bursts):
            # Every window gets its own trace: the same byte often bursts
            # twice (fade-out, then fade-in) and the directions differ.
            if presented(x):
                vals = [r["blobs"][ti][x - base]
                        for r in rows[max(0, start - 2):end + 6]]
                traces.append({"addr": f"{x:#010x}",
                               "cadence": round(cnt / max(1, end - start + 1), 3),
                               "changes": cnt, "window": [start, end],
                               "values": [f"{v:02x}" for v in vals]})
        for cad, addr, ti2, off in near[:trace_n]:
            vals = [r["blobs"][ti2][off] for r in rows[:80]]
            traces.append({"addr": f"{addr:#010x}", "cadence": round(cad, 3),
                           "values": [f"{v:02x}" for v in vals]})
        out[name] = {"changed_bytes": len(changed_at),
                     "histogram": {f"{k:.2f}": v for k, v in sorted(hist.items())},
                     "alternating": gate_addrs,
                     "transient_alternating": transient_addrs,
                     "burst_alternating": sorted(
                         f"{x:#010x}@{s}-{e}" for x, s, e, _ in bursts
                         if presented(x)),
                     "internal_alternating": internal,
                     "alternating_phases": {str(k): v for k, v in
                                            sorted(phases.items())},
                     "near_half": [{"addr": f"{a:#010x}", "cadence": round(c, 3)}
                                   for c, a, _, _ in near[:20]],
                     "traces": traces}
    return sched, out


def main():
    ap = argparse.ArgumentParser(
        description="guest render-path update-cadence probe "
                    "(compute-at-60/read-at-30 detector)")
    ap.add_argument("--frames", type=int, default=96,
                    help="VBlanks to step and sample (default 96)")
    ap.add_argument("--state", default="",
                    help="savestate fixture to load first (e.g. game.state1); "
                         "default: auto-use game.state1 when present")
    ap.add_argument("--no-state", action="store_true",
                    help="probe the boot path even if game.state1 exists")
    ap.add_argument("--keyinput", default="",
                    help="held buttons: names and/or hex mask, comma list "
                         "(e.g. right, or right,a); default: none held")
    ap.add_argument("--script", default="",
                    help="per-step keyinput schedule \"0:a,4:none,14:right\" "
                         "(step:buttons[,step:buttons...]; buttons use the "
                         "--keyinput names, '+' chords) — overrides "
                         "--keyinput from each listed step on")
    ap.add_argument("--replay", default="",
                    help="gbarecomp-keyinput-v1 trace to replay per step "
                         "(see reference/dev-gotchas.md § Input trace "
                         "format); first non-idle input lands at step 8")
    ap.add_argument("--watch", default="",
                    help="extra per-frame watches \"0x02002C10:0x20,...\" "
                         "(addr:len, auto read-command by region)")
    ap.add_argument("--regions", default="io,iwram,oam,pal",
                    help="comma list of " + ",".join(REGIONS) +
                         " (vram is slow; opt in)")
    ap.add_argument("--strict", action="store_true",
                    help="every-other-frame addresses on the presented "
                         "surfaces fail the run")
    ap.add_argument("--table", action="store_true",
                    help="print the per-frame scheduler/scroll table")
    ap.add_argument("--traces", type=int, default=6,
                    help="near-half value traces to print (default 6)")
    ap.add_argument("--json", default="",
                    help="also write the full report as JSON here")
    ap.add_argument("--port", type=int, default=0,
                    help="tcp debug port (default 0 = auto; fixed ports "
                         "collide when check.py runs suites concurrently)")
    a = ap.parse_args()

    for p in (EXE, BIOS, ROM):
        if not p.exists():
            print(f"cadence_probe: missing {p.name} (build/ROM/BIOS required)")
            return 2
    regions = [r.strip() for r in a.regions.split(",") if r.strip()]
    bad = [r for r in regions if r not in REGIONS]
    if bad:
        print(f"cadence_probe: unknown region(s): {', '.join(bad)}")
        return 2
    if a.frames < 8:
        print("cadence_probe: --frames must be >= 8")
        return 2

    state = pathlib.Path(a.state) if a.state else (
        REPO / "game.state1" if (REPO / "game.state1").exists() else None)
    if a.no_state:
        state = None
    keyinput = parse_keyinput(a.keyinput)
    script = parse_script(a.script) if a.script else (
        parse_trace(a.replay, 8) if a.replay else [])
    targets = []
    for name in regions:
        base, size, cmd = REGIONS[name]
        targets.append((name, base, size, cmd))
    for addr, ln in parse_watch(a.watch):
        targets.append((f"watch@{addr:#x}", addr, ln, read_cmd_for(addr)))

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="ffta_cadence_"))
    log = open(tmp / "run.log", "wb")
    port = a.port or find_free_port()
    proc = subprocess.Popen(
        [str(EXE), "--bios", str(BIOS), "--rom", str(ROM),
         "--save-path", str(tmp / "probe.sav"), "--tcp", str(port)],
        cwd=str(REPO), env=clean_env(), stdout=log, stderr=subprocess.STDOUT,
        start_new_session=True)
    try:
        try:
            sock = connect(port)
            call(sock, "pause")  # deterministic; the pacer must not run
            call(sock, "run_frames", n=10)
            loaded = "boot path"
            if state is not None:
                if not state.exists():
                    print(f"cadence_probe: state fixture missing: {state}")
                    return 2
                r = call(sock, "savestate_load", path=str(state))
                if not r.get("ok"):
                    print(f"cadence_probe: savestate_load failed: {r}")
                    return 2
                loaded = state.name
            call(sock, "run_frames", n=6, keyinput=keyinput)
            rows = collect(sock, a.frames, keyinput, targets, script)
            call(sock, "quit")
        except (ConnectionError, OSError) as exc:
            print(f"cadence_probe: tcp session failed ({exc}); "
                  f"see {tmp / 'run.log'}")
            return 2
    finally:
        proc.terminate()
        try:
            proc.wait(5)
        except Exception:
            proc.kill()
        log.close()

    sched, stats = analyze(targets, rows, a.traces)

    drive = (f"replay={pathlib.Path(a.replay).name}" if a.replay else
             f"script={a.script}" if a.script else
             f"keyinput={a.keyinput or 'none'}")
    print(f"cadence_probe: {a.frames} steps on {loaded}, {drive}, "
          f"targets={','.join(t[0] for t in targets)}")
    if a.table:
        print(f"{'frame':>6} {'pa':>2} {'pb':>2} {'vb':>6} {'dvb':>3}")
        prev = None
        for r in rows[:60]:
            dvb = 0 if prev is None else r["vb"] - prev
            print(f"{r['frame'] or 0:>6} {r['pa']:>2} {r['pb']:>2} "
                  f"{r['vb']:>6} {dvb:>3}")
            prev = r["vb"]
    print(f"scheduler: parity toggle {sched['parity_rate']:.2f}/step, "
          f"parity A==B disagreements {sched['parity_disagreements']}, "
          f"vblank +1/step {sched['vblank_rate']:.2f}")
    for name, _base, _size, _cmd in targets:
        s = stats[name]
        print(f"== {name}: {s['changed_bytes']} bytes changed")
        print("   histogram (cadence: bytes): "
              + " ".join(f"{k}:{v}" for k, v in s["histogram"].items()))
        if s["alternating"]:
            print(f"   EVERY-OTHER-FRAME on presented surface: "
                  f"{', '.join(s['alternating'])}")
        else:
            print("   every-other-frame on presented surface: none")
        if s["transient_alternating"]:
            print(f"   transient alternation (short-run, review manually — "
                  f"OAM slot recycling mimics this): "
                  f"{', '.join(s['transient_alternating'])}")
        if s["burst_alternating"]:
            print(f"   burst alternation (localized gap-2 run, addr@first-last "
                  f"step — survives later changes to the same byte): "
                  f"{', '.join(s['burst_alternating'])}")
        if s["internal_alternating"]:
            print(f"   internal staging alternation (double buffer): "
                  f"{s['internal_alternating']} bytes, phases "
                  f"{s['alternating_phases']}")
        for t in s["traces"]:
            tag = (f"@{t['window'][0]}-{t['window'][1]}"
                   if "window" in t else "")
            print(f"   trace {t['addr']}{tag} cad={t['cadence']:.2f}: "
                  + " ".join(t["values"]))

    if a.json:
        pathlib.Path(a.json).write_text(json.dumps(
            {"loaded": loaded, "frames": a.frames, "keyinput": a.keyinput,
             "scheduler": sched, "regions": stats}, indent=2))

    failures = []
    if sched["parity_disagreements"]:
        failures.append("parity A!=B on some step")
    if sched["parity_rate"] < 0.95:
        failures.append(f"parity toggles only {sched['parity_rate']:.2f}/step "
                        "(frame_step not every VBlank?)")
    if sched["vblank_rate"] < 0.95:
        failures.append(f"vblank +1/step only {sched['vblank_rate']:.2f}")
    if a.strict:
        for name in stats:
            if stats[name]["alternating"]:
                failures.append(f"{name}: every-other-frame cadence at "
                                + ", ".join(stats[name]["alternating"]))

    if failures:
        print("cadence_probe: FAIL — " + "; ".join(failures))
        return 1
    half = sum(len(stats[n]["alternating"]) for n in stats)
    print(f"cadence_probe: PASS — scheduler 60 Hz, {half} every-other-frame "
          f"address(es)" + ("" if a.strict else " (--strict gates them)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
