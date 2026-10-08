#!/usr/bin/env python3
"""Widescreen smoke test (W3) — margin census + center-crop compare + stale guard.

For each case (scene fixture) x view width the native runner is executed
headless twice: once at the target width, once at faithful 240. Checks:

  center  — the wide render's center [extra_left, extra_left+240) must be
            pixel-identical to the faithful 240 render (0 differing pixels).
  margins — census of non-black pixels in the two margin strips; policy:
            ring scenes (battle/pub) must be filled, the world map must be
            exact black (pillarbox), enforced by the per-scene policy.
  fade    — transition frames: margins may be black or dim with the scene,
            but never brighter than the center (no bright bars against a
            dark fade).
  stale   — battle_idle vs battle_pan margin strips must differ: the margins
            carry live scene content, not a frozen capture (Emerald-style
            stale-request guard).

Fixtures: game.state1 (mid-battle overview, frame 24722) / game.state2
(world map, frame 51827) are local-only savestates (game-derived, gitignored,
never committed) and SHA-256-pinned: the per-case frame budgets and the
CSV's absolute guest frames depend on these exact states. Exit 2 when they
are missing or changed. Input traces are committed under inputs/ws_*.csv.
NOTE: --frames is the frame count run AFTER the state loads; replay events
key on absolute guest frames, so each case's budget must cover its CSV
events (guest end noted per case). Rendered frames are ROM-derived — written
to a temp dir and deleted unless --keep. PNG decoding is dependency-free
(zlib + unfilter, 8-bit RGB/RGBA). Engine invocations run in parallel
(--jobs, default 8) with isolated dump/save paths.

Exit: 0 pass, 1 fail, 2 fixtures missing (skip; fresh clone).
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import pathlib
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib

REPO = pathlib.Path(__file__).resolve().parents[1]

NATIVE_W = 240
FILLED_MIN_FRAC = 0.99   # ring-scene margins must be ~fully covered
STALE_MIN_FRAC = 0.02    # idle vs panned margins must differ by at least this

# frames = frames to run after the state loads (budget must cover the CSV's
# absolute-guest-frame events); each case notes the resulting guest end frame
CASES: dict[str, dict] = {
    "world_idle":  dict(state="game.state2", csv=None, frames=90, expect="pillar",
                        desc="world map at rest, guest 51917 (256-px tilemaps -> pillarbox)"),
    "pub_idle":    dict(state="game.state2", csv="inputs/ws_pub_enter.csv",
                        frames=240, expect="filled", desc="pub interior, guest 52067"),
    "pub_fade":    dict(state="game.state2", csv="inputs/ws_pub_enter.csv",
                        frames=200, expect="fade",
                        desc="mid-fade world->pub, guest 52027 (screen fully black)"),
    "pub_exit":    dict(state="game.state2", csv="inputs/ws_pub_exit.csv",
                        frames=520, expect="pillar",
                        desc="world map again after leaving the pub, guest 52347"),
    "battle_idle": dict(state="game.state1", csv=None, frames=60, expect="filled",
                        desc="battle overview at rest, guest 24782"),
    "battle_pan":  dict(state="game.state1", csv="inputs/ws_pan_right.csv",
                        frames=130, expect="filled", desc="battle mid-pan, guest 24852"),
}
STALE_PAIR = ("battle_idle", "battle_pan")

# Local-only savestate fixtures, sha256 prefixes: the frame budgets below and
# the CSV event frames are pinned to these exact states; a silent substitution
# would make every result meaningless, so treat a hash change as "no fixture".
FIXTURE_STATES = {
    "game.state1": "2066d61ccb0d",   # mid-battle overview, frame 24722
    "game.state2": "0163a908c073",   # world map, frame 51827
}


def read_png(path: pathlib.Path):
    """Decode a non-interlaced 8-bit RGB/RGBA PNG -> (w, h, bpp, rows)."""
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{path}: not a PNG"
    pos, idat = 8, bytearray()
    w = h = ctype = None
    while pos < len(data):
        ln = struct.unpack(">I", data[pos:pos + 4])[0]
        typ = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + ln]
        pos += 12 + ln
        if typ == b"IHDR":
            w, h, depth, ctype, comp, filt, inter = struct.unpack(">IIBBBBB", chunk)
            assert depth == 8 and comp == 0 and filt == 0 and inter == 0, "unsupported PNG"
            assert ctype in (2, 6), f"unsupported color type {ctype}"
        elif typ == b"IDAT":
            idat += chunk
        elif typ == b"IEND":
            break
    raw = zlib.decompress(bytes(idat))
    bpp = 3 if ctype == 2 else 4
    stride = w * bpp
    rows, prev, p = [], bytearray(stride), 0
    for _ in range(h):
        f = raw[p]; p += 1
        line = bytearray(raw[p:p + stride]); p += stride
        if f == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif f == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif f == 3:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif f == 4:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xFF
        rows.append(bytes(line))
        prev = line
    return w, h, bpp, rows


def analyze(path: pathlib.Path) -> dict:
    w, h, bpp, rows = read_png(path)
    assert h == 160, f"{path}: expected 160 rows, got {h}"
    extra_left = (w - NATIVE_W) // 2
    extra_right = w - NATIVE_W - extra_left
    left_px = right_px = left_nb = right_nb = 0
    margin_bytes = bytearray()
    center = []
    margin_max = center_max = 0
    for line in rows:
        for x in range(extra_left):
            off = x * bpp
            left_px += 1
            mx = max(line[off], line[off + 1], line[off + 2])
            if mx:
                left_nb += 1
            if mx > margin_max:
                margin_max = mx
        for x in range(w - extra_right, w):
            off = x * bpp
            right_px += 1
            mx = max(line[off], line[off + 1], line[off + 2])
            if mx:
                right_nb += 1
            if mx > margin_max:
                margin_max = mx
        margin_bytes += line[0:extra_left * bpp]
        margin_bytes += line[(w - extra_right) * bpp:]
        center.append(line[extra_left * bpp:(extra_left + NATIVE_W) * bpp])
    for line_bytes in center:
        for x in range(NATIVE_W):
            off = x * bpp
            mx = max(line_bytes[off], line_bytes[off + 1], line_bytes[off + 2])
            if mx > center_max:
                center_max = mx
    return dict(w=w, extra_left=extra_left, extra_right=extra_right,
                left_px=left_px, left_nb=left_nb, right_px=right_px, right_nb=right_nb,
                margin_max=margin_max, center_max=center_max,
                margin_bytes=bytes(margin_bytes), center=center)


def center_diff(wide: dict, faithful: dict) -> int:
    assert len(wide["center"]) == len(faithful["center"])
    return sum(1 for a, b in zip(wide["center"], faithful["center"]) if a != b)


def margin_changed(a: bytes, b: bytes) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    tot = len(a) // 3
    changed = sum(1 for i in range(0, len(a), 3) if a[i:i + 3] != b[i:i + 3])
    return changed / tot


def run_case(case: dict, width: int, png: pathlib.Path, sav: pathlib.Path) -> tuple[bool, str]:
    cmd = ["./build/FFTARecomp", "--bios", "gbarecomp/bios/gba_bios.bin",
           "--rom", "game.gba", "--load-state", case["state"],
           "--save-path", str(sav),
           "--frames", str(case["frames"]), "--dump-png", str(png), "--no-window"]
    if width != NATIVE_W:
        cmd += ["--view-width", str(width)]
    env = {k: v for k, v in os.environ.items() if not k.startswith("GBARECOMP_")}
    if case["csv"]:
        env["GBARECOMP_INPUT_REPLAY"] = case["csv"]
    # Parallel safety: keep coverage/frag artifacts per-run in the temp dir so
    # concurrent engines never race on the repo-root files.
    env["GBARECOMP_COVERAGE_JSON"] = str(sav.with_suffix(".cov.json"))
    env["GBARECOMP_MISS_FRAG"] = str(sav.with_suffix(".frag"))
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600, env=env,
                       cwd=REPO)
    out = r.stdout + r.stderr
    if "savestate_loaded" not in out:
        return False, "state did not load: " + "\n".join(out.splitlines()[-4:])
    if not png.exists() or png.stat().st_size == 0:
        return False, "no frame dumped: " + "\n".join(out.splitlines()[-4:])
    clamp = [l for l in out.splitlines() if "clamping to" in l]
    if clamp and width != NATIVE_W:
        return False, "width clamped: " + clamp[0]
    return True, ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--widths", default="320,384,448",
                    help="comma-separated view widths (default 320,384,448)")
    ap.add_argument("--only", help="comma-separated case names")
    ap.add_argument("--jobs", type=int, default=8,
                    help="parallel engine runs (default 8; 1 = sequential)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--report-only", action="store_true",
                    help="print the census without verdicts (calibration)")
    ap.add_argument("--keep", action="store_true", help="keep dumped frames")
    a = ap.parse_args()

    needed = [REPO / c["state"] for c in CASES.values()]
    needed += [REPO / c["csv"] for c in CASES.values() if c["csv"]]
    missing = [str(p.relative_to(REPO)) for p in needed if not p.exists()]
    if missing:
        print("ws_check: SKIP — fixtures missing: " + ", ".join(sorted(set(missing))))
        return 2
    changed = []
    for rel, prefix in FIXTURE_STATES.items():
        p = REPO / rel
        if p.exists():
            h = hashlib.sha256(p.read_bytes()).hexdigest()
            if not h.startswith(prefix):
                changed.append(f"{rel} sha256 {h[:12]}... != pinned {prefix}...")
    if changed:
        print("ws_check: SKIP — pinned fixture changed: " + "; ".join(changed) +
              " (frame budgets and CSV event frames are pinned to these states; "
              "regenerate the expectations deliberately)")
        return 2

    widths = [int(w) for w in a.widths.split(",")]
    names = list(CASES)
    if a.only:
        names = [n for n in a.only.split(",") if n in CASES]
        bad = [n for n in a.only.split(",") if n not in CASES]
        if bad:
            print("unknown cases:", ", ".join(bad))
            return 1

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="ffta_ws_check_"))
    results: dict = {"widths": widths, "cases": {}}
    failures: list[str] = []
    verdicts: list[str] = []
    stats: dict = {}   # (case, width) -> analyze dict

    try:
        # ── run every engine invocation in parallel ─────────────────────
        # Runs are independent processes with isolated dump/save paths; the
        # analysis below then walks them in stable case/width order.
        run_tasks = []
        for name in names:
            run_tasks.append((name, NATIVE_W, tmp / f"{name}_240.png",
                              tmp / f"save_{name}_240.sav"))
            for width in widths:
                run_tasks.append((name, width, tmp / f"{name}_{width}.png",
                                  tmp / f"save_{name}_{width}.sav"))
        outcomes: dict = {}
        with concurrent.futures.ThreadPoolExecutor(
                max_workers=max(1, min(a.jobs, len(run_tasks)))) as ex:
            futs = {ex.submit(run_case, CASES[n], w, png, sav): (n, w)
                    for n, w, png, sav in run_tasks}
            for fut in concurrent.futures.as_completed(futs):
                outcomes[futs[fut]] = fut.result()

        for name in names:
            case = CASES[name]
            ok, err = outcomes[(name, NATIVE_W)]
            if not ok:
                failures.append(f"{name}: faithful run failed: {err}")
                continue
            faithful = analyze(tmp / f"{name}_240.png")
            for width in widths:
                wide_png = tmp / f"{name}_{width}.png"
                ok, err = outcomes[(name, width)]
                if not ok:
                    failures.append(f"{name}@{width}: {err}")
                    continue
                wide = analyze(wide_png)
                cdiff = center_diff(wide, faithful)
                lf = wide["left_nb"] / max(wide["left_px"], 1)
                rf = wide["right_nb"] / max(wide["right_px"], 1)
                stats[(name, width)] = wide
                results["cases"].setdefault(name, {})[width] = dict(
                    left_nonblack=wide["left_nb"], left_px=wide["left_px"],
                    right_nonblack=wide["right_nb"], right_px=wide["right_px"],
                    center_diff=cdiff, extra_left=wide["extra_left"],
                    extra_right=wide["extra_right"],
                )
                print(f"{name:12s} {width:4d}  margins L {wide['left_nb']:5d}/{wide['left_px']:5d} "
                      f"({lf*100:5.1f}%)  R {wide['right_nb']:5d}/{wide['right_px']:5d} ({rf*100:5.1f}%)  "
                      f"center {cdiff}/{NATIVE_W*160}")
                if a.report_only:
                    continue
                if cdiff > 0:
                    failures.append(f"{name}@{width}: center differs from faithful ({cdiff} px)")
                if case["expect"] == "pillar":
                    if wide["left_nb"] or wide["right_nb"]:
                        failures.append(f"{name}@{width}: pillarbox expected, margins not black")
                elif case["expect"] == "filled":
                    if lf < FILLED_MIN_FRAC or rf < FILLED_MIN_FRAC:
                        failures.append(f"{name}@{width}: margins not filled "
                                        f"({lf*100:.1f}% / {rf*100:.1f}%)")
                elif case["expect"] == "fade":
                    # Transition invariant: margins may be black or dim with
                    # the scene, but never brighter than the center (no bright
                    # bars against a dark fade).
                    if wide["margin_max"] > wide["center_max"] + 8:
                        failures.append(f"{name}@{width}: margins brighter than center "
                                        f"during fade ({wide['margin_max']} > {wide['center_max']}+8)")

        # stale-request guard across the battle pair, per width
        if not a.report_only and all(n in names for n in STALE_PAIR):
            for width in widths:
                a1 = stats.get((STALE_PAIR[0], width))
                a2 = stats.get((STALE_PAIR[1], width))
                if not a1 or not a2:
                    continue
                frac = margin_changed(a1["margin_bytes"], a2["margin_bytes"])
                results.setdefault("stale", {})[width] = round(frac, 4)
                print(f"stale guard  {width:4d}  idle-vs-pan margin change {frac*100:5.1f}%")
                if frac < STALE_MIN_FRAC:
                    failures.append(f"stale guard @{width}: margins did not change "
                                    f"between idle and pan ({frac*100:.1f}%)")

        if a.json:
            print(json.dumps(results, indent=1))
        if a.report_only:
            print("report-only: no verdicts")
            return 0
        if failures:
            print("\nws_check: FAIL")
            for f in failures:
                print("  - " + f)
            return 1
        print(f"\nws_check: PASS ({len(names)} cases x {len(widths)} widths)")
        return 0
    finally:
        if a.keep:
            print("frames kept:", tmp)
        else:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
