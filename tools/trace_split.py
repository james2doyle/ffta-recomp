#!/usr/bin/env python3
"""Split a gbarecomp keyinput trace into monotonic segments.

tools/play.sh records sparse (frame,keyinput) pairs. If you load a savestate
mid-session the guest frame counter jumps BACKWARD, so the trace is no longer
strictly increasing and GBARECOMP_INPUT_REPLAY rejects it with
"invalid input trace line: <frame>,0x....".

This tool writes one trace file per monotonic segment (header preserved), so
each segment can be replayed from the same starting state with
tools/resolve.py --load-state <the state that was loaded>.

Usage:
  .venv/bin/python tools/trace_split.py --trace logs/playthrough.csv \
      [--out-dir /tmp] [--prefix seg]

Prints one line per segment: <path>  <events>  <first_frame>-><last_frame>.
Exit code 0 if the trace was already monotonic (single segment written).
"""
import argparse
import pathlib
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace", required=True)
    ap.add_argument("--out-dir", default="/tmp")
    ap.add_argument("--prefix", default="seg")
    a = ap.parse_args()

    lines = pathlib.Path(a.trace).read_text().splitlines()
    events = []
    for i, l in enumerate(lines, 1):
        l = l.strip()
        if not l or l.startswith("#"):
            continue
        try:
            int(l.split(",")[0], 10)
        except ValueError:
            print(f"warning: unparsable line {i}: {l!r}", file=sys.stderr)
            continue
        events.append(l)
    if not events:
        print("no events in trace", file=sys.stderr)
        return 1

    segs, cur, prev = [], [], None
    breaks = 0
    for l in events:
        f = int(l.split(",")[0], 10)
        if prev is not None and f < prev:
            segs.append(cur)
            cur = []
            breaks += 1
        cur.append(l)
        prev = f
    if cur:
        segs.append(cur)

    outdir = pathlib.Path(a.out_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    for i, seg in enumerate(segs, 1):
        p = outdir / f"{a.prefix}{i}.csv"
        p.write_text("\n".join(["# gbarecomp-keyinput-v1",
                                "# frame,keyinput_active_low", *seg]) + "\n")
        span = f"{seg[0].split(',')[0]}->{seg[-1].split(',')[0]}"
        print(f"{p}  {len(seg)} events  {span}")
    if breaks:
        print(f"{breaks} backward jump(s) split; replay each segment with the "
              f"same --load-state and a --frames budget covering its span.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
