#!/usr/bin/env python3
"""Host-side tests for the Python tooling (stdlib unittest, no pytest).

Covers the pure logic the FFTA harness depends on:
  - TsvGuardTests: symbols/*.tsv shape, alignment, duplicate discipline
  - RomTruthTests: ROM-pinned facts behind the symbol tables (LOCAL-ONLY,
    skips without game.gba) — dispatch tables, pointer cells, party base,
    SWI veneers
  - EmibiosBytePinTests: the COMMITTED launch BIOS (clean-room emibios,
    issue #17) byte-pinned at its contract points — exception vectors, the
    IRQ trampoline + 0x138 epilogue, the SWI dispatcher + its halfword
    table, the .vc_irqh handler — plus the recompile TOML's seed
    inventory. Runs EVERYWHERE (repo material, not a dump): CI included.
  - RegenStampContractTests: the .regen_stamp cross-script contract
    (build.py/cycle.py write it after a regen; build_apk.py's freshness
    gate reads it — corpus mtimes cannot date a regen)
  - ReleasePackTests: tools/make_release.py — the public-artifact sweep
    (ROM under any name, unpinned .bin, forbidden extensions, symlink,
    required set, exec bit) + the deterministic portable zip writer;
    driven on synthetic stages, so these run on CI tier 1 too

The framework-protocol tools' tests (trace_split, cache_harvest,
misspack) moved with the tools into gbarecompx/tools/tests/ — the fork's
CI guard job runs them.

Run: .venv/bin/python tests/python/test_tools.py [-v]
"""
import hashlib
import os
import pathlib
import re
import struct
import subprocess
import sys
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))


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


class BackendDefaultCacheTests(unittest.TestCase):
    """The product-build gate must reject a headless-configured canonical
    dir: build/ with GBARECOMP_RAYLIB_HEADLESS=ON is a windowless Memory
    build, not the raylib product, even though GBARECOMP_RAYLIB_ENABLED is
    still ON."""

    def predicate(self):
        import check
        return check.backend_default_cache_ok

    def test_product_cache_accepted(self):
        ok, _ = self.predicate()("GBARECOMP_RAYLIB_ENABLED:INTERNAL=ON\n"
                                  "GBARECOMP_RAYLIB_HEADLESS:BOOL=OFF\n")
        self.assertTrue(ok)

    def test_unset_headless_accepted(self):
        ok, _ = self.predicate()("GBARECOMP_RAYLIB_ENABLED:INTERNAL=ON\n")
        self.assertTrue(ok)

    def test_headless_cache_refused(self):
        ok, detail = self.predicate()(
            "GBARECOMP_RAYLIB_ENABLED:INTERNAL=ON\n"
            "GBARECOMP_RAYLIB_HEADLESS:BOOL=ON\n")
        self.assertFalse(ok)
        self.assertIn("HEADLESS", detail)

    def test_non_raylib_cache_refused(self):
        ok, _ = self.predicate()("GBARECOMP_RAYLIB_ENABLED:INTERNAL=OFF\n")
        self.assertFalse(ok)


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


class TsvGuardTests(unittest.TestCase):
    """symbols/*..tsv must stay machine-parseable: a malformed line or a
    non-identifier name breaks gba_recompile --symbols at regen time (or,
    worse, silently mislabels an emitted unit). Cheap structural sweep."""

    def _tsv_rows(self, path):
        rows = []
        for i, line in enumerate(path.read_text().splitlines(), 1):
            if not line or line.startswith("#"):
                continue
            rows.append((i, line.split("\t")))
        return rows

    def test_ffta_symbols_tsv_shape(self):
        path = REPO / "symbols" / "ffta_symbols.tsv"
        self.assertTrue(path.exists())
        for i, f in self._tsv_rows(path):
            self.assertEqual(len(f), 3, f"symbols line {i}: 3 fields")
            self.assertRegex(f[0], r"^0x[0-9A-Fa-f]{8}$",
                             f"symbols line {i}: address")
            self.assertIn(f[1].lower(), ("arm", "thumb"),
                          f"symbols line {i}: mode")
            self.assertRegex(f[2], r"^[A-Za-z_][A-Za-z_0-9]*$",
                             f"symbols line {i}: C identifier name")
            self.assertGreater(len(f[2]), 2, f"symbols line {i}: name")

    def test_ffta_data_symbols_tsv_shape(self):
        path = REPO / "symbols" / "ffta_data_symbols.tsv"
        self.assertTrue(path.exists())
        for i, f in self._tsv_rows(path):
            self.assertEqual(len(f), 4, f"data symbols line {i}: 4 fields")
            self.assertRegex(f[0], r"^0x[0-9A-Fa-f]{8}$",
                             f"data symbols line {i}: address")
            self.assertIn(f[1].lower(), ("ewram", "iwram", "rom", "pal", "oam",
                                         "vram", "sram", "bio", "irq"),
                          f"data symbols line {i}: region")
            self.assertRegex(f[2], r"^0x[0-9A-Fa-f]+$",
                             f"data symbols line {i}: size")
            self.assertRegex(f[3], r"^[A-Za-z_][A-Za-z_0-9]*$",
                             f"data symbols line {i}: C identifier name")

    def test_no_duplicate_symbol_names(self):
        seen = {}
        for name in ("ffta_symbols", "ffta_data_symbols"):
            path = REPO / "symbols" / f"{name}.tsv"
            for i, f in self._tsv_rows(path):
                sym, addr = f[-1], f[0]
                if sym in seen and seen[sym][0] != addr:
                    self.fail(f"duplicate name {sym} ({seen[sym][0]} vs "
                              f"{addr}, {name} line {i})")
                seen[sym] = (addr, name)

    def test_thumb_arm_alignment(self):
        # Mirrors cycle.py's dispatch sanity at the source: a thumb seed
        # must be even, an ARM seed 4-aligned. An odd address means a raw
        # interworking pointer slipped into the TSV.
        for name in ("ffta_symbols", "ffta_data_symbols"):
            path = REPO / "symbols" / f"{name}.tsv"
            for i, f in self._tsv_rows(path):
                addr = int(f[0], 16)
                if name == "ffta_symbols":
                    if f[1].lower() == "thumb":
                        self.assertEqual(addr & 1, 0,
                                         f"{name} line {i}: odd thumb {f[0]}")
                    else:
                        self.assertEqual(addr & 3, 0,
                                         f"{name} line {i}: misaligned arm "
                                         f"{f[0]}")

    def test_no_duplicate_symbol_addrs(self):
        # Two rows for one address split the debug meaning (and one of the
        # names silently loses in symbol_map.cpp). Four overlaps are
        # tolerated, all deliberate and documented in the TSVs: the three
        # accessor entries (function seed doubles as table label —
        # UnitStat/AbilityProp/AbilityMpCost, data-symbols § 3). The fourth
        # allowlist entry (0x085680DC gTextRandomUnitNames vs gNamePtrTableB,
        # same bytes two views) was collapsed to one row 2026-10-12.
        allowed = {"0X080C7EA4", "0X080CCD50", "0X0812ED98"}
        seen = {}
        for name in ("ffta_symbols", "ffta_data_symbols"):
            path = REPO / "symbols" / f"{name}.tsv"
            for i, f in self._tsv_rows(path):
                addr = f[0].upper()
                if addr in seen and addr not in allowed:
                    self.fail(f"duplicate address {f[0]} ({seen[addr]} vs "
                              f"{name} line {i})")
                seen.setdefault(addr, f"{name} line {i}")


class BiosBytePinTests(unittest.TestCase):
    """gba_bios.bin must stay byte-stable at the contract points our engine
    code cites. These exact words are pinned by armv4t runtime comments/logic
    (vector targets, the IRQ wrapper epilogue, the SWI dispatcher's
    System-mode service switch and epilogue — BRINGUP 2026-10-09); a
    replaced or patched BIOS silently invalidates them.

    NOTE (issue #17 swap): this is the RETAIL dump — local-only REFERENCE
    material (the launcher-accepted alternative + the oracle's default),
    no longer the launch BIOS. The launch BIOS is the committed clean-room
    emibios, pinned EVERYWHERE by EmibiosBytePinTests above. The dump is
    ROM/BIOS-derived and never in git (gbarecompx/.gitignore bios/*.bin)
    — these tests stay LOCAL-ONLY and skip on any checkout without it
    (CI included)."""

    BIOS = REPO / "gbarecompx" / "bios" / "gba_bios.bin"

    @classmethod
    def setUpClass(cls):
        if not cls.BIOS.exists():
            raise unittest.SkipTest(
                "gba_bios.bin absent (gitignored by design, never in git; "
                "local-only test)")

    def _u32(self, off):
        with self.BIOS.open("rb") as f:
            f.seek(off)
            return struct.unpack("<I", f.read(4))[0]

    def test_sha1_pin(self):
        import hashlib
        self.assertEqual(
            hashlib.sha1(self.BIOS.read_bytes()).hexdigest(),
            "300c20df6731a33952ded8c436f7f186d25d3492",
            "gba_bios.bin replaced/patched — every engine BIOS citation is "
            "now suspect")

    def test_vectors(self):
        # Exception vector table: B (0xEA...) targets computed from each slot.
        # 0x1C is the shared Undefined/Abort/FIQ handler's entry (not a B).
        cases = {0x00: 0x68, 0x08: 0x140, 0x18: 0x128, 0x1C: None}
        for off, target in cases.items():
            if target is not None:
                w = self._u32(off)
                self.assertEqual(w >> 24, 0xEA,
                                 f"vector at {off:#05x} not a B")
                self.assertEqual(off + 8 + ((w & 0xFFFFFF) << 2), target,
                                 f"vector at {off:#05x} target")

    def test_irq_wrapper_epilogue(self):
        # IRQ wrapper (0x128..): pop {r0-r3,ip,lr} then subs pc,lr,#4.
        self.assertEqual(self._u32(0x138), 0xE8BD500F, "IRQ pop")
        self.assertEqual(self._u32(0x13C), 0xE25EF004, "IRQ subs pc,lr,#4")

    def test_swi_dispatcher_service_switch_and_epilogue(self):
        # SWI dispatcher (0x140): switch to System mode for the service
        # (msr cpsr_fc), restore SVC, pop {fp,ip,lr}, movs pc,lr.
        self.assertEqual(self._u32(0x160), 0xE129F00B, "msr cpsr_fc,fp")
        self.assertEqual(self._u32(0x174), 0xE3A0C0D3, "mov ip,#0xd3")
        self.assertEqual(self._u32(0x184), 0xE8BD5800, "SWI pop")
        self.assertEqual(self._u32(0x188), 0xE1B0F00E, "SWI movs pc,lr")


class EmibiosBytePinTests(unittest.TestCase):
    """bios/emibios_gba_bios.bin — the LAUNCH BIOS since the issue #17
    swap — byte-pinned at the contract points the engine cites.

    Unlike BiosBytePinTests above (the retail dump: local-only, skips on
    CI), emibios is COMMITTED clean-room repo material (LGPL-3.0-or-later,
    bios/README.md), so these pins run EVERYWHERE — a fresh clone carries
    the file and a replaced/rebuilt-different emibios must fail loudly,
    not skip: it would silently invalidate the game.toml [bios] pin, the
    build.gradle biosSha1 manifest pin, the launcher pin-set acceptance,
    the corpus seeds' addresses/names, and the BIOS-address prose in
    reference/dev-gotchas.md. emibios deliberately mirrors retail's
    layout (its dispatcher.s documents the contract), so most pins share
    retail's addresses — but 0x1C differs (a real reserved handler at
    0x1FC, not retail's shared entry) and the SWI number is read from
    bits 23..16 (lr-2) instead of retail's low byte.

    Missing file = broken checkout (repo material): FAIL, never skip.
    """

    BIOS = REPO / "bios" / "emibios_gba_bios.bin"
    TOML = REPO / "bios" / "emibios_gba_bios.toml"
    SHA1 = "0c0d404d16c6b55b3071aba714f82077da132f14"
    # emibios main @c4d5d71 (LGPL-3.0-or-later; the only build these pins
    # have been derived against — a bump re-derives every one of them).

    @classmethod
    def setUpClass(cls):
        # Committed repo material: absence is a broken checkout, not the
        # local-only skip the retail dump takes.
        import hashlib
        if not cls.BIOS.is_file():
            raise AssertionError(
                "bios/emibios_gba_bios.bin missing — the committed "
                "clean-room BIOS (issue #17) is repo material; a "
                "checkout without it is broken, restore it")
        cls.data = cls.BIOS.read_bytes()

    def _u32(self, off):
        return struct.unpack_from("<I", self.data, off)[0]

    def _u16(self, off):
        return struct.unpack_from("<H", self.data, off)[0]

    def test_sha1_pin(self):
        import hashlib
        self.assertEqual(
            hashlib.sha1(self.data).hexdigest(), self.SHA1,
            "emibios replaced/rebuilt — every pin below and every config "
            "pin (game.toml [bios], build.gradle biosSha1, "
            "android_static EMIBIOS_SHA1) is now suspect")

    def test_size(self):
        self.assertEqual(len(self.data), 16384,
                         "not a 16 KiB BIOS image anymore")

    def test_vectors(self):
        # Exception vectors: B (0xEA...) targets computed from each slot.
        # 0x00/0x08/0x18 mirror retail deliberately; 0x1C is emibios's own
        # reserved handler (retail: shared Undefined/Abort/FIQ entry).
        cases = {0x00: 0x68, 0x08: 0x140, 0x18: 0x128, 0x1C: 0x1FC}
        for slot, target in cases.items():
            w = self._u32(slot)
            self.assertEqual(w >> 24, 0xEA,
                             f"vector at {slot:#05x} not a B")
            self.assertEqual(slot + 8 + ((w & 0xFFFFFF) << 2), target,
                             f"vector at {slot:#05x} target")

    def test_irq_trampoline(self):
        # IRQ wrapper 0x128..: push {r0-r3,ip,lr}; mov r0,#0x4000000;
        # add lr,pc,#0 (installs 0x138 as the handlers' runtime return
        # target — the `after_interrupt` seed); ldr pc,[r0,#-4] (jumps
        # the [0x03FFFFFC] mirror of [0x03007FFC]); pop; subs pc,lr,#4.
        words = {0x128: 0xE92D500F, 0x12C: 0xE3A00301,
                 0x130: 0xE28FE000, 0x134: 0xE510F004,
                 0x138: 0xE8BD500F, 0x13C: 0xE25EF004}
        for off, want in words.items():
            self.assertEqual(self._u32(off), want,
                             f"IRQ trampoline word at {off:#05x}")

    def test_swi_dispatcher(self):
        # SWI dispatcher 0x140..: push {fp,ip,lr}; ldrb ip,[lr,#-2]
        # (the number, bits 23..16 at lr-2 — the commercial `swi #(n<<16)`
        # encoding FFTA uses); table lookup via add/ldrh (base 0x194);
        # msr cpsr_fc (System-mode service switch, caller's IRQ/FIQ mask
        # carried); mov ip,#0xd3 (restore SVC); pop; movs pc,lr.
        words = {0x140: 0xE92D5800, 0x144: 0xE55EC002,
                 0x148: 0xE08FB08C, 0x14C: 0xE1DBC4B4,
                 0x160: 0xE129F00B, 0x174: 0xE3A0C0D3,
                 0x184: 0xE8BD5800, 0x188: 0xE1B0F00E}
        for off, want in words.items():
            self.assertEqual(self._u32(off), want,
                             f"SWI dispatcher word at {off:#05x}")

    def test_swi_table(self):
        # The halfword handler table at 0x194 (0x140+0x54), entries
        # 0x00..0x2A (43), mixed-mode (bit0 set = Thumb handler). Pinned
        # as a 44-halfword blob: 43 entries plus the boundary word, so a
        # table-size/extent change also fails here; the bounds check
        # covers the real entries only.
        import hashlib
        blob = bytes(struct.pack("<44H",
                                 *[self._u16(0x194 + 2 * i)
                                   for i in range(44)]))
        self.assertEqual(
            hashlib.sha1(blob).hexdigest(),
            "e1a8dd82c2b3a8062663990bc892da074cb46abf",
            "SWI handler table changed — re-derive the table pins (and "
            "the game.toml [[jump_table]] analog if one is seeded)")
        for i in range(43):
            t = self._u16(0x194 + 2 * i)
            self.assertLess(t, 0x4000,
                            f"SWI 0x{i:02X} target {t:#06x} out of image")

    def test_vc_irqh(self):
        # .vc_irqh at 0x3E74: emibios's own interim VBlank IRQ handler,
        # installed into [0x03007FFC] at runtime by boot_final_burn — the
        # statically-undiscoverable seed from the 2026-10-11 device-resume
        # harvest (game.toml extra_func of the same name).
        words = {0x3E74: 0xE3A03004, 0x3E78: 0xE1C130B2,
                 0x3E7C: 0xE3A03000, 0x3E80: 0xE1C130B8,
                 0x3E84: 0xE12FFF1E}
        for off, want in words.items():
            self.assertEqual(self._u32(off), want,
                             f".vc_irqh body word at {off:#06x}")

    def test_toml_seed_inventory(self):
        # The recompile TOML must keep the essential dispatch seeds — the
        # runtime-critical vectors, the trampoline epilogue, and the two
        # statically-undiscoverable fragments. Accidental deletion of any
        # one breaks strict-static on the next regen; this fails first,
        # with the name attached.
        text = self.TOML.read_text(encoding="utf-8")
        entries = {}
        for block in text.split("[[extra_func]]")[1:]:
            ma = re.search(r'addr\s*=\s*(0x[0-9A-Fa-f]+)', block)
            mn = re.search(r'name\s*=\s*"([^"]+)"', block)
            if ma and mn:
                entries[int(ma.group(1), 16)] = mn.group(1)
        for addr, name in ((0x00000000, "bios_reset_vector"),
                           (0x00000008, "bios_swi_vector"),
                           (0x00000018, "bios_irq_vector"),
                           (0x00000068, "exception_reset"),
                           (0x00000128, "exception_irq"),
                           (0x00000138, "after_interrupt"),
                           (0x00003E74, "vc_irqh")):
            self.assertEqual(
                entries.get(addr), name,
                f"bios/emibios_gba_bios.toml seed {name} @ {addr:#010x} "
                "missing or renamed — strict-static breaks on regen")


class RegenStampContractTests(unittest.TestCase):
    """The .regen_stamp contract spans three scripts (2026-10-11): build.py
    and tools/cycle.py stamp generated/ after a regen; build_apk.py's
    freshness gate reads it. Corpus mtimes cannot date a regen — the
    recompiler (commit_generated_file) preserves them for byte-identical
    output, so the pre-fix gate said 'stale' forever after a
    content-neutral game.toml touch. A rename in any one script breaks the
    other two silently; pin the token everywhere it appears, and keep the
    gate from ever comparing an emitted corpus file's own mtime again.
    """

    def test_stamp_writers_and_reader_agree(self):
        for script in ("build.py", "tools/cycle.py", "build_apk.py"):
            text = (REPO / script).read_text(encoding="utf-8")
            self.assertIn('".regen_stamp"', text,
                          "%s must use the .regen_stamp token — the "
                          "regen-date contract shared with build.py, "
                          "cycle.py and build_apk.py" % script)

    def test_freshness_inputs_are_regen_inputs_only(self):
        text = (REPO / "build_apk.py").read_text(encoding="utf-8")
        m = re.search(r"FRESHNESS_INPUTS = \((.*?)\)", text, re.S)
        self.assertTrue(m, "FRESHNESS_INPUTS missing from build_apk.py")
        self.assertNotIn("generated", m.group(1),
                         "FRESHNESS_INPUTS must not compare emitted corpus "
                         "mtimes (the recompiler preserves them for "
                         "byte-identical output — the 2026-10-11 lesson); "
                         "the .regen_stamp is the regen date")


class RomTruthTests(unittest.TestCase):
    """game.gba words pinned behind symbols/*.tsv rows (BRINGUP 2026-10-11).

    Every value here was read from the ROM during the Event-Editor /
    Engine-Hacks import and cross-checked against vanilla code. The pins
    exist so the two traps found then can never silently regress: the
    editor's EUR handler addresses (importing one breaks the table-hash
    and handler-membership tests) and the inherited 0x02000000 party base
    (moving gPartyUnits back breaks the literal pins). LOCAL-ONLY like
    BiosBytePinTests: skips without game.gba (CI included)."""

    ROM = REPO / "game.gba"
    SCENE_TABLE = 0x083A7EE4  # 115 entries x (u16 size, u32 thumb handler)
    COND_TABLE = 0x0836D5A4  # 17 entries x (u16 size, u32 thumb handler)

    @classmethod
    def setUpClass(cls):
        if not cls.ROM.exists():
            raise unittest.SkipTest("game.gba absent (local-only test)")
        cls.rom = cls.ROM.read_bytes()

    def _u16(self, addr):
        return struct.unpack_from("<H", self.rom, addr - 0x08000000)[0]

    def _u32(self, addr):
        return struct.unpack_from("<I", self.rom, addr - 0x08000000)[0]

    def _table_handlers(self, base, count):
        return {self._u32(base + i * 6 + 2) & ~1 for i in range(count)}

    def test_vm_dispatch_tables_hash(self):
        # Both opcode dispatch tables byte-for-byte (sizes + handlers).
        # Entry 0x72 of the scene table is garbage in-ROM; it is included
        # because the pin is over bytes, not semantics.
        import hashlib
        blob = (self.rom[0x3A7EE4:0x3A7EE4 + 115 * 6]
                + self.rom[0x36D5A4:0x36D5A4 + 17 * 6])
        self.assertEqual(
            hashlib.sha256(blob).hexdigest(),
            "91c1ce0d51b1882da5d6e3b3eb2edca7d520b7ab319e5baa33145bba4604686a",
            "event VM dispatch tables changed — every scene_*/cond_* row "
            "and gSceneOpcodeTable/gCondOpcodeTable is now suspect")

    def test_tsv_handlers_in_rom_tables(self):
        # Each scene_*/cond_* TSV row must name a handler the ROM tables
        # actually dispatch to (even entry address; table holds thumb +1).
        # An EUR address can never satisfy this.
        handlers = (self._table_handlers(self.SCENE_TABLE, 114)
                    | self._table_handlers(self.COND_TABLE, 17))
        rows = 0
        for line in (REPO / "symbols" / "ffta_symbols.tsv"
                     ).read_text().splitlines():
            if not line or line.startswith("#"):
                continue
            addr_s, _, name = line.split("\t")[:3]
            if not (name.startswith("scene_") or name.startswith("cond_")):
                continue
            if name == "scene_gfx_load":
                continue  # not a VM handler (scene-load pipeline, § 14)
            rows += 1
            self.assertIn(int(addr_s, 16), handlers,
                          f"{name} {addr_s} not a ROM table handler")
        self.assertGreater(rows, 100, "scene_/cond_ rows went missing?")

    def test_event_pointer_cells(self):
        # USA cells (the EUR cells at 0x08009AAC/0x08125ED0/0x0800A234 hold
        # region garbage — correctly excluded from the data symbols).
        cases = {0x08009A20: 0x08A19970,  # gEventListPtrCell
                 0x081223C0: 0x089A5D54,  # gSceneBanksPtrCell
                 0x0800A148: 0x08A1A908,  # gCondTypeListPtrCell
                 0x08009A88: 0x089C1484}  # gTextBankEnPtrCell
        for cell, target in cases.items():
            self.assertEqual(self._u32(cell), target,
                             f"pointer cell {cell:#010x}")

    def test_event_list_pad_bytes(self):
        # 234 x {script, scene, text, pad}; pad must be 0 (gEventList 0x3A8).
        for i in range(234):
            self.assertEqual(self.rom[0xA19970 + i * 4 + 3], 0,
                             f"event {i} pad byte")

    def test_party_base_literals(self):
        # The mission-end heal loop bases its 24x0x108 party walk at
        # 0x02000080 (never 0x02000000): pool words of 0x0802D824/0x0802D934.
        self.assertEqual(self._u32(0x0802D878), 0x02000080)
        self.assertEqual(self._u32(0x0802D9E4), 0x02000080)
        # Enemy loop base: 0x02000080 + 0x2F44 = gFirstEnemyUnit.
        self.assertEqual(self._u32(0x0802D9F8), 0x00002F44)
        # UnitStat dispatcher reads its table base from 0x080C7EBC, and
        # index-0 (name) reads struct+0x00 — the corrected framing.
        self.assertEqual(self._u32(0x080C7EBC), 0x080C7EC0)
        self.assertEqual(self._u16(0x080C7FD4), 0x6810, "ldr r0,[r2]")

    def test_swi_veneer_table(self):
        # 0x08141860+: (svc #N, bx lr) pairs; 0x0814186C = SWI 0x0B = CpuSet
        # (NOT CpuFastSet — the fill-mode bit24 calls prove it).
        for addr, svc in ((0x08141860, 0x0A), (0x08141864, 0x0E),
                          (0x08141868, 0x0C), (0x0814186C, 0x0B)):
            self.assertEqual(self._u16(addr), 0xDF00 | svc,
                             f"veneer {addr:#010x} svc imm")
            self.assertEqual(self._u16(addr + 2), 0x4770,
                             f"veneer {addr:#010x} bx lr")


class ReleasePackTests(unittest.TestCase):
    """tools/make_release.py — the public-artifact packager (issue #3, R1).

    sweep_stage() is the contract that keeps a public release free of
    private material: ROM bytes under ANY name, a .bin that is not the
    pinned clean-room BIOS (a retail dump), forbidden extensions,
    symlinks, a de-exec'd binary, a missing required file. The zip writer
    must be deterministic and portable (fixed timestamps, sorted entries,
    forward-slash names, permissions preserved) so CI can hash releases.

    Everything runs against synthetic stages (the real committed BIOS
    copied in — repo material, present everywhere): no build tree needed,
    so these run on CI tier 1. The live `check.py --only release` suite
    packages the real build on a full tree (tier 2/local).
    """

    @classmethod
    def setUpClass(cls):
        import make_release  # noqa: E402 (tools/ on sys.path)
        cls.mr = make_release

    def _stage(self, td, platform="linux"):
        """Minimal passing stage: the required set, nothing else."""
        root = pathlib.Path(td) / "stage"
        root.mkdir(parents=True)
        exe = "FFTARecomp.exe" if platform == "windows" else "FFTARecomp"

        def f(rel, data=b"x"):
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
            p.chmod(0o755 if rel == exe else 0o644)

        f(exe)
        f("game.toml")
        f("recomplauncher.json")
        # The real committed BIOS at its pin: the one .bin the sweep allows.
        f("bios/emibios_gba_bios.bin",
          (REPO / "bios/emibios_gba_bios.bin").read_bytes())
        f("bios/README.md")
        f("README.md")
        f("LICENSE")
        # EVERY staged license document (licenses_required() in
        # tools/make_release.py) — the set grew with the Windows release,
        # so build it from the contract, never by hand-counting paths.
        for lic in self.mr.licenses_required():
            if lic != "LICENSE":
                f(lic)
        f("THIRD_PARTY_ATTRIBUTION.md")
        f("mods/packages/ffta.enhancement.widescreen/1.0.1/manifest.toml")
        f("assets/fonts/Pro.ttf")
        f("assets/img/box.png")
        return root

    def test_sweep_clean(self):
        import tempfile
        with tempfile.TemporaryDirectory(dir="/tmp") as td:
            root = self._stage(td)
            self.assertEqual(self.mr.sweep_stage(root), [])

    def test_sweep_windows_clean(self):
        # The R2 windows stage: same layout, same rules, the .exe name —
        # and the bare linux binary must FAIL there (not the required exe).
        import tempfile
        with tempfile.TemporaryDirectory(dir="/tmp") as td:
            root = self._stage(td, platform="windows")
            self.assertEqual(self.mr.sweep_stage(root, platform="windows"),
                             [])
            (root / "FFTARecomp.exe").unlink()
            (root / "FFTARecomp").write_bytes(b"x")
            v = self.mr.sweep_stage(root, platform="windows")
            self.assertTrue(
                any("missing required file: FFTARecomp.exe" in x for x in v),
                v)

    def test_static_link_guard(self):
        # Pure core of the --windows static-link gate: synthetic objdump
        # output → forbidden DLLs flagged, system DLLs clean.
        fake_objdump = """
FFTARecomp.exe:     file format pei-x86-64

The Import Tables (interpreted .idata section contents)
vma:            Hint    Time      Forward  DLL       First
                Table   Stamp     Chain    Name      Thunk
...
\tDLL Name: KERNEL32.dll
\tDLL Name: USER32.dll
\tDLL Name: GDI32.dll
\tDLL Name: SDL2.dll
\tDLL Name: libgcc_s_seh-1.dll
"""
        dlls = self.mr.parse_import_dlls(fake_objdump)
        self.assertEqual(
            sorted(dlls),
            ["GDI32.DLL", "KERNEL32.DLL", "LIBGCC_S_SEH-1.DLL", "SDL2.DLL",
             "USER32.DLL"])
        bad = self.mr.static_link_violations(dlls)
        self.assertEqual(bad, ["LIBGCC_S_SEH-1.DLL"])
        clean = {"KERNEL32.DLL", "MSVCRT.DLL", "USER32.DLL", "ADVAPI32.DLL",
                 "SHELL32.DLL", "OPENGL32.DLL", "VERSION.DLL"}
        self.assertEqual(self.mr.static_link_violations(clean), [])

    def test_sweep_requires_recomplauncher_manifest(self):
        # Every release ships the launcher profile; a stage without it
        # must be rejected, not silently packaged.
        import tempfile
        with tempfile.TemporaryDirectory(dir="/tmp") as td:
            root = self._stage(td)
            (root / "recomplauncher.json").unlink()
            v = self.mr.sweep_stage(root)
            self.assertTrue(
                any("missing required file: recomplauncher.json" in x
                    for x in v), v)

    def test_recomplauncher_manifest_starts_staged_executables(self):
        # The committed profile must name the executables the packager
        # stages (the .exe, the Linux binary) and pass the ROM by path.
        import json
        manifest = json.loads((REPO / "recomplauncher.json").read_text())
        self.assertEqual(manifest["format"], 1)
        program = manifest["start"]["program"]
        self.assertIn("FFTARecomp.exe", program)
        self.assertIn("FFTARecomp", program)
        self.assertEqual(manifest["start"]["args"], ["--rom", "{input:rom}"])

    def test_sweep_rejects_gba(self):
        import tempfile
        with tempfile.TemporaryDirectory(dir="/tmp") as td:
            root = self._stage(td)
            (root / "final_fantasy.gba").write_bytes(b"ROM")
            v = self.mr.sweep_stage(root)
            self.assertTrue(any("forbidden extension" in x for x in v), v)

    def test_sweep_rejects_unpinned_bin(self):
        import tempfile
        with tempfile.TemporaryDirectory(dir="/tmp") as td:
            root = self._stage(td)
            (root / "bios/other.bin").write_bytes(b"NOPE")
            v = self.mr.sweep_stage(root)
            self.assertTrue(
                any("not the pinned clean-room BIOS" in x for x in v), v)

    def test_sweep_rejects_disguised_rom(self):
        # The hash rule catches renamed material: patch the ROM pin to the
        # digest of a planted payload under an innocent name.
        import hashlib
        import tempfile
        with tempfile.TemporaryDirectory(dir="/tmp") as td:
            root = self._stage(td)
            payload = b"pretend this is rom bytes"
            (root / "harmless.txt").write_bytes(payload)
            old = self.mr.ROM_SHA1
            self.mr.ROM_SHA1 = hashlib.sha1(payload).hexdigest()
            try:
                v = self.mr.sweep_stage(root)
            finally:
                self.mr.ROM_SHA1 = old
            self.assertTrue(any("disguised name" in x for x in v), v)

    def test_sweep_rejects_retail_bios_bytes(self):
        # Same code path for the retail-dump pin (the launcher-accepted
        # local alternative — it must never enter a public artifact).
        import hashlib
        import tempfile
        with tempfile.TemporaryDirectory(dir="/tmp") as td:
            root = self._stage(td)
            payload = b"pretend these are retail bios bytes"
            (root / "keep.dat").write_bytes(payload)
            old = self.mr.RETAIL_BIOS_SHA1
            self.mr.RETAIL_BIOS_SHA1 = hashlib.sha1(payload).hexdigest()
            try:
                v = self.mr.sweep_stage(root)
            finally:
                self.mr.RETAIL_BIOS_SHA1 = old
            self.assertTrue(any("retail BIOS dump" in x for x in v), v)

    def test_sweep_rejects_symlink(self):
        import tempfile
        with tempfile.TemporaryDirectory(dir="/tmp") as td:
            root = self._stage(td)
            os.symlink("/etc/passwd", root / "escape")
            v = self.mr.sweep_stage(root)
            self.assertTrue(any("symlink" in x for x in v), v)

    def test_sweep_requires_binary_exec_bit(self):
        import tempfile
        with tempfile.TemporaryDirectory(dir="/tmp") as td:
            root = self._stage(td)
            (root / "FFTARecomp").chmod(0o644)
            v = self.mr.sweep_stage(root)
            self.assertTrue(any("exec bit" in x for x in v), v)

    def test_sweep_requires_readme(self):
        import tempfile
        with tempfile.TemporaryDirectory(dir="/tmp") as td:
            root = self._stage(td)
            (root / "README.md").unlink()
            v = self.mr.sweep_stage(root)
            self.assertTrue(any("missing required file: README.md" in x
                                for x in v), v)

    def test_sweep_requires_license_bundle(self):
        # The release redistributes statically-linked code, so its license
        # documents ship (the set: root LICENSE + LGPL + one document per
        # linked third-party library). Missing exactly one → named failure.
        # The victim is picked from the module contract (licenses_required())
        # so a future license-set change edits one place, not this test.
        import tempfile
        with tempfile.TemporaryDirectory(dir="/tmp") as td:
            root = self._stage(td)
            victim = next(p for p in self.mr.licenses_required()
                          if p.startswith("LICENSES/"))
            (root / victim).unlink()
            v = self.mr.sweep_stage(root)
            self.assertTrue(
                any(f"missing required file: {victim}" in x for x in v), v)
            # ...and the synthetic helper itself builds the bundle from the
            # module contract, so the next license addition fails loudly
            # instead of drifting:
            got = sorted(str(REPO / p) for p in self.mr.licenses_required())
            staged = sorted(str(root / p) for p in self.mr.licenses_required())
            self.assertEqual(len(got), len(staged))

    def test_license_bundle_covers_licenses_dir(self):
        # The sweep contract must cover every document in LICENSES/ (minus
        # the root LICENSE, which lives beside it): a fifth license text
        # dropped into the dir with no sweep entry fails HERE, not silent
        # in a shipped zip.
        on_disk = {p.relative_to(REPO).as_posix()
                   for p in (REPO / "LICENSES").glob("*.txt")}
        covered = {p for p in self.mr.licenses_required()
                   if p.startswith("LICENSES/")}
        self.assertEqual(
            covered, on_disk,
            "LICENSES/ holds documents the sweep does not require — add "
            "them to required_files() in tools/make_release.py (and to "
            "THIRD_PARTY_ATTRIBUTION.md)")

    def test_zip_deterministic_portable(self):
        import hashlib
        import tempfile
        with tempfile.TemporaryDirectory(dir="/tmp") as td:
            root = self._stage(td)
            z1 = pathlib.Path(td) / "a.zip"
            z2 = pathlib.Path(td) / "b.zip"
            n1 = self.mr.write_portable_zip(root, "FFTARecomp-x", z1)
            n2 = self.mr.write_portable_zip(root, "FFTARecomp-x", z2)
            self.assertEqual(n1, n2)
            self.assertEqual(
                hashlib.sha1(z1.read_bytes()).hexdigest(),
                hashlib.sha1(z2.read_bytes()).hexdigest(),
                "same tree, same zip bytes — releases must be hashable")
            self.assertEqual(self.mr.verify_zip(z1, n1), [],
                             "read-back: portable names, count, exec bit")



class AppImageTests(unittest.TestCase):
    """tools/make_appimage.py + tools/compat_build.py pure contracts.

    The AppImage's two non-obvious promises are testable without building
    or downloading anything: the AppRun wrapper must unpack into a
    writable XDG data directory (the game writes sidecars beside its
    executable) and must not delete player files on an update; the glibc
    validator must reject a symbol floor newer than the SteamOS target.
    """

    @classmethod
    def setUpClass(cls):
        import compat_build  # noqa: E402 (tools/ on sys.path)
        import make_appimage  # noqa: E402
        cls.ai = make_appimage
        cls.cb = compat_build

    def test_apprun_uses_writable_xdg_data_dir(self):
        s = self.ai.apprun_script("v1.7-deadbeef")
        self.assertIn("XDG_DATA_HOME", s)
        self.assertIn('DATA_ROOT="$XDG_DATA_HOME/ffta-recomp"', s)
        self.assertIn('DEST="$DATA_ROOT/app"', s)
        self.assertIn('cp -a "$APPDIR/usr/bin/." "$DEST/"', s)
        self.assertIn('exec "$DEST/FFTARecomp" "$@"', s)

    def test_apprun_update_preserves_player_files(self):
        s = self.ai.apprun_script("v1.7-deadbeef")
        # Updates copy the payload over the data dir; they must not wipe
        # rom.cfg/config.ini/saves/ (the reason the wrapper exists).
        self.assertNotIn('rm -rf "$DEST"', s)
        self.assertIn("player files", s)

    def test_apprun_steam_deck_defaults(self):
        s = self.ai.apprun_script("v1.7-deadbeef")
        self.assertIn('"${SteamDeck:-0}" = "1"', s)
        self.assertIn("--fullscreen=1 --resize-view", s)
        self.assertIn("FFTA_APPIMAGE_NO_DECK_DEFAULTS", s)
        self.assertIn('*" --fullscreen"*', s)

    def test_desktop_entry(self):
        d = self.ai.desktop_entry("v1.7")
        for line in ("Type=Application", "Name=FFTA Recomp",
                     "Exec=FFTARecomp", "Icon=ffta-recomp",
                     "Categories=Game;", "X-AppImage-Version=v1.7"):
            self.assertIn(line, d)

    def test_payload_id_is_content_addressed(self):
        import tempfile
        with tempfile.TemporaryDirectory(dir="/tmp") as td:
            root = pathlib.Path(td)
            (root / "a").write_bytes(b"one")
            (root / "sub").mkdir()
            (root / "sub" / "b").write_bytes(b"two")
            first = self.ai.payload_id(root)
            self.assertEqual(first, self.ai.payload_id(root))
            self.assertEqual(len(first), 12)
            (root / "sub" / "b").write_bytes(b"changed")
            self.assertNotEqual(first, self.ai.payload_id(root))

    def test_glibc_version_parser(self):
        text = ("  (GLIBC_2.34) foo\n  (GLIBC_2.2.5) bar\n"
                "  (GLIBC_2.43) baz\n")
        self.assertEqual(self.cb.parse_glibc_versions(text),
                         [(2, 2), (2, 34), (2, 43)])
        self.assertEqual(self.cb.version_tuple("2.36"), (2, 36))
        with self.assertRaises(self.cb.Fail):
            self.cb.version_tuple("debian")

    def test_glibc_floor_is_a_real_release_check(self):
        # The exact failure that made the compat container necessary:
        # a CachyOS build advertised GLIBC_2.43. The validator must treat
        # anything above the pinned floor as a hard failure.
        text = "  (GLIBC_2.43) atan2f\n"
        versions = self.cb.parse_glibc_versions(text)
        self.assertGreater(versions[-1], self.cb.version_tuple("2.36"))


class PublishReleaseTests(unittest.TestCase):
    """tools/publish_release.py — local build/verify/upload contract."""

    @classmethod
    def setUpClass(cls):
        import publish_release
        cls.pr = publish_release

    def test_artifact_names(self):
        n = self.pr.artifact_names("v1.7")
        self.assertEqual(n["linux"], "FFTARecomp-v1.7-linux-x64.zip")
        self.assertEqual(n["windows"], "FFTARecomp-v1.7-windows-x64.zip")
        self.assertEqual(n["appimage"],
                         "FFTARecomp-v1.7-linux-x86_64.AppImage")
        self.assertEqual(n["apk"],
                         "FFTARecomp-v1.7-android-arm64-v8a.apk")

    def test_sums_text_is_sorted_and_sha256(self):
        import tempfile
        with tempfile.TemporaryDirectory(dir="/tmp") as td:
            a = pathlib.Path(td) / "b.bin"
            b = pathlib.Path(td) / "a.bin"
            a.write_bytes(b"one")
            b.write_bytes(b"two")
            text = self.pr.sums_text([a, b])
            self.assertEqual([line.split("  ")[1] for line in
                              text.strip().splitlines()], ["a.bin", "b.bin"])
            self.assertIn(hashlib.sha256(b"one").hexdigest(), text)


if __name__ == "__main__":
    unittest.main(verbosity=1)


