#!/usr/bin/env python3
"""Host-side tests for the Python tooling (stdlib unittest, no pytest).

Covers the pure logic the healing/audit flow depends on:
  - trace_split: backward-jump segmentation + header preservation
  - cache_harvest: recomp_cache unit-file parsing + game.toml address set
  - misspack.prologue_scan: thumb push-with-lr backscan on a synthetic ROM

Run: .venv/bin/python tests/python/test_tools.py [-v]
"""
import pathlib
import struct
import subprocess
import sys
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

import cache_harvest  # noqa: E402
import misspack  # noqa: E402


class TraceSplitTest(unittest.TestCase):
    def test_backward_jump_splits_and_headers_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            t = pathlib.Path(td) / "trace.csv"
            t.write_text("# gbarecomp-keyinput-v1\n# frame,keyinput_active_low\n"
                         "0,0x03FF\n10,0x03F7\n20,0x03FF\n5,0x03FE\n15,0x03FF\n")
            r = subprocess.run(
                [sys.executable, "tools/trace_split.py", "--trace", str(t),
                 "--out-dir", td, "--prefix", "seg"],
                cwd=str(REPO), capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            seg1 = (pathlib.Path(td) / "seg1.csv").read_text()
            seg2 = (pathlib.Path(td) / "seg2.csv").read_text()
            self.assertIn("# gbarecomp-keyinput-v1", seg1)
            self.assertIn("20,0x03FF", seg1)
            self.assertNotIn("5,0x03FE", seg1)
            self.assertIn("5,0x03FE", seg2)
            self.assertIn("15,0x03FF", seg2)
            self.assertNotIn("20,0x03FF", seg2)

    def test_monotonic_single_segment(self):
        with tempfile.TemporaryDirectory() as td:
            t = pathlib.Path(td) / "trace.csv"
            t.write_text("0,0x03FF\n5,0x03F7\n")
            r = subprocess.run(
                [sys.executable, "tools/trace_split.py", "--trace", str(t),
                 "--out-dir", td, "--prefix", "m"],
                cwd=str(REPO), capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue((pathlib.Path(td) / "m1.csv").exists())
            self.assertFalse((pathlib.Path(td) / "m2.csv").exists())


class CacheHarvestTest(unittest.TestCase):
    def test_collect_parses_unit_filenames(self):
        with tempfile.TemporaryDirectory() as td:
            repo = pathlib.Path(td)
            d = repo / "recomp_cache" / "x" / "y"
            d.mkdir(parents=True)
            (d / "005F0000_DEADBEEF_t.c").write_text("")
            (d / "005F0000_DEADBEEF_t.log").write_text("")
            (d / "805F0000_FEEDFACE_a.c").write_text("")
            (d / "not-a-unit.txt").write_text("")
            units = cache_harvest.collect(repo)
            self.assertEqual(units, {0x005F0000: "t", 0x805F0000: "a"})

    def test_game_addrs_reads_game_toml(self):
        with tempfile.TemporaryDirectory() as td:
            repo = pathlib.Path(td)
            (repo / "game.toml").write_text(
                '[[extra_func]]\naddr = 0x005F0000\nmode = "thumb"\n')
            self.assertEqual(cache_harvest.game_addrs(repo), {0x005F0000})


class PrologueScanTest(unittest.TestCase):
    def test_thumb_push_backscan_finds_prologue(self):
        rom = bytearray(0x400)
        struct.pack_into("<H", rom, 0x40, 0xB510)  # push {r4, lr}
        hits = misspack.prologue_scan(bytes(rom), misspack.ROM_BASE + 0x60,
                                      "thumb", limit=0x100)
        self.assertEqual(hits[0][0], misspack.ROM_BASE + 0x40)
        self.assertTrue(hits[0][1].startswith("push"))

    def test_no_prologue_returns_empty(self):
        hits = misspack.prologue_scan(bytes(0x400), misspack.ROM_BASE + 0x60,
                                      "thumb", limit=0x100)
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main(verbosity=1)
