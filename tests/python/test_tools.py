#!/usr/bin/env python3
"""Host-side tests for the Python tooling (stdlib unittest, no pytest).

Covers the pure logic the healing/audit flow depends on:
  - trace_split: backward-jump segmentation + header preservation
  - cache_harvest: recomp_cache unit-file parsing + game.toml address set
  - misspack.prologue_scan: thumb push-with-lr backscan on a synthetic ROM

Run: .venv/bin/python tests/python/test_tools.py [-v]
Requires capstone (misspack dependency): use .venv per README setup, or
`pip install capstone==5.0.7` — CI installs that same pin.
"""
import pathlib
import struct
import subprocess
import sys
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

try:
    import cache_harvest  # noqa: E402
    import misspack  # noqa: E402
except ModuleNotFoundError as exc:
    if exc.name == "capstone":
        raise SystemExit(
            "unit-py needs capstone (misspack dependency): run via "
            ".venv/bin/python (README setup) or `pip install "
            "capstone==5.0.7`") from None
    raise


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


class SaveCheckTest(unittest.TestCase):
    """savecheck.py end-to-end on synthetic saves (real-ROM checksum table)."""

    @classmethod
    def setUpClass(cls):
        if not (REPO / "game.gba").exists():
            raise unittest.SkipTest("game.gba missing (checksum table needed)")
        sys.path.insert(0, str(REPO / "tools"))
        import savecheck
        savecheck.crc_tab = savecheck.load_crc_table()
        cls.savecheck = savecheck

    def _raw_save(self):
        """Valid 64 KiB image: header group in sectors 3..0 (header = 3)."""
        f = bytearray(0x10000)
        for i in range(16):
            for j in range(0, 0x1000, 16):
                f[i * 0x1000 + j] = (i * 7 + j) & 0xFF
        hdr = 3 * 0x1000
        f[hdr:hdr + 8] = b"FFTEX000"
        struct.pack_into("<I", f, hdr + 0x08, 7)      # counter
        struct.pack_into("<I", f, hdr + 0x0C, 0)      # checksum placeholder
        f[hdr + 0x12:hdr + 0x16] = bytes([3, 2, 1, 0])
        group = bytes().join(bytes(f[s * 0x1000:(s + 1) * 0x1000])
                             for s in (3, 2, 1, 0))
        struct.pack_into("<I", f, hdr + 0x0C, self.savecheck.group_checksum(group))
        return f

    def _run(self, td, data, name="t.sav"):
        p = pathlib.Path(td) / name
        p.write_bytes(data)
        return subprocess.run([sys.executable, "tools/savecheck.py", str(p)],
                              cwd=str(REPO), capture_output=True, text=True)

    def test_valid_save_ok(self):
        with tempfile.TemporaryDirectory() as td:
            r = self._run(td, bytes(self._raw_save()))
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("checksum=0x", r.stdout)
            self.assertIn("OK", r.stdout)

    def test_corrupted_group_flagged(self):
        with tempfile.TemporaryDirectory() as td:
            data = self._raw_save()
            data[0x1100] ^= 0xFF  # sector 1, inside the checksummed 0x2FC4 prefix
            r = self._run(td, bytes(data))
            self.assertEqual(r.returncode, 1)
            self.assertIn("MISMATCH", r.stdout)

    def test_rtn5_container_ok_and_crc_flagged(self):
        import zlib
        raw = bytes(self._raw_save())
        payload = zlib.compress(raw)
        hdr = struct.pack("<IHHIIII", 0x354E5452, 1, 1, len(raw),
                          len(payload), 24, zlib.crc32(raw) & 0xFFFFFFFF)
        with tempfile.TemporaryDirectory() as td:
            r = self._run(td, hdr + payload, "c.sav")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("RTN5", r.stdout)
            bad = bytearray(hdr + payload)
            bad[20] ^= 0xFF  # corrupt the stored CRC32
            r2 = self._run(td, bytes(bad), "bad.sav")
            self.assertEqual(r2.returncode, 1)
            self.assertIn("CRC32 mismatch", r2.stdout)


class BuildPyTest(unittest.TestCase):
    """Root bootstrap script stays runnable on the system python (stdlib)."""

    def test_help_runs(self):
        r = subprocess.run([sys.executable, "build.py", "--help"],
                           cwd=str(REPO), capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("--force", r.stdout)
        self.assertIn("--no-smoke", r.stdout)


class RepoHygieneTests(unittest.TestCase):
    """Tracked files must stay portable: no absolute home-directory paths
    (they leak the author's layout and break on every other checkout)."""

    def test_no_absolute_home_paths(self):
        if not (REPO / ".git").exists():
            self.skipTest("not a git checkout")
        # git grep exits 1 when there are no matches (the good case).
        # The pathspec excludes THIS file: its source necessarily contains
        # the pattern string and would otherwise match itself.
        r = subprocess.run(
            ["git", "-C", str(REPO), "grep", "-n", "-I", "-E",
             r"/home/|/Users/", "--", ".",
             ":(exclude)tests/python/test_tools.py"],
            capture_output=True, text=True)
        self.assertIn(r.returncode, (0, 1), r.stderr)
        if r.returncode == 0:
            self.fail("absolute home paths in tracked files:\n" + r.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=1)
