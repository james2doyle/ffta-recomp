# BRINGUP.md — FFTA Recomp bring-up log

Decision log for the static recompilation of Final Fantasy Tactics Advance (US)
to native PC via [mstan/gbarecomp](https://github.com/mstan/gbarecomp).
Ground rules live in `AGENTS.md` (§ Ground rules).

Legend: every ROM claim below was verified by disassembly/slicing of `game.gba`
via capstone (`tools/disarm.py`) or direct byte inspection; addresses are
GBA bus addresses (ROM base 0x08000000). Evidence follows each claim.

---

## 2026-10-06 — Phase 0: ROM recon (COMPLETE)

### ROM identity
| Field | Value | Evidence |
|---|---|---|
| Size | 16,777,216 bytes (16 MiB, exact) | `stat game.gba` |
| SHA-1 | `4ac05441f4de70a4ec3dd932116346c61b8783d9` | `sha1sum` |
| MD5 | `cd99cdde3d45554c1b36fbeb8863b7bd` | `md5sum` |

### Cartridge header (0xA0–0xBF)
| Field | Value |
|---|---|
| Title (0xA0–0xAB) | `FFTA_USVER.` (ASCII, null-padded) |
| Game code (0xAC–0xAF) | **AFXE** (US) |
| Maker code (0xB0–0xB1) | `01` |
| Fixed value 0xB2 | 0x96 (correct) |
| Software version (0xBD) | 0x89 (unusual — most carts are 0x00/0x01) |
| Complement check | **PASSES** — sum(0xA0..0xBD)+0x19+rom[0xBE] ≡ 0 (mod 256) |

Note: `complement_valid` computed by gbarecomp's `gba_scan` should be re-run
once the submodule is checked out; my independent check passes.

### Entry point (verified by disassembly)
- `0x08000000: ea00002e  b 0x080000C0` — ROM word 0 = ARM branch to crt0.
- **entry_pc = 0x080000C0** (ARM).

### crt0 (0x080000C0–0x080000F0), ARM
- `mov r0,#0x12; msr cpsr,r0` (0x080000C0) — enter IRQ mode, sp=IRQ stack.
  `ldr sp,[pc,#0x28]` (0x080000C8) → literal 0xF4 = **0x03007EC0**.
- `mov r0,#0x1f; msr cpsr,r0` (0x080000CC) — enter SYS mode, sp=SYS stack.
  `ldr sp,[pc,#0x18]` (0x080000D4) → literal 0xF8 = **0x03007FA0**.
- `ldr r1,[pc,#0x15c]` (0x080000D8) → literal 0x23C = **0x03007FFC** (BIOS IRQ
  vector at top of IWRAM, as per GBA BIOS contract).
- `add r0,pc,#0x18` (0x080000DC) → **0x080000FC**; `str r0,[r1]` (0x080000E0) —
  installs ROM IRQ dispatcher (at 0x080000FC) into 0x03007F­FC.
- `ldr r1,[pc,#0x154]` (0x080000E4) → literal 0x240 = **0x08000255** (Thumb,
  LSB=1). `mov lr,pc; bx r1` (0x080000E8–EC) — jumps to Thumb **main at
  0x08000254**.
- `b 0x080000C0` (0x080000F0) — infinite loop on return (main never returns).

### IRQ dispatcher (ROM 0x080000FC, ARM) — important for recomp IRQ handling
Reads `0x04000202` (IF) — actually via `mov r3,#0x04000000; add r3,#0x200;
ldr r2,[r3]` (0x080000FC–0x08000110): standard masked-IF read at 0x04000200/02.
- `and`/`lsr` decode of IF bits (0x08000108–0x0800017C): V-Blank → handler
  `bl 0x08000188`? No — V-Blank branch target: 0x0800018C; H-Blank →
  0x080001E4; gamepad? — see below.
- V-Blank path (0x0800018C): acknowledges IF at `[r3,#2]` (0x04000202). 0x08000190 `ldr r0,[pc,#0xb0]` → literal @0x248 = **0x03000E50**; `ldr r1,[r0]` → loads callback from table at 0x03000E50; `strh r1,[r3]` (0x08000198) acknowledges IF at 0x04000200. Then `mrs/msr` restore to mode 0x1F (SYS).
- H-Blank path (0x080001E4): `strh r0,[r3,#2]` — ack at 0x04000202, `mov r1,#0`, `strh r1,[r3]` — clear IF at 0x04000200. 0x080001AC `ldr r1,[pc,#0x98]` → literal @0x248 = **0x03000E50**; `add r1,r1,r2` (r2 = sub-handler offset, multiples of 4) → `ldr r0,[r1]`; `stmdb sp!,{lr}; add lr,pc,#0; bx r0` (0x080001B8–C0) — indexed callback dispatch into the H-Blank slot of the same table.
- **IRQ callback table base: 0x03000E50 (IWRAM), 4-byte stride per IRQ source; V-Blank uses slot [0], H-Blank slot offset by r2.** Both paths share the 0x03000E50 table.

### main() = 0x08000254 (Thumb) — first 0x50 bytes disassembled
- `push {r7,lr}`, `mov r7,sp`, register init via literals, then init calls:
  `bl 0x08000A48`, `bl 0x0800105C`, `bl 0x081414BC` (deep init chain).
- Boot handoff `bx r1` targets literal 0x08000255 (LSB=1) → Thumb **main at 0x08000254**.

### m4a / MusicPlayer2000 (Sappy) sound driver — DETECTED
- Method: faithful Python port of Bregalad/loveemu's sappy_detector logic
  (`tools/m4a_detect.py`), both library generations of the SelectSong prologue
  pattern; old-library encoding matched at file offset 0x1451C0. Cross-checked
  against the berg8793/gba-mus-ripper fork — its detector is byte-identical.
- **SelectSong at ROM 0x081451C0** (old-library encoding).
- Song table pointer word (at selectsong+0x28): **0x0814BB48**; first 12 entries
  verified valid (each 8-byte entry: song header ptr + u32 0; headers start
  `0c 00 01 a8 ...` — valid MP2K song headers, e.g. [1] → 0x0814CF48).
- Engine header 16/32 bytes before m4a-main: **absent/invalid** at both offsets —
  FFTA's build is "headerless" (like Metroid per Bregalad's FAQ; the detector
  reports "Only a partial sound engine was found"). Engine params live in the
  driver code — follow-up in Phase 4 audit; song table + SelectSong are
  unambiguous, so the framework's MP2K runtime model applies.
- SoundMain wrapper: `0x081451B4: push {lr}; bl 0x08144510; pop {r0}; bx r0` —
  real mixer at **0x08144510**. Exact identity (SoundMain vs SoundMainRAM) to
  be confirmed at runtime.
- Sound-area literal: 0x4000084 (SOUNDCNT_H) at ROM 0x081454C0 — inside the
  driver cluster. DMA1/2 FIFO dst (0x040000A0/A4) constants: built by
  `mov`/`add`, not literal pools.
- Driver cluster spans roughly **0x08144000–0x08146000** (exact boundaries in
  Phase 4 audit).

### Cartridge hardware profile
- Standard ROM-only cartridge (no RTC/gyro/solar). Save type: TBD empirically
  (FFTA US uses flash 1M … to be confirmed against gbarecomp runtime + save
  write patterns; do NOT hardcode).
- BIOS: required for LLE (`[bios] hle = false`); user must supply their own
  BIOS dump at `gbarecomp/bios/gba_bios.bin` (never committed; sha1
  300c20df6731a33952ded8c436f7f186d25d3492 per gbarecomp docs).

### RAM map notes (from crt0/literals — verified)
- SYS mode sp = **0x03007FA0**, IRQ mode sp = **0x03007EC0** (crt0 literals 0xF4/0xF8).
- BIOS IRQ vector target: **0x03007FFC** ← 0x080000FC (crt0 installs).
- Indexed IRQ callback table base: **0x03000E50** (crt0 literals 0x244/0x248; used by IRQ dispatcher `bx` path at 0x080001C0). 0x030008D0 (literal 0x24C) — usage TBD.
- VBlank scheduler queue **0x03000E10**: +0 u16 tick flag (exactly what `vblank_wait_loop` polls — 0x08000418 `ldrh`/`cmp`/`beq` spin, verified 2026-10-09), +2 count, +3 current; task array 0x03002800; runner **0x080069F4**, init **0x08006A7C**; tick set in `vblank_callback` (0x080004B0).
- m4a sound info: pointer slot **0x03007FF0** → struct **0x020084E0** (ident magic 0x68736D54 at +0; pcm counter +4); per-frame engine tick **0x08144AF0**, the first call of `vblank_callback` (0x080004B4). 2026-10-09 disarm + hang-trace evidence (BRINGUP § 2026-10-09).

### Phase 0 result
All Phase 0 checks pass; ROM is a genuine AFXE US retail dump, exact 16 MiB.
No blockers.

---

## 2026-10-06 — Phase 1: Framework setup (COMPLETE)

### Submodules
- `gbarecomp` @ **ecc9c55** (branch `main`, "Merge pull request #28
  fix/flash512-chip-id"). Note: reference game repos pin 2952aff; we
  deliberately chose current main (newer, includes flash512 chip-id fix and
  kirby view-anchoring fix — relevant since gba_scan detects our save type as
  Flash 512 Kbit). `git describe`: gen3-pokemon-v0.0.1-248-gecc9c55.
- `recomp-ui` @ **cac2b8f** (master).
- Nested (from gbarecomp's pins): arm-recomp-core @ 15fc7b7, rbengine @ 2a03e7,
  recomp-net @ c58f125, android SDL @ 8e28503 (unavailable upstream, not
  needed on Linux desktop build — cloned successfully but origin lacks the
  revision; harmless).
- Pitfall hit: first `git submodule update --init --recursive` left
  arm-recomp-core's worktree empty (CMakeLists.txt deleted state) → CMake
  configure failed at `ArmRecompCore.cmake`. Fix: `git submodule update
  --checkout --recursive`. Resolution: second pass checked out all nested
  pins correctly.

### Docs read (Phase 1 requirement, before building)
- `gbarecomp/README.md` — ecosystem overview, build, strict-static coverage.
- `gbarecomp/docs/TOML_SCHEMA.md` — full schema: [program], [identity],
  [[extra_func]] (addr/mode/resume/source_addr/name/note), [[resume_range]],
  [[data_range]], [[code_copy]], [[jump_table]] (formats abs32/abs16/
  pcrel_thumb/pcrel_arm; entries_mode arm/thumb/auto), [[exclude_func]],
  [[mod_function_hook]], [[thumb_alu_immediate_override]], overlay rules.
- `gbarecomp/CLAUDE.md` + `PRINCIPLES.md` + `DEBUG.md` — BIOS is sacred
  (recompiled, not HLE), honest self-healing, coverage honesty, first-divergence
  debug loop, ring-buffer-first, no printf debugging, no editing generated/.
- `gbarecomp/docs/WINDOWS_GAME_SETUP.md` — bring-up path for new games.
- Reference repo (DragonBallZLegacyOfGokuRecomp) game.toml, CMakeLists.txt,
  src/main.cpp, .gitmodules — copied conventions for our game.toml/CMakeLists
  shape (Phase 2/3).

### Framework tools built
- `cmake -S gbarecomp -B gbarecomp/build -G Ninja -DCMAKE_BUILD_TYPE=Release`
  → configured (toml++ v3.4.0 fetched+pinned, SDL2 found, ccache detected).
- `cmake --build gbarecomp/build --target gba_recompile gba_scan --parallel 8`
  → built clean.
- Note from configure: "BIOS recompiled output absent — placeholder dispatch
  only. Run `gba_recompile --bios bios/gba_bios.bin` to populate." → the
  BIOS recomp step is required before any LLE run (Phase 3), user must supply
  the dump.

### gba_scan cross-validation of Phase 0
`./gbarecomp/build/gba_scan game.gba` (independent tool, first use → validated
against my manual analysis per DEBUG.md Rule 0):
```
rom_size=0x1000000, entry_branch_word=0xea00002e, entry_target=0x080000c0
game_title=FFTA_USVER., game_code=AFXE, maker_code=01
complement_check=0x89, complement_valid=1, logo_present=1
save_type=Flash 64KB (512 Kbit), save_signature=FLASH512_V,
save_signature_offset=0x0036ce28, ok=1
```
- Entry point 0x080000C0 and header values match my Phase 0 disassembly
  exactly. Complement math (0x89) matches my byte-level computation.
- **Save type: Flash 64KB (512 Kbit), signature FLASH512_V at 0x0036CE28**
  — resolves the Phase 0 "save type TBD" empirically from the ROM's flash
  command strings. (Note: my earlier guess "likely flash 1M" was wrong.)

### AGENTS.md created (instead of CLAUDE.md, per user direction 2026-10-06)
Contains ground rules, commands, submodule pins, environment notes, status,
next milestone. Framework's own `gbarecomp/CLAUDE.md` left untouched
(submodule).

### Phase 1 result
Submodules pinned and built, ROM validated by the framework's own tool,
docs read completely, AGENTS.md written. No blockers.

---

## 2026-10-06 — Phase 2: game.toml (COMPLETE)

### Field semantics verified against parser source (not just docs)
- `tools/gba_recompile/config.cpp:747` — `[program].entry_pc` required, hex.
- `tools/gba_recompile/main.cpp:1097-1098` — `entry_pc` becomes the discovery
  entry when `--config` is present.
- `tools/gba_recompile/main.cpp:1250` — cart mode seeds entry as
  **`CpuMode::Arm`** unconditionally. Correct for FFTA: word at 0x08000000 is
  ARM `ea00002e b 0x080000C0`.
- `src/runtime/runtime.cpp:2005` + `src/runtime/bios_hle.cpp:518-540` — the
  real BIOS hands off to the cart at **0x08000000** (`R15 = cart_entry`);
  `bios_hle_boot_skip` is only the intro-skip presentation path, same handoff
  address.
- **Decision: `entry_pc = 0x08000000`** — the bootstrap prompt's 0x080000C0
  guess would seed crt0 directly and leave the reset-branch word itself
  unrecompiled. Reference repos (DBZ) also use 0x08000000. Framework evidence
  supersedes the prompt (ground rule 7).
- `src/runtime/save_config.cpp:32-47` — `[save].type` tokens:
  `sram|eeprom|flash512|flash1m`; Flash512 valid size = 65536.
- `src/runtime/runtime.cpp:688-779` (`apply_toml_file`) — runtime-side keys
  verified: `[game].short_name/default_region`, `[bios].path/sha1/hle`,
  `[rom].path/sha1`, `[save].path/type/size`, `[video].screen/view_width/
  resize_view`, `[audio].shadow`. `[runtime]` table is informational only
  (parsed by CMake compile definitions in Phase 3, not by the runtime).

### Save type — first-hand byte evidence
- ASCII string `FLASH512_V130\0` at ROM file offset 0x36CE28 (xxd + Python,
  2026-10-06). No `FLASH1M_V`/`SRAM_V`/`EEPROM_V` strings anywhere in the ROM.
- `gba_scan` independently: `save_type=Flash 64KB (512 Kbit)`,
  `save_signature=FLASH512_V`, `save_signature_offset=0x0036ce28`.
- → `[save] type = "flash512"`, `size = 65536`.

### game.toml created — full validation run
`./gbarecomp/build/gba_recompile --rom game.gba --config game.toml
--out /tmp/ffta_p2_validate --max-functions 65536` (temp dir, NOT
generated/ — Phase 3 will regenerate into generated/):
```
identity sha1: 4ac05441... (verified)
extra_func entries: 2
==> discovered 1072 functions (arm=9 thumb=1063 indirect=457 undefined=0
    branch_targets=8736)
discovered_by_walk: 1069   redundant_manual: 1   manual_seeds_only: 2
auto_jump_tables: 7 (208 targets) auto-detected
midfn_aliases: 6381 entries -> 1018 hosts
TOTAL emitted: 1072
```
- Identity verified; config parsed by both the recompiler (toml++) and a
  runtime-parse mirror check (all keys/values valid per save_config rules).
- 0 undefined functions, 0 control-flow-into-data errors, 0 finder rejections.
- 7 auto-detected jump tables (208 targets) — clustered at 0x08004058/
  0x080044C8/0x080C7EC0/0x080C85A0/0x080C9EF4/0x080CA33C/0x080CA7CC —
  audit candidates for Phase 4 (likely the scripting/VM cluster; expect
  FFTA's in-game interpreter here).

### Seed A/B differential (evidence for keeping both seeds)
- No seeds: 1066 functions (arm=3), 1 manual-only (entry).
- IRQ-dispatcher seed only: 1072 (arm=9), 2 manual-only — walk from the
  dispatcher reaches main's call tree.
- main seed only: 1072 (arm=9), 2 manual-only — walk from main reaches the
  dispatcher region.
- Both: 1072; one seed redundant with walk. Discovery converges to the same
  1072-function corpus from either seed. Both kept: each is an indirect
  transfer target the walk cannot see (bx through 0x03007FFC install, bx r1
  literal), so the seeds are the correctness anchors; the names carry
  documentation value.

### Phase 2 result
`game.toml` created, identity-pinned (SHA-1 + MD5), schema-exact (verified
against parser source), evidence-backed ([program] from Phase 0 disassembly,
[save] from FLASH512_V130 bytes, [[extra_func]] ×2 with cited instructions).
BIOS requirement flagged to user: `hle = false` needs a user-supplied dump
at `gbarecomp/bios/gba_bios.bin` (SHA-1 300c20df...) — never downloaded,
never committed.

**STOP — Phase 3 not started, per user instruction.**

---

## 2026-10-06 — Phase 3: first recompile, build, run (COMPLETE)

### BIOS recomp generated + linked
- BIOS dump verified: 16,384 bytes, SHA-1 300c20df6731a33952ded8c436f7f186d25d3492
  (matches [bios].sha1; user-supplied, gitignored).
- `gba_recompile --bios gbarecomp/bios/gba_bios.bin --config gbarecomp/bios/gba_bios.toml`
  → 770 functions, 92 redundant-manual, 80 manual-only, 73 jump-table-expanded,
  2 data_ranges honored. Wrote `src/runtime/generated_bios/`.
- **Pitfall 1 (root-caused, fixed):** running `--bios` from the repo root wrote
  generated output into `<root>/src/runtime/generated_bios/` — NOT the
  framework worktree — so `gbarecomp_runtime` linked the placeholder stub and
  the runtime silently fell back to BIOS HLE boot ("recompiled BIOS is not
  linked" banner), which then segfaulted on FFTA's IWRAM code. Fix: copy
  output into `gbarecomp/src/runtime/generated_bios/` (its designed location,
  gitignored inside the submodule) + re-run CMake *configure* (the
  `EXISTS bios_recompiled.cpp` check only re-evaluates at configure time, not
  on rebuild). Framework docs' `build/gba_recompile.exe --bios bios/gba_bios.bin`
  assumes cwd = gbarecomp checkout — record for future sessions: run BIOS gen
  from inside `gbarecomp/`.
- Collateral: accidentally `rm -rf src/` (untracked host sources) while
  cleaning the misplaced output; recreated main.cpp / game_launcher_boot.{h,cpp}
  from the exact contents in session context. Lesson recorded: commit host
  sources *before* experimenting with generated-output locations.

### Host project created
- `CMakeLists.txt` — modeled on DragonBallZLegacyOfGokuRecomp (verified
  against its actual files): GBARECOMP_ROOT/RECOMP_UI_ROOT, EXCLUDE_FROM_ALL
  subdirectory, generated glob, recompiled_*.cpp at -O1 -g0, start-group link
  of runtime/debug/gba/armv4t, compile definitions
  (GBARECOMP_DEFAULT_DEBUG_PORT=19888, WINDOW_TITLE, DEFAULT_GAME_CONFIG),
  recomp-ui launcher (game_launcher_ui static lib + boxart.tga placeholder —
  host-authored gradient, no ROM-derived bytes), 16 MiB stack on MSVC/MinGW.
- `src/main.cpp` — RunOptions: builtin_game_name "Final Fantasy Tactics
  Advance", builtin_rom_sha1 4ac05441..., launcher_region "USA",
  launcher_game_config "game.toml". No mod/widescreen opts (not validated).
- `src/game_launcher_boot.{h,cpp}` — gbarecomp_launcher_preboot seam.

### Pitfall 2 (root-caused, fixed): Linux host stack exhaustion
- First run: SIGSEGV in `render_scanline_internal` with rsp 0x380 bytes below
  the 8 MiB main-thread stack mapping bottom — the generated code's
  VBlank-wait loop (`gf_tfunc_08000428` ↔ `gf_tfunc_08000418` alternating)
  never unwinds guest frames; each guest BL becomes a host C call, plus
  device ticks. First gdb backtrace showed rsp flush against [stack] end.
- Framework only reserves 16 MiB on Windows (`LINKER:--stack`, exe-suffix
  gated — see gbarecomp/CMakeLists.txt:317-338 `gbarecomp_target_link_host_stack`).
  Linux main-thread stack = RLIMIT_STACK (8 MiB default here).
- Fix in src/main.cpp: `raise_stack_limit()` — setrlimit(RLIMIT_STACK) to
  RLIM_INFINITY at main() entry (hard limit is unlimited on this host).
  First attempt (64 MiB cap) moved the crash to `tick_timers` at exactly
  64 MiB below stack top — same class, deeper budget. Unlimited resolves it.

### Run results (headless, --no-window)
| Frames | Mode | Result |
|---|---|---|
| 60 | strict (GBARECOMP_STRICT_STATIC=1) | **FULLY_STATIC**, 0 misses, 0 interpreted — BIOS intro + early boot fully native |
| 120 | strict | **FULLY_STATIC** |
| 240 | strict | **FULLY_STATIC** — final framebuffer dump: 240x160 PNG, ~93% white + blue/magenta accents (post-intro white screen; real PPU render, not garbage) |
| 480 | strict | dispatch-miss abort at pc=0x03005E78 (thumb) — first static gap |
| 480 | self-heal | runs to completion, exit 0, full diagnostics written: **NOT_STATIC, 12 distinct misses, 505361 interpreted insns, 14 healed, 5 failed heals** |
| 600 | self-heal | SIGSEGV (stack) — heal bridges + present-in-place accumulate host frames; heal-bridge re-entry doesn't unwind. 480 frames is the current non-strict budget ceiling. |

- final_pc=0x08000428, ppu_frames=480, unmapped=0, io_unhandled=0.
- Artifacts archived (gitignored, ROM-derived): `logs/miss480.frag`
  (12 [[extra_func]] proposals), `logs/cov480.json`, `logs/run480.log`,
  frame dumps at /tmp (reproduce with the commands in AGENTS.md).

### Phase 4 miss list (handoff, from miss480.frag — needs per-PC audit)
- IWRAM-installed code (5): 0x03000F10 arm x200, 0x03005E78 thumb x411,
  0x03005EE8 x6, 0x03007D64 x48, 0x03007E60 x2 — FFTA copies code to RAM
  (sound mixer + IRQ dispatch, per DBZ precedent) → need `[[code_copy]]`
  mappings backed by runtime IWRAM dumps (GBARECOMP_IWRAM_DUMP) + literal
  evidence; do NOT guess.
- ROM interior resume/call targets (7): 0x080004D8, 0x0800076E x199,
  0x08003674 x195, 0x0800367C, 0x0800371C, 0x080098C4 x197, 0x0813BCF0 x196
  — audit each: push roots / literal pools / jump-table membership
  (candidates near the auto_jt cluster at 0x08004058/0x080044C8).
- 0x081448C4 (near gf_tfunc_08144456+0x46E, m4a region) appeared in the
  earlier 600-frame verbose log but not the 480 frag — re-observe.

### Phase 3 result
Built binary + recompiled BIOS linked + runs headless 480 frames with full
coverage diagnostics; BIOS intro + first ~240 frames are FULLY_STATIC.
Expected-not-permanent: NOT_STATIC at 480 (12 misses, all characterized
above) — Phase 4's audit loop starts from `logs/miss480.frag`.
**STOP — Phase 4 not started, per user instruction.**

---

## 2026-10-06 — Phase 4: audit loop (COMPLETE for the 480-frame horizon)

### Result
**Strict 480-frame run: FULLY_STATIC — 0 dispatch misses, 0 interpreted
insns** (`GBARECOMP_STRICT_STATIC=1 ./build/FFTARecomp … --frames 480
--no-window --dump-png /tmp/ffta480_final.png`, exit 0, final_pc=0x08000428,
cycles=62191750). Artifacts: `logs/strict_v9.log`, `logs/run_v9.log`,
`logs/cov_v9.json`. Corpus grew 1072 → **1438 functions** (arm=18,
thumb=1420; 0 undefined, 0 rejections) purely through reviewed seeds +
their cascading walks.

### Verification protocol (established this session)
- **Cold-cache runs are the deterministic baseline** for audit
  verification: `rm -rf recomp_cache` before each verify run. The
  self-heal overlay cache shifts IRQ-resume landing PCs run-to-run
  (warm-state miss sets differed: 0x080013B6 vs 0x080013CC vs …), so
  warm runs cannot verify a fix. Strict runs are inherently cold.
- Per-entry cycle (cheap, ~5 s total): regenerate (0.15 s) → build
  (Ninja, ~3 s) → cold 480-frame run → check the miss list
  (`recomp_coverage_AFXE.json`). One entry per cycle — never batch-verify.
- Artifacts per cycle archived as `logs/{cov,miss,run}_vN.*`.

### Audit entries (game.toml "Phase 4 audit seeds" + "IWRAM code copies")
| # | Fix (entry) | Misses removed (evidence summary) | Miss count |
|---|---|---|---|
| 1 | `[[extra_func]]` 0x080004B0 | 0x080004D8 interior resume (bne join @0x080004CE); prologue 80b5 @0x080004B0 after prev func's pool; only ref = thumb ptr 0x080004B1 @0x08149434 | 12→10 |
| 2 | `[[code_copy]]` 0x03000F10←0x080000FC (0x160) + `[[extra_func]]` 0x03000F10, 0x03000FD8 (arm) | IWRAM IRQ dispatcher copy; byte-identical exit-dump span; 0x03000FD8 = copy of 0x080001C4 (IRQ exit path, callback-return target of `stmdb sp!,{lr}; bx r0` @0x080001B8-C0) | 10→8 |
| 3 | `[[code_copy]]` 0x03005E78←0x08A38A2C (0x2F8) + `[[extra_func]]` 0x03005E78, 0x03005EE8 | IWRAM RAM helpers (zero-fill; word/byte copy); byte-identical dump span | 8→6 |
| 4 | `[[code_copy]]` 0x03007D64←0x08141AF0 (0x24) + `[[extra_func]]` 0x03007D64 | tiny forward byte-copy helper; byte-identical; tail bytes 9342f8d1 uniquely locate source | 6→5 |
| 5 | `[[extra_func]]` 0x08003660 | byte-switch function; cases 0x08003674/7C/1C; entered via IWRAM slot 0x030027D0 (init tables @0x08000588/0x081494C8 store 0x08003661); no BL target | 5→4 |
| 6 | `[[extra_func]]` 0x080098C4 | 30b5 prologue after prev pool; registered via thumb word @0x0800998C + `bl 0x08006ADC` @0x08009978 | 4→3 |
| 7 | `[[extra_func]]` 0x0813BCF0 | 70b5 prologue after getter+pool @0x0813BCE4..EC; pointer 0x0813BCF1 in the 0x08003704 handler table | 3→2 |
| 8 | `[[extra_func]]` 0x081448C4 | m4a leaf (zero 64B at r0); after prior return+pool 0x081448C0; ptr 0x081448C5 unique @0x0836D124 | 2→1 |
| 9 | `[[code_copy]]` 0x03007E60←0x08141AAC (0x4) + `[[extra_func]]` 0x03007E60 | runtime-planted 4-byte flash getter `ldrb r0,[r0]; bx lr` (see below) | 1→0 |

Miss-class cases #2/#3/#4/#9 were the handoff's IWRAM code-copy misses;
#1 was the handoff ROM interior miss; #5-#8 were found during this audit.

### The last miss (0x03007E60) — mechanism, fully traced
The save/flash driver (0x081418E0 region) reads the flash window
0x0E000000/0x0E000001 through a 4-byte IWRAM getter that it calls via the
`bx r5` veneer @0x08142258 with **r5=0x03007E61 (= sp|1; sp=0x03007E60)**
— i.e. it executes the mini getter planted at its own stack slot.
Traced with the fingerprint ring (`GBARECOMP_INSN_TRACE=1
GBARECOMP_FP_SAVE=…`, 8.4 M-entry ring = last ~180 frames at 480 f; the
480-frame dump ended too late, a 340-frame run put the hits inside):
record idx 5274670/5274679 have pc=0x03007E60, prior instruction pc=0x08142258
(`bx r5`), r14=0x08141907/13, r0=0x0E000001/0x0E000000. Live
`GBARECOMP_MISS_IWRAM_DUMP` at the miss shows `00 78 70 47` @0x03007E60.
Identical bytes exist in ROM at 0x08141AAC (pool word 0x47707800 in the
[0x08141A98,0x08141AB0) pool; unique 4-aligned hit in 0x08140xxx-0x08143xxx)
→ declared as the decode source (code_copy + extra_func with source_addr).
RISK, noted in game.toml: if any other path ever plants different bytes at
this exact PC, this mapping must be revisited (both observed hits were the
getter).

### Insights / gotchas recorded for future sessions
- **Corpus gaps host indirect-only code.** The finder never walked these
  regions (no static edge); execution enters mid-body or via function
  pointers, so runtime dispatch hits interior PCs. Seeding the contained
  function start fixes the whole region: `static_resume_all=true` gives
  every interior instruction a resume alias, and the walk cascades
  massively (one seed → +201 functions; 0x0813BCF0's seed → +103).
- **Warm self-heal cache perturbs IRQ timing** (different PCs served
  natively → different IRQ landing instructions). Cold-cache verify (or
  strict) is required; warm-run miss lists are not stable evidence.
- **Tracing tools that worked** (all pinned-build, no code changes):
  `GBARECOMP_MISS_IWRAM_DUMP` (first IWRAM-miss state), `GBARECOMP_IWRAM_DUMP`
  (exit state), `GBARECOMP_WRAM_TRACE`+`_LO/_HI` (per-frame write diff),
  `GBARECOMP_INSN_TRACE=1`+`GBARECOMP_FP_SAVE` (per-instruction fingerprint
  ring: {cycles,pc,cpsr,r0..r15}; dump window = last ~8.4 M instructions —
  size the frame count so the event falls in the window).
- The pinned TCP surface (ecc9c55) is minimal: `ping`, `pause`, `continue`,
  memory/ring reads (`read_iwram`, `cyc_anchor`, `irq_cap`, `state_hash`);
  **`run_to_pc` / `get_registers` / `call_stack` / `rdb_*` are NOT present**
  (TCP.md describes a newer surface). Future debug: extend
  `src/debug/tcp_debug_server.cpp` or build with `--reverse-debug`.
- `tools/disarm.py` stops silently at the first undecodable halfword —
  use narrow windows anchored on known boundaries.
- Non-TCP headless 480-frame runs are stable end-to-end; runs with `--tcp`
  aborted this session with a generated call-return stack overflow
  (`return_pc=0x08144B6C`) after pause/continue — investigate before
  relying on TCP for long runs.

### Phase 4 result
All 12 handoff misses + all session-discovered misses are either fixed in
`game.toml` (13 `[[extra_func]]`, 4 `[[code_copy]]` entries, each with
disassembly/dump evidence) or explicitly documented (none outstanding).
Strict 480 = FULLY_STATIC. Next horizon: extend frames beyond 480 (stack
budget / heal-bridge unwind), then Phase 5 (mGBA + frame-diff harness).

---

## 2026-10-06 — Phase 5 start: mGBA oracle + framediff harness

### Oracle setup
- `mgba-sdl`/`mgba-qt` installed by the user (system, 0.10.5, `extra`).
- Framework oracle built from gbarecomp's own mGBA source tree:
  `gbarecomp/oracle/setup-mgba.sh` (clones mGBA tag 0.10.5 → builds
  `third_party/mgba/build/libmgba.a`) → `cmake -B build -S . -DGBARECOMP_BUILD_ORACLE=ON`
  → `cmake --build build --target gbarecomp_oracle`.
  Binary: `gbarecomp/build/oracle/gbarecomp_oracle` (TCP, default port 19843;
  takes `--bios --rom --port`). Submodule tree stays clean (third_party/ and
  build/ are gitignored).
- Framework ships ready-made comparators (`gbarecomp/oracle/diff_cart.py`,
  `diff_frame.py`, `gba_tcp.py`); our durable tool is `tools/framediff.py`
  (see below). Recomp-side capture: `GBARECOMP_FRAMEDUMP_DIR/_START/_COUNT`
  (windowed path only; PNG per guest frame `f_%06llu.png`) — verified
  working headless via `SDL_VIDEODRIVER=dummy GBARECOMP_FORCE_DRAWABLE=240x160
  GBARECOMP_PRESENT_IN_PLACE=0` + `--window` (smoke: 5 PNGs, strict, exit 0);
  `--dump-png` = single final frame, works under `--no-window`.

### Comparison protocol — the phase offset (important)
- The recomp runner's `step`/`run_frames` stop at **VBlank-start** (scanline
  159→160), *before* the VBlank IRQ handler executes; mGBA's `runFrame`
  (oracle `emu_step`/`emu_step_to_vblank`) stops at the **VBlank wrap**
  (scanline 227→0), *after* the handler. Same-index region reads are
  therefore one IRQ handler apart → small standing byte differences.
- **Per-frame DELTA comparison cancels this**: compare (old→new per byte)
  transitions instead of absolute bytes; identical changes = phase noise;
  side-only changes or different transformations = candidates. Implemented
  in `tools/framediff.py` (delta mode; standing offsets reported separately).
- Known phase-sensitive bytes to expect in early BIOS screens: BIOS
  `pcmDmaCounter` at 0x03003B30 (±1 per service-call phase; wraps every 8
  frames), IntrWait flag 0x03007FF8 (set mid-wait / cleared post-IRQ), and
  handler stack residue around 0x03007F88-0x03007F9D.

### First divergence work (vblank 8) — resolved as phase artifacts
Scan (vblanks 4..64, IWRAM): 41/61 transitions byte-identical after delta
comparison; all "mismatches" are the known phase cluster + the counter's
periodic wraps. Verified the counter's value chain by BIOS disassembly +
fingerprint ring: 0x03003B30 = `pcmDmaCounter` (struct base 0x03003B2C,
pointer kept at [0x03007FF0]); decremented once per VBlank service at BIOS
pc 0x211C; on borrow reloaded from struct+0xB (`pcmDmaPeriod`, pc 0x2122) =
0x630/0xE0 = **7** (computed at pc 0x1730 via ARM division 0x3A8; all inputs
ROM constants — no hardware reads). Our engine's trace: 0 → 0xFF (borrow) →
7 → 6 → … — i.e. **same stored values as the oracle**; the observed ±1 is
the service-call count at the sampling instant. No genuine guest divergence
found in frames 4-64.

### Extended scan (vblanks 4..300) — handoff cluster found
`tools/framediff.py --lo 4 --hi 300` → 196/296 transitions clean (report
archived `logs/report_4_300.json`). Frames 4..~280: only the known phase
artifacts (counter ±1 + wrap events every ~7 f; IntrWait flag briefly).
**New cluster from ~vblank 281-287, sparse to 300**, concentrated at the
BIOS→cart handoff: stack-top 0x03007D24-0x03007E63 and 0x03007E80-0x03007EB6
(bytes 0x03007E80/E84/E89 flag native-only nearly every frame out to 300) plus
game-init cells 0x03000884, 0x03000E10, 0x03002BBC, 0x030034B0-B3.
Hypotheses to test next: (a) handoff happens on a different vblank index on
the two engines (BIOS exit is a VCOUNT compare) — would shift all cart init
by one frame; (b) differing IRQ-stack residue right after handoff. Root-cause
before treating frames 280+ as verified. Plan: watch the cart's first visible
writes (e.g. IRQ vector/dispatcher setup 0x03000E10/0x03000F10 region,
0x030034B0-B3) on both sides at 1-frame granularity to pin the handoff
vblank, then drill 0x03007E80/E84/E89.

### Handoff cluster — RESOLVED as phase artifacts (probe + LCG chain math)
Cell identities (agent audit + own disasm): 0x030034B0 = LCG RNG state
(next = state*0x41C64E6D + 0x3039; seeded to 1 at vblank 280; stepped once
per main-loop iteration; step fn 0x08002804, 4-step/output variant
0x08002838; writer sites 0x08002810/28/72; getter 0x08002830); 0x03000E10 =
VBlank scheduler queue (+0 u16 tick flag, +2 count=3, +3 current; task ptr
array 0x03002800, state bytes 0x030027D0; init 0x08006A7C, runner 0x080069F4,
tick set in the VBlank handler 0x080004B0); 0x03000884 = second queue
0x03000880 +4 (tasks-run counter); 0x03002BBC = saved DISPCNT mirror
(save @0x080006D0, restore @0x08000788, DMA1 restore @0x08000718);
0x03007E80-9F = IRQ/SYS stack arena (per-IRQ 0x28 B: BIOS save 0x18 + cart
dispatcher 0x10).
Probe (both engines, vblanks 270-306, per-frame values): every cell shows
the SAME values with a one-frame sample offset (DISPCNT save native @282 /
oracle @283; queue counters @285/@286; stack bytes 0/4/0x20/1 toggling in
opposite phase from f287+). RNG: native@f281 = chain step 167, oracle@f281 =
step 171, both @f282 = step 251 (positions verified by walking/inverting the
LCG); steady state advances exactly 1 step/frame (9/9 transitions verified).
Conclusion: the whole >280 cluster = sampling-instant artifacts (pre-IRQ vs
post-IRQ plus mid-burst sampling), **not** value divergence. No genuine
divergence found in vblanks 0-306.
Corrections recorded: 0x03000E50 is an IF-ack mask cell, NOT the callback
table; the IRQ callback table is 0x030008D0 (thumb ptrs copied from ROM
0x0814942C); its +8 slot = VBlank fn 0x080004B0.

### Horizon extension: strict 600 (audit loop, in progress)
The strict-600 run replaces 480 as the frontier test; it aborts at the first
non-static PC beyond the old horizon — serial audit loop, recipe as Phase 4
(evidence → game.toml entry → regenerate → rebuild → cold run). Progress
this stretch (corpus 1438 → 2690 discovered):
- #10 0x08148740 — m4a-region fn (`push {lr}` after prev ret+pool+stubs);
  ptr 0x08148741 unique @0x089A5CFC (m4a ptr table).
- #11 0x0813BF5C — byte-switch handler; ptr 0x0813BF5D @0x080036FC (the same
  0x08003660 case-0 handler table as #7).
- #12 0x0813C0EC — 4.8 KB state machine (switch on [r1]; case 0 seeds the
  RNG via `bl 0x08002824`); ptr 0x0813C0ED @0x0813BFB4 (pool of #11).
- #13 0x08144B2C — m4a callback registered via pool word 0x08144B2D
  @0x081458A8 (beside m4a ident 0x68736D53 / struct ptr 0x03007FF0).
- #14 0x08145CAC — m4a callback (reads [0x03007FF0]-struct +0xa countdown).
- #15 `[[code_copy]]` iwram_m4a_blob — 0x030034DC ← 0x08144594, 896 B
  verbatim (miss-IWRAM-dump vs ROM, forward+backward run): the m4a engine's
  SoundMain-style IWRAM relocation; + thumb entry 0x030034DC and ARM entry
  0x030034E8 (= 0x081445A0, via the head's `adr r1,#4; bx r1`).
- Current frontier: strict 600 aborts at pc=0x08144A0C (thumb, m4a region)
  — next in the loop. ARM corpus grew 19→40 (blob ARM section walked).

### Reference-repo study + bulk harvest + the entries_mode lesson
Studied mstan's five sibling repos (shallow clones; Emerald / FireRedLeafGreen /
RubySapphire / MinishCap / WarioWareTwisted) for reusable practice:
- Adopted **bulk miss harvest** (Emerald/FRLG reviewed-seed workflow): one
  non-strict pass collects ALL miss PCs; per-miss strict cycles are for
  verification only. Applied: non-strict 1200-frame run → **32 distinct miss
  PCs in ONE pass** (all m4a region).
- Adopted **pointer-table declaration** (MinishCap [[jump_table]] practice):
  scanned for each missed handler start's thumb word → the 36-entry m4a
  command handler table at 0x0836D098 (stride 4; default slot 0x081448FD
  x12) + 2 stragglers (#17) → strict 1200 FULLY_STATIC, corpus 2690→2800.
- Our pin already carries static_resume_all (on), resume_range,
  alu-immediate overrides, overlay `--config` layering, symbol_map.cpp;
  reference repos ship NO frame-diff harness (ours is ahead).

**Then the first real divergence hunt — and it was self-inflicted.**
Symptoms: banner `unmapped=121722415` open-bus W4 writes descending below
EWRAM with frames {0x02008E60, 0x020084E0, 0, 0x081455C7}; scheduler cell
0x03000E10 clobbered to 0x081455C7 from f275; ring: 0x08145608 (m4a
song-start, `push {r4,r5,r6,lr}`) re-executing 255× back-to-back (SP −16 per
iteration); framebuffer 59% / EWRAM 67% different at f1200. Bisect (stash
#16/#17): pre-seed build clean → **our jump_table declaration caused it**.
Root cause (dispatch-table diff): `entries_mode = "thumb"` does NOT mask the
raw pointers' bit0 (TOML_SCHEMA: "the low bit … is not consulted"), so the
finder seeded literal ODD addresses (0x08145609, +2, +4 …) as function
starts → odd-pc host ladder → dispatcher re-entered the function's first
instruction forever. FIX: `entries_mode = "auto"` (decodes bit0 → THUMB and
clears it). Post-fix: `unmapped=0`, E10 normal, strict 1200 FULLY_STATIC;
IWRAM diff at f600 = 83 B (~phase noise), EWRAM 275 B, cell-alignment probe:
same-index best (70% match vs 30-40% at ±1/±2 shifts — no global offset).
**Lesson: manual [[jump_table]] entries with interworking-convention pointers
MUST use entries_mode = "auto"; after any jump_table change, grep the
generated dispatch rows for odd addresses.**

### Coverage report tooling (three lenses)
`tools/coverage_report.py` regenerates the mapping-coverage table
programmatically. Lens definitions (documented here so numbers stay
comparable over time):
- **Executed path** — strict native run (default 1200 frames) exit banner:
  FULLY_STATIC ⇒ 100% of everything that ran is natively mapped.
- **Walker's static reach** — trial config with `aot_scan_end` widened to
  the whole ROM (0x09000000): everything the walker can find at all.
  Current: 2,797 / 2,805 units ≈ 99.7% (the gap was +75 before the bulk
  harvest; now +8).
- **Pointer pool** — trial with `speculative_literal_harvest = true`:
  2,797 / 23,157 ≈ 12.1%; the harvest kept 979 plausible pointers out of
  65,792 PC-relative literals (trial only — `false` in game.toml by
  evidence-driven policy).
Trials are string-substituted copies of the live `game.toml` regenerated in
a throwaway temp dir with a cold cache; `game.toml` and `generated/` are
never touched. Usage: `.venv/bin/python tools/coverage_report.py
[--frames N] [--json] [--log FILE] [--no-run]`; the executed-lens run log
lands in `logs/coverage_report_strict_N.log` (gitignored). Verified
end-to-end 2026-10-06: reproduces the numbers above in ~4 s (commit ae6966d).

### Title-animation corridor + park-phase semantics (probes f556–f9600)
- Strict 2400 = FULLY_STATIC (0 misses; corridor saturated since 1200).
- Timeline (native `--dump-png`): logos f60/f240 → title-screen animation
  (book → "It was a day" → snow montage) f~600–3400 → title logo f3600 →
  "Push Start" f4200…≥f6000; f7800/f9600 sampled black (fade/loop segment —
  needs a contact-sheet run).
- **Corrected comparison semantics (source-verified in both engines).**
  Both engines park at VBlank-start (scanline 159→160); mGBA `runFrame`
  returns there too (video.c frameCounter++ at vcount 160). The real phase
  difference is CPU-side: our runner executes the VBlank IRQ handler before
  parking (post-handler); mGBA raises the IRQ (+7 cycles pending) and
  vectors it at the start of the next step (pre-handler). Same-index state
  reads differ by exactly one handler's effects — native ahead.
- **Proof — snow RNG chain.** f1210 region: oracle@f1198 = oracle@f1197 =
  0x083d9a03; native@f1198 = chain(oracle, 13) (backward chain walk; forward
  walk ≥20 M finds nothing — earlier "NOT FOUND" was the wrong direction).
  Constant Δ=13 steps from then on: the title animation's snow code consumes
  13 RNG steps/frame inside the VBlank handler; at sample time native has
  run it, mGBA hasn't yet. Constant offset ⇒ **no guest-state divergence**.
- **Pixels:** native `screenshot` = latched completed frame (pre-handler
  snapshot at vblank_started; tcp_debug_server.cpp:971-994, gba_ppu.h:199-
  212); oracle `emu_screenshot` = mGBA's completed-frame buffer. Same-index
  compare is correct (offset probe over f600–640: 0.78 % diff bytes at
  shift 0 vs 5.8–15 % at ±1..3). Static stretches byte-exact (f825–950 all
  zero); animated content shows bounded band diffs (f640: rows 64–78 = the
  scrolling "It was a day" text band, ≤ ~2 kB) — sub-frame update placement
  / rasterization granularity of the two models, not game-state divergence.
  Fade/transition frames can flip whole-frame visibility (native scene vs
  oracle black at f1300) — same class; pick stable frames for golden hashes.

### Phase 5 tooling — built 2026-10-06
- `tools/dualrun.py` — lockstep native↔oracle probes (regions / pixels /
  cells / PNG dumps; free ports; encodes the park-phase model). Smoke-tested:
  iwram @f60 shows exactly the two known phase cells (0x03003B30, 0x03007FF8);
  pixel dump @f620 = 1661 bytes (the animated-band class).
- `tools/attract_check.py` — the attract regression gate (WarioWare
  `verify-attract.ps1` pattern): strict headless run, banner asserts, golden
  SHA-256 pinned in-script (`--repin` adopts deliberate changes; frames=1200
  pinned at commit time; verify = PASS).
- `tools/misspack.py` — miss-frag → evidence pack + PROPOSED TOML stubs
  (disasm window, backward prologue scan, ROM pointer scan with table-run
  detection → `[[jump_table]]` proposals carrying `entries_mode = "auto"`,
  nearest dispatch entry). Table path validated against the m4a table
  (0x08144A0C / 0x081448DC hits inside 0x0836D0xx; the run detector is
  deliberately over-wide — trim the extent on review). Manual review only;
  never auto-writes game.toml.
- `tools/cycle.py` — the standard change cycle: cold regen → aligned-dispatch
  sanity check (the entries_mode guard) → build → attract gate; `--harvest N`
  adds a non-strict miss fragment. Tested 2026-10-06: PASS in 3.4 s. Use this
  after every game.toml change.
- `tools/ringscan.py` — FP_SAVE instruction-ring queries (`--pc`, `--reg`,
  `--reg-range`, `--cyc`, `--context`; capstone decode). Tested on the f1198
  ring: resolves the RNG LCG writer chain (0x08002806..0x08002810).
- `tools/play.sh` — interactive playtest launcher (the healing loop's front
  end): records the input trace + miss frag, archives the previous session's
  savestates/traces under `saves/`; letter-key map via `build/keybinds.ini`
  (§ "Desktop playtest input" above).
- `tools/cache_harvest.py` — crash-safe miss recovery: extracts `<PC>` from
  `recomp_cache` unit filenames when a crash kills the session before the
  `.frag` flushes (exit-only flush; validated on two real crashes).
- `tools/resolve.py` — strict-replay a recording, seed each miss via a temp
  overlay, rebuild, repeat until FULLY_STATIC; emits a proposal file (never
  auto-writes game.toml). Smoke-tested 2026-10-06.
- Remaining follow-ups: contact-sheet dump for the f6000+ attract loop;
  finish the tutorial battle + post-battle content (play → harvest →
  resolve); savestate-wedge root cause (see session-6 section) + upstream
  reports (bridge stop-contract runaway #1/#2; wedge once pinned).
  Sessions 1–6 and their batches are logged below.

### Map-data regions verified (spiiin/FFTAUtils study, 2026-10-06)
Studied spiiin/FFTAUtils — map-hacking utilities (C#, VS2012, single 2014
commit, NO license: reimplement don't copy; Windows-only; their repo
contains ROM-derived bytes, never import). Findings cross-verified against
our ROM (SHA-1 matched; their MAP_COUNT=163 is an off-by-one):
- Map record table: **162 records × 0x58** at ROM **0x08569104** (fields:
  +0x00 gfx, +0x04 arrangement, +0x08 clipping, +0x0C palette, +0x10
  height, +0x14.. animation; addresses stored as u32 + 0x08569104).
  Phantom tail "entries" 0x088EB124 / 0x288E9104 / 0xD4969384 are bogus.
- **Verified DATA regions** (compressed map blobs — any proposed function
  start inside is suspect): gfx 0x0856C8B4–0x08694884 (50), arrangement
  0x0856F528–0x08696EA8 (122), heights 0x085704C8–0x08698218 (113);
  combined span 0x0856C8B4–0x08698218.
- Compression tags: 0x10 = LZ77 (u32 LE size; LSB-first flags), 0x11 =
  LZ77 + 3-byte trueMap redirect (0xFFFFFF = standalone), 0x20 = LZSS,
  0x22 = LZSS + 4-byte skip; decompressed caps: arrangement ≤ 0x10000,
  tiles ≤ 0x8000, height 0x400, clipping 0x2000, palette 0x800.
- Palette pointer tables at 0x0801A4F8 / 0x0801A514 (mask 0x1FFFFFF).
- Lead (unverified): 29 literal occurrences of 0x08569104 at ROM
  0x0801A058–0x08020704 (4-aligned, pool-like) — candidate map-loader
  refs; disassemble with tools/disarm.py when naming map code.
- No scripting/VM content in the repo (nothing for the 0x080C7EC0
  cluster). Candidate hygiene: declare a data-range guard for
  0x0856C8B4–0x08698218 if the walker ever misdetects there (check
  TOML_SCHEMA for the data-range key before adding).

### New-game path unlocked + first audit batches (2026-10-06)
- Input trace `inputs/title_to_newgame.csv` (Start @4201, A @4267, A @4333;
  active-low, sticky) authored from TCP sessions and **verified via headless
  replay** (`GBARECOMP_INPUT_REPLAY=... --frames 4638 --dump-png` shows the
  intro house scene). GOTCHA: replay events are applied by the headless
  `--frames` loop only — TCP `run_frames`/`step` does NOT apply them
  (probe: KEYINPUT 0x04000130 stayed 0x3FF through a replay session's
  frames 4196-4320).
- Attract gate unaffected throughout (same pinned SHA).
- Non-strict harvest (6000 f, replay): **120 dispatch misses in ONE pass**
  (logs/ng_harvest.frag). Classification via `tools/misspack` + a start
  proposal pass (logs/ng_start_proposal.txt): ~110 were interior resume
  points of 50 unseeded function starts; 10 needed wide scans; 2 had
  callback pointers. Batch a: 50 seeds; batch b: 7 resolve-loop seeds;
  singles 0x0813DB34 (ptr 0x813C024), 0x08136084. **Corpus 2,797 → 23,395;
  auto_jump_tables 8 (213 tgt) → 142 (3,466 tgt)** — the new-game path
  opened the engine/menu regions (200k branch targets).
- Framework note: 5 auto-detected JT sites warn "control-flow entry"
  (mis-modeled switches; bytes kept as data; residual branches self-heal).
- **IWRAM tail blob**: frontier pc 0x03006B44 → miss-time dump match gives
  one contiguous copy: IWRAM 0x03005E78..0x03006D68 ← ROM 0x08A38A2C..
  0x08A3991C. New entry `iwram_ram_helpers_tail` (0x03006170 ← 0x08A38D24,
  0xBF8 B, byte-identical span). LESSON (schema): `[[code_copy]]` only maps
  decoding — runtime entry PCs inside the span ALSO need `[[extra_func]]`
  (added 0x03006B44; a source-side prologue scan then seeded 11 tail-blob
  starts; island 0x03006B6C seeded separately — the walk from 0x03006B54
  ends at 0x03006B68).
- **Current strict frontier: 0x08022148** (thumb; strict 6000 + replay,
  logs/ng_strict6000_i.log). Continue the resolve loop from there.
- Tool fix: `misspack.prologue_scan` now checks `pc` itself (misses are
  often function starts).

### FFTA_Engine_Hacks study (2026-10-06) — VM cluster CORRECTION
Studied LeonarthCG/FFTA_Engine_Hacks (Event Assembler hack package, no
license → reference/quote only; derived address indexes from a scratch
clone — re-clone the public repo if needed). It is effectively an
**address→description index**: 576
`ORG $addr` patch sites, each with an inline comment about the vanilla
routine.
- **CORRECTION (ROM-verified during the study): the 0x080C7EC0 / 0x080C85A0
  / 0x080C9EF4 / 0x080CA33C / 0x080CA7CC auto-tables are NOT a scripting
  VM** — they are unit/job/ability/stat switch tables in the
  0x080C7xxx-0x080CAxxx data-accessor cluster (0x080C7EA4 = unit-stat
  getter, table index 0 = name; 0x080C8570/857C = job-stat routines).
  The **event interpreter is at 0x08122xxx-0x08123xxx** (opcode 0x13 @
  0x08122680, opcode 0x70 @0x08122AAA, healing opcode @0x0812386C; event
  scripts + pointer table at 0x089A5E4C+; two raw-format sample scripts in
  the repo). The text engine (0x40-prefixed control codes) and the battle-
  animation format are separate VMs.
- Useful naming/RAM facts: party unit array 0x02000080 stride 0x108; battle
  unit control 0x08092xxx-0x08096xxx; engine helpers 0x08005xxx (0x08005B28
  = string/list helper); 0x0814xxxx = m4a + BIOS veneers (0x0814186C =
  CpuSet veneer).
- Future option: import names as a symbols overlay (docs/SYMBOL_OVERLAY.md;
  `[[extra_func]]` name field) — most sites are interior patch points,
  filter to real prologues first.

### charlie-troy/ffta-decomp study (2026-10-06) — revision-exact cross-reference
Reviewed charlie-troy/ffta-decomp (225 commits; active the same day). Partial
matching decomp + battle-AI RE. **Targets exactly our ROM**: their
`tools/verify_rom.py` / `data/functions.json` pin sha1
`4ac05441f4de70a4ec3dd932116346c61b8783d9` (USA/AFXE) = ours. **NO license**
— reference facts with attribution only; do not ingest sources/logs (also
ROM-derived).
- State: 173 functions matched in C (9,888 B total, all Thumb; 111 of them in
  0x080C0000-0x080CFFFF = battle/AI region); full 16 MB rebuilds byte-
  identical via incbin (CI gates per-object SHA-256); discovery claims 3,594
  boundaries (manifest not committed). Symbol registry: 96 bindings, only
  ~16 descriptive (rest `sub_*`).
- **Spot-checked against our ROM (tools/disarm.py):** 0x080C7EA4 `UnitStat` =
  `cmp r0,#0x44; lsls #2; ldr table; mov pc` — 69-entry stat dispatcher,
  consistent with the 0x080C7EC0 table; 0x08002804 = the Phase 4 LCG exactly;
  0x08123670 (their "battle event-script VM spawn command") = real function
  calling 0x08096E18/0x08096D7C (near our 0x08096CB8/0x08096E78 seeds). No
  contradictions found anywhere.
- Useful anchors: `UnitStat` 0x080C7EA4, `AbilityProp` 0x080CCD50,
  `AbilityMpCost` 0x0812ED98, `gRngState` 0x030034B0, `gSongTable` 0x0814BB48
  (640×8 MP2K entries), `gAbilityTable` 0x0855187C; turn-order chain
  sub_0809E1E0 → sub_0809E05C → sub_0809DF7C; AI evaluator sub_080C32C0
  (5,352 B, matched in C).
- Docs to mine later (cite/paraphrase): `docs/ai-findings.md` (75 KB),
  `turn-order.md`, `audio-driver.md` (m4a island 0x08141500-0x081458AC,
  94 fns), `text.md` (8 string tables), `map-data.md` (confirms our
  162×0x58 @0x08569104), `unit-struct.md`. Event VM: scattered refs only
  (spawn cmd 0x08123670) — no interpreter map.
- Import notes: gbarecomp's symbol pipeline (SYMBOL_OVERLAY.md) can consume
  their build (agbcc in /tmp; ~207 seeds, mostly `sub_*`, + ~16 globals) —
  modest yield; carry on as targeted cross-reference. Optional build route:
  per-function SHA gates + baseline-vs-overlay validation (frames /
  FULLY_STATIC / pixels must agree).
- Next targeted checks: their 0x08123670 vs our VM sites
  0x08122680/0x08122AAA/0x0812386C; 0x08096E18 and 0x08096E46-5E around our
  seed 0x08096E78; full read of the AI docs when the battle path opens.

### Conversion queue — reference studies → artifacts (2026-10-06)
Status of the user-requested queue (turning recorded studies into repo output):
- [DONE] FFTAUtils map-data guard: `[[data_range]]` 0x08569104–0x08698218
  (162×0x58 table + compressed gfx/arrangement/height blobs; zero
  dispatch/extra_func overlap at add time). Regen accepted (no control flow
  enters), strict 2400 FULLY_STATIC after.
- [DONE] ffta-decomp symbols: `symbols/ffta_symbols.tsv` (173 byte-matched
  functions from their data/functions.json + verified descriptive overrides;
  section 2 = engine-hacks-derived rows) and `symbols/ffta_data_symbols.tsv`
  (13 debug-only memory names). Wired into `tools/cycle.py` and
  `tools/coverage_report.py` regen; discovery grew +55 units (23,450);
  attract gate PASS with the **same pinned hash** (SYMBOL_OVERLAY step-4
  validation: names/seeds must not change behaviour) and strict 2400
  FULLY_STATIC after.
- [DONE] Engine Hacks: 5 game.toml seeds annotated as event-interpreter
  region (commit 5536cf3) + 2 start-verified names in the symbols file
  (section 2; the rest of its index is interior patch sites — filtered).
- [FUTURE] decomp full build-route import (agbcc ELF → readelf/ld -Map →
  import_decomp_symbols.py) only if the 176-seed subset proves limiting;
  targeted VM checks (their 0x08123670 vs our 0x08122680/0x08122AAA/
  0x0812386C) when the interpreter moves to the audit front.

### Desktop playtest input — IBus special-key swallowing (2026-10-06)
Interactive play initially received only some keys on the user's
GNOME/Wayland session: `GBARECOMP_INPUT_RECORD` showed Up/X registering while
Enter/Backspace/C intermittently vanished. Synthetic injection (ydotool with
HELD presses, all 10 codes) proved the runtime + keybinds pipeline registers
every button, isolating the loss to the host input layer — an input-method
daemon (IBus present on the host) swallowing special keys in game windows, a
known Linux/GNOME gotcha. Resolution: a **letter-only player map** — working
map committed as `tools/playtest_keybinds.ini.example`, installed at
`build/keybinds.ini` (local, gitignored); the user can now play the desktop
build interactively. Verification tooling that made this debuggable:
`GBARECOMP_INPUT_RECORD`, `tools/keyprobe.py`, and `ydotool key <code>:1/:0`
with held presses (note: single-tick synthetic taps can fall between 60 Hz
input samples — a test artifact, not a game bug).

### Android port findings (research 2026-10-06; not started)
Researched ahead of a possible Android release (user question: what gates
Android playability — answer: not the pointer-pool lens; only the executed
path matters, and device builds have self-heal disabled, so misses fail
loudly and feed the Phase 5 audit loop). Sources: mstan's EmeraldRecomp and
WarioWareTwistedRecomp (shallow scratch clones — re-clone the public repos
if needed), engine checkout at gbarecomp/platform/android/.

- **The Android app shell lives in the ENGINE, not the game repos.**
  `gbarecomp/platform/android/` is present in our pin `ecc9c55` (same
  revision family as Emerald's pin): shared Gradle config
  (`gbarecomp-app.gradle`), manifests (debug adds INTERNET for loopback
  TCP via adb forward), Java activities (GbaSetupActivity — SAF file
  picker + SHA-1 verify → app-private storage; GbaGameActivity), vendored
  SDLActivity sources, native CMake root; SDL 2.32.10 as a pinned
  submodule (`platform/android/third_party/SDL` → github.com/mstan/SDL).
  Each game repo carries only a thin `android/` dir: Gradle wrapper
  (Gradle 8.11.1 / AGP 8.10.1), `app/build.gradle` with an `ext.gbaGame`
  block, `game_android.toml`, icon/strings.
- **Templates**: Emerald `android/` = release-grade (ABI pinning
  arm64-v8a, APK ROM/BIOS-content guard in tools/make_release.ps1, payload
  staging); WWT = `android/README.md` + `tools/validate-s22.ps1` device
  validation gate (asserts no dispatch misses / no crash in logcat).
- **FFTA work items** (all mechanical, orthogonal to Phase 5):
  1. `android/` Gradle project + `game_android.toml` (identity-pinned ROM
     SHA-1 `4ac05441…`, BIOS required, saves in app-private files/).
  2. CMakeLists `if(ANDROID)` branch: SHARED `main` lib (SDLActivity
     loads libmain.so), reuse parent SDL2::SDL2, skip desktop post-build.
  3. `src/main.cpp` mobile hooks: `mobile_prepare_process` / `SDL_main` /
     `mobile_run_with_stack` (engine APIs `src/runtime/mobile_platform.*`),
     touch-friendly RunOptions.
  4. Env: JDK 17 + Android SDK (compile/target 35, minSdk 28, NDK
     27.1.12297006, CMake 3.22.1); init the SDL submodule inside
     gbarecomp; engine helper scripts are PowerShell-only (pwsh or call
     Gradle directly).
- **Device facts**: game runs on a 256 MiB pthread (never the ~1 MiB SDL
  main thread); self-heal DISABLED on device; WWT needed
  `GBARECOMP_FORCE_INTERP=1` + `GBARECOMP_AUDIO_DIRECT=1` +
  `GBARECOMP_HANG_WATCHDOG=0` (per-game tuning expected).
- **Sequencing**: independent of Phase 5; an early port is a second
  harvesting surface (adb-forwarded TCP debug), but playable depth still
  comes from the Phase 5 audit loop.

### Android port — skeleton to device-verified boot (2026-10-08)
Implemented on the engine's Android shell (pin `ecc9c55`, which is upstream
`main`; `platform/android` verified against all remote heads).

- **Game-side surface**: `android/` Gradle project (Gradle 8.11.1 / AGP
  8.10.1; identity `org.gbarecomp.fftarecomp`, variant
  `final_fantasy_tactics_advance`, landscape), runtime-only
  `android/game_android.toml`, CMake `if(ANDROID)` → SHARED target `main`
  with forced `GBARECOMP_ENABLE_MODS=ON` (links the trusted-plugin
  lifecycle), SDL2-target guard for the launcher, per-platform default
  config; `src/main.cpp` mobile hooks (`mobile_prepare_process`, phone run
  options, `SDL_main` via `mobile_run_with_stack`).
- **Build**: JDK 21 (Gradle 8.11.1 rejects JDK 27); NDK 27.1.12297006 via
  sdkmanager (its exit 1 on a root-owned `emulator/package.xml` is
  harmless — the NDK unzips fine). First build 2m51s; libmain.so ≈ 99 MB;
  APK 37 MB with private ROM/BIOS embed (never committed; `.gitignore`
  covers `*.apk`).
- **Device (Xiaomi Mi 11, Android 14/API 34)**: AUTOSTART boot to gameplay;
  `cpu_backend=static-recompiled`; zero dispatch misses; flash512 detected;
  virtual pad default; 256 MiB game thread. `[video] resize_view = true`
  enables the desktop-validated expanded view: 356x160 filling 3200x1440
  (~9x); authored margins verified on the intro field (house/fence continue
  into the margins, no wrap). 256-wide title/UI BGs wrap cosmetically at
  wide views — same policy behavior desktop validated.
- **Mods state quirk**: the runtime's startup commit persists raw
  `enabled=false` for default-enabled, never-touched features (no launcher
  seeding on mobile), so they switch off from the second launch on.
  `android/payload/mods/state.toml` now ships `enabled = true` for fresh
  installs (player-owned thereafter; device state fixed manually).
  Candidate upstream note.
- **Gate**: `tools/validate_android.sh` (install → AUTOSTART launch → five
  assertions → evidence pull to `android/artifacts/last-run/`); PASSED on
  device. Its fetch handling treats `exec-out`-folded remote `cat:` errors
  as missing files (caught a false-positive miss frag before the fix).
- **Deferred**: release signing/packaging, touch-first scheme, perf/size
  pass, upstream note, AGENTS/README pointers.

### Android device crash — split vblank wait loop exhausted the finite stack (2026-10-08)
Three native crashes on the Mi 11 port (within ~2–15 min of launch):
SIGSEGV "stack pointer is not in a rw map", 512+ frames of alternating
`gf_vblank_wait_loop+596` under `runtime_tick`.

- **Root cause.** The main loop's vblank-flag gate is two generated
  functions (0x08000418 loop head / 0x08000428 back-edge block, reached only
  by the head's `beq`). The back-edge compiles to a host call, so a spin
  whose wake flag (0x03000E10, written by the 0x080004B0 callback) does not
  arrive nests ~2 host frames per iteration. Present-in-place suppresses the
  frame-boundary unwind and its depth guard counts only BL pushes, so the
  growth is unbounded; desktop masks this with an unlimited main-thread
  stack (Pitfall 2) — the finite 256 MiB mobile thread turns it into a
  crash. Why the flag stalls on device is the subject of § "Android device
  hang" below (reproducible via the in-battle suspend-save flow).
- **Config fix attempted, blocked by the finder.** `[[extra_func]]
  resume = true` at 0x08000428 does not roll in: alias containment requires
  the candidate to lie inside the host's *linear* walk extent (0x418..0x422,
  terminated by `b 0x42A` before the literal pool), and the `beq` target
  sits beyond it. Reverted. Upstream item: extend mid-function alias
  roll-in to branch-target blocks in the walk-end..next-real-start gap.
- **Fix shipped:** `tools/patches/mobile-host-stack-guard.patch` (superseded
  2026-10-09 by `tools/patches/host-stack-guard-desktop.patch`, which also
  arms the desktop TCP game thread) — the
  mobile game thread arms a host-stack budget (stack minus 32 MiB); the
  per-instruction `runtime_should_yield` probe unwinds through the standard
  yield path once crossed (gated: never inside a live IRQ handler; same
  protocol as the vblank yield), logging
  `runtime: host-stack guard unwind count=… pc=0x…`. Desktop inactive.
- **Verification:** desktop cycle + check ALL PASS (9/9; patch listed);
  device gate PASS on the guard build; 10-minute soak monitored. Expected
  behavior under a recurring stall: bounded spin with guard log lines
  instead of a crash.

### Android: virtual pad idle auto-hide (2026-10-08)
- Feature: the touch pad hides after 15 s of screen-wide touch inactivity
  (user-tuned from 5 s the same day);
  any touch reveals it and the revealing touch also acts (a first cut
  consumed the wake gesture — two swallowed taps while driving the menus
  over adb proved the double-tap friction, so reveal now presses through).
  Held pad/toggle touches keep it visible so a control never vanishes
  mid-press.
- Engine: `tools/patches/touch-pad-idle-hide.patch` —
  `RunOptions::touch_pad_idle_hide_seconds` (0 = off) flows through
  `configure_touch` into `host_window`: per-present idle check, a `reveal`
  gesture category in the finger dispatcher, and draw/hit-test gates via
  `pad_overlay_shown`/`pad_toggle_shown`. First hide logs
  `host_window: pad idle-hidden (N s quiet)`.
- FFTA opts in with 5 s (`src/main.cpp`); inert without a touch pad.
- Verified: desktop cycle + check ALL PASS (9/9, patch listed); device
  screencaps: pad visible @3 s (BIOS), hidden @9 s (log line present);
  after the flip, a single tap on the idle-hidden menu pressed through
  (opened the Load screen, byte-identical render) with the pad restored.
  Upstream candidate.
- Tuned 5 s → 15 s on user request the same evening; re-verified on device
  (`pad idle-hidden (15 s quiet)` fires; live gameplay naturally exercises
  reveal-and-act).

### Android device hang — in-battle save → title (2026-10-08, open)
User-reproducible (three captures): an in-battle suspend save followed by
the return to title wedges the game. Live forensics (no root — whole-stack
dump via `run-as` + `/proc/<pid>/mem`, plus the TCP observe channel;
recipe: `reference/dev-gotchas.md` § Android device forensics):

- **Carrier = the split vblank wait loop.** The 256 MiB game-thread stack
  holds ~2.1 M nested frames of `gf_vblank_wait_loop` ↔
  `gf_vblank_wait_loop_cont` (64-byte frames; return into
  `gf_vblank_wait_loop+0x258`, right after `bl gf_vblank_wait_loop_cont`;
  each frame carries guest resume PC 0x0800041A) — the cross-function
  back-edge nesting from the crash section above, growing ~20 MiB/min. The
  host-stack guard would unwind it at 224 MiB (a bounded freeze, not a
  crash — working as designed); no guard line had fired when captured.
- **Trigger = the suspend-save flow.** Every capture shows the flash
  record mid-write (next group counter, checksum mismatch; the previous
  group stays valid, so a restart recovers the earlier suspend — save
  safety verified with `tools/savecheck.py`). The guest then waits on flag
  0x03000E10, which the vblank callback (0x080004B0 … m4a SoundMain) must
  set; it never arrives.
- **No coverage component** in the latest captures (FULLY_STATIC, zero
  misses; one earlier capture had a single intermittent bridged miss — a
  red herring).
- **Prime suspect: device audio.** `PlayerBase::stop() from IPlayer` at
  ~28/s since the first boot (~96 k lines — the SDL audio device is
  constantly restarting). The wake callback runs SoundMain before setting
  the flag (session-6 mechanics). First knob to try:
  `GBARECOMP_AUDIO_DIRECT=1` (the WWT device fix); IWRAM m4a-blob frames
  (`gf_tfunc_03003550/03003564`, `gf_afunc_0300364C/030037B4`) sit just
  above the nesting on the stack.
- **Mobile miss journaling is wired:** `src/main.cpp` sets
  `GBARECOMP_MISS_FRAG` under `on_mobile`, so bridged PCs durably rewrite
  `files/recomp_master_misses_AFXE.toml.frag` — a hung/killed session can
  no longer lose the proposal (the exit-time report never runs on kill).
- **Probe kit:** `tools/hangprobe.py <port>` — read-only registers,
  IF/IE/IME, wake flag, IRQ vector, miss report. Never send
  `savestate_save` to a stalled observe server: it queues at "the next
  present" and wedges the single-client server (learned the hard way).
- **Next:** capture IF/IE/IME + flag on the next reproduction (distinguishes
  "IRQs blocked" from "callback stalled"); then test the direct-audio knob;
  upstream note: stack-guard patch + the finder roll-in gap (a
  branch-target block beyond a host's linear walk extent cannot merge).

**Update (same evening, live-session findings).** Read-only observe probes
plus a breakpoint test on a fresh reproduction:

- IRQ ring (`irq_cap`): **exactly one vblank IRQ per frame** (src=1;
  cycle delta = 280,896 = one frame), taken in the wait loop, no storm, no
  nesting in steady state. IF shows vblank pending mid-vblank as expected.
- The callback is entered every frame (`set_break_pc 0x080004B0` pins all
  samples there) **and reaches the flag-write sequence**
  (`set_break_pc 0x0800050A` pins; disasm 0x4B0..0x522 shows a
  straight-line `strh #1 → 0x03000E10` at 0x051C) — yet the wait loop
  reads the flag as 0 (`ldrh r1,[0x03000E10]` sampled live). The flag is
  either set-then-undone by another reader, or the write does not stick;
  this contradiction is the crux.
- The m4a mixer runs real work each callback (hot PCs 0x0300377x..B4 with
  live sample pointers and sane counters — not a corrupted state).
- Save record mid-write in every capture; the previous group keeps loading.
- **Caution:** clearing that break tripped the engine's handler-abandon
  rail ("handler at depth 2 did not iret after 4M dispatches") and the
  session derailed (bridged miss 0x03005710 → interpreter Undefined
  0x030057DC → crash). `set_break_pc` on an IRQ-path PC is a last-act
  inspection tool; expect the session to die afterward.
- **Next:** reproduce the same save + flow on desktop (scratch config +
  the pulled save image) and chase the flag contradiction locally with
  rings and the oracle.

### 2026-10-09 — Android hang reproduced on desktop: deterministic steppable crash + nesting mechanism
**Repro (deterministic, ~30 s, headless).** `--tcp` (steppable) + TCP
`savestate_load game.state3` (loads at f4515; plain `--load-state` is NOT
applied by the `--tcp` path) → `step`×98 → `set_keyinput 0x03FE`×4 →
`0x03FF` → the process **SIGSEGVs (rc 139) 26 steps after the press**; the
crash step starts at pc 0x08006CE4. 600 pre-press steps are clean. This
closes the Android entry's next-step: the save+flow hang now reproduces on
desktop without a device.
**Mechanism (gdb-verified).** Backtrace at the crash: ~284k alternating
host frames `gf_vblank_wait_loop ↔ gf_vblank_wait_loop_cont`, rsp at the
bottom of the 8 MiB thread stack, RIP inside `render_scanline_internal`
(host PPU render called from `runtime_tick` from inside the deep loop) —
i.e. host-stack exhaustion by the generated split of the 4-instruction
vblank spin (0x08000418 `ldrh` / 0x0800041C `cmp` / 0x0800041E `beq` /
0x08000428 `b`): each spin iteration maps onto host **calls** pairing the
two generated functions (+2 frames/iteration, ≈59 B each — same signature
as the device's "64-byte frames"). In normal operation the spin exits on
the first vblank-flag set, so the cascade unwinds every frame and never
accumulates; **after the A press the steppable path keeps spinning within a
step and the cascade grows without bound** until the stack (and then the
render call path) dies. The windowed path's present-in-place hook bypasses
the per-frame unwind/redispatch, so it does not nest — instead the same
flow shows an endless title/intro "churn" (screens cycle for 30+ min of
guest time; input-response yet unverified locally due to window-focus
issues). Device guard (`tools/patches/host-stack-guard-desktop.patch`) is
the existing bounded mitigation for exactly this nesting; the desktop
steppable path has no equivalent.
**Boundary-state reads (pre and post press, per frame).** flag
0x03000E10=1, IE=0x2003, IF=0, IME=1, KEYINPUT clean; pc at the wait loop
at every frame boundary — so the spin-exit failure is within-step, not a
global IRQ lockout.
**Anti-red-herrings (re-checked today).** Watchdog "busy-spin" trips fire
in healthy play too; the m4a "spin" in the dump (`pc=0x03003514`) is the
engine's normal mixer block (bounded, `subs/bgt`, count=0x83); the m4a
ident 0x68736D54 in the sound struct is the standard "engine enabled"
handshake, and the open-bus reads at a garbage pointer are the (already
present) MC-HP-002 open-bus behavior. None of these is the root cause.
**Oracle context (mGBA, same save):** suspend→A returns to the title; a
return-to-title (soft reset SELECT+START+A+B verified) replays the intro
("It was a day like any other…"), and START during the attract interrupts
to the title menu — i.e. the intended post-press flow is title→attract
with live input, which is what the windowed churn should be compared
against.
**Artifacts (gitignored):** `logs/savehang/{gdb_tcp3.log,gdb_tcp4.log,
tcp2.log,tcp3.log,pcflag.csv,churn/,ramsnaps-*}` plus the failed-press
recipes. Fix candidates: (a) arm the stack-budget guard on desktop
non-PIP paths; (b) root-fix the split-loop nesting (upstream finder
roll-in gap, see the Android entry's upstream note); (c) nail why the spin
does not exit within the step post-press.

### 2026-10-09 (later) — guard ported to desktop; nest-depth poisoning identified
**Walk results (gdb + per-instruction ring `fp_save`; all local, gitignored):**
- The spin **does** exit: in the last 8.3M instructions the ring shows 126
  clean passes (flag read=1 exactly 126×, clear@0x08000416 126×, IRQ set
  @0x0800051C 126×, exit@0x0800042A 126×). Guest logic = intact.
- The leak is host-side: the generated split of the vblank spin
  (`gf_vblank_wait_loop` ↔ `gf_vblank_wait_loop_cont`) compiles to **real
  nested calls** (objdump-verified: `call` + `ret`, no tail-calls), ~1 pair
  per spin iteration; the chain stops unwinding after the suspend flow and
  grows ~412 KB/frame (≈6,000 pairs) until the 8 MiB thread stack dies.
- **Poisoning event (~31 frames post-press):** the last clean IRQ request
  comes from the game's DISPSTAT `wait_for_vblank` helper
  (`0x08003398`; `gpc=0x080033BA` inside it); from
  the next frame onward `g_irq_nest_depth` **never returns to 0** (measured:
  the wait-block clear `0x08000416` runs at nd=1, the handler at nd=2). The
  mainline permanently runs "inside" a handler that never re-accounts its
  exit (guest `pop {r0}; bx r0` return interleaved with the vblank request).
  This explains the desktop churn *and* mirrors the device's
  flag-contradiction/handler findings. It also explains why the mobile
  guard's `nest_depth == 0` gate never fires once stuck.
**Fix shipped (safety net):** `tools/patches/host-stack-guard-desktop.patch`
(supersedes `mobile-host-stack-guard.patch`): the guard is platform-neutral,
armed on the desktop `--tcp` game thread via `host_stack_guard_arm_current`
(2 MiB margin), plus a **critical tier** (`host_stack_critically_low`, last
0.5 MiB) that unwinds even when `g_irq_nest_depth > 0` — the stuck state.
Validated: the deterministic press repro (SIGSEGV at +26) now survives with
`runtime: host-stack guard unwind count=… (nested)` lines; the process stays
alive (bounded; steps become very slow while the poisoned state persists).
Android arming extended with the same critical tier (untested on device).
**Still open (the true root):** the nest-depth accounting at the
return/IRQ interleave in `runtime_irq`/`runtime_exception_return`
(`g_irq_nest_depth`/`g_irq_iret_depth`), and the upstream split-loop merge
(roll-in gap) that would remove the recursion entirely. Also: whether the
windowed churn (PIP path) and the device signatures share this exact
poisoning once the guard keeps it alive.
**Regression coverage (same day):** unit tier —
`tests/unit/test_host_stack_guard.cpp` (folded into the `unit-cpp` CI
suite): the armed-path checks fail if the guard is desktop-stubbed again
and pin the two-tier ordering against real thread bounds. End-to-end —
`tools/hangrepro.py` (`check.py --only hangrepro`, ~90 s): the state3 press
must stay bounded with `host-stack guard unwind` lines instead of the
former SIGSEGV (skips without the gitignored state/save). Tighten
hangrepro's assertion (nest depth must no longer stick) when the accounting
root fix lands.




### Playtest session 1 — first-battle path now fully static (2026-10-06)
The user played the desktop build interactively (letter-only keymap; see the
IBus note above) through the intro, menus and into the first battle (two
savestates kept at the repo root: `game.state1`/`game.state2`, gitignored).
Session totals: 29,070 recorded input frames (`logs/playthrough.csv`), **901
distinct self-heal miss PCs** (`logs/playtest_misses.frag`; 484 in
0x0802xxxx, 156 in 0x0809xxxx, 124 in 0x0812xxxx).
- **Batch a**: 181 prologue-scan starts + 2 IWRAM islands (tools/misspack
  evidence in `logs/playtest_pack.md` / `logs/playtest_start_proposal.txt`).
- **Batch b**: 15-iteration strict-replay resolve loop added 20 more seeds
  (candidate start when valid; direct seed of the miss PC itself for
  switch-case interiors whose starts were ineffective).
- **Result: strict replay of the entire session (29,100 frames) =
  FULLY_STATIC, 0 dispatch misses** (`logs/playtest_strict_final.log`).
  Attract gate unchanged (same pinned hash) throughout.
- Coverage after merge: corpus 23,450 → **28,491 units**; pointer-pool lens
  49.4% → **57.8%**; walker's static reach 99.2%.
- **Pointer-pool calibration**: only 241/901 played PCs (27%) were inside the
  pointer-pool proxy and 0/901 in the walker's reach — execution found the
  rest via table math / computed targets. The pool is a different proxy,
  not a superset of real code.
- Next: battle-region harvesting from the savestates (`--load-state` +
  the trace's tail replays into the battle without the intro), then
  continue the play session to complete the battle.

### Battle-session crash: self-heal bridge runaway — resolved by coverage (2026-10-06)
- **Symptom**: SIGABRT after a ~56k-frame state2-loaded battle session. Core:
  `abort()` inside `runtime_bridge_interpret` ← generated code. Terminal
  message: `SELF-HEAL bridge for 0x080DAE78/0x0811F9F0 exceeded 200000000
  instructions without returning to stop_pc=0x08092858 (current pc=0x0800041C)`
  — the interpreter bridge spun executing code whose exit condition (an
  IRQ-driven flag / VM state) cannot progress under the bridge's model; the
  200M-instruction watchdog aborted loudly *by design* (PRINCIPLES: never
  spin silently). Same `stop_pc` both times → same call context (battle code
  at 0x080928xx calling into the script VM).
- **Lost artifact**: the `.frag` proposal file flushes only at clean exit; the
  crash lost that session's miss list. The durable record was the **heal
  cache** (168 completed units) plus the terminal text.
- **Deterministic repro**: `--load-state game.state2` +
  `GBARECOMP_INPUT_REPLAY=logs/playthrough.csv` (the trace's frame counter
  jumps `0 → 29592` at the state load because recordings are guest-frame
  based → faithful replay). Abort reproduced headless within minutes.
- **Resolution — batches c/d/e** (231 units total): c = session-2 cache units
  (168), d = state2-repro heals (61, incl. script-VM blocks near
  `gf_tfunc_0811F944`), e = final tail (2: 0x08122EC0, 0x08123958).
  **Strict state2 battle repro (60,000 frames): FULLY_STATIC, 0 misses**
  (`logs/state2_strict.log`); strict boot→newgame 6000-frame regression also
  FULLY_STATIC; attract-gate hash unchanged throughout.
- **Tooling**: added `tools/cache_harvest.py` — recovers miss pcs from
  `recomp_cache` filenames when a session crashes before the `.frag` flushes
  (the `.frag` writes at exit only — verified again this session).
  Trace archived at `inputs/session2_battle_trace.csv` (needs local
  `game.state2`).
- **Open observation (framework-level)**: the bridge's stop contract
  (LR / call-stack-top) was never satisfied for these mid-block entries — it
  aborted rather than bridging. Coverage now avoids the situation entirely;
  worth reporting upstream as a bridge-limitation data point.

### Crash #2 (session 3, 2026-10-06): same bridge-runaway family — resolved by cache harvest
- **Session shape**: state2 loaded at boot, then two backward replays
  (guest-frame timeline 0→98,327; backward jumps 70,858→66,370 and
  68,120→66,357 = state2 reloads), heavy savestate save churn — the
  intermediate f66191 state was overwritten and is unrecoverable; the final
  `game.state2` resumes at frame 97,209.
- **Crash**: bridge entry **0x0811E2A4** — a `BL`-return point after
  `bl 0x814186C` (the same SWI-stub thunk family as crash #1) — same
  `stop_pc=0x08092858`; watchdog abort after 200M instructions (current
  pc=0x08000428, the VBlank-wait loop). Saves interleaved during the spin.
  The `.frag` again did not flush (exit-only; mtime unchanged).
- **Harvest**: heal cache had 61 completed units from the session
  (0x0800D3xx, 0x080D95xx/0x080DFBxx, 0x0811E1xx–0x0811E2xx clusters) —
  merged as **batch f**; it includes 0x0811E2A4 itself (game.toml line 3191).
  `tools/cache_harvest.py` used again (second validated use).
- **Verification**: strict continuation from the final state2 (frame 97,209,
  60,000 frames idle) = **FULLY_STATIC**, 0 misses
  (`logs/state3_strict.log`); attract gate unchanged.
- **Tooling**: `play.sh` now auto-archives the previous session's
  `game.stateN` → `saves/*_prev_<ts>.state` and the previous trace →
  `saves/trace_prev_<ts>.csv` at launch (states are destructive across
  sessions; this session's f66191 state was lost that way). The final state
  from this session is archived at `saves/session3_state2_late_f97209.state`.
- **Pattern**: both crashes = bridge entered at a stub-call **return point**
  inside the 0x0811xxxx VM region; each session's discovery wave moves
  deeper. The `.frag`-flush gap is covered by cache_harvest; the bridge
  stop-contract limitation stays noted for upstream.

### Session 4: first crash-free continuation (2026-10-06)
- Short continuation from session-3's final state (guest frames
  97,209→97,618). **No crash.** play.sh's new auto-archive preserved the
  prior session's state + trace (`saves/game_prev_20261006_171723.state` /
  `trace_prev_20261006_171723.csv`) — exact files used for the acceptance
  replay below.
- The `.frag` **flushed on clean exit** (first in-the-wild confirmation of
  the exit-only flush policy).
- Harvest: 5 VM units (0x0811E7E0, 0x0812260C, 0x08122EF8, 0x08123564,
  0x081239DC) — heal cache and frag agree exactly (first dual-source
  cross-validation). Merged as **batch g**.
- **Acceptance: strict replay of the exact session** (load the archived
  start state + session-4 trace, 99k-frame bound) = **FULLY_STATIC**,
  0 misses (`logs/session4_strict.log`); attract gate unchanged.
- play.sh fix: per-slot archive names (`state1_prev_`/`state2_prev_`) —
  the first version collided both slots onto one filename.
- Frontier trend (miss units per session): 901 → 168 → 61 → 5. The
  discovery wave is closing as the VM region converges.

### Session 5 (2026-10-06): wider window, crash-free; first follow-on-only resolve
- Played with `--scale 8` (1920×1280; window-size doc fix committed same
  night — `--view-width` is the widescreen-*view* feature, clamped to 240
  for FFTA; `--scale` is the size knob). State resume f104,591 → 111,485;
  crash-free; `.frag` flushed; play.sh per-slot archives worked (start state
  = `saves/state2_prev_20261006_172820.state`).
- **Batch h**: 10 units (0x0800A244, 0x08029188, 0x080BFDB0, 0x08123098/A0,
  0x08123848, 0x081239F8, 0x08124D58, 0x081287C4, 0x0812BA08) — heal cache
  and frag agree.
- **Follow-on pattern**: the strict replay then exposed ONE callee
  (0x08019480) the play session never surfaced — its caller had always run
  inside a bridged subtree, so the callee only appears once the caller is
  static. **Batch h2** seeds it. Expect ~1 follow-on iteration per session
  from now on.
- **Acceptance: strict replay of session 5 from game.toml = FULLY_STATIC,
  0 misses** (`logs/session5_strict_final.log`); attract gate unchanged.
- **Tooling**: the resolve loop is now scripted — `tools/resolve.py`
  (temp overlay + proposal file; never writes game.toml). Next session
  closes with: cache_harvest → merge → `resolve.py` → cycle → commit.

### Session 6 + the savestate wedge (2026-10-06 late)
- **Savestate wedge (OPEN)**: loading `game.state2` (captured at f115,148
  right at the user's 17:41 in-game save) and pressing A wedges the game at
  guest frame **115,248** — deterministic in strict and non-strict, headless;
  >150 s with zero progress (not a coverage miss — nothing bridged; without
  the press the same state runs 140,000 f clean; frames 1–99 after the press
  are normal ~0.5 s). Repro preserved: `saves/state2_prev_20261006_*.state`
  (identical copies, 20:51–21:10 archives). Evidence so far: the spin is
  guest-side in the frame-gate wait loop (0x08000418/0x08000428, flag
  `0x03000E10`) with IRQs enabled; gdb sampling shows m4a-region code (BIOS
  SWI wrappers @0x0814186x; m4a track setup @0x081377B0 calling CpuFastSet)
  rotating with PPU-render ticks from `runtime_tick` — the post-load path
  re-enters the per-frame m4a sync handshake and never completes it.
  Next: read flag/IF/IE/IME at the wedge (gdb child + `&g_cpu`/bus frame
  reads) and compare against the mGBA oracle driven from the in-game save.
  The user re-ran the repro at 20:51/21:10 (unchanged) and moved on via a
  fresh playthrough.
- **Fresh-playthrough sessions**: A = boot → f11,210 (in-game save 21:11;
  state2 saved @f11,635 = `state2_prev_20261006_215054.state`); B = from
  that state → f19,274 (the 21-unit heal wave, 21:51–52). Strict replays of
  both are **FULLY_STATIC** (`logs/session6a_strict.log`,
  `logs/session6_strict.log`).
- **Batch j**: 5 reviewed entries — starts 0x080E8590 / 0x080E87C0 (cover
  18 switch-interior entries) + direct entries 0x080E8734 / 0x080E8956 /
  0x080E8A18 — cover all 21 session-6 units; frag and heal-cache agree
  exactly (3rd cross-validation). The two starts walked out **+3,391 units**
  (corpus 30,554 → 33,945); pointer-pool lens 59.8 % → 65.2 %.
- **Batch i** (merged earlier, committed here): 0x080191B0 + 0x08142160 —
  live-healed during the 17:41 in-game save; save-path helpers.

### Session 7 (2026-10-07 morning): first non-tutorial battle completed
- Session shape: loaded the state2 snapshot saved at the end of session B
  (f19,076 — mid-battle), finished the battle in ~40 s of play
  (f19,076 → f21,467), saved state @f21,467, clean exit (frag flushed).
- **Batch k**: 4 heal units, all four verified push-rooted starts (first
  all-clean batch): 0x080E2C54 (battle-end path, bridged x15) + the first
  three **event-interpreter (0x08123xxx)** seeds — 0x08123860, 0x08123B68,
  0x08123CFC — the AGENTS "known hard spot" region, healed live without
  incident. resolve.py = PASSED iter 0, 0 seeds; strict replay FULLY_STATIC
  (`logs/session7_strict.log`); cycle.py PASS (attract hash unchanged);
  corpus 33,945 → 33,989; pointer-pool lens steady ≈ 65.2 %.

### Session 8 (2026-10-07 07:15–07:17): main-game content continues
- Loaded the session-7 end state (f21,467), ~2.5 min of play to ≈f26.6k,
  clean exit; **31 heal units** — the largest wave since the 22-unit
  new-game batch.
- **Batch l**: 14 verified starts cover all 31 units (no direct seeds). The
  frag's 15-entry jump-table candidate [0x0811E890, 0x0811E92A] turned out
  to be two ordinary functions (0x0811E890 + 0x0811E8E0) whose case targets
  are all interiors — starts + walker sufficed again. Also 0x08123968 /
  0x08123A08 (event-interpreter) and 0x0812B7F0.
- resolve.py = PASSED iter 0, 0 seeds; strict replay FULLY_STATIC
  (`logs/session8_strict.log`); cycle.py PASS (attract hash unchanged);
  corpus 33,989 → 34,362 (+373); walker ≈ 98.5 %; pool ≈ 65.5 %.

### Session 9 (2026-10-07 07:29–07:31): mid-session savestate reload
- Loaded the session-8 end state (f26,481), played, then **reloaded the same
  state mid-session** (guest frame jumped 29,853 → 26,6xx) and continued —
  the recorded trace is no longer monotonic and `GBARECOMP_INPUT_REPLAY`
  rejects it ("invalid input trace line"). New tool: `tools/trace_split.py`
  splits a trace into monotonic segments; each segment then resolves from
  the same start state.
- **Batch m**: 18 heal units (frag+cache agree, 4th validation) → 9 verified
  starts; the hot 6-PC jump-table candidate [0x0803155C, 0x08031636]
  (bridged up to x487) was again two ordinary functions. First 0x08122xxx
  event-interpreter seeds merged. Strict acceptance of both segments caught
  2 extra PCs (0x080318D0/DC — tiny `push {lr}` thunks into 0x08031708);
  merged.
- seg1 + seg2 strict replays FULLY_STATIC (`logs/session9{a,b}_strict.log`);
  cycle.py PASS (attract hash unchanged). Corpus 34,362 → **39,027** (+4,665
  — the 0x08031xxx walk-out); walker ≈ 98.7 %; **pointer-pool 65.5 % → 74.3 %**.

### Session 10 (2026-10-07 07:44): region sweep in a short session
- Loaded the session-9 end state (f30,634), ~20 s of play to ≈f31.9k, clean
  exit; 9 heal units (frag+cache agree, 5th validation) across 0x0803xxxx,
  0x0804xxxx, 0x0805Cxxx and 0x0806xxxx.
- **Batch n**: 6 verified starts + 1 direct epilogue entry (0x08044D72 — a
  shared epilogue block reached via `bls` @0x08044D68). Strict acceptance
  caught 1 extra start (0x0806094C, `push {r4-r7,lr}`); merged.
- Strict replay FULLY_STATIC (`logs/session10_strict.log`); cycle.py PASS
  (attract hash unchanged). Corpus 39,027 → **40,518** (+1,491); walker
  ≈ 98.8 %; **pointer-pool 74.3 % → 77.2 %**.

### Session 11 (2026-10-07 08:00): first 6-seed resolve chain
- Loaded the session-10 end state (f32,050), ~50 s to ≈f35.0k, clean exit;
  5 heal units (frag+cache agree, 6th validation).
- **Batch o**: 4 starts (incl. 0x0808A158, binary-search-shaped, covering
  interior 0x0808A1E8). The resolve then needed **6 iterations — a
  new-region chain**: the already-seeded start did not walk the interior
  (resolve direct-seeded 0x0808A1E8), then 5 more clean starts surfaced
  (0x080220B4/CC, 0x08058D40, 0x080592F8, 0x08059454); all merged.
- Strict replay FULLY_STATIC (`logs/session11_strict.log`); cycle.py PASS
  (attract hash unchanged). Corpus 40,518 → **41,728** (+1,210); walker
  ≈ 98.8 %; **pointer-pool 77.2 % → 79.5 %**.

### Session 12 (2026-10-07 08:15–08:18): party-menu wave, two sessions
- Two sessions ran since session 11 (A: 08:15→08:17, 17 units; B: the
  party-menu pass, 5 units); heal-cache mtimes attributed the units and
  the frag+cache agreement held (22 total, 7th validation).
- **Batch p**: 8 verified starts + 2 direct post-pool entries (0x0807698C,
  0x0807934C) cover all 22. Unlike earlier batches, the hot 6-PC candidate
  [0x08076560, 0x08076610] (bridged up to x2024) was **one** function, and
  the 4-PC candidate [0x08078818, 0x08078894] was one function too.
- resolve.py: both sessions PASSED iter 0 with 0 seeds (batch p was complete
  on the first try); strict acceptance FULLY_STATIC for both
  (`logs/session12{a,b}_strict.log`); cycle.py PASS (attract hash
  unchanged). Corpus 41,728 → **43,900** (+2,172); walker ≈ 98.9 %;
  **pointer-pool 79.5 % → 83.6 %**.

### Session 13 (2026-10-07 08:39–08:41): short session, 7 starts
- Loaded the session-12b end state (f41,238), ~95 s to ≈f47.2k, clean exit;
  13 heal units (frag+cache agree, 8th validation) — further 0x08018-19xxx
  region code (the A-press-incident neighborhood) plus a 0x080601xx pair.
- **Batch q**: 7 verified starts cover all 13; the 8-PC candidate run
  [0x080194A8, 0x08019594] resolved to **three** adjacent functions
  (0x080194A8, 0x080194E4, 0x08019574 — each with interiors).
- resolve iter 0, 0 seeds; strict FULLY_STATIC (`logs/session13_strict.log`);
  cycle.py PASS (attract hash unchanged). Corpus 43,900 → **43,981** (+81 —
  near-leaf functions); walker ≈ 98.9 %; pointer-pool 83.6 % (flat).

### Session 14 (2026-10-07 08:47): shopping trip, 6-seed resolve chain
- Loaded the session-13 end state (f47,414), ~30 s of shopping/menus to
  ≈f49.3k, clean exit; 2 heal units (frag+cache agree, 9th validation).
- **Batch r**: 1 start (0x08068AE0) covered both units. The resolve then
  chained another new-region wave — 6 clean starts (0x08068C10, 0x08069574,
  0x08069658, 0x0806B338, 0x0806EB48, 0x08018D38); all merged. 12m07s
  wall for 6 iterations (~2 min/iter — regen+build dominated).
- Strict FULLY_STATIC (`logs/session14_strict.log`); cycle.py PASS (attract
  hash unchanged). Corpus 43,981 → **45,122** (+1,141); walker ≈ 98.9 %;
  **pointer-pool 83.6 % → 85.8 %**.

### Session 15 (2026-10-07 09:09): second shopping run — mega-function test
- Loaded the session-14 end state (f47,414), ~70 s of shopping to ≈f51.8k,
  clean exit; 14 heal units (frag+cache agree, 10th validation), all in the
  0x0806B/C/D shop/menu region.
- **Batch s**: 2 starts (0x0806B228, 0x0806B6D0) merged first; 11 of the
  unit PCs are deep interiors of the 0x0806B6D0 **mega-function** (measured
  up to 0x1AF0 back). The walker covered all 11 from the single start —
  good validation of the start-first policy on multi-KB state machines.
  Resolve chained 1 extra clean start (0x0806D2B4); merged; iter 1 pass.
- Strict FULLY_STATIC (`logs/session15_strict.log`); cycle.py PASS (attract
  hash unchanged). Corpus 45,122 → **45,537** (+415); walker ≈ 98.9 %;
  **pointer-pool 85.8 % → 86.6 %**.

### Native-save hang #2 (2026-10-07 09:20) — reproducible; root-cause in progress
- **Symptom**: field-menu native (flash) save — the save WRITES successfully
  (`saves/playtest.sav`, 09:20:57) and the game then hangs forever (hot spin,
  99.8 % CPU; live process SIGABRT-captured to `/tmp/ffta_hang.core`).
- **Capture/stacks**: main thread spinning with alternating
  `0x08141B74`/`0x08141B80` frames + nested `runtime_irq`/IWRAM frames;
  guest pc at kill was in IWRAM, sp=0x03007FF0. Matching binary preserved at
  `/tmp/FFTARecomp_at_hang`; post-hang save copy `/tmp/playtest_at_hang_0921.sav`.
- **Deterministic repro (preserved)**: `--load-state
  saves/state2_prev_20261007_092041.state` + `GBARECOMP_INPUT_REPLAY=
  logs/playthrough.csv` + `--frames 2756` → non-strict hangs (timeout);
  strict aborts at the coverage frontier below.
- **Fixed (batch t)**: the save path was never statically covered (it only
  runs on save). Merged: starts 0x081419C0, 0x08141E30 (strict repro's first
  miss); planted-IWRAM getters 0x03007D48/0x03007D9C/0x03007E00 (`ldrb
  r0,[r0]; bx lr`, dump-verified, same plant mechanism as the 0x03007E60
  getter); copied byte-compare 0x03007CE4 ← ROM 0x08141BB0 (0x2E B, verbatim
  dump match); byte-copy loop re-planted unaligned at 0x03007CA2 (entry
  0x03007CA4 ← ROM 0x08141AEE/0x08141AF0, dump-verified 0x26 B).
- **Frontier (open)**: with those merged, the strict repro advances into the
  save driver's runtime **code-relocation machinery**: the driver assembles
  a helper on its stack (sp=0x03007D08), calls it through the `bx r5` veneer
  @0x08142250 (r5=sp|1), and then executes/copies targeting **0x2201D008**
  (trace ring, `GBARECOMP_RUNTIME_TRACE=1`: final events r0=0x03007D09,
  r1=0x2201D008, r2=0x80, ARM mode; then a bridged fetch at 0xE25EF004 =
  garbage). 0x22xxxxxx is outside every decode region (gbarecomp: OpenBus;
  no EWRAM mirror above 0x02FFFFFF) → garbage execution → hang. **Open
  question**: is 0x2201D008 a game constant read from its EWRAM structures
  (→ model it), or a value corrupted earlier in our run (→ first-divergence
  hunt before the save call)? Key evidence already local: final trace-ring
  dump (see /tmp/repro_ns3.log), driver tail disasm 0x08141B86..BA2, core.
- **Not crashes**: cores 123841/124227/128372 (08:56/08:58/09:13) are
  resolve-iteration strict aborts (expected mode of the resolve loop).

### Batch t status (needed by the strict frontier)
- The nine healed units of the hung session are fully merged via the entries
  above; strict acceptance of the repro trace still stops at the open
  frontier (0x2201D008), so batch t is **partially** accepted: attract gate
  PASS, coverage corpus 45,537 → 45,559, walker ≈ 98.9 %, pool ≈ 86.6 %.

### Native-save session (2026-10-06, 17:41): Batch i — the session that produced `game.state2`
- The user played a continuation and performed an in-game (native/flash)
  save at 17:41. The session produced the post-save savestate `game.state2`
  (frame 115,148) and the battery save `saves/playtest.sav` (its SAV0 chunk
  parses clean — verified during the session-6 hang investigation below).
- Self-heal live-healed 2 units while the save ran; both landed in the repo
  heal cache (17:41). Prologues re-verified by disarm at commit time:
  `push {r4,lr}` @0x080191B0; `push {r4-r7,lr}; sub sp,#0x40` @0x08142160.
- **Batch i**: both merged into `game.toml` as `[[extra_func]]` seeds
  (they sat uncommitted until now).
- **Validation at commit** (`tools/cycle.py --frames 1200`, cold regen):
  regen OK (30,554 units emitted — the README snapshot's 30,554 already
  includes Batch i), dispatch sanity OK, build OK, **attract gate PASS**
  (golden sha256 `1EF4C118…EF321C1` unchanged — the seeds alter no
  behavior).
- Cross-reference: Batch i is **unrelated** to the session-6 hang — the
  hang investigation confirmed the wedged runs never bridged any unmapped
  PC (heal caches stayed empty through every repro); these two units only
  execute inside the save flow itself.

### Session 6 hang (2026-10-06, user report "still got a hang"): reproduced + root-caused to a nestable-VBlank × non-reentrant-SoundMain race — TIMING bug, not coverage
- **User report**: interactive playthrough froze; the user pinned the repro
  himself: load `game.state2` (the post-native-save savestate, frame
  115,148), press A (guest frame 115,302) → hang.
- **Reproduction (deterministic)**: headless `--load-state game.state2` +
  `GBARECOMP_INPUT_REPLAY=logs/playthrough.csv` + `--frames N`: for any
  N ≥ ~1140 the run NEVER exits (timeout kill; the guest wedges inside ONE
  never-returning dispatch — a budget-1200 run ran its vblank counter to
  1439+ past its own budget without the runner loop ever iterating again;
  a budget-1140 run likewise never exited) → wedge onset ≈ frame
  116,288 (≈1140 after the load).
  Two concurrent identical runs trip the hang watchdog at byte-identical
  guest state (pc=0x08001646, cycles=404,347,423, vblank=1439, identical
  m4a snapshot) → the guest state at the wedge is deterministic; earlier
  one-off trip-point scatter (1281/1403) was wall-clock sampling of the
  same stuck loop at different host speeds. **NOT a coverage problem**:
  FULLY_STATIC, dispatch_misses=0, interpreted_insns=0, empty heal cache
  through every repro run.
- **Guest-side mechanism (all ROM-verified via tools/disarm.py)**:
  - Main loop frame sync is a BUSY-WAIT, not IntrWait: 0x0800040C-0x08000416
    clears the flag `[0x03000E10]`, then 0x08000418-0x08000428 spins until
    non-zero, then `bl 0x08000460` runs the frame step.
  - The flag is written at the very END of the per-frame callback
    0x080004B0 (called from the VBlank path): 0x0800050A-0x0800051C
    (`ldrh; movs#0; orrs#1; strh` → flag=1). Before that the callback runs
    SoundMain (`bl 0x08144AF0` @0x080004B4 — the IWRAM mixer copy
    0x030034DC..0x0300385C, game.toml audit #15) plus ~12 subsystem calls
    (0x080004B8-0x08000506).
  - At the wedge the callback NEVER reaches its flag write: the
    hang-watchdog fp tail (16k records, INSN_TRACE armed) is 100% mixer
    (0x03003774-0x030037B8 etc.) — SoundMain's channel walk never
    terminates (voices progress forever into the same 264-sample chunk at
    0x02008D58, spv=264) → the main loop's wait spins forever → frozen
    screen with the mixer burning the CPU (no HALT; vblank_starts still
    ticks because the spin's cycles still advance the PPU).
- **The trigger scene**: `irq_cap` (TCP) around guest frame ~1197-1290
  (≈17 s after the A press) shows VBlank IRQs vectoring with rets INSIDE
  sound-driver code (0x081466xx-0x081468xx, 0x08142C3E) and BIOS/early-ROM
  code (~50% of frames) — a cutscene/transition whose per-frame work
  (mixer + task handler 0x0813C0EC + sprite math 0x080014C8 + CpuSet
  thunks) sits at the one-frame limit.
- **Why the game can wedge at all**: FFTA's IRQ dispatcher
  (ROM 0x080000FC, IWRAM copy 0x03000F10) RE-ENABLES interrupts inside the
  handler — `mrs r3,apsr; bic r3,r3,#0xdf; orr r3,r3,#0x1f; msr
  cpsr_fc,r3` @0x0800019C-0x080001A8 clears the I-bit and enters system
  mode. Nesting is by design (hardware too). m4a SoundMain is NOT
  reentrant: a VBlank that vectors while SoundMain is mid-walk corrupts
  the shared channel-walk state → the walk never ends. The runtime models
  all of this faithfully (runtime_irq sets CPSR_I_BIT, tracks nesting).
- **Driver sensitivity (the knife edge)**: the SAME state+press driven
  over TCP (`set_keyinput` + `continue`) survives the scene (ran 12k
  frames, parked later at the same flag-wait pattern ~frame 10.9k), while
  the replay path wedges at ~1.2k. Identical input (composed KEYINPUT =
  host&synth, both default 0x3FF — verified gba_io.h:264-265); identical
  guest state; only per-dispatch host work differs (apply_input_replay
  after every dispatch in the --frames path). The scene is right at the
  280,896-cycle frame boundary, so small IRQ-delivery/batching shifts
  decide whether SoundMain finishes before the next VBlank vectors.
- **Excluded by evidence**: flash save engine state (SAV0 chunk of the
  state parsed: flash_state=Idle, id_mode=0, bank=0, dirty=0 — clean, not
  mid-write); self-heal bridging (0 misses); present-in-place (hang
  reproduces with GBARECOMP_PRESENT_IN_PLACE=0); touch-policy composition;
  KEYINPUT divergence between drivers.
- **Measured our cycle model in the mixer inner loop** (fp-ring deltas):
  ~1 cycle per simple insn, 1 cycle for MUL (hardware ARM7TDMI: 2-5+), 6
  cycles per ROM sample fetch (`ldrsb` from 0x0816xxxx/0x081BAxxxx). The
  VBlank IRQ cadence is exact (280,890-280,906 cycles, TCP irq_cap) — IRQ
  delivery is not drifting.
- **Root cause statement**: a TIMING knife-edge. The post-save cutscene
  runs SoundMain-in-a-nestable-VBlank at (or over) one frame of work; when
  the next VBlank vectors mid-SoundMain, the non-reentrant mixer corrupts
  and the channel walk never terminates. Whether the boundary is crossed
  depends on sub-frame timing deltas between our runtime and hardware.
  Next steps: (a) mGBA oracle comparison of SoundMain's cycle cost at this
  scene (blocked: the oracle cannot load our GBAS savestates — needs a
  boot-to-scene trace; the playthrough traces exist but span state loads),
  (b) audit the wait model against mGBA for the mixer's ROM/EWRAM fetch
  pattern (runtime_wait_model.h — prefetch/WAITCNT), (c) upstream note:
  gbarecomp should expose a diagnostic for "IRQ vectored while a prior
  same-source handler is in flight" (g_irq_nest_depth by source) to make
  this class self-documenting, (d) workaround candidate: none clean —
  this is guest-legal behavior; the fix must be timing-accuracy.
- Scratch artifacts from the hunt live under /tmp/opencode/ffta-hang/
  (repro dirs, probes, ring dumps) — nothing repo-side changed; no
  game.toml edits (this is not a coverage issue).
- **Community corroboration (web research, 2026-10-06)**: FFTA has a
  documented class of freezes at exactly this shape — audio/transition
  moments and data-driven walks:
  - ffhacktics "FFTA: Revisited" thread: "unit moved to slot 1, dismissed,
    saving afterward causes the game to freeze" (a SAVE→freeze bug).
  - ffhacktics "Screen Freezing in Shop": freeze from items with 0x00
    quantity / inventory past 99 — a data walk that never terminates.
  - ffhacktics "FFTA Crash"/"Dispatch results crash" (mGBA 0.9.3, USA):
    freeze "when the jingle plays just before the results screen" —
    audio+screen-transition, same shape as ours; one case fixed only by
    editing the .sav to remove the faulty item.
  - multiworld.gg FFTA guide: "Pausing in a battle on a Jagd area causes
    the game to freeze. Same with certain missions like Decision Time" —
    REAL-HARDWARE game freezes at specific content points.
  - mGBA issues #2790 (FFTA crashes appearing between 0.10.0→0.10.1) —
    FFTA instability tracks emulator timing changes.
  - ipatix/gba-hq-mixer's hardware cycle table (LDRSB ROM = 6 cycles)
    matches our measured mixer costs exactly — our per-instruction
    timing is calibrated right.
  Conclusion: the wedge sits on a genuine game fragility (nestable VBlank
  × non-reentrant SoundMain at a heavy scene) that the community has hit
  in adjacent forms; our runtime's sub-frame timing delta tips it at this
  scene. Remaining unknown: whether hardware/mGBA also wedges at THIS
  exact point (needs the oracle at the scene — blocked by the
  savestate-format interop gap; noted for upstream).

### Session 7 (2026-10-06, 21:10): boot→load-native-save playthrough; Batch j — all 68 frag misses reviewed
- The user played from **boot** (title → loaded the native save →
  in-game), ~11.6k frames, clean exit: frag flushed to
  `logs/playtest_misses.frag` (68 proposals), trace `logs/playthrough.csv`
  (frames 0..11,210), exit auto-save wrote a new `game.state2` (frame
  11,635 — the session's end state; the slot had held the 17:41
  post-save state at frame 115,148). No hang this time — consistent with
  the session-6 knife-edge being scene/timing-specific, not a
  save-load bug.
- **Batch j** (all 68 reviewed via misspack + disarm): 25
  `[[extra_func]]` + 4 sized `[[jump_table]]` (55 targets):
  - 23 prologue-verified function entries (0x0807C7E8, 0x0807D96C,
    0x0807E2C4, 0x08083FB0, 0x080BEF28, 0x080D4D2C, 0x080D4DEC,
    0x080DAE7C, 0x080DC55C, 0x080DCAD4, 0x080DD900, 0x080DD9AC,
    0x080DDA94, 0x080DE61C, 0x080DFF04, 0x080E0824, 0x080E0A8C,
    0x080E0E98, 0x080E2398, 0x080E7D20, 0x080E7F4C, 0x08122C28,
    0x08126B9C).
  - 0x080E0506: interior-split entry — shared epilogue (`add sp,#0x34;
    pop {r4-r7}; pop {r1}; bx r1`) of the body at 0x080E03F8, walked
    inside emitted unit gf_tfunc_080DFEAE; reached by `b #0x80e0506`
    @0x080E0414 + runtime entry from outside the host unit.
  - 0x0813215C: 1-insn `bx lr` no-op stub, registered callback
    @0x083A88AC (record table of {ptr,0,1} triples).
  - jump_table 0x0807C810 ×19 — 0x0807C7E8's computed switch (bound
    `cmp r0,#0x12; bls`; dispatcher ends `mov pc,r0` — non-interworking,
    entries stored EVEN → entries_mode="thumb").
  - jump_table 0x080036D8 ×12 — callback pool (covers 0x08139C70, x468 =
    the session's hottest miss).
  - jump_table 0x081454D8 ×12 — m4a callback pool (covers the m4a
    command dispatcher 0x081464C4).
  - jump_table 0x0836D340 ×12 — m4a command-handler table
    (0xFFFFFFFF-terminated; dispatcher = 0x081464C4: `ldrb r3,[r2];
    lsls r3,r3,#2; ldr r2,[pc,#0x10]; ldr r2,[r3]; bl`).
- **Frag heuristic overridden by disarm evidence**: the frag's 5
  "JUMP-TABLE CANDIDATE" clusters are if/else comparison chains
  (cmp/bne/beq/bgt trees), NOT computed jumps — every mid-function miss
  in them is a direct branch target or a BL fall-through, covered by
  walking each function entry. Only 0x0807C7E8 has a true computed
  switch. Mid-function miss taxonomy for future reviews: (a) computed-
  switch case targets → sized [[jump_table]]; (b) branch targets of
  un-emitted if-tree functions → covered by the entry's walk;
  (c) BL fall-throughs → covered by the enclosing unit; (d) runtime
  entries into emitted spans → own [[extra_func]] (interior split).
- **Acceptance: strict replay of session 7 from game.toml = FULLY_STATIC,
  0 misses, 0 follow-on seeds** (`tools/resolve.py --trace
  logs/playthrough.csv --frames 12000` — passed iteration 0).
- **Cycle**: cold regen OK (30,554 → **33,868** emitted — the seeds
  unlocked whole previously-unreachable islands: menus/shops/m4a
  subtrees), dispatch sanity OK, build OK, attract gate PASS (golden
  sha256 `1EF4C118…EF321C1` unchanged).

### Native-save hang #2b: LOAD path (2026-10-07 09:56) — same machinery, tiny repro
- **Symptom (reported)**: boot → title → Continue → select the flash save → hang.
  The save file itself is fine (written before the earlier hang).
- **This gives the BEST repro we have**: boot + `logs/playthrough.csv` (57 lines,
  last input frame 908) + `saves/playtest.sav` + `--frames 3000` →
  non-strict HANGS (timeout); strict aborts at `pc=0xE25EF004 (arm)`.
  Saved copies: `saves/playthrough_before_loadhang_20261007_095630.csv`,
  `/tmp/loadhang_playtest.sav`, core `/tmp/ffta_load_hang.core`,
  binary `/tmp/FFTARecomp_at_load_hang`.
- **Mechanism (trace ring + core evidence, high confidence)**:
  1. The load flow uses the same save driver (call site `lr=0x08141BA5`, the
     `bl 0x08142250` veneer at 0x08141BA0) to call an IWRAM helper
     (`0x03007D72`, within our mapped byte-copy span) that runs a
     byte loop over ~0x1000 bytes writing 0x00 across `0x030008xx..`
     (caught live: `mem-write abort pc=0x03007D74 addr=0x030008D8 value=0
     width=1 (vblanks=1813)`) — i.e. it clears/restages the game's IWRAM
     variable block, which contains the IRQ handler table at 0x030008D0.
  2. A VBlank IRQ fires mid-staging. The game's IWRAM IRQ dispatcher
     (copy of ROM 0x080000FC; live bytes byte-verified == ROM at both
     0x03000F10 and pools 0x03001050-1064) computes the handler slot
     (`r1 = [0x03001060]=0x030008D0; +r2(=8)`) and reads `r0=[0x030008D8]`.
  3. In the failing instant r0 comes out as `0xE25EF004` (which is the ARM
     encoding of `subs pc, lr, #4` — an instruction word, not a pointer);
     `bx r0` executes garbage → bridged cascade → the observed permanent
     spin (core bt: wait-loop `0x08141B74 ⇄ 0x08141B80` with the
     call-thunk `0x03000FCC` and IWRAM IRQ frames nested).
  4. At the abort, IWRAM+0x8D8 already holds *other* staged bytes
     (core: 0x68207841-ish) — consistent with the slot being written by the
     staging sweep while the IRQ consumed it (torn read) — the values at
     [0x03000E50] also rotate during the flow (IE-restore low half 0xF004 is
     stable; upper half = adjacent live data).
- **Why it must not happen on hardware**: the real game clearly must have
  IRQs masked (or not sweep the table) while restaging, else it would hit the
  same torn pointer. Our run either (a) misses the game's IME/IE masking
  somewhere upstream, or (b) our staging bounds/source data are wrong
  (divergence), or (c) we execute the staging where the game wouldn't.
- **Unifying lead with hang #1 (write path)**: both hangs show the driver
  computing/consuming garbage pointers that look like code words
  (`0x2201D008` = bytes `08 D0 01 22`, `0xE25EF004` = `subs pc,lr,#4`),
  after reading its EWRAM context (`ldr r0,[0x08141BAC]=0x0200F370;
  ldr r0,[r0]; ldrb r0,[r0,#8]` in the driver tail). Next tools:
  `GBARECOMP_WRAM_TRACE` on the EWRAM context range
  (0x0200F300-0x02010000) and on `0x04000200/0x04000208` (IE/IME) during
  the boot+load repro; `GBARECOMP_ABORT_ON_MEM_WRITE_ADDR` per candidate
  cell; the two cores above for before/after snapshots.
- **Batch t status unchanged**: save-path coverage merged; strict acceptance
  of both repros still stops at the relocation/IRQ frontier above.

### 2026-10-07 — Save/load flow: oracle save autoload, serve-mode gap, boot-scan decode
Goal of this pass: pin the first divergence of the native's save/load flows
against mGBA instead of guessing from one side. Tooling built + findings:

1. **Oracle now autoloads battery saves** (`tools/patches/oracle-save-autoload.patch`,
   applied in the gbarecomp working tree; rebuild: `cmake --build gbarecomp/build
   --target gbarecomp_oracle`). Root cause of the old behaviour: the oracle
   wrapper used a raw `core->loadROM()` and never `mCoreLoadFile()` +
   `mCoreAutoloadSave()`, so the oracle always ran without any .sav. With the
   patch, `<rom>.sav` next to the ROM autoloads (verified: the oracle reads
   0xFF for erased sectors and scans sectors 0..15 of saves/playtest.sav).
2. **`tools/dualrun.py` extended**: `probe saveflow --trace <csv> --save <sav>
   --checkpoints <frames> [--dump-dir] [--png-at]` — lockstep native-vs-oracle
   with per-frame input injection (set_keyinput / emu_set_keys), a save copy
   staged next to a symlinked ROM for the oracle, per-checkpoint region diffs
   and raw dumps. First use: honest but confounded — see (3).
3. **Found: the interactive `--tcp` serve mode does NOT load the battery save.**
   Clean-exit logs of `--tcp` runs (with `--save-path ... --frames 0` style)
   contain neither `rom_loaded`/`bios_loaded` nor `save_loaded`; the flash
   array stays zero-initialised. All TCP-driven register probes therefore ran
   on an unloaded flash: the game's boot save-scan (`0x0813AE30`) reads zeros,
   `buf[0x10]==sector` spuriously matches, and the scan re-issues the same
   sector-0 read every frame (observed at f282..f289+; buffer = 0x00 vs the
   oracle's 0xFF). **Consequence: do not use the interactive `--tcp` path for
   save/load comparisons until it honours `--save-path` like the normal run
   path does; normal `--frames`/windowed runs do load it (`save_loaded` prints,
   verified).**
4. **Boot save-scan decoded** (ROM-verified, `tools/disarm.py`):
   `0x0813AE30` scans 16 sectors (3 passes): `bl 0x08141B14` (flash read via
   `0x08141BA0` → `bx`-trampoline `0x08142250` → the memcpy the driver copies
   onto its stack at `sp`, loop head at `sp+0x0E`), then `memcmp(buf, magic, 8)`
   (`bl 0x081443B0`) and a `buf[0x10] == pass` check; found sectors are
   recorded and processed afterwards. The oracle's call-site registers for a
   read are (r0=flash addr, r1=dest, r2=count, r3=sp|1, r4=sector<<12).
5. **Next steps (in order):**
   a. Make the serve mode load the save (same stanza as `run_game`'s normal
      path) — small framework edit, export as a patch like (1).
   b. Re-run the register capture at `0x08141BA0` + `probe saveflow` on the
      save-loading path vs the oracle; first real divergence should now be
      measurable in the load flow (the f~1750 runaway repro: boot +
      `logs/playthrough.csv` + `saves/playtest.sav`).
   c. Then fix the actual runaway (source addr garbage family
      `0x01004Bxx`/`0x0200B1xx` seen in unloaded runs — re-derive on the
      loaded path before trusting those values).
6. Housekeeping: `gbarecomp` submodule working tree has the oracle patch
   applied (uncommitted; patch exported to `tools/patches/`). Re-apply after
   submodule updates.

### 2026-10-07 (cont.) — f1750 runaway = a bad 4KB clear/copy over IWRAM bottom
- Abort-on-write at the sweep's low end (headless repro, save loaded,
  `GBARECOMP_ABORT_ON_MEM_WRITE_ADDR=0x03000800 MIN_FRAME=1000`) confirms the
  event: the planted memcpy loop (`0x03007D72`, `lr=0x08141BA5`) writes `0x00`
  byte-by-byte with dest=**r1 ascending through 0x030007F2..0x030008D8+**,
  `r2=0x1000` (count 4KB), source read from `r4=0x01004B50↑` (unmapped → open
  bus = 0x00), and the loop guard `r3=0x0200B225↓` — a ~33.6M-iteration loop
  (`while (--r3 != r2)`), i.e. the runaway that zeroes IWRAM (incl. the IRQ
  handler table at 0x030008D0) and cascades into the 0xE25EF004 dispatch.
- The (r3,r4) pair is locked: `r3 + r4 = 0x0300FD75` const. The values are of
  the same "mangled high-byte" family as the earlier write-hang's 0x2201D008
  (`0x0E…`-family addresses with wrong high bytes) — re-derive on the loaded
  path before quoting as fact.
- Next probes queued: (1) abort lower (0x03000700/0x03000600) to find the true
  sweep start and catch the call/entry context in the ring; (2) capture the
  caller chain of the copy invocation at the load flow; (3) diff the oracle
  at the same logical step (its save-processing completes; the same read's
  registers on the oracle = the intended values — mirrored from the boot-scan
  probe pattern in § "Save/load flow: oracle save autoload…").

### 2026-10-07 — Correction: two retracted claims (probe artifacts)
1. **The `--tcp` serve mode DOES load the battery save.** It sets
   `args.quiet = true` (runtime.cpp:945, same for `--window`: line ~1116),
   which suppresses every `!args.quiet`-guarded boot print — including
   `save_loaded` / `rom_loaded` / `bios_loaded` — while unguarded lines
   (`cpu_backend`, `save_config`, `strict_static`) still appear. That's why
   TCP logs looked like the save was skipped. Verified end-to-end: with
   `--save-path /tmp/ramp.sav` (sector 0 = `11 12 … 20`), the game's own
   driver reads the ramp through the flash window in TCP mode.
2. **The "native re-reads sector 0 every frame / reads zeros" claim (prior
   entry) was a probe artifact.** The `set_break_pc` yield parks the core
   until the instruction is stepped past; a probe that re-armed without
   stepping produced fake repeats. Corrected probe (step past each hit;
   second breakpoint at the call's return site `0x08141BA4` to read the
   destination buffer right after the copy) shows the native boot scan
   reads sectors 0→15 then wraps — same as the oracle — with correct data
   (sector 0 = ramp, others FF), all inside guest frame 281.
- Net status: save loading, flash reads, and the boot save-scan are all
  healthy in both engines. The divergence to chase is in the **load flow**
  after the input trace (driver call sequence at `0x08141BA0` from ~f900
  onward). Oracle reference (same trace): first load call reads sector 8
  (`src=0x0E008000`) into `dest=0x02008430`, `count=0x1000`, returning to
  lr `0x0813AE9D`-family. Next: capture the native's corresponding sequence
  and find the first divergent call.

### 2026-10-07 — Load-hang root cause & fix: moving stack-copy code vs stale AOT

**Root cause (verified).** FFTA's save/flash driver (`0x08141B14`) relocates
short position-independent helpers into its own stack frame and calls them by
computed address through the `bx` veneer `0x08142250` (`r3/r5 = sp|1`). The
copy address MOVES with the stack depth, so the fixed dispatch table can end up
executing stale AOT for a re-planted slot. In the load flow the driver's copy
landed at **0x03007D74**: the live bytes there are the routine's prologue
(`10 b5 …` = `push {r4,lr}`), but the static resume entry at `0x03007D74`
(alias inside `gf_tfunc_03007D72`, from the earlier dump where the copy sat at
`0x03007D64`) ran the OLD dump's loop body (`strb`). The prologue was skipped
— entry registers observed at the wedge: `r2=0x1000`, `r3=0x30007D74`,
`r4=0x8001`, i.e. the count/sentinel/terminator setup never ran — the loop
never terminated, zeroed low IWRAM (incl. the IRQ handler table at
`0x030008D0`), and cascaded into the bad dispatch `pc=0xE25EF004`:
strict abort / non-strict spin (root-cause chain first documented in
§ "f1750 runaway…" and § "Native-save hang #2").

**Fix.** New `src/ffta_ram_dispatch.h`, installed in `src/main.cpp` as
`g_runtime_ram_dispatch_hook` before `run_game()` (framework's sanctioned
"game-owned canonicalizer for position-independent code copied to transient
RAM addresses (notably routines executed from a moving stack frame)",
`src/armv4t/runtime_arm.h`; pattern from EmeraldRecomp
`src/emerald_ram_dispatch.h`). It runs before the fixed table for every
RAM-range dispatch, byte-verifies the live copy against its ROM source, and
runs the canonical generated body:
- byte-copy `← ROM 0x08141AF0 (0x24)` → `gf_tfunc_03007D64` (covers entries at
  `0x03007D64`, `0x03007D74`, and the 2-byte-offset re-plant `0x03007CA4`);
- byte-compare `← ROM 0x08141BB0 (0x2E)` → `gf_tfunc_03007CE4`;
- 4-byte getter `← ROM 0x08141AAC` (`00 78 70 47`) → `gf_tfunc_03007D48`.
A slot whose live bytes no longer match any template falls through to the
normal dispatcher (no false canonicalization).

**Validation (cache-free, deterministic).**
- Load repro (boot + `logs/playthrough.csv` + `saves/playtest.sav`,
  `--frames 3000`): BEFORE (preserved `/tmp/FFTARecomp_at_hang`): strict
  `STRICT_STATIC dispatch miss for pc=0xE25EF004` → abort (exit 134); AFTER:
  exit 0, `FULLY_STATIC dispatch_misses=0 interpreted_insns=0`; `--dump-png`
  at f1050 shows the load menu, matching the oracle f1050 screenshot from
  `tools/dualrun.py probe saveflow`. Non-strict: 3000 frames, exit 0.
- Strict load flow to **8000 f**: exit 0, FULLY_STATIC (main loop alive).
- Strict boot→newgame 6000 f (standard gate): exit 0, FULLY_STATIC.
- Write-flow repro (`state2_prev_20261007_092041` +
  `trace_prev_20261007_092041.csv`, 2756 f): strict exit 0, FULLY_STATIC,
  no hang; at 9756 f the game is back on the world map (screenshot). NOTE:
  this repro no longer hangs even with the old binary under a COLD cache —
  the original live write-hang was warm-cache-linked, so the write path is
  confirmed by this fix at the "no hang / no miss" level only; re-verify the
  actual flash write in the next live session.
- Attract gate unchanged: `attract_verify=PASS frames=1200
  sha256=1EF4C118…`.
- `dualrun probe saveflow`: oracle dumps are deterministic across runs;
  native f1050 state is ~identical pre/post fix (109 B IWRAM); the ~1.2 KB
  IWRAM / ~4.7 KB EWRAM same-index plateau is a pre-existing park-phase
  property, and blank native TCP `screenshot` PNGs (192 B) are a pre-existing
  artifact of the `frames_presented=0` path (headless `--dump-png` works).

**Open items.** (1) If a future session shows a moving-copy variant not
covered by the three templates (e.g. the compare-routine tail assembled at
`sp=0x03007D08`-family addresses), extend `ffta_ram_dispatch.h` with the same
byte-verify+canonical pattern — do not rely on the stale static entry.
(2) Optional: teach the TCP `screenshot` path to serve the PPU frame in
headless/`--tcp` runs so lockstep probes can compare pixels directly.

### 2026-10-07 (cont.) — Session 11:46 battle-cluster frag batch (batch u)
- **Session**: play.sh 11:46→11:47, started from `state2_prev_20261007_114607`
  (f47414, auto-loaded); `logs/playthrough.csv` ends f53092. Non-strict exit:
  `NOT_STATIC distinct_misses=11 healed_native=11`; the 11:47 frag and
  `cache_harvest --new` agree on the same 11 PCs.
- **Merged (batch u)**: nine push-root starts — 0x0800A330, 0x08018E20,
  0x08019120, 0x0801920C, 0x080192C0, 0x080543EC (bridged x439), 0x080601B4,
  0x08061188, 0x0806119C — plus two pre-verified interior block entries:
  0x08019150 (block entry after the literal pool at 0x08019146..4E; preceded
  by `b 0x080191a0`) and 0x080544CA (mid-body continuation of 0x080543EC,
  bridged x374 — the hot pair is the per-frame battle update path).
- **Resolve addendum**: strict replay on the session trace surfaced 4 more
  frontier misses — 0x08054664, 0x08054DA8, 0x08054E14, 0x08055F10 (all clean
  push roots in the same battle cluster; disasm evidence in notes). Merged;
  replay then passed end-to-end.
- **Acceptance**: `tools/cycle.py` PASS — cold regen discovered 46,383
  functions (+824 from the new roots' walks, 45,559 → 46,383); dispatch
  sanity OK; attract hash unchanged (`1EF4C118…`). Final strict session
  replay (no overlay): `FULLY_STATIC`, 0 misses / 0 interpreted, f47414→53392.
- **Coverage (post-batch)**: executed 100 % (strict 1200); walker's static
  reach ≈ 98.9 %; pointer-pool lens **86.6 % → 88.1 %** (2,078 literal seeds
  from 103,418 scanned).

### 2026-10-07 (cont.) — Save-record scan/validate divergence (found-save + playtest-save stalls)

**External save provenance/format.** `saves/found_save.sav` (online source) is
a **Retro5.net "RTN5" container**: 24-byte header (u32 magic `0x354E5452`,
u16 fmtVer=1, u16 flags&1=zlib, u32 origSize=0x10000, u32 packedSize,
u32 dataOffset=24, u32 CRC32 of the *uncompressed* data) + zlib payload =
raw 64 KiB flash image. Verified: CRC matches; decompressed bytes are
byte-identical (0 diffs) to the user's second export,
`saves/found_save.mGBA.sav` (raw, SHA-1 `b64ed938…`). Use the raw file
directly with `--save-path` (last-wins over play.sh's default).

**Save-record format (from the two files + the validator disassembly).**
64 KiB flash, 16×4 KiB sectors; records live in 4-sector groups (observed
groups {0..3} and {11..14}) ending in a header sector starting with
`FFTEX000`. Header fields: +0x08 u32 save counter (found 0x3D8/0x3D9, our
playtest 1), +0x0C u32 checksum, +0x10..+0x11 flags, +0x12..+0x15 a 4-byte
descending stamp (found-A `03 02 01 00`, found-B `0e 0d 0c 0b`, playtest
`07 06 05 04`), +0x16.. zeros. Validator loop at **0x0813B57C** (disarm):
reads each group via the flash driver (0x08141B14), memcmp 8-byte magic
(0x081443B0), then **zeroes +0xC and +0x12..+0x16 in the RAM copy** and
recomputes the checksum (bl 0x0813ADF0) to compare with the stored value.
Found save health: passes the game's own validation on the oracle (slots
render identically — the odd name "ZWZVXWYVP" is its own content — and the
load completes); its two redundant copies differ in only 12 bytes
(consecutive counters + matching checksums + stamps). **Not corrupt.**

**Two stalls, one signature.**
1. Found save: stalls at "Loading…" after selecting the file (f~1080+;
   EWRAM fills with `0xC002E55E`-pattern garbage; the oracle reads 12 sectors
   — scan f864 {3,2,1,0}+{E,D,C,B}, load f1043 {E,D,C,B} — and says "Load
   complete" by f1100 while our buffer keeps the un-blanked stamp bytes the
   oracle zeroed).
2. Playtest save + `saves/trace_prev_20261007_114607.csv` (the 11:42
   session): stalls in the in-game save flow (headless: between f2000 and
   f2400; TCP-driven lockstep: stopped ~f1732 under CPU contention — rerun
   in progress); the save file is NOT rewritten (dies before the program
   step).
Both end in the same runaway: the driver's byte-copy is called with
**`source = ~count`** (found `0x00FEFEF0 = ~0xFF01010F`; pt `0x00FF3180 =
~0xFF00CE7F`) → 4-billion-iteration copy sweeping IWRAM → the `0xE25EF004`
cascade abort (strict) / spin (non-strict).

**Bisect**: the pt stall reproduces identically on the pre-batch-u regen
(45,559 functions) — **not** a batch-u regression; the trigger is the
current `playtest.sav` content (written by the 11:46 session's menu save).
I.e. a data-dependent divergence in the scan/validate path; the oracle
completes both flows.

**Deterministic repro (in use)**: strict + boot +
`saves/trace_prev_20261007_114607.csv` + `--save-path <copy of current
saves/playtest.sav>` + `--frames 2400` → abort `0xE25EF004` (this replay
passed earlier the same day, before the 11:47 save write).

**Tooling**: `tools/readseq_probe.py` — captures the flash read/copy
driver-call sequence (pc 0x08141BA0; args + caller LR) on both engines
(native breakpoint + oracle `emu_run_until_pc` variants). TCP gotcha:
`set_break_pc` is a yield predicate — on hit: clear (value 0) → `step_inst`
→ re-arm, else identical fake repeats.

**Status**: open. Next: clean oracle lockstep on the pt repro checkpoints
(1700→2040), dump-diff the first divergent frame, then capture the
validator's memcmp/checksum calls (0x0813B634 / 0x0813B650) on both engines
to isolate the branch that diverges.

### 2026-10-07 (cont.) — Batch v merge; save-flow stall now blocks replays; runaway stack-growth leak

**Batch v merged** (`game.toml`): 50 heal-cache units from the user's two
play sessions (13:19 + 13:22, frags `saves/frag_prev_20261007_132226.frag` +
`logs/playtest_misses.frag`, no overlap; cache harvest matches exactly). The
three "JUMP-TABLE CANDIDATE" blocks were over-cautious: disarm shows they are
start roots containing branch-target interiors (e.g. `0x0812803C`'s cluster;
it `bl`s `0x0800DB0C` @0x08128430) — seeded as start + split-interior entries.
**Acceptance deferred**: the session-A strict replay does NOT converge — it
hits the open save-flow divergence (below) and sits in the runaway (strict
mode cannot heal it). Trace A enters the runaway at vblank≈1954 (verified
with `GBARECOMP_ABORT_ON_MEM_WRITE_ADDR`). Re-run the A/B resolves after the
save-flow fix lands.

**Runaway memory leak — root-caused (was: "system memory climbing" 33 MB/s).**
Measured with an `LD_PRELOAD` malloc interposer + `/proc/PID/smaps` diff:
the growth is the **main-thread stack** (top mapping grew 240→637 MB in
12 s), not the heap (no malloc growth, mapping count constant). `gdb`
(parent-launched; attach is blocked by yama=1) caught the stack: unbounded
C++ recursion of **`gf_afunc_03000FCC`** — a unit inside the runtime copy of
the **ROM IRQ dispatcher** (`[[code_copy]]` span `0x03000F10..0x03001070` ←
ROM `0x080000FC`). When the runaway's copy sweep (dest ascending through
IWRAM low) overwrites that dispatcher copy, each VBlank re-enters the
dispatcher unit with corrupted registers/LR and return-to-self loops: every
hop re-dispatches **recursively** (+1 C++ frame, each doing
`bus_read_u8 → runtime_mmio_catch_up → tick_timers`), so the stack grows
~33 MB/s + CPU pegged. Downstream of the root scan/validate divergence; the
process frees everything on exit. Mitigations in use: probes stop via
abort-on-write (seconds); do not leave a stalled session open.

**Tooling**: `tools/resolve.py` now stops with a clear message when the
"miss" PC is outside addressable code (`>=0x09000000` or 0x04–0x08 range) —
that PC class means the replay diverged (behavioral bug), not a coverage gap,
and must never be seeded into the overlay.

### 2026-10-07 (cont.) — Save-flow divergence narrowed to the record-validation success path

**Structural first divergence (pt repro, oracle lockstep, fine bracket).**
Tracking the EWRAM structures across checkpoints f900→1720: the load window
(f~1043) produces a **decoded save-slot descriptor at guest `0x02000000`**
(`FFTEX000` + counter + checksum + ROM pointers `0x80xx…`, 82 bytes) on the
**oracle only**; the native leaves it zeroed all the way to the stall. The
f1660–1690 "buffer fill" seen earlier was phase noise — this 82-byte block
is the stable divergence, born between f1000 and f1100 (the load).

**Correction: the read asymmetry was a probe artifact.** The
`readseq_probe` capture (TCP-driven) showed "native 1 read vs oracle 4" —
but the always-on instruction ring (headless regime, `GBARECOMP_INSN_TRACE`
+ `FP_SAVE` + `ringscan.py`) proves the native ran the loop **4 times too**
(4× driver entry `0x08141B14`, 4× bookkeeping `0x0813B622`, stub loop at
`0x03007D74`). Root cause of the artifact: the native breakpoint is a *yield
predicate* — it cannot fire on mid-block PCs; counts from it are lower
bounds. **Rule: verify any mid-block breakpoint capture with the instruction
ring before concluding divergence.** (The earlier found-save "1 vs 12" read
asymmetry is suspect for the same reason; the found-save zeroing-difference
evidence came from dumps and stands.)

**Validator anatomy (`0x0813B57C`, thumb, disarm-verified).** Args: `r0` =
slot/index (0/1 → selects aux ptr `[sp+0x14]` = pool 0x3CA8-family), `r1` =
caller's buffer (`r7`, observed `0x02003CB0`). Calls `0x0813B060(index,
&local)` and requires **result == 4** to proceed (`cmp r0,#4; beq
0x813B5CC`), else returns 0. Then the 4-sector read loop (sectors 7,6,5,4 →
`buf + 0x1000*i`), memcmp 8-byte magic (`0x081443B0`) on the completed
buffer, then zeroes `+0xC` and `+0x12..+0x16`, recomputes checksum
(`0x0813ADF0(buffer, [sp+0x14], 0)`) and compares with the saved `+0xC`
(match path → `0x813B5C8`; mismatch/retry counter `sb ≤ 2` → re-scan).
Two wrapper variants exist around `0x0813AA94`/`0x0813AB2A` (write mode
bytes 0x3C/0x1F/0x1E after calling `0x08135854` + `0x0808A604(3,2)`); the
slot-list UI builder near `0x0813BBE0` reads the `0x02000000` structure
(`ldrh [0x02000000+idx]` vs `0x2FBF`, display codes 0x3B/0x3C).

**Next probes (queued).** (1) Capture `0x0813B060` call results on both
engines (expect 4; suspect the native gets something else or skips the
descriptor step after). (2) Capture `0x0813ADF0` checksum results per record
on both engines. (3) Find the writer of `0x02000000` by ring-querying the
load window for stores (ring `--cyc` context around the store time), not by
mid-block breakpoints.

### 2026-10-07 (cont.) — Batch w: session 13:57 (party/ability menus) — ACCEPTED

27 heal-cache units (frag 6,640 B; cache 77 total / 27 new) from one play
session. Three hot multi-entry functions — `0x0804E408` (10 dispatched
interiors, bridged x1110/x118/x14/x10/x29), `0x0804E6EC` (x731/x72), and the
`0x0804CABC`/`0x0804CAD0` pair — seeded as start + split-interior entries
(prologue scans verified; the frag's "jump-table candidate" flags again
resolved to branch-target interiors). Standalones: `0x080197BC`,
`0x0804D91C`, `0x0804E858`, `0x08050F1C`, `0x080CB63C` (interior of a start
outside the frag). Acceptance: `resolve.py` on the session trace
(`logs/playthrough.csv`, f7500) — **iter 0 STRICT replay PASSED end-to-end,
0 seeds, FULLY_STATIC**. Cold cycle: regen OK (discovered **47,677**
functions — the batch-v/w seeds pulled in a ~+1.2k cascade over the
previously emitted 46,4xx), dispatch sanity OK, **attract gate PASS**
(sha256 `1EF4C118…`, unchanged since pinning). `cycle: PASS`.

### 2026-10-07 (cont.) — Batch x: session 14:07 — ACCEPTED

1 heal-cache unit: `0x0807E37C` (start `push {r4-r7,lr}`, bridged x170 —
hot). Acceptance: resolve (session trace, f7000) — **iter 0 STRICT replay
PASSED end-to-end, 0 seeds, FULLY_STATIC**. Cold cycle: regen OK
(discovered **47,874** functions — single-seed cascade +197), dispatch sanity
OK, attract gate PASS (sha256 `1EF4C118…`, unchanged). `cycle: PASS`. Heal
cache fully merged (78/78 units).

### 2026-10-07 (cont.) — Batch y: multi-session wave (14:13–14:17) — ACCEPTED

51 heal-cache units across ~5 sessions (four quick runs + one main session;
frag 12,336 B). Dense switch clusters in `0x080E3xxx` (11-run) and
`0x08107xxx` (10-run), plus `0x080EE2F4`/`0x080EED88`/`0x080EEF6C`/
`0x080F7720`/`0x08146BB0` families and two interiors of starts outside the
frag (`0x08131EC0` ← `0x08131E90`; `0x0813254C` ← `0x08132520`); start +
split-interior seeds, prologue scans verified. Acceptance: resolve (main
session trace, f9000) — **iter 0 STRICT replay PASSED end-to-end, 0 seeds,
FULLY_STATIC**. Cold cycle: regen OK (discovered **48,247** — +373 cascade),
dispatch sanity OK, attract gate PASS (`1EF4C118…` unchanged). `cycle: PASS`.
Heal cache fully merged.

### 2026-10-07 (cont.) — Batch z: crash-spiral battle sessions — ACCEPTED

83 heal-cache units (crash-safe harvest; the crashed session's frag never
flushed — the cache is the durable store, as designed). 20 starts + 63
dispatched interiors across the battle regions (`0x080B`/`0x080D–0x080E`,
`0x080F2F–31`, `0x0810–0x0811`, `0x081321`); split-unit seeds. Crash context:
SIGABRT from `runtime_bridge_interpret` under `gf_tfunc_0814186E` — the
game's BIOS SWI thunk bank (`svc #N; bx lr`; corpus unit root `0x08141838`)
— during a live battle while the session was healing these units. A faithful
replay with the warm cache runs the whole route clean (21,400 frames), so
the abort is a mid-heal bridge artifact, not a persistent bad path; making
the path static is the fix. Acceptance: resolve (session F trace, f21400) —
**iter 0 STRICT replay PASSED end-to-end, 0 seeds, FULLY_STATIC**. Cold
cycle: regen OK (discovered **49,084** — +837 cascade), dispatch sanity OK,
attract gate PASS (`1EF4C118…` unchanged). `cycle: PASS`.

### 2026-10-07 (cont.) — Batch aa: session 14:34 (Totema summon stall) — merge OK; route DIVERGES (deterministic repro!)

14 heal-cache units (`0x08114D–0x081151` dense battle/effect cluster;
crash-safe harvest). User-identified trigger: a **Totema summon**. The strict
replay of session G's route **deterministically diverges — landing on
`pc=0xE25EF004`, the same corrupted-dispatch signature as the save-flow
stalls** (found-save load; playtest save). The resolve guard (out-of-range
PC stop) caught it cleanly without seeding garbage. Two different gameplay
contexts hitting the same signature ⇒ suspected shared root. Pre-summon
repro seed: slot-1 savestate (`game.state1`, frame 18,643) + trace tail
(`saves/trace_sessionG_1436.csv`, events f18,716–18,958). Next: abort-on-write
probe on this route to capture the runaway caller chain and compare with the
save-flow's `src = ~count` signature.

### 2026-10-07 (cont.) — Summon crash: corrupted copy-invocation captured (entry + stack decoded)

Deterministic repro (session G route) narrowed with `tools/chunkprobe.py` (new:
chunked breakpoint driver + stack dump; parks at the copy unit entry
`0x03007D72` with the break armed late). Capture at f18,335 (the corruption
onset — ~300 frames BEFORE the user's state save at 18,643):
`r0=0 (src=0), r1=0x02A1BC48 (dst), r2=0xFFFFFFFF (count) → immediate
4-billion-iteration runaway; lr=0x08141BA5 (inside the flash driver, its
stub-call site)` — with NO driver-entry (`0x08141B14`) dispatch after
f17,794. The guest-stack dump at the park shows why: the frame still holds
the **save-load operation from f17,794** — job descriptor `{0x03007E08,
0x02003CB0, 0x02003CB0}`, load-loop return `0x0813B60D`, validator-caller
return `0x0813B4A3`, and **the planted copy routine verbatim at sp+0x20
(=0x03007D74)**. I.e. the copy is re-invoked from a stale, never-unwound
save-flow frame with irrelevant (battle) registers — a broken two-phase
handoff, the same subsystem whose `0x02000000` descriptor write diverges in
the pt repro. Ring capacity note: `GBARECOMP_TRACE_DUMP_DEPTH` clamps at
4096 events. Next: compare the handoff state (`0x03007E08`/`0x02003CB0`
structures) native-vs-oracle in the mid-session read window; trace events
around f18,3xx listed above.

### 2026-10-07 (cont.) — Community references: DataCrystal FFTA pages recovered

User recovered the old DataCrystal FFTA wiki pages (Wayback 2021-06-14);
text extractions committed under
`reference/datacrystal/` (GFDL 1.2, attribution in its README). Standouts:
- **Scripting page** = event-VM opcode table (execute callback / fade /
  set map / message box / …) — the documentation layer for the
  `0x08122xxx–0x08123xxx` interpreter family.
- **Compression Formats** = decompressor entry ≈`0x0801F100` (type byte
  0x10/0x01/0x11; unmatched path does `bl 0x08141868` — **the SWI-thunk
  bank adjacent to session-F's crash address `0x0814186E`**, i.e. the
  battle/effect path runs this decompression + copy machinery family); LZSS
  derivative with track-back copies + `0x1000`-word zero fills.
- RAM map (sparse: day/time `0x02002FBA..BF`; mission items `0x02002B08`,
  64×4B), ROM map, Maps, Jobs, Abilities, String Tables — annotation
  material for `symbols/ffta_data_symbols.tsv`.
Nothing on save internals or the relocation/two-phase handoff (as before —
those remain our own reverse-engineering). Also verified BCROBERT's notes
pack landmarks (`0x0812E368` speed formula, `0x0812D3D4` Parley formula)
match the disassembly bit-for-bit.

### 2026-10-07 (cont.) — LZSS decoder guard: save-menu/summon hangs fixed (all routes green)

The remaining hangs (strict-replay stall at f17,794; the user's post-summon
hang) came from a **ROM-resident LZSS decompressor at 0x0800543C**
(DataCrystal "Compression Formats": big-endian output length at src+0, stream
at src+4; the byte loop at 0x08005558 is its track-back copy) being re-entered
with a corrupted source pointer by the save-menu/summon flow → decoded
length ≈ 4G → endless loop. It is a normal static ROM function: the RAM hook
never sees it, and the aborts left no sweep to canary. Located with
`tools/spinhunt.py` (chunked TCP driver that detects a stalled pc and dumps
regs+stack).

Fix: a reviewed **`[[mod_function_hook]]`** seam (game.toml) + host plugin
`ffta.lzss-guard` (src/main.cpp) — at the entry it reads the header length;
>1MB ⇒ skip the call back to the caller (`R15=LR`, logged); otherwise
decline and the original body runs. (An earlier attempt to use the
framework's `program_dispatch` field was impossible — the context pointer is
file-local in `runtime_arm.cpp`; the mod-hook registry is the sanctioned,
always-linked seam.)

Verified: strict route G f19,400 **FULLY_STATIC** (previously stalled);
warm G clean; sessionH (user's post-summon hang) warm f22,000 clean and
**strict resolve 0 seeds, FULLY_STATIC**; cycle PASS — regen discovered
**49,186** functions, attract gate PASS (`1EF4C118…` unchanged). Batch ab
(8 units) merged. The underlying stale-frame re-invocation divergence
remains open but every observed symptom is now bounded (degraded call, no
hang). New tool: `tools/spinhunt.py`.

### 2026-10-07 (cont.) — Batch ad: session J — first full Totema summon; live watchdog tooling

Session J (post-fix, windowed observe mode): the user's summon retry **completed
end-to-end** — first full Totema summon on record through their real play path.
13 heal-cache units merged (batch ad; 0.081155xx battle cluster continuing);
strict resolve 0 seeds PASS; cycle PASS — regen **49,235** functions, attract
gate PASS (`1EF4C118…` unchanged). New: `tools/livewatch.py` (frame-stall
watchdog over the windowed observe port; froze-state capture) + playbook
"Live-session debugging" section (state-load discontinuities break boot
replays; two-clean-replays rule; frame counter = hang signal). Note: the
observe listener serves a handful of sequential clients then stops accepting —
one long-lived watcher per session. Session J's trace archived
(`saves/trace_sessionJ_1639.csv`) as the first summon-completing route.

### 2026-10-07 (cont.) — Batch ae: session K — summon subsystem going static (43 units)

Session K (post-fix observe session 2; deepest yet, f29,384): first summon
*turn completion* + a second (magic) summon. Clean-exit frag (9.4 KB) → 43
units merged: 32 in the 0x080F0x–0x080F24 animation/effect cluster (summon
visuals), 5 in the 0x0812 script VM (summon scripts), rest scattered.
Resolve 0 seeds PASS; cycle PASS — regen **49,492** functions; attract gate
`1EF4C118…` unchanged. Trace archived `saves/trace_sessionK_1648.csv`.
Next: three-lens coverage report, then the bounded pointer-pool harvest
trial (offline coverage push for unplayed content).

### 2026-10-07 (cont.) — Offline coverage push: trialled, regression found, tabled

The speculative literal harvest was enabled for a real trial: regen **54,404**
emitted units (+4,912); sanity/build OK; **attract gate PASS unchanged**.
Acceptance: session-K strict replay (f29,384) **0 seeds FULLY_STATIC** — but
the save-menu route G (f19,400) **regressed into the memory-runaway class**:
strict replay pinned at 99.6 % CPU with RSS climbing to **31.8 GB** (killed).
Spin-hunt showed the same frame as the original stall (f17,794) with a new
entry path — `0x080052DC → 0x08005544 → 0x08005498/4A2 → 0x08005552` — the
flow now resumes **inside the LZSS decoder, past the guarded entry**
(`0x0800543C`), so `ffta.lzss-guard` never runs and the corrupted stream
loops. The with-flag generated set references the interior address
(`/tmp/gen_trial/recompiled_009.cpp`); the no-flag build does not enter there.
Reverted (`speculative_literal_harvest = false`); route G strict replay is
**FULLY_STATIC** again.

Conclusion: speculative splits can mint dispatchable **interior** roots
inside guarded routines; entry guards do not cover interiors. Tabled. Re-trial
prerequisites (README § Roadmap item 1 + playbook):
(a) a **route-level golden gate** — a long strict replay of the save-menu
route in the harness (the 1.2k-frame attract gate cannot catch this class);
(b) an **interior-split policy** (extend guards to interior roots, or exclude
the guarded span from speculation). The harvest itself looks sound (K stayed
static, attract unchanged); the blocker is policy, not seed accuracy.

### 2026-10-07 (cont.) — Found-save load: characterized to the root; fix belongs at the save-flow divergence

The imported save (`saves/found_save.mGBA.sav`, sha256 59bb5d47…) hangs on
load. Deterministic strict repro: found save +
`saves/trace_sessionL_1736.csv` (872 events) → `dispatch miss for pc=0x700200F2`
at f≤1,272. The failed call = the relocated byte-copy stub entered at its
2-before-plant artifact `0x03007D72` with the driver's read-shaped args
(r0=flash sector, r1=buffer, r2=0xFFFFFFFF, r3=count−1, lr=0x08141BA5).
Baseline behavior there: the RAM hook's byte-check declines (plant stale or
mid-write) → the static interior unit at 0x03007D72 self-re-enters under the
frame-boundary yield (ring: prologue pushes only; stack descends 2 words per
frame) → garbage dispatch. The same address at boot is benign: the plant
matches the ROM stub and the hook canonicalizes to the body.

Shims tried and REVERTED (all defeated by a gate; build restored to baseline,
attract hash `1EF4C118…` exact):
- unconditional 0x03007D72 → canonical body: livelocks at the load (nested
  body yields after its prologue at frame boundaries; the unwind restores
  pre-dispatch registers). Framework yield-suppression attempted; the boot
  scan's *legitimate* interior calls then livelock too.
- hook-side C byte-copy for the shape: completes without yield points but with
  ZERO guest cycles vs the body's ~13/byte → attract timeline changes
  (the golden gate caught it; cycles matter).
- r2 == 0xFFFFFFFF as corruption marker: invalid — the interior loop
  legitimately runs with r2 == −1, so boot matches that shape too.

Conclusion: no register-level predicate separates the corrupted load-time call
from legitimate interior calls; the corrupted call is produced UPSTREAM by the
still-open save-flow divergence. Fix the divergence and this class disappears.
Evidence: `logs/found_{strict,strict2,ring3,warm2}.log`. Player's own saves
unaffected (route K strict FULLY_STATIC throughout).

### 2026-10-07 (cont.) — Event/script static walk: first batch (af) — +523 units, gates green

- `tools/eventcrawl.py`: script tables validated (62 blocks / 213 unique
  scripts, 0x089A5E6C..0x089C12C3). Scripts carry NO code pointers
  (353 distinct 0x08-patterns in script bytes = operand collisions; 1
  false-positive push; 0 real) — code is reached via opcodes only.
- Family pointer tables (0x0810-0x0813): 22 found; ALL are compiler switch
  tables (targets = interior case bodies, often repeated); zero survive the
  exact first-instruction `push {.., lr}` test. Loose forward prologue
  scans mislabel these (they find the NEXT function) — do not use them
  for seeding decisions.
- Lever: trial literal-pool diff (speculative regen vs corpus) = 4,695
  walker-missed candidates; 189 strict-push starts; 15 inside the
  event/battle families sit in un-walked islands (0x081288BA-0x0812A060,
  0x0812BD42-0x0812C510, 0x08126108-0x0812638C). Sampled 0x081288C8 =
  loader calling the (guarded) LZSS decoder 0x0800543C.
- Batch af = those 15 seeds: regen 49,492 -> 50,015 (+523 cascade);
  attract hash byte-exact; strict G/K FULLY_STATIC; coverage: walker
  50,015/50,839 (~98.4%), pointer-pool 50,015/54,404 (~91.9%).
- Queue: remaining 174 strict-push candidates in other regions (0x0805+64,
  0x0806+22, 0x080A+21, 0x0808+13, ...) — one scoped batch at a time, same
  gates (attract + strict routes + coverage).

### 2026-10-07 (cont.) — Event-crawl batch ag: remainder lifted; pool reach ~99.9%

- Method refinement (tools/eventcrawl.py): candidates = trial PRIMARY starts
  (resume=0 rows) not covered by any current dispatchable row (per-row
  addresses, starts AND resume points — a name-based extraction under-reports
  and leaks emitted functions back into the candidate list). 173 strict-push
  seeds across all regions (0x0805+64, 0x0806+22, 0x080A+21, 0x0808+13, ...).
- Regen 50,015 -> 54,327 (+4,312 cascade — within 77 units of the trial's
  54,404); attract hash byte-exact; dispatch sanity clean; strict G/K
  FULLY_STATIC; coverage: pool 54,327/54,404 (~99.9%), walker 54,327/55,643
  (~97.6%; its denominator grew with the walk's own scan).
- The speculative-harvest GOAL (pool reach) is now achieved deliberately via
  188 reviewed seeds (af+ag) with every gate green — the blind path itself
  stays off (interior-split hazard, preserved in README/Roadmap).
- Remainder: 77 pool units (review individually; likely data-adjacent) and
  walker leftovers (proxy only — the bar remains FULLY_STATIC on executed
  paths).

### 2026-10-07 (cont.) — Annotation pass 6: event-VM anchors, decompressor entry, 26118 closed

- `reference/event-vm.md` (new): script storage (62 blocks / 213 scripts,
  validated), VM register roles from engine-hacks hooks, verified anchor
  table (op13 arg 0x08122680; op70 0x08122AAA; battle spawn 0x08123670;
  healing 0x08123860/6C; death 0x08123B68/7C; mission trigger 0x08123898;
  char ptr 0x08125578), decompressor family (0x0801F098 = REAL entry — the
  old 0x0801F100 anchor was an interior; 0x08141868 = SWI 0x0C thunk;
  0x0800543C = the guarded LZSS).
- `symbols/ffta_symbols.tsv` § 5: six name-only rows for the emitted
  primaries (attract gate guards the rename; no coverage change).
- FAQ 26118 deep-mine CLOSED: the full copy is encrypted CodeBreaker pairs
  (no raw addresses; "03xx" hits are code-word fragments). Its usable
  content was already captured via 25621/22129 (cross-agree, data-symbols
  § 7). Re-open only if CBA decryption is ever wanted.

### 2026-10-07 (cont.) — Widescreen investigation: framework path, FFTA facts, staged plan

- Framework: opt-in = `RunOptions::max_view_width` > 240 (ours to set in
  src/main.cpp); users ask via `--view-width` / `GBARECOMP_VIEW_WIDTH` /
  `[video].view_width`; engine max 896 px. Capability = shared PPU wide
  path; POLICY (which scenes, how wide, clamping) is per-game. WIP dev
  override `GBARECOMP_WS_WIP=1` unlocks experiments without an opt-in.
- Gotcha recorded in AGENTS: under `--tcp` the runtime does NOT process
  `--load-state` (silently skipped); load over TCP with `savestate_load
  {path}` instead (this cost two cold-boot probes before it was spotted!).
- FFTA scene facts (TCP probes; game.state2 = world map, frame 51,827):
  mode 0, four BGs. BG0/BG1 = field layers, tilemap 256x512 (size=2),
  scr 0x5000/0x6000, h=0 v=151; BG2/BG3 = static 256x256 UI (0x7000/0x7800).
  Node travel: Down moved v 151->192 (+41, recenter) then stopped; Left/
  Right had no adjacent node from Sprohm and its southern neighbour; h
  stayed 0 at every reached node. Vertical = true scroll; horizontal
  mechanism unresolved (likely strip redraw; draw window is 256 px).
- Experiment (zero code changes): `GBARECOMP_WS_WIP=1 --view-width 320`
  renders 320x160 headless (runtime banner "extended view ON ... 40/40").
  The 240-space stays CENTERED (UI/OAM intact); margins show WRAPPED
  BG0/BG1 edge columns (cols 30-39 read as 30/31 + 0-7; left margin =
  cols 24-31) — visually map-like, positionally wrong. Conclusion:
  pure-PPU widescreen is NOT correct for FFTA; margins must be
  materialized by the guest (FRLG Strategy A, docs/WIDESCREEN_STEPC_PLAN.md).
- Staged plan: W1 locate the field strip-draw + camera code (leads: gMap*
  fields § 4 — gMapTileData 0x02007CB0, gMapHeightRead/WriteAddr
  0x08019E7C/0x0801F0DC; DataCrystal Maps.txt; bcrobert map anchors;
  confirm horizontal mechanism by reaching an east node or reading the
  camera code). W2 relocate field screenblocks to 512-wide (size=3) and
  extend the draw to fill extra columns behind a mod function hook; add a
  camera bias ((W-240)/2) so the player stays centered. W3 policy: wide
  only where margins are materialized (world map, battle field); menus/UI
  pillarbox; then opt in via opts.max_view_width.
- Artifacts (ROM-derived, /tmp only): ws240.png, ws320.png (world map
  240 vs 320), ws_battle2_f2.png, ws_map_down.png (v-scroll evidence),
  probe logs wsprobe*.log.

### 2026-10-07 (cont.) — Close-hang investigation (widescreen session) — workaround shipped

- Symptom (user, wide session): the game window would not close; the process
  kept running. Probed via the observe TCP port: game healthy, frames
  advancing, 320x160 view active.
- Evidence: TCP `quit` closes cleanly (verified 4x; play.sh still archives
  states + flushes the frag). Window close reproduced under
  SDL_VIDEODRIVER=x11 + `xdotool windowclose` (/tmp/close_repro2.log):
  teardown STARTS (the debug listener closes -> connection refused), then
  the process lingers; the log ends with
  `X Error ... BadWindow ... XInputExtension` (a poll against the already-
  destroyed window) followed by `terminate called without an active
  exception` (a joinable std::thread destroyed on some exit path).
  SIGTERM is swallowed outright (survivors observed); no signal handlers
  exist in the tree except tinyfiledialogs', so library-side masking
  (SDL/GTK/PipeWire) is suspected.
- Suspects for a framework-side fix: observer-thread join vs stop ordering
  (runtime.cpp ~2580-2840), gamepad/XInput polling after window destroy,
  and the joinable-thread destruction on the window-close exit path.
- Tooling caveat learned: x11-forced launches on this Wayland desktop
  intermittently stall during early SDL init (also under gdb; `cpu_backend`
  is the last line). Retry, or use the default driver.
- SHIPPED: `tools/quit.py <port>` (default 19870) = clean-close helper;
  documented in README (play.sh examples) + AGENTS gotchas. Use whenever
  the window close misbehaves; the heal loop is unaffected.
- Open: framework teardown fix + possible upstream issue (same family as
  the bridge stop-contract note).

### 2026-10-08 — Widescreen W1: camera struct, ease code, and the DMA apply path

- Savestate diffing (a new technique here) found the world-map camera
  struct: 0x02002C10-0x02002C1F — v-scroll at +0x0C (151 -> 192 during a
  pan; equals the register value), eased twin +0x0E (stepped 152, 153, ...),
  coordinate +0x08 (256 -> 330), strip pointers +0x02/+0x0A; reached via
  IWRAM object [[0x03002810]+4].
- Update code: ease-step unit 0x08038BF2/0x08038C3E (delta<=3 1:1, <=0xB /2,
  else /4), coordinate writer 0x080376A2, cluster head 0x080328BA; reader
  0x0804C24A-0x0804C288 (flags/coords; unidentified caller role yet).
  Abort-on-write 0x02002C1C caught the first step (pc=0x08038C5E 0x98) with
  the full event chain.
- Scroll REGISTER apply = guest-owned hardware DMA: helper family
  0x08001300-0x08001420 (SAD/DAD/CNT writes + bit31 poll) observed with DAD
  0x04000010/12/14/16 in the FP ring; reached via pointers, not BLs. These
  writes never appear in GBARECOMP_MMIO_CAP — heal_gate.cpp's Journal is
  the registered BusWriteObserver and the prime suspect for the gap.
- W1b (open): the strip drawer. Within-map pans cause zero VRAM-range
  register touches (FP ring), so the drawer runs on scene/map load — next:
  abort-on-write 0x06005000/0x06006000 during world-map and battle ENTRY.
- Tooling learned: (1) savestate before/after diff for state vars;
  (2) FP ring + ringscan --reg/--reg-range for "code that touches X";
  (3) ABORT_ON_MEM_WRITE_ADDR for writer chains (RAM/VRAM only, not IO);
  (4) DMA_WATCH_ADDR for DMA attribution.
- Artifacts: logs/fp_pan.bin (671 MB ring of the pan run; query, don't
  commit), /tmp/ws_{before,after}.state, reference/widescreen.md (new).

### 2026-10-08 (cont.) — Close-hang update: narrowed to the Wayland close path

- X11/XWayland window close tested CLEAN twice (windowclose -> exit < 5 s);
  the user's Wayland-native closes hang consistently (4+ sessions) -> the
  teardown bug is in the SDL Wayland close path (or Wayland-specific
  teardown ordering), not in the generic quit logic.
- The earlier one-shot X11 hang (2026-10-07 repro2: listener closed, XInput
  BadWindow on the destroyed window, `terminate called without an active
  exception`, process lingered) did NOT re-reproduce under X11 -> either
  transient or a second, rarer path. Keep it in mind if a hung X11 close
  ever appears again.
- Signal probe (headless): no SIGTERM/SIGINT handlers registered (SigCgt
  only carries SIG32); the windowed process survives SIGTERM entirely ->
  signals are not a close mechanism here.
- Next diagnostic (agreed with the user): leave the next Wayland hang
  RUNNING; read `ps -L` + /proc/<pid>/task/*/wchan live (ptrace-free); if a
  full backtrace is needed, one-time `sudo sysctl kernel.yama.ptrace_scope=0`
  then gdb attach.
- Interim close (unchanged): `tools/quit.py <port>` / TCP `quit`.

### 2026-10-08 (cont.) — Close-hang SOLVED: not a teardown bug — the close EVENT is never delivered

- User tip paid off: `ydotool` (uinput) can inject input into Wayland
  windows. ESC closes the game CLEANLY and reproducibly (2/2, rc=0,
  teardown ~2 s, verified at the title screen via the watcher probe).
- Alt+F4 (the same xdg close request as the titlebar X) does NOTHING: the
  game keeps running, TCP stays up. Combined with the clean ESC exit, the
  earlier "teardown hang" framing is WRONG for the user's daily case: the
  quit/teardown machinery is healthy; the WM close request never reaches
  the runtime.
- Prime suspect: the binary links `libSDL2-2.0` from **sdl2-compat
  2.32.74 (= an SDL3 shim)** — SDL3's Wayland close-requested event is not
  being translated into the SDL2 events the pump handles (SDL_QUIT /
  SDL_WINDOWEVENT_CLOSE; both ARE handled in host_window.cpp ~2742/2761).
  (The one-shot 2026-10-07 X11 repro hang stays as a separate, rarer
  anomaly.)
- Workarounds SHIPPED/documented: press **ESC** to close (interactive;
  README playtest block + AGENTS gotcha); `tools/quit.py <port>` for
  scripted closes. Both leave play.sh's archive/flush intact.
- Tooling facts for future sessions: `ydotool key 1:1 1:0` = ESC (Linux
  keycode 1); the observe TCP server serves ONE client at a time
  (concurrent watcher + probe connections time out — disconnect first); a
  minimal SDL2 test program against the same lib is the proposed
  upstream-report follow-up for the sdl2-compat close translation.
- Leftover cleanup note: killing a watcher mid-connection can make a
  pending quit.py round-trip time out — the quit is still processed.

### 2026-10-08 — Save-load abort FIXED: copy-hook recursion on split-boundary crossings

- Reproduced the user's fresh-boot "loading my save" abort deterministically:
  strict + boot + saves trace (user menu-nav trace) + their flash save ->
  abort `pc=0x700200F2` (torn IRQ-table slot) after a call storm at
  `0x03007D72`.
- **Root cause**: `ffta::ram_dispatch`'s 2-bytes-early branch re-fired on the
  setup fragment's OWN mid-body fall-through. With the copy planted at
  `0x03007D74`: entry -> `gf_tfunc_03007D64` (setup fragment; its span ends
  at 0x03007D72) -> `runtime_dispatch(0x03007D72)` with `r2=0xFFFFFFFF` (its
  own `rsbs` just ran) -> the branch condition (`pc==0x03007D72 && bytes@pc+2
  == copy-starts`) matched again -> re-ran the setup -> INFINITE recursion:
  8 stack bytes per cycle, zero bytes copied -> VBlank fired mid-march ->
  IRQ table torn read -> `bx 0x700200F3` -> abort.
- **Fix** (src/ffta_ram_dispatch.h): guard the 2-early branch with
  `r2 != 0xFFFFFFFF`. Mid-run crossings now fall through to the fixed table:
  `0x03007D72` = loop unit, `0x03007D80` = tail (pops + bx) — correct code,
  no recursion. Fresh 2-early entries (r2 = real count) still serviced.
- **Verified**: user repro strict = FULLY_STATIC, 1600 f, exit 0 (was abort);
  dumped frame shows the loaded game (in-game menu); attract gate byte-exact;
  strict G FULLY_STATIC. The old found-save + old-trace repro now passes the
  storm and stops at a DIFFERENT frontier (strict miss `0x02003CB0` arm) —
  remaining follow-up, separate from this fix.
- Note: the earlier "torn IRQ table / hunt the record decode" framing was a
  downstream symptom of this recursion (timing + stack march), not the
  scan/validate divergence itself.
- **User confirmation (2026-10-08 08:53, windowed play.sh, scale 4 / width 320):**
  fresh boot -> Start -> Continue -> the save loaded and played (inputs f919-f1357);
  clean close, no core, no heal units, no frag rewrite - the route that used to
  abort now runs heals-free in the real windowed flow.

### 2026-10-08 (cont.) — Annotation pass 7: save/flash driver cluster named

Name-only rows (verified primaries; evidence: the save-flow sections above +
today's disarm/traces): `byte_copy` 0x08141AF0, `byte_compare` 0x08141BB0,
`flash_read` 0x08141B14, `bx_r3_veneer` 0x08142250, `save_sector_scan`
0x0813AE30, `save_record_validate` 0x0813B57C, `save_checksum` 0x0813ADF0;
data row `gIrqCallbackTable` 0x030008D0 (slot+8 = VBlank fn; sources
0x0814942C). `gf_rom_irq_dispatcher` was already named via the code_copy.
Cycle PASS, attract byte-exact, strict G FULLY_STATIC.

### 2026-10-08 (cont.) — Host unit tests for the RAM-dispatch hook

`tests/unit/test_ram_dispatch.cpp` + CTest target `ffta_unit_tests`
(`cmake --build build --target ffta_unit_tests`; `ctest --test-dir build -R
ram_dispatch`). Covers `copy_entry_fixup` semantics (resume reconstruction,
garbage clamps), every hook match branch, ARM pass-through, and a REGRESSION
for today's recursion: a 0x03007D72 dispatch with r2==-1 (the setup
fragment's post-`rsbs` crossing) must fall through, while fresh
two-byte-early entries are still serviced. Synthetic byte patterns only
(no ROM-derived bytes). Framework ctest suites stay unbuilt
(EXCLUDE_FROM_ALL) — scope runs with `-R`.

### 2026-10-08 (cont.) — Annotation pass 8: BRINGUP-described rows

Mined BRINGUP for verified-but-unnamed entities. Functions: `crt0`
0x080000C0, `vblank_callback` 0x080004B0, `vblank_wait_loop`/`_cont`
0x08000418/28, `m4a_soundmain_wrapper` 0x081451B4, `m4a_mixer_core`
0x08144510, `memcmp` 0x081443B0 (disarm-verified word/byte diff loop),
`iwram_zero_fill` 0x03005E78, `iwram_ram_copy` 0x03005EE8. Data:
`gUserIrqHandler` 0x03007FFC, `gIrqAckMask` 0x03000E50,
`gIrqCallbackRomTable` 0x0814942C. Skipped as already-named: main,
m4a_player_info_for_song, gSongTable. Skipped as vague/interior: init-chain
calls, handler tables, the 0x030027D0 slot. Cycle PASS, attract byte-exact.

### 2026-10-08 (cont.) — Regression gate: tools/check.py + tool tests + probe sanity

- `tools/check.py`: one command runs host unit tests (C++ + Python), the
  attract golden gate, and three strict replays (user save-load repro,
  session G, session K) against frozen fixtures in `saves/regress/`
  (sha-pinned save `65742af1...`; traces user_load/sessionG/sessionK).
  Exit non-zero unless every check passes; `--fast` / `--only NAME` exist.
- `tests/python/test_tools.py` (stdlib unittest, 6 checks): trace_split
  backward-jump segmentation + header preservation, cache_harvest
  unit-file parsing + game.toml address set, misspack prologue_scan thumb
  push backscan (synthetic ROM; no real ROM bytes).
- `tools/readseq_probe.py`: now fails loudly (exit 2) when the native
  capture yields 0 calls while the oracle saw >0 — the 2026-10-08
  silent-failure signature (its set_break_pc is a dispatch-entry yield and
  does not fire for mid-function pcs).

### 2026-10-08 (cont.) — Save checksum reversed; savecheck tool; new labels

- `save_checksum` (0x0813ADF0) decoded: standard CRC-32 table (ROM
  0x08393318, now labeled `gSaveCrcTable`) folded into a 24-bit
  accumulator; the validator calls it with seed=0 over the FIRST 0x2FC4
  bytes of the 4-sector group (header sector first) after zeroing
  +0x0C..0x10 and +0x12..0x16. Verified empirically against all three
  known-good groups (user save + both found-save groups).
- `tools/savecheck.py`: structural + checksum validation for raw 64 KiB
  images and RTN5 containers (zlib + CRC32 verified); all three local saves
  validate OK. Labels: `gSaveCrcTable` 0x08393318, `gSaveHeaderMagic`
  0x08149FF8 ("FFTEX000", the validator's memcmp target).
- `tests/python/test_tools.py`: +3 savecheck tests (valid OK / in-prefix
  corruption flagged / RTN5 CRC flagged) — the corruption test caught a
  real savecheck exit-code bug before commit. `check.py` gains a
  `savecheck` entry (fixture must validate).
- **route_G frontier (open)**: with the save present, the G replay aborts
  strict at pc=0x02003CB0 (arm) around f17,950-18,000 — the flash driver's
  epilogue pops a wrong return value (the scan-buffer address) and
  branches into 0x02003CB0 as ARM. Oracle driver-call comparison running
  (full-route scan); route_G stays in the gate until resolved.

- **route_G frontier — updated evidence (oracle scans + native probes):**
  both engines run a record/save flow reading the user-save group (sectors
  9,8,7,6 into 0x02003CB0): oracle at **f18,742** (`src=0x0e009000
  dst=0x02003cb0 n=0x1000 ... lr=0x0813b60d`, four calls, the last n=0xFC4
  via lr=0x0813B623); oracle driver-call scans over 15,000-18,000 = ZERO
  calls, 250-900 = only the f253 boot-scan (0x80-byte sector header reads
  into IWRAM 0x03007DF8, helper planted at 0x03007D64). The native aborts
  during its version of the flow at ~f17,95x; a first-write probe showed
  0x02003CB0 is ALSO general EWRAM scratch (a scene-clear at f17,789 wrote
  it from ROM 0x0800537A while the BIOS cleared VRAM), so watch-target
  probes on it are ambiguous. Open question: the ~790-frame offset between
  the same-looking flows (prior desync vs native-only extra flow). Next:
  dual-engine IWRAM/EWRAM diff at f17,940 to decide, then first-divergence
  hunt if desynced.

### 2026-10-08 (cont.2) — route_G FIXED: mid-copy resume must not re-enter the body

ROOT CAUSE (route_G strict abort pc=0x02003CB0; same class as the
found_save repro): the save driver re-plants its byte-copy helper at its
own stack pointer per call, so a mid-copy IRQ-resume PC can coincide with a
fresh plant and byte-match the routine start. The hook's case-1 treated the
resume as a fresh call and re-ran the canonical body: second push, setup
re-run (r4 <- r0 = stale), full loop — a stack tear; the driver's epilogue
then popped the scan-buffer pointer (0x02003CB0) as a return address and
branched into it (ARM) -> strict miss; non-strict -> runaway.

EVIDENCE: `FFTA_DISPATCH_LOG` decision trail (kept; env-gated): record-read
call at plant 0x03007D74 (r2=0x1000) -> body -> loop; IRQ resume at
0x03007D74 (r2=-1, r3=0x0D5F, r1 mid-record) -> case1 re-entry -> second
push -> loop completes with clobbered r4 -> abort (window bisected to
f17,700-17,800). Oracle cross-checks: engines delta-in-sync at f17,700
(per-frame transition comparison, handler-run shifted); oracle runs the
record reads at f18,742; 0x02003CB0 is shared EWRAM scratch (unstable watch
target — scene clears write it too).

FIX: `ram_dispatch` falls through for every r2==0xFFFFFFFF dispatch
(resume-passthru) before any byte-match case — a mid-copy state must never
run the canonical body; the fixed table's loop-unit resume labels
(0x03007D72..0x03007D7E) continue with the live registers. The old
0x03007D72-only guard is subsumed and removed.

RESULT: strict G 19,400 = FULLY_STATIC (steps 11,895 -> 31,199 — the save
flow now completes); `tools/check.py` 7/7 PASS, attract byte-exact.
Observation for follow-up: the extended flow reports unmapped=46 (open-bus
accesses in newly-reached code) — not chased yet; run completes and gates
are green.

- Hardening follow-up (same day): `copy_entry_fixup`'s r2==-1 count
  reconstruction is removed (resume-passthru makes it unreachable, and it
  embodied the unsafe re-run semantics); the unit suite now pins the new
  rule — a resume (r2 == -1) passes through from ANY address, including a
  byte-matching fresh plant (the exact route_G regression), across both
  chained crossing forms. New label: `gSaveRecordStage` 0x02003CB0
  (0x4000; readseq evidence, shared-scratch caveat in the tsv note).
  `tools/check.py` 7/7.

### 2026-10-08 (cont.3) — unmapped=46: unit-walk name resolution reads above the bus

The 46 open-bus accesses unlocked by the route_G fix (strict G 19,400;
window f17,760-17,800 = the record-read/validation burst) are the game's
own name-pointer resolver, called once per unit record by the save
cluster:

- Accessor 0x080CA1BC (thumb; instruction-ring verified): r1 = [r0];
  mode = byte[r0+0x106]; mode 1 -> *(0x085516D0 + (r1<<2)); mode 0 ->
  *(0x085680DC + (r1<<2)); else -> 0x02001F1C (party name-ptr array).
  Caller loop 0x0813B4B6..CA walks records with stride 0x108 and stores
  each result at r7+0x80+r6.
- The walked records' first words are NOT indexes: mode-1 units hold
  string-region pointers (0x0856C4A8..0x0856D39B; one is 0x085512C7 =
  name-table entry #8, Montblanc's string); mode-0 units hold code-like
  words (0x07084708 = bytes `08 47 08 47`). `table + (ptr<<2)` therefore
  lands above the 28-bit bus (0x24xxxxxx/0x29xxxxxx): 22 reads repeat one
  address, 24 are distinct (46 total).
- Engine responses differ by design: ours returns open-bus prefetch
  (0x47084708); mGBA (src: `address >> 24` -> region 41 -> default
  `_deadbeef`) returns the constant 0xE710B710; real hardware (A28-A31
  not decoded) would mirror into ROM. The caller stores these values, so
  a hidden engine-value divergence exists in this path.
  **WRONG — corrected 2026-10-08 (cont.4): data loads do not hit
  `_deadbeef` (fetch path only); mGBA returns the same open-bus value we
  do (0x47084708), verified empirically on both engines. See cont.4.**
- Open: why the walk's inputs hold pointers (writer not traced; the
  ~950-frame native-vs-oracle flow offset blocks same-frame state diffs).
- Options: (a) framework bus parity for A28+ reads (mGBA's _deadbeef
  constant) — scoped, no other route reads above 28 bits today; (b) true
  hardware mirror model (drop A28+) if retail accuracy beats oracle
  parity. **BOTH WITHDRAWN — no bus change is needed (cont.4).**

Symbols added: `name_ptr_resolve` 0x080CA1BC; `gNamePtrTableA`
0x085516D0 (107 entries); `gNamePtrTableB` 0x085680DC (512).

### 2026-10-08 (cont.4) — CORRECTION: unmapped=46 is oracle-identical; no bus change

Re-trace + measurement overturn the cont.3 "engine-value divergence"
conclusion (the `_deadbeef` path it cited is fetch-only):

- mGBA interpreter data loads go `cpu->memory.load32` -> `GBALoad32`
  (call sites: isa-arm.c:556ff, isa-thumb.c:105ff); the `default:` case
  runs `LOAD_BAD` -> `GBALoadBad()`. For THUMB with PC in ROM that
  returns `prefetch[1] | <<16` — and `ThumbStep`'s recurrence makes
  `prefetch[1] = H(exec_pc + 4)` during execution — i.e. the same
  "[PC+4] halfword mirrored" formula our bus implements. `_deadbeef`
  (`0xE710B710`) serves only fetch/execution in a dead region.
- Ring reconstruction of the f17,799 burst (~12k cycles): the save flow
  rebuilds 24 unit records at staging (0x02003CB0 + 0x80, stride 0x108)
  with the name resolver 0x080CA1BC ([unit+0] = index, mode byte +0x106:
  1 -> gNamePtrTableA, 0 -> gNamePtrTableB, else 0x02001F1C; result
  written back to [unit+0]). The loop runs 3x back-to-back: run 1
  resolves indexes -> pointers (23 valid table reads; sequence
  0x02001F1C, 0x085512C7, 0x08566EAD, 0x08567281, ...); runs 2-3 feed
  the just-written pointers back as indexes -> 23 + 23 = the 46
  out-of-range reads -> field degrades to 0x47084708; a later phase
  restores the real pointers.
- Empirical cross-check (oracle EWRAM snapshots): f18,600/18,700 hold
  0x47084708 in exactly these staging slots (23 of 24); f18,800 holds
  the same resolved-pointer sequence as our run 1. Byte-for-byte the
  engines agree through every observed phase.
- Conclusion: neither option (a) nor (b) — our open-bus behavior already
  matches the pinned oracle for these reads; no framework bus change is
  warranted. (The ~950-frame native-vs-oracle flow offset remains a
  separate, still-open question.)

### 2026-10-08 — Batch af: session M playthrough (new 0x08019xxx cluster)

Playthrough 10:48-10:53 (session M; trace `saves/trace_sessionM_1054.csv`,
last event f9,125). No frag was flushed (session ended non-clean — the
teardown/close path), so the missing PCs were recovered from the heal
cache (`cache_harvest --new`; units compiled 10:49-10:50): 0x08018DAC
plus the 0x0801928C / 0x08019398 / 0x080193CC / 0x080193FC / 0x08019430
family — 6 prologue-verified starts + 5 runtime-dispatched interiors,
both seeded as split-interior entries (11 total; corpus 54,327 ->
54,355 emitted). Strict replay of the session trace: FULLY_STATIC
(resolve needed 0 seeds); cycle PASS (attract byte-exact).

Reminder: `logs/playtest_misses.frag` is journaled live as misses occur (see
the hardening entry below); close with ESC or `tools/quit.py`, and harvest the
`recomp_cache` as a second source if anything looks off.

### 2026-10-08 (cont.) — Hardening: durable miss-frag journal + bounded close

The session-M close (11 heals) stuck and its frag was never flushed — only
recovered via `cache_harvest`. Root cause unproven (no coredump, no exit log),
so the failure class is hardened instead. Two structural gaps: (1) the
proposal frag was written only at the very END of a clean exit; (2) that exit
path joins the heal worker, which drained its whole compile queue (each item
spawns a compiler subprocess) — the only heals-dependent close-path work, and
unbounded.

Guards (gbarecomp working tree; exported patch:
`tools/patches/selfheal-journal-close-hardening.patch` — re-apply after
submodule updates):
- `runtime_arm_default_aborts.cpp`: the frag is (re)written atomically
  (tmp+rename; one shared writer with the exit report) the moment each new
  miss is recorded, env-gated on `GBARECOMP_MISS_FRAG` (play.sh / cycle.py set
  it). An unclean end can no longer lose proposals.
- `overlay_loader.cpp`: shutdown stops the worker after the in-flight compile
  and abandons the queued backlog (already journaled; the next session
  re-requests it) — close latency is bounded.
- `runtime.cpp`: `emit_exit_diagnostics()` (frag + coverage JSON) now runs
  BEFORE the worker join at both game-over exit sites.

Verified: build OK; `tools/check.py` **7/7** (unit-cpp / unit-py / savecheck /
attract byte-exact `1EF4C118…` / user_load / route_G / route_K strict
FULLY_STATIC); zero-miss smoke: no journal write, banner + coverage JSON
intact; framework `selfheal_cluster_test` passes. The record-time journal's
positive path is exercised by the next session that misses a PC — watch
`logs/playtest_misses.frag` mtime update mid-session.

### 2026-10-08 (cont.) — check.py: parallel gate

The gate's checks are independent processes, so `tools/check.py` now runs
them concurrently (`--jobs N`; default auto = min(8, cpus); `--jobs 1` = the
old serial order) and prints results as they complete; crashes/timeouts are
reported as FAIL instead of killing the run. Parallel safety needed two
isolations: each strict route gets its own battery-save copy in /tmp (the
runner flushes "<save>.tmp" → rename; a shared path would race) and a unique
`GBARECOMP_COVERAGE_JSON` path (runs previously clobbered the repo-root
coverage json); `attract_check.py` moves its coverage json into its tempdir.

Measured: full gate 2m40s → **1m30 / 1m41** (two runs, 7/7 both, attract
sha256 `1EF4C118…` unchanged, routes FULLY_STATIC); `--fast --jobs 1`
serial path OK.

### 2026-10-08 (cont.) — Public-repo compliance audit

Full audit before the repository goes public (read-only subagent sweeps over
`reference/`, `symbols/`, `tools/`, `src/` + `git rev-list --objects --all`
history scans; engineering review, not legal advice).

**Clean:** no ROM-derived bytes or binary assets ever committed (history
object scan: zero save/frame/generated/log/BIOS blobs); ROM/BIOS/saves/
caches all ignored and user-supplied; `reference/` guide notes are
summaries with attribution; `symbols/` rows are address/name facts with
per-section credits; no secrets, images, or vendored third-party code in
the tree.

**Fixed:**
- `reference/datacrystal/` — the recovered pages are verbatim Wayback
  captures (GFDL 1.2). Per user direction the wiki content stays, now fully
  licensed: added `LICENSE-GFDL-1.2.txt` (canonical text), rewrote the
  README (attribution, source URLs/oldids, HTML→text modification note,
  license segregation vs the repo's PolyForm NC). **Removed** the
  `String Tables.txt` dump — ROM-ripped in-game text, against the project's
  no-ROM-content rule regardless of the wiki license, so it stays out of
  version control (the rest of the recovered set is likewise not committed).
- Root `LICENSE`: PolyForm Noncommercial 1.0.0 (matches the gbarecomp
  framework), per user decision.
- `THIRD_PARTY_ATTRIBUTION.md` (new): submodules (gbarecomp PolyForm NC,
  recomp-ui MIT), patches-to-gbarecomp note, `tools/m4a_detect.py` credit
  (Bregalad/loveemu `sappy_detector.c`; upstream "free to redistribute with
  credit" statement + forks), pattern credits (`attract_check.py` ←
  WarioWareTwistedRecomp; `ffta_ram_dispatch.h` ← EmeraldRecomp), and the
  reference-material list (facts/quotes only).
- `tools/patches/README.md` (new): patches target gbarecomp; patched
  copies stay under its terms.
- README: legal block (no game content; unofficial; no Square Enix/Nintendo
  affiliation), License section, and a "Thanks" section crediting the
  referenced projects/authors; AGENTS rule 8 (public-repo hygiene — never
  add verbatim third-party text again; keep the attribution file current).

**No history rewrite** (user decision): the retained GFDL pages are
compliant as distributed (license text + attribution included in-tree);
commit `26b0658` stays as-is.

### 2026-10-08 (cont.) — Fresh-clone newcomer verification (2 real blockers found)

Ran the README build path end-to-end from a scratch clone (`/tmp/ffta_fresh`:
clone → submodules → venv → framework tools → dumps → patches → BIOS
recompile → corpus → host build → strict smoke + attract). It caught two
things the dev checkout never could:

**Blocker 1 — `tools/patches/oracle-save-autoload.patch` was not a diff.**
Committed as a side-by-side/formatter view of the change (same class as the
old "`git diff` through a formatter" lesson); `git apply` rejected it ("No
valid patches in input") — never apply-able in committed form. Fixed:
regenerated via `git --no-pager -C gbarecomp diff --no-ext-diff --no-color
-- oracle/main.cpp`, verified forward on a pristine pinned submodule and
reverse on the dev tree. Hardened: `tools/check.py` gained a `patches` check
(forward-or-reverse apply must succeed; included in `--fast`) — the class
had no gate before.

**Blocker 2 — BIOS recompile needs `--config bios/gba_bios.toml`.**
Without it only 666 BIOS functions are discovered (vs **770** with it; the
setup text omitted the flag). The truncated BIOS aborts strict runs with
`dispatch miss for pc=0x00000300 (arm)` (attract gate exit -6 on a fresh
build). With the config, the fresh-clone `bios_recompiled.cpp` is
**byte-identical** to this checkout's (`c3e2cfb4…`); strict 2400 =
FULLY_STATIC and attract PASS (`1EF4C118…`). README step 6 + troubleshooting
and the AGENTS BIOS note updated.

Evidence: `/tmp/fresh_resume.log`, `/tmp/fresh_bios2.log`,
`/tmp/fresh_smoke2.log` (scratch clone at `/tmp/ffta_fresh`).

**Pass 2 (untampered re-run of the fixed path, from the committed tree):
clean through all nine steps** — submodules checked out, both patches applied
to the pinned submodule, BIOS 770 funcs, corpus emitted 54,355, host build
linked the recompiled BIOS, strict 2400 `FULLY_STATIC`, attract
`1EF4C118…` PASS. Evidence: `/tmp/fresh_verify2.log`.

### 2026-10-08 (cont.) — Coverage snapshot refresh (README)

Re-ran `tools/coverage_report.py` on the committed tree (strict 1200-frame
run + cold trials): executed path **100 % FULLY_STATIC**; corpus **54,355
emitted units**; walker's static reach **54,355 / 55,673 ≈ 97.6 %**;
pointer-pool reach **54,355 / 54,432 ≈ 99.9 %**; harvest trial kept 2,122
candidate pointers of 104,915 PC-relative literals. README status paragraph +
snapshot table refreshed (was the 54,327 snapshot of 2026-10-07); AGENTS
status line aligned. Historical landing figures for the event crawl (roadmap
item 3) left as written.

### 2026-10-08 (cont.) — Save-flow investigation: closed for docs (repro re-verified)

Re-ran the classic found-save strict repro now that the ram-dispatch resume
fix (cont.2) has landed: `GBARECOMP_STRICT_STATIC=1` + trace
`sessionL_1736.csv` + save copy (2,600 frames) → **FULLY_STATIC, exit 0**
(previously `dispatch miss pc=0x700200F2` at f ≤ 1,272; `unmapped=18`, the
oracle-identical open-bus reads). Together with route_G/K + user_load
strict-green in the gate, every deterministic save repro is now clean. The
2026-10-07 "descriptor zeroed / validator divergence" theory is superseded by
the cont.2 root cause (our hook's mid-copy re-entry — the stack tear produced
the garbage calls and the wrong epilogue pop). Remaining open-minor: the
~950-frame native-vs-oracle flow offset (cont.4 note). Docs updated: README
(open-investigation paragraph, acceptance list, roadmap item 4), AGENTS
gotcha bullet.

### 2026-10-08 (cont.) — README state cleanup

Swept the README for statements that no longer represent the current state
(save-investigation closure, coverage refresh, annotation pass, event walk):
the status paragraph now lists the real remaining set (widescreen W1b–W3,
gated offline re-trial, f6000+ contact sheet, upstream note, Android port;
batch range a–ag), and the Roadmap is restructured into "Open / next" vs
"Landed (context)" — the annotation pass, event walk (af/ag), save-flow
resolution, and main-game content moved under Landed. The offline-push item
notes that condition (a), the route-level gate, is now satisfied by the
`check.py` route replays, with (b) (interior-split policy) still the
re-trial trigger. AGENTS "Remaining" aligned.

### 2026-10-08 (cont.) — MMIO cap gap: guest-DMA register writes now recorded (fixed)

The W1 `GBARECOMP_MMIO_CAP` caveat is resolved; it was our bug, not the
Journal's. `GbaIo::write32` decomposes 32-bit IO stores into two 16-bit calls
and set a file-local `g_mmio_split` flag so the ring records ONE size-4 entry
(peer to the oracle) instead of the synthetic halves. But a 32-bit store of
the DMA CNT field — FFTA's display commit at 0x0800073C (`str r1,[r0]`, the
0x0800072x-3C channel setup; helper form `str r0,[r2,#8]` at 0x080013E0) —
kicks the whole transfer from the CNT_H half, i.e. INSIDE the flagged window:
every destination write of the transfer was swallowed.

Repro: world map (`game.state2`, frame 51,827) + Down recenter via input
trace; WRAM/IO value traces proved the registers DID update (VOFS stepping
0x97→0xA1 with the camera ease) while the cap held 0 writes to 0x04000010-16.
After the fix: 36,117 → 51,678 cap entries; the newly visible set is the
per-frame display-commit DMA block copy — 39 halfwords
0x04000008..0x04000054 (BGxCNT/HOFS/VOFS, affine, windows, blend), one copy
per frame, kick pc 0x0800073C, 39×399 entries; pan-phase VOFS values in
lockstep. The 32-bit single-entry behavior is preserved (0x040000B8 count
unchanged at 1,596).

Fix: per-call record control (`write16_commit(off, v, bool record)` in
gba_io.{h,cpp}); synthetic halves pass record=false, while reentrant writes
(DMA transfers, side effects) keep recording; `g_mmio_split` removed. Patch:
`tools/patches/mmio-cap-dma-reentrancy.patch` (re-export after submodule
updates). `tools/check.py`'s patches check now globs `*.patch` so the new
file is covered (reverse-ok, as all three). Gate: `.venv/bin/python
tools/check.py` — 8/8 PASS; attract 1EF4C118… byte-exact. Candidate for the
upstream issue (with the bridge stop-contract + relocated-stub classes).

### 2026-10-08 (cont.) — Annotation: display commit + shadow named (from the MMIO-cap work)

The fixed cap + DMA watch pinned the per-frame display commit precisely:
DMA0, SAD = IWRAM 0x03000942 (literal @ 0x0800075C), DAD = 0x04000008,
CNT = 0x80000027 (39x 16-bit), busy-poll after; routine start 0x08000718
(prologue; already emitted). Added symbols:
- `display_regs_commit` 0x08000718 (thumb) — Section 13, ffta_symbols.tsv.
- `gDisplayRegShadow` 0x03000942 (iwram, 0x4E) — Section 13, data symbols
  (watched SAD + CNT_L=39).
Section-6 note updated: the 0x08001300-0x08001420 sequences are inline
program+poll sites inside larger pointer-reached routines (0x080012BC fills
1024 B at 0x07000000, then runs them; role unpinned — not named).
reference/widescreen.md index updated. Regenerated (names-only; corpus
54,355 unchanged) + cycle PASS: attract 1EF4C118… byte-exact.

### 2026-10-08 (cont.) — Widescreen W1b: the strip drawer LOCATED (LZSS → staging → DMA)

Repro: world map (`game.state2`) + two A presses (enter Sprohm/pub).
Traps chained: VRAM value trace → DMA watch → FP ring + ringscan.

- The field screenblocks get their content at frames ~193-196
  (0x6000/0x6800/0x7000/0x7800; 0x5000/0x5800 follow, 196-236), by DMA
  streaming from EWRAM staging buffers (ch=0, e.g. dad=0x06006800,
  src=0x0200BDDC/0x0200BA5C, 32x16-bit chunks).
- The staging is written by the LZSS decompressor at 0x0800543C — the
  entry the ffta.lzss-guard seam already protects (hot loops 0x0800553E-6A;
  0x08005544 is the interior-split point from the offline-push notes).
  Captured live call: `0x08022A2E bl 0x0800543C` with src(r1)=0x083AF504,
  dst(r0)=0x02003CB0 — the shared scratch also used by the save driver
  (this overlap explains earlier save-vs-scene churn at that address).
- Decoder callers during the load: `scene_gfx_load` 0x08022A04 (bitmask
  arg; decompress + CpuFastSet copies), plus 0x0801A620 and 0x080CB8C6
  (other resource loaders).
- Fills/evictions (0x08023Fxx/0x080240xx CpuSet/DMA zero-fills) precede the
  content; the previous scene's blocks are already zero so the fills are
  value-invisible (only visible via abort probes).

Symbols: `lzss_decompress` 0x0800543C + `scene_gfx_load` 0x08022A04
(Section 14); gSaveRecordStage note refined. reference/widescreen.md § W1b
rewritten with the pipeline + repro; README roadmap + AGENTS updated.
Cycle PASS; attract 1EF4C118… byte-exact. Next: battle-map variant confirm
(same pipeline expected) + W2 hook design (extend at the upload stage).

### 2026-10-08 (cont.) — W1b battle variant: pan redraw pipeline mapped (strip blit)

User-provided state `game.state1` (mid-battle overview — cursor pans the map).
Holding Right pans BG2/BG3 horizontally (BG2HOFS/BG3HOFS 0x04000018/0x1C,
~0x12/frame eased; BG0/BG1 VOFS animate separately); the world-map camera
struct 0x02002C10 is NOT used in battle (zero writes during the pan).

The pan REWRITES the field screenblocks 0x06006000-0x06007FFF (frames 62-115
for a right-hold) via the strip pipeline: `strip_refresh_engine` 0x0801AC78
-> `strip_refresh` 0x0801B7F8 -> `strip_blit` 0x0801AF08 (chunked
staging->VRAM: manual ch0 DMA 32x16-bit, src += 0x80 / dst += 0x40,
busy-poll; CpuSet variant via the 0x0814186C thunk). Staging
(0x0200B000-0x0200C000 traced) is PRE-COMPOSED — zero writes across the
whole run; the LZSS decoder does NOT run per pan step (two decoder calls in
the run came from 0x080CB8AA, ~every 48 frames = the animated-tiles refresh,
not the pan). The blit walks offset counters in `gStripBlitDesc` 0x02007F40
(0x28-byte entries; +0x24/+0x26 advance with the pan; two entries seen).
Internal map model is 64 columns wide (`cmp #0x3f`) = 512 px — the engine
already handles >=512-px-wide maps internally; the visible window is 256 px.

Symbols: Section 15 (strip_refresh_engine/strip_blit/strip_window_fill/
strip_refresh) + data Section 14 (gStripBlitDesc). reference/widescreen.md
W1b rewritten (both variants); camera section corrected (battle: not this
struct). README roadmap updated. Cycle PASS; corpus 54,355; attract
1EF4C118… byte-exact.

W2 consequence: hook at strip_blit / the descriptor walk (materialize the
extra columns there) — the decoder is NOT in the pan path.

### 2026-10-08 (cont.) — Widescreen W2 milestone 1: authored margins LANDED

Implementation (game-side only; framework pin untouched beyond existing APIs):
- `opts.max_view_width = 320` in src/main.cpp — validated capability; run
  `--view-width 320` (or --resize-view); default stays faithful 240.
- `opts.extended_view_init = ffta_ws_install_margin_hooks` installs
  `g_ws_authored_margin_layers = 1` (margin columns render from the guest's
  own 512-wide rings instead of pillarbox black; savestate loads then keep
  the pillarbox policy off) and `g_ws_obj_native_clip = 1` (parked off-screen
  OAM never leaks into margins). extended_view_init is the right seam:
  run_game() clears game-owned WS hooks on entry ("never leak into a later
  faithful run"), so installs must happen from inside the run.
- Debug path worth remembering: the pinned engine does NOT link
  mod_runtime.cpp (no `gba_mod_register_activation_plugin`; the lzss-guard
  link error on 2026-10-07 was this class). Usable seams: RunOptions
  extended_view_init / extended_view_frame + fn-entry plugins.

Verified (headless dumps, --view-width 320, WS_WIP NOT needed):
- battle at rest / pans f100+f150 / pub interior post-load: margins 100 %
  non-black, filled from the ring's own content (water/cliff continuation);
- world map: margins render but as its 256-px map's wrapped edge (UI chip
  tail leaks) → W3 per-scene policy;
- center fidelity: wide center [40..280) vs faithful 240 render =
  0/38,400 differing pixels; attract byte-exact; check.py 8/8; routes
  FULLY_STATIC;
- temporary gba_ppu.cpp debug instrumentation fully reverted — submodule
  diff scope back to the documented patch set.

Reference inspection (user-supplied URLs): EmeraldRecomp ships the full
widescreen architecture (docs/WIDESCREEN_EXPERIMENT.md +
src/mods/emerald_adaptive_view_plugin.cpp): host-synthesized margins
(tilemap provider for ring-wrap games + object layer + UI edge-anchoring),
fail-closed pillarbox, per-frame policy, verification probes and smoke
tools. FFTA needs none of the provider machinery for field scenes (its
rings are real 512-px data); the UI-anchoring model is the reference for
W3 if HUD stays wide. WarioWareTwistedRecomp has NO widescreen
implementation (attract tooling reference only).

W3 next: per-scene policy via `extended_view_frame` (world map → pillarbox
or clamp; menus/transitions → pillarbox; field → wide); margin polish
during transitions; wider validated widths (384/448); Emerald-style smoke
compare for the test suite.

### 2026-10-08 (cont.) — Build config: GBARECOMP_ENABLE_MODS=ON (adopted); symbol: strip_scroll_compute

- Upstream check: a live `git ls-remote` shows origin/main tip = `ecc9c55` =
  our pin — **we are on the latest gbarecomp** (tip dated 2026-10-03;
  nothing newer has landed). The "couple weeks behind" applies to Emerald's
  published deps, not us. The real difference vs Emerald: they build with
  **`GBARECOMP_ENABLE_MODS=ON`**, which compiles `mod_runtime.cpp` — the
  activation/reset plugin lifecycle, `gba_mod_set_view_width`, committed
  plugin options (the APIs our 2026-10-07 session hit as "undefined
  reference"). Trialed ON: build clean, `gba_mod_register_activation_plugin`
  now linked; full gate 8/8, attract 1EF4C118… byte-exact, routes
  FULLY_STATIC → **adopted** (`-DGBARECOMP_ENABLE_MODS=ON`; README + AGENTS
  updated). Our WS wiring stays on `extended_view_init` for now; migrating
  to the activation/reset lifecycle is a W3 cleanup (enables launcher-side
  mod options for widescreen).
- Symbols: added `strip_scroll_compute` 0x0801C984 (Section 15: reads the
  blit desc +0x20/+0x22/+0x24/+0x26, returns targets/deltas; live call from
  0x0808F004 during pans) and enriched the `gStripBlitDesc` field map
  (Section 14: verified +0x04/+0x06 limits, +0x14/+0x18 engine args,
  +0x28/+0x2A deltas, +0x2C flag bits). 0x080006D0 left unnamed: mechanics
  clear (DISPCNT → 0x03002BBC; DISPCNT := 0x0080; REG_IE := [0x03000E50])
  but intent unpinned — "never guess". Cycle PASS; corpus unchanged.

### 2026-10-08 (cont.) — Skills refresh (playbook): capture-layer bugs, state census, engine hooks, margin policy

Updated `.agents/skills/gbarecomp-recomp-playbook/` with the lessons from
the MMIO/W1b/W2 arc: tooling-and-pitfalls now covers the instruction-ring
window's density dependence + the `--max` scan-progress semantics, the
zero-over-zero write invisibility pitfall, the capture layer's own
reentrancy-bug class (the MMIO split-flag story: bisect the capture path
before blaming the guest), DMA-watch exact-address semantics, a new
"Offline state census" subsection (parse the save-state container for
VRAM/IO answers without running), widescreen margin-policy traps +
expanded-path proof recipe (center pixel-identical, margins decoded,
default-off hash), and a new "Game-owned engine hooks" subsection (hooks
are cleared per run — install via runner callbacks; check build flags with
`nm`; verify pins with `git ls-remote`). debugging.md gains the
"chained-traps" writer-hunt recipe; reproducibility.md notes input replays
key on the GUEST frame counter (absolute frames after state loads);
verification.md gains submodule-patch gates + formatter-mangled export
warnings and default-off evidence for presentation expansions. miss-triage
needed no change.

### 2026-10-08 (cont.) — Widescreen W3 milestone 1: per-scene margin policy (+ W2 pub-check correction)

`src/main.cpp` now installs `opts.extended_view_frame = ffta_ws_margin_policy`
(per-frame, pre-scanline): world-map scenes (BG0/BG1 size=2 = 256-px
tilemaps) set `g_ws_pillarbox = 1` (black bars — their margins are the wrap
edge); ring scenes (size=1: battle/pub) stay wide. BG2/BG3 (256-wide UI
screens) return no-pixel outside the native 240 span via
`g_ws_bg_x_provider` (+ mask `(1<<2)|(1<<3)`) so menu/funds/dialogue edges
can no longer wrap into the margins (this was visible in the pub before
the fix: "ME/Ru/Qu/Lea" fragments in the right margin).

Verified with --view-width 320: battle margins 12800/12800; pub margins
12800/12800 CLEAN (UI fragments gone; center vs faithful 0/38400); world
margins 0/12800 (pillarbox); attract byte-exact; check.py 8/8; routes
FULLY_STATIC. Battle @384 spot check: 72-px margins filled (full validation
pending).

CORRECTION (documented per discipline): the W2-era "pub interior post-load
— margins 100 %" verification had run without `GBARECOMP_INPUT_REPLAY` set,
so that run never left the world map — it was a world-map wrap check, not
the pub. Found during the W3 re-check (the pub "failed" the new pillarbox
detector precisely because the scene was the world map all along). The pub
is now genuinely verified (above); reference/widescreen.md + README updated.

### 2026-10-08 (cont.) — Batch ah: link-feature session (65 units) + ARM RAM-dispatch case

Session N (trace archived `saves/trace_sessionN_1527.csv`, 5,612 frames,
played on `saves/my_skyemu.sav`, link feature attempted): 65 misses,
journaled live through the exit issue (the close hang persists
intermittently; the frag survived as designed — no re-investigation per the
standing direction).

- 64 thumb units in the `0x08062xxx-0x08066xxx` cluster (the link/comm code
  the session reached) — merged with prologue-scan evidence
  (start/interior notes). Seed cascade: corpus 54,355 → **55,098** (+743).
- The FIRST miss was an **ARM-planted** helper at `0x03002B70` ← ROM
  `0x08005088` (0x40 bytes; unique match from the live IWRAM dump captured
  with `GBARECOMP_MISS_IWRAM_DUMP`): IE-off 8-word rotate at
  `[0x030028A0]+0x40`. Root cause of the miss: `ram_dispatch` declined ALL
  ARM dispatches (`if (!thumb) return 0`). Fix: ARM branch byte-verifying
  the template and running the canonical body; `[[code_copy]]` +
  `[[extra_func]]` (arm) added to game.toml; unit tests extended (match at
  any plant address; non-match falls through; second fake-ROM window).
- Tooling: `resolve.py` gained `--save-path` (traces that include an
  in-game load need the session's battery save; without it the replay
  diverges before the interesting code).

Acceptance: strict replay of session N = FULLY_STATIC (resolve iter 0);
attract 1EF4C118… byte-exact; `check.py` 8/8; coverage refreshed (walker
55,098/56,328 ≈ 97.8 %, pool 55,098/55,510 ≈ 99.3 %). All ROM claims
byte-matched (disasm + live dump evidence).

Annotation from the same batch: `irq_buffer_swap` (0x03002B70 arm — the
canonical name for the planted ROM 0x08005088 helper) + `gMsgWorkBuffer`
(0x030028A0, 0x60 — the queue-manager work struct the cluster and the swap
touch; Section 15 data / Section 16 symbols, roles with notes). The
0x08062xxx-0x08066xxx message/queue cluster is documented in the Section 16
comment (a duplicated strip_scroll_compute row from an earlier edit was
also removed). Cycle PASS; corpus unchanged by naming.

### 2026-10-08 (cont.) — Batch ai: pub mission screen (3 units)

Session O (trace archived `saves/trace_sessionO_1553.csv`, 32,354 frames,
boot-based, played on `saves/my_skyemu.sav` — pub mission screen browsing):
3 misses, all in the 0x08018xxx region (mission/UI code paths reached from
the mission list): 0x8018E94 and 0x8019268 are function starts, 0x8019280
is an interior/split seed inside 0x8019268. Merged with prologue evidence;
resolve iter 0 = FULLY_STATIC; corpus 55,103 (+5 incl. cascade); attract
1EF4C118… byte-exact; check.py 8/8; coverage refreshed (walker
55,103/56,333 ≈ 97.8 %, pool 55,103/55,515 ≈ 99.3 %). The close issue
recurred (third session in a row) — the live journal preserved the frag
again; no re-investigation per the standing direction.

### 2026-10-08 (cont.) — W3 m2: widescreen smoke + full 320/384/448 matrix

- `tools/ws_check.py` (new): per scene fixture x view width — headless
  engine runs in parallel (`--jobs`, isolated dump/save/coverage/frag
  paths); checks center-crop equality vs the faithful 240 render, the
  margin census against the per-scene policy, and an idle-vs-pan stale
  guard on the margins. Fixtures: local `game.state1`/`game.state2` +
  committed `inputs/ws_{pub_enter,pan_right}.csv`; exit 2 when missing.
- Full matrix PASS (4 cases x 3 widths, ~2.6 s): world map margins 0 %
  (pillarbox exact), pub/battle 100 % filled, center 0/38,400 differing
  everywhere, stale guard 96.2/92.2/81.4 % idle-vs-pan change.
- Capability raised: `opts.max_view_width` 320 -> 448 and resize-driven
  view enabled (`max_resize_view_width = 448`); `--resize-view` now
  authorized (windowed only by design). Default stays faithful 240.
- Gotcha recorded (reference/widescreen.md): `--frames` = frames to RUN
  after a state load, not an absolute guest target; budgets must cover the
  CSV's absolute-frame events. First calibration ran 51,917-frame
  marathons (~3 min/run); corrected runs ~1 s.
- Gate: `check.py` gains `ws_smoke` — ALL PASS 9/9; cycle PASS; attract
  byte-exact. Remaining W3: transition polish + plugin-lifecycle migration.

### 2026-10-08 (cont.) — W3 m3: transitions verified + plugin-lifecycle migration (W3 COMPLETE)

- Transitions: world->pub entry fades through full black (guest 52027) and
  fades in with margins dimming with the center (52067: margin max == center
  max); leaving the pub (B@52120, new fixture `inputs/ws_pub_exit.csv`)
  fades through black and the world map returns pillarboxed (52347: margins
  exactly 0). Ring pans/recenters keep margins fresh (stale guard). Margins
  sample the same layers through the same compositor, so fades apply
  uniformly — no policy change needed; the invariant is now gated
  (pub_fade case: margins never brighter than center +8).
- Smoke test: 6 cases x 3 widths PASS (world_idle, pub_idle, pub_fade,
  pub_exit, battle_idle, battle_pan + stale guard).
- Lifecycle: all game-owned hooks install through the trusted activation
  pass — reset callback (clears presentation state; re-arms the lzss entry
  guard after the engine's disable-all) + activation plugin
  `ffta.widescreen` (margin hooks). New default-enabled manifest
  `mods/preloaded/packages/ffta.enhancement.widescreen/1.0.0`, shipped to
  `<exe>/mods` by CMake; `opts.mod_game_id = "ffta-us"`; `extended_view_init`
  dropped (per-frame policy stays as `extended_view_frame`). Feature-off
  fallback verified (engine-default sampling; game runs; policy applies).
- Framework race patched: concurrent launches collided on the shared
  `state.toml.tmp` (rename ENOENT whose retry deleted the published
  output) — `tools/patches/mod-state-publish-race.patch` (unique per-PID
  temp); 4/4 parallel smoke runs clean after.
- Gates: cycle PASS (attract byte-exact); `check.py` 9/9 (4 patches
  validated); routes FULLY_STATIC. **W3 backlog complete.**

### 2026-10-08 (cont.) — Skills refresh: W3 + harness/CI lessons

Playbook updated from the W3 arc + the parallel-harness/CI work (docs
only, no code change):

- tooling-and-pitfalls: engine-hook **ordering** expanded (activation pass
  runs on every run, after cleanup; install from the activation plugin;
  re-arm entry guards from the reset callback; entry plugins register
  disabled; ship via the mods catalog gated on game id + ROM hash; verify
  feature-off fallback and note game-code vs plugin-owned parts).
- reproducibility: frame-budget bullet now says the budget must reach the
  last absolute-frame replay event (misreading = idle marathon that looks
  like a hang).
- verification: gate bullets gained dedicated fixture copies (separate
  from player-overwritten slots; missing-vs-changed semantics with the
  reason surfaced), concurrent-check isolation incl. engine temp files
  (the `state.toml.tmp` race, fixed + exported as a patch), the CI tier
  split by private material, and the presentation-matrix refinements
  (≥2 widths, sample authored columns, fade compositor invariant,
  stale-margin guard, headless-only caveat for windowed paths).

### 2026-10-08 (cont.) — CI fix: unit-py needs capstone on the runner

GitHub CI (tier 1) failed `unit-py` with an empty detail line. Root cause
(reproduced in a fresh clone with system `python3`): `test_tools.py` imports
`tools/misspack.py`, which does a module-level `import capstone`; local
runs always used `.venv` (capstone 5.0.7) but CI runs the system
interpreter, so the import aborted the whole module before unittest could
run. The empty detail was a second (reporting) gap: `check_unit_py()` read
only the last *stdout* line, and unittest/tracebacks go to stderr.

Fixes:
- `.github/workflows/ci.yml`: `actions/setup-python` 3.12 +
  `pip install capstone==5.0.7` (pinned to match `.venv`; manylinux
  `py3-none` wheel — no build deps on the runner).
- `tools/check.py`: `check_unit_py()` falls back to the most useful stderr
  line on failure instead of an empty detail.
- `tests/python/test_tools.py`: missing capstone raises a one-line
  actionable `SystemExit` ("run via .venv" / pip line), not a raw traceback.
Verified: fresh-clone `--only unit-py` passes with capstone importable
(PYTHONPATH simulation of the CI env); fails with the friendly line without
it; local `--only unit-cpp,unit-py,patches` green via `.venv`.

### 2026-10-08 (cont.) — build.py: fresh-clone bootstrap lands

`build.py` (repo root) wraps the whole newcomer setup — the recipe the
fresh-clone verification scripted by hand — into one idempotent script:
submodules (two-pass) → dump validation → `.venv`/capstone (uv, else
venv + pip) → framework patches (apply/reverse-checked per file) →
framework tools build → BIOS recompile → corpus regen → host build →
strict 2400-frame smoke. Stdlib-only so it runs on the system python
before `.venv` exists; every step detects completion (re-runs: 1.4 s in
the dev tree, 8.4 s in a fresh clone); `--force` redoes BIOS + corpus,
`--no-smoke` and `--jobs N` available.

Validation before any long build, each failure ending in an actionable
hint (all rc=1):
- dumps: existence + size (ROM 16,777,216 / BIOS 16,384) + SHA-1 —
  distinct messages for missing / truncated ("wrong size") / wrong
  content ("SHA-1 mismatch ... wrong or corrupt dump?").
- submodules: pinned-worktree markers + off-pin drift warning
  (`git submodule status --recursive`).
- patches: missing/empty patch dir checked; per-file forward/reverse
  `git apply --check`.
- build steps: rc + output tails + artifact existence (tool binaries,
  bios_recompiled.cpp, generated/dispatch_table.cpp, build/FFTARecomp).

Docs: README § Setup now leads with the one-command path (manual route
kept as a collapsible reference, renumbered to build.py's order; separate
Troubleshooting entries for the new step names); AGENTS commands table
row; playbook bootstrap bullet (stdlib-only, per-step idempotence, fail
before long builds); `BuildPyTest` keeps `build.py --help` runnable on
the system python (unit-py 11 tests).

End-to-end evidence (scratch clone of the committed tree, no submodules,
no dumps):
- run 1 (no dumps): rc=1, `ROM missing: game.gba` + "place your own
  legally-dumped ROM" hint — after submodules were fetched and pinned
  (all six checked out at their recorded commits).
- run 2: 4 patches applied, framework build, BIOS recompile (770),
  corpus (55,103 units), host build, smoke = FULLY_STATIC; DONE in
  204.2 s, rc=0 (job 6m06s total incl. submodule fetch).
- negative suite on the built tree: missing ROM / truncated ROM /
  wrong-hash ROM / truncated BIOS — all rc=1 with their distinct
  messages; restored tree re-ran idempotent (8.4 s, FULLY_STATIC).

### 2026-10-08 (cont.) — README split: testing docs → tests/README.md

Root README's § "Playtesting & debugging with tools/play.sh",
§ "The playtest → healing loop", § "Verification & regression" and
§ "Continuous integration" moved verbatim to the new `tests/README.md`
(316 lines; it also hosts the host-unit-test commands). Root keeps a
short "Testing & debugging" pointer section between "Run it" and the
layout table; Setup and its collapsible manual route are unchanged.
Cross-references updated: AGENTS.md (reading order, workflow B,
reference index), `tools/check.py` docstring, `ci.yml` tier comment;
in-file "see below" pointers now target `tests/README.md` sections.
Docs-only — no behavior change (`unit-py` green, 11 tests).

### 2026-10-09 — Docs: ANDROID.md → android/README.md; Android pointers refreshed

The Android guide moved from the repo root into the target it documents:
`git mv ANDROID.md android/README.md` (history preserved). Nothing had
linked the old path yet, so the move also wired the guide into the doc map;
`android/README.md` itself notes the move and drops its "AGENTS.md / README
pointers" deferred item (now done).

State sweep of the docs that still described the port as pending:
- README: status paragraph now lists **Android playable on device**
  (engine-shell port 2026-10-08) with a link; "Testing & debugging" gains a
  device-gate bullet; layout table gains an `android/` row; Roadmap item 3
  becomes **Android release prep** (packaging/signing, arm64-only, APK
  content guard, version stamping, touch-first input, perf/size pass,
  upstream mods-state note).
- AGENTS.md: "Android port" removed from the remaining list (landed +
  device-verified), codebase map and reference index point at
  `android/README.md`.
- tests/README.md: Android device-gate bullet + a CI note (device-bound,
  manual — not part of either tier).
- reference/dev-gotchas.md § Android device forensics: guide pointer.

Docs-only — no code, config, or gate change (`unit-py` re-run green, 11
tests).

### 2026-10-09 (cont.) — Android device-free checks land; CI tier 1 runs them

Implements the Tier-1 slice of the device-free test survey: new
`tools/android_static_check.py` — the `android-static` suite in
`tools/check.py` (also in `--fast`), run by CI tier 1
(`--only unit-cpp,unit-py,patches,android-static`). Stdlib Python only: no
SDK, no device, no Gradle build, no private material.

17 checks:
- identity: applicationId ↔ the gate's PACKAGE; gate activity constants;
  variant ↔ `[game] short_name` across build.gradle / game.toml /
  game_android.toml; ROM sha1 (4 sources) + size + filename; BIOS sha1
  across game.toml / game_android.toml / the engine template default (LLE
  stays on); save type/size parity.
- payload: `state.toml` enables `ffta.enhancement.widescreen` (the
  second-launch persistence fix) and matches the pinned catalog manifest;
  both mods sources wired; `resize_view = true` stays the Android opt-in.
- hygiene: no ROM/save/APK/state artifacts tracked; android
  build/artifacts/local.properties outputs stay gitignored.
- gate behavior: `tools/validate_android.sh` against a fake `adb` (PATH shim
  + `FADB_SCENARIO`; shellcheck-clean): clean run GATE PASSED with evidence
  pulled; SELF-HEAL / missing-log / crash-buffer / setup-still-resumed runs
  GATE FAILED with the matching assertion; `--help` exits 0, bad usage 2.

Evidence: suite green locally (0.7 s in the gate); the exact CI line
`--only unit-cpp,unit-py,patches,android-static` ALL PASS; in-memory
mutation checks (resize_view=false, variant drift) are caught. Docs: AGENTS
commands table, tests/README verification + CI, android/README § Device-free
checks (+ thin-surface row), gate-script header, README testing bullet +
tools list; the playbook's verification reference gains the portable lesson
(fake-tool gate self-test + config-contract CI tier).

Remaining from the survey (tiers 2–3): Robolectric shell unit tests and the
APK content guard — both need SDK/Gradle (and the guard a built APK); a
separate tier when wanted. Both now sit on the `android/README.md` deferred
list (Robolectric as its own item; the guard under release packaging).

### 2026-10-09 (cont.) — Android APK content guard lands (`android-apk`)

Implements the deferred "APK content guard" (device-free test survey, Tier
3): `tools/android_apk_check.py` — a static pass over a built APK (unzip +
aapt2; no phone, no Gradle rebuild). Eight checks: badging identity
(package/minSdk/targetSdk/launcher vs build.gradle + engine template);
public/private marker-vs-content consistency (`--expect` optional); payload
byte-equality against the staging sources with an exact entry-set compare;
private ROM/BIOS size + SHA-1 against the pins (public must embed neither);
exactly one libmain.so per ABI with the expected library set + a badging
cross-check; both activities in sensorLandscape + debuggable matching the
build type; no packaged debug-args.txt; packaging sanity (zip CRC, duplicate
entries, stray paths, assets outside payload, oversized non-lib entries —
the incremental-repackaging junk-blob class).

Wiring: `check.py --only android-apk`, excluded from the default run and
`--fast` (a desktop-only worktree has no APK); direct use accepts `--apk
PATH` and `--expect public|private`.

Found + fixed while verifying: the documented private-build command passed
`-PprivateRom=../game.gba -PprivateBios=../gbarecomp/bios/gba_bios.bin`, but
the engine template resolves `-Pprivate*` paths against `android/app` — a
private rebuild failed ("Private BIOS must be the 16 KiB dump").
`android/README.md` now uses `../../…` (build re-run green).

Evidence: private arm64 APK PASSES (embedded ROM sha1 == pin; 35.5 MiB); a
fresh PUBLIC build PASSES under `--expect public` (29.8 MiB), and its staged
payload correctly shed roms/bios — the "distributable build never inherits
private assets" Sync claim verified on a real repackage; 12 crafted-zip
negatives all caught (missing/altered/extra payload file, 2 MiB junk blob,
duplicate entries, public+ROM, empty private, ROM hash mismatch, unexpected
lib, unexpected ABI, orientation drift, `--expect` mismatch). The private
arm64 artifact was rebuilt afterwards (gate-ready).

Docs: android/README (thin-surface row, § Device-free checks, build-command
fix, junk-blob cross-ref, deferred item 1 now packaging-only), tests/README
(verification + CI notes), AGENTS commands, README tools list; the playbook
verification reference gains the artifact-guard bullet.

## 2026-10-09 — Suspend→A IRQ abandonment: the phantom nest-depth is closed
## (state3 press repro)

Follows the hang-walk entry above. The press repro's `g_irq_nest_depth`
poison is fixed at the drive loop; the stack guard remains the second line
of defense.

**Evidence chain (deterministic, instrumented):**
- gdb transition log over the press (breakpoints on the depth increment, the
  iret site, the decrement sites): healthy frames = `IRQ++` (nd 0→1) →
  IRET-SIG → next entry at nd=0. At vbl=129 the IRQ fires from the DISPSTAT
  wait helper (`0x080033BA`, inside `wait_for_vblank`) and **no IRQ-mode
  exception return (BIOS 0x13C) ever follows** — the handler chain is cut
  short (its SWI-return cancels churn at `0x0814186E`, the `bl 0x814186c`
  return site). From vbl=140 every VBlank nests inside the phantom
  (nd=2; 45,690 entries logged at kill).
- Host backtrace at the first nested entry: the drive loop is dispatching
  mainline (`0x08141B74` halfword-copy loop + bx veneer → `ram_dispatch`
  into IWRAM `0x03007D64/72`).
- Cancel trace (vbl 126–145): the handler's return ledger falls back to the
  IRQ floor (depth 6 → floor 3) without the iret; the floor holds, but the
  drive loop then adopts whatever executes next — forever.

**Fix** (`tools/patches/irq-handler-abandon-close.patch`,
`gbarecomp/src/armv4t/runtime_arm.cpp`): `runtime_irq`'s drive loop detects
the abandonment — ledger at the IRQ floor while running outside the BIOS
(~0x40000 dispatches), or simply ≥4 VBlank boundaries inside the loop (no
legal GBA handler spans multiple frames) — and closes the IRQ as if the iret
had fired: completion signal, ledger restore, depth decrement. The entry
register snapshot is deliberately NOT restored on that path (the mainline has
advanced past the interrupted instant; clobbering its live registers would
corrupt the in-flight work).

**Validated:** the repro's transition log shows every IRQ entry at nd=1
(129/129), one `handler at depth 1 abandoned without an iret (4 vblanks …
— closing the IRQ` line, and the step that previously wedged for 240 s
completes in 0.02 s. `check.py --only hangrepro` → 1.2 s PASS (suite updated:
the press must close the phantom and advance past the old wedge). `cycle.py`
PASS, attract hash unchanged.

**Residual (open, next session):** after the close the flow advances ~4
frames into the suspend-return routine (`0x08145470+`) and ends at the
self-heal coverage boundary — Thumb code `0x08145484` is reached with
CPSR.T clear → ARM lookup → dispatch miss → bridge Undefined at
`0x08145488`. The proposal frag `[[extra_func]] 0x08145484 mode = "arm"` must
NOT be seeded (the code is Thumb; the T-bit loss is fallout of the original
handler abandonment). The true root remains open: *why* the SWI-return
cancel chain cuts the handler short (floor respected, handler still lost) —
the close makes that a correctness bug, not a hang.

**Playtest confirmation (same day, user):** closing the game after the
suspend flow behaved cleanly — no hang (the pre-fix failure mode), matching
the instrumented repro. The remaining boundary (coverage-corruption fallout
after the close) is unchanged and tracked above.

## 2026-10-09 — Split-loop gap roll-in: the vblank wait loop is one host
## frame now (issue #30 proposed fix 4)

**Root.** The crt0 frame gate at 0x08000418: the finder's linear walk stops
at the unconditional `b 0x0800042A` @0x08000420 (literal pool
[0x08000424,0x08000428) follows), so the beq target 0x08000428 — the 2-byte
back-edge `b 0x08000418` — sat beyond the walk extent and was rooted as its
own function (`vblank_wait_loop_cont`). Emission lowered the loop's two
edges as host C calls (`call gf_vblank_wait_loop_cont` on the beq-taken
path; `call gf_vblank_wait_loop` on the back-edge — objdump-verified
`call`/`ret` pairs), nesting ~2 host frames per spin iteration. Healthy
frames unwound every pass; a stalled flag (the suspend-flow era) nested to
284k frames / stack death.

**Fix (three small parts + a seed):**
- finder (`function_finder.cpp`): the mid-function alias phase gains a *gap
  roll-in* — an explicit `resume` candidate beyond every host's clamped
  extent rolls into a host that directly branches to it when it lies before
  the next real function start; the host extent grows over the block (and
  the dead pool bytes between the old end and it).
- emitter (`emit_function.cpp`): builds the in-body goto-target set
  (backward targets ∪ alias entries) for the codegen.
- codegen (nested `external/arm-recomp-core`): a direct branch inside the
  current function's extent whose target is labelled lowers to
  `goto L_<addr>` (was backward-only; forward labelled targets fell to C
  calls).
- config: `[[extra_func]] 0x08000428 resume = true` (game.toml, with the
  disarm.py evidence note) — the gating that keeps gap roll-in opt-in.

**Verified:** dispatch entry `{0x08000428u, 1u, 1u, gf_vblank_wait_loop}`
(resume alias); `vblank_wait_loop_cont` gone (corpus 55103 → 55102); the
built loop body contains NO generated-function call except the once-per-pass
exit block (`gf_tfunc_0800042A`) — the per-iteration call pair is gone;
attract hash byte-identical; `check.py` ALL PASS (11/11; route replays
FULLY_STATIC); `hangrepro` 1.2 s PASS. The IRQ-abandonment close (d152a46)
stays as the second line of defense.

**Audit note:** the only other `_cont` split
(`worldmap_camera_ease_cont`, 0x08038C3E) is a different shape — a
clamp-truncated block chain whose edges lower via block dispatch, no host
framing — no action needed. The `vblank_wait_loop_cont` symbol name is kept
in the TSV for trace readability (the address is still a dispatchable
resume entry).

**Patches:** consolidated exports are now TWO — `gbarecomp-local.patch`
(nested gitlink excluded: GNU patch cannot apply a submodule-commit hunk)
plus the nested repo's first local patch `arm-recomp-core-local.patch`;
`check.py`'s `patches` check routes by filename prefix and replays both
against their pins.

**Still open:** the true root of the handler loss (why the SWI-return cancel
chain cuts the handler short) — unchanged; the press repro still ends at
the coverage boundary.

## 2026-10-09 — True root of the handler loss: ring-proven corruption chain

Full instruction-ring capture of the press repro, dumped at the exact miss
(`fp_save` via gdb at `runtime_dispatch_miss`; 8.4M records; recipe below).
The chain, in execution order:

1. **vbl129.** The IRQ interrupts mainline inside the DISPSTAT wait helper
   (`0x080033BA`, `wait_for_vblank`). The handler runs; in its tail the
   suspend-save transition routine (`0x8145486`) calls SWI 0x0B (CpuFastSet,
   via the veneer at `0x814186C: svc #0xb; bx lr`) to copy 0x40 bytes of
   saved context from the stack area (`0x3007E94`) to EWRAM.
2. **The SWI's exception return (BIOS epilogue at `0x188`, SVC mode)
   resumes at `0x080033BA` — the IRQ-interrupted mainline PC — instead of
   the veneer continuation `0x814186E`.** The ring shows the fetch sequence
   `0x188 (SVC) → 0x080033BA (System)`, `LR=0x814548B` untouched. This is
   the "handler cut short": the SWI return carried the IRQ's saved context,
   so the save routine was abandoned mid-flight and the interrupted helper
   resumed.
3. **The resumed helper's `pop {r0}; bx r0` (`0x8033C2`) reads a zeroed
   stack slot: `[0x3007E90] = 0x0`** (`r0 := 0`, `SP: 0x3007E90→0x3007E94`).
   `bx r0` → **PC = 0** — the helper's push/pop pairing belongs to the
   pre-IRQ invocation; the slot was clobbered during the phantom-era stack
   churn (the save flow had just copied the region above it).
4. **PC=0 executes the BIOS reset vector**: `0x00 → 0x68 → 0x84 → 0x88` —
   the BIOS init path — which switches to ARM: `cpsr=0x…DF (T=0)` at
   `0x88`. The walk then drifts through BIOS ARM exception code
   (`0x1C..0x64`, stack dancing across the banked-SP tops
   `0x3007FF0/0x3007FE8/0x3007FE0`).
5. **BIOS `0x64` = `subs pc, lr, #4`** (the ARM exception-return
   instruction) executes in that garbage context with `LR=0x814548B`; the
   engine lowers it as an exception return, computing
   `new_pc = (LR − 4) & ~3 = 0x8145484` **in ARM mode** → dispatch miss
   (`0x8145484` is Thumb-only) → self-heal bridge interprets Thumb bytes as
   ARM → Undefined → abort. (The 0x…484 boundary death, explained end to
   end.)

**Root layers, from the bottom:**
- **R1 (engine, open — the real root):** an SWI executed inside a driven IRQ
  handler returned to the IRQ-interrupted PC, not to its own continuation.
  The BIOS epilogue pops its return from the guest stacks; the value was the
  IRQ's saved context (written by the IRQ entry or by the save flow's
  context copy). Candidate fix: in `runtime_swi`/exception-return handling,
  validate an SWI's SVC-context return against the continuation the engine
  recorded at SWI entry (`return_address+4`) when `g_irq_nest_depth > 0`,
  and keep the recorded value on mismatch (loud log).
- **R2 (guest-stack corruption):** `[0x3007E90]=0` — the interrupted
  helper's saved LR slot clobbered during the phantom era (the unbalanced
  handler/SWI churn on the shared System stack).
- **R3 (our close, secondary, fixable now):** the abandon-close can fire
  mid-cancel-flight (observed: cancels continued after the close dropped
  `g_call_return_floor` to 0, popping below the interrupted floor). The
  close should defer while a cancel/return cascade is in flight.

**Recipe (repeatable):** steppable `--tcp` + `savestate_load game.state3`
+ A press; launch with `GBARECOMP_INSN_TRACE=1`; gdb:
`break runtime_dispatch_miss`, condition `entry_pc==0x08145484`, then
`call runtime_fp_save_file("/tmp/fp.bin")` at the stop. Parse records
`<Q18I` 80 B: cycles, pc, cpsr, r0..r12, sp(=16), lr(=17).

**Playtest re-confirmation (same day):** loading `game.state3` alone (no A
press) reproduces the close and then the boundary abort (SIGABRT at the
bridge) — the poisoned flow re-executes from the restored context; expect
this endpoint until the R1 containment fix lands.

**Detail correction (disarm-verified):** the miss target `0x8145484` is not
a call — it is the *second* instruction of the CpuFastSet argument setup in
`post_suspend_flow` (`0x8145482 mov r0,sp; 0x8145484 adds r1,r5,#0;
0x8145486 bl swi0b_thunk`). The corrupted BIOS `subs pc, lr, #4` computed
`new_pc = (LR−4)&~3 = 0x814548B−4 → 0x8145484`, i.e. the exception return
landed two bytes inside the setup, and ARM-mode decoding of `adds r1,r5,#0`
is the "Undefined at 0x8145488" abort. The earlier "interior resume seed"
reading of this address was a mislabel of the same mechanism.

## 2026-10-09 — Fix: coherent close (delayed-iret resume) for abandoned IRQs — SUPERSEDED (same day)

> The restore described below rewound the guest to the interrupted mainline;
> the ring then proved the state at close time is the *live flow's own*
> (coherent) and must be left alone. See "flow-continuation resume" below.

**Action.** `runtime_irq` (runtime_arm.cpp) now performs a *full delayed-iret
restore* when a handler is closed without a legal iret:

- volatile regs r0–r3/r12 restored in BOTH close modes (the old
  skip-on-abandon rule is reversed — its premise was falsified, below);
- abandon-only additionally: banked SP/LR captured **at entry** (the
  interrupted snapshot; live bank_out/in calls during the phantom era
  otherwise overwrite the banks), call-ledger `g_call_return_depth` +
  `g_call_return_floor` restored to the pre-IRQ snapshot,
  mode/CPSR restored via `bank_out`/`bank_in`, and `R15 = return_address`
  — the exact target the BIOS wrapper's `subs pc, lr, #4` would restore;
- both close log lines now carry `(delayed-iret resume pc=… sp=…)`.

**Why.** The ring-proven chain (previous entry): the resumed flow IS the
interrupted instant (the interrupted block re-runs on the next main-loop
step) — the earlier "mainline has advanced past the interruption" theory was
wrong. The phantom era's scratch use of the System stack had zeroed the
interrupted helper's return slot (`[0x3007E90]=0`); with SP left at the
phantom's value, the resumed helper popped 0 → PC=0 → BIOS reset vector →
T=0 ARM walk → BIOS `subs pc,lr,#4` → `0x8145484` dispatch in ARM mode →
bridge abort. Restoring SP+ledger+mode+pc removes exactly this class
instead of letting the lookup-clamped guard merely bound it.

**Result (2026-10-09).** `hangrepro`: **survives the press (+40 steps,
guard unwinds=0, irq closes=1)** — previously SIGSEGV at +26, then the
`0x8145484` boundary abort; zero `interpreter Undefined` lines. `cycle.py`
PASS (attract byte-identical). `tools/patches/gbarecomp-local.patch` +
`irq-handler-abandon-close.patch` re-exported (gitlink excluded — the
export must use `-- . ':(exclude)external/arm-recomp-core'`); patches replay
431-file tree matches. Full `check.py`: **ALL PASS (11/11)** — hangrepro,
attract byte-identical, ws_smoke, route_G/route_K FULLY_STATIC, all units.

**Note.** Entry-snapshot SP (0x3007E78 in the repro) reflects the stack at
IRQ delivery; the ring's previously observed resume SP (0x3007E90) was the
phantom's. The harness confirms the resumed mainline is coherent.

## 2026-10-09 — Fix: flow-continuation resume (supersedes the coherent close)

**What the black screen was.** The coherent close restored the *interrupted*
snapshot at abandon time. But the state at close time is not the interrupted
context: the flow that kept running under the drive is the guest's own (the
suspend-save tail), and its registers, stack, banks and call ledger are
already coherent. Rewinding them abandoned the save: the flow idled forever
in the main-loop frame gate with the screen blanked (user-visible: black
screen after A).

**The real remaining break.** After `runtime_irq` returns, the interrupted
instruction's block resumes and its per-instruction R15 installs trample the
exception-return target the guest had just computed (`0x814186E` — the save
flow's continuation after its CpuFastSet SWI). The guest therefore never
executed its own continuation; instead the trampled flow ran the
pop-to-garbage path (pre-coherent: accidental reset-ish walk → bridge abort
at `0x8145484`).

**The fix (runtime_arm.cpp).** On an abandon close: do not touch the guest
state at all; capture `g_cpu.R[15]` (the live flow's genuine next pc) and
one-shot redirect the *next* `runtime_dispatch` there
(`g_abandon_resume_pc`), defeating the trample. Log line:
`closing the IRQ (flow-continuation resume pc=0x…)`.

**Verified end-to-end (2026-10-09).** `game.state3` + A press:
close → the save flow's tail executes (pc 0x08141944 observed) → the save
UI / black phase → **the game's suspend-save reboot: cloud backdrop → "It
was a day like any other…"** — the oracle's `e2_afterreset` screen
(`logs/savehang/oracle/replay/f17116.png` shows the oracle later playable);
the flow then animates continuously (26 distinct screens over 700 steps,
graceful TCP quit, FULLY_STATIC). Load-without-press (idle) unchanged; no
close fires. Gates: cycle PASS (attract byte-identical); `check.py` 11/11;
patches re-exported (`gbarecomp-local.patch`, `irq-handler-abandon-close.patch`).

**Note for the record.** The two fixes between them explain the whole
symptom family: (1) the abandon close stops the never-returning handler
from poisoning `g_irq_nest_depth`; (2) the flow-continuation resume makes
the *guest's own* flow survive the close. The earlier "coherent close" is
superseded — its snapshot restore was the wrong direction.

## 2026-10-09 — Desktop TCP acceptance passes (free-run via the debug port)

**Tool:** `tools/desktop_accept.py` — two modes, one scorer: a savestate
load, a real-time 3 s wait, an A press, then a scored observation window
(press seen, frames advance, >=12 distinct screens, no abort/Undefined,
process alive; the close route and its resume pc are reported).
- `--mode tcp`: headless free-run `--tcp` — the run is driven AND observed
  entirely over the debug port (`savestate_load`, `continue`,
  `set_keyinput`, `run_status`, `screenshot`). This is the primary
  acceptance for the suspend-save press on a continuous (desktop-class)
  run: **three consecutive PASSes** (close route 24k frames/35 screens
  and 19.5k/26; clean route 24k/37; zero stalls, zero aborts).
- `--mode window`: `tools/play.sh` + `--tcp-observe` + ydotool — kept for
  hand-parity; the present-paced windowed loop still hits a residual
  stall in some close-route runs (see below).

**Engine additions rolled in with the acceptance:**
- The abandon close restores the **IRQ-enable state** captured at IRQ
  entry (IE/IME). (Corrected reading, later entry: the gate the stalled
  flow waits at is the crt0 frame gate on `[0x03000E10]`, which is the
  save flow's own one-time completion marker (writes 0x0100), *not* an
  IRQ-ticked flag — IF stays 0 throughout the healthy flow. The restore
  is kept as coherence hygiene; observed IE/IME 0 -> 0x2003/1.)
- The resume intercept logs its pair (`abandon-resume intercept
  want=… got=…`) so the mechanism is visible in every run.

**Residual (open, documented):** the *windowed* present-loop path can
still stall after a close-route press (no `runtime_dispatch` occurs in
that pacing before the flow parks in the frame-tick wait, so the resume
intercept cannot fire; IE-restore alone does not move it). Steppable and
free-run TCP paths are green; windowed pacing is queued for the next
session with this note and the capture recipe (watchdog ring + observe
reads).

### 2026-10-09 (late) — Windowed close-route fixed: the full chain

The present-paced windowed path (`play.sh` + `--tcp-observe`) now passes
the acceptance too. Each mechanism, all visible in the run log:

1. **ISR vector guard** — the phantom excursion trampled IWRAM
   `[0x03007FFC]` (observed wild 0x080000FC; healthy 0x03000F10). The
   abandon close snapshots it at IRQ entry and restores it
   (`restore ISR vector at close: 0x080000FC->0x03000F10`).
2. **IRQ-enable restore** — IE/IME 0 -> entry values (`0x2003`/`1`).
3. **Mode-coherent resume** — `runtime_dispatch` derives the execution
   mode from `CPSR.T`, not the pc bit; the phantom's ARM excursion left T
   clear, so the redirect to `0x814186E` resolved as an **ARM** dispatch
   -> table miss -> self-heal bridge -> interpreter `Undefined` at
   `0x8141906` -> deliberate abort (also the source of the
   `mode="arm"` self-heal frag for `0x814186E` — **do not seed**). The
   intercept now forces `CPSR.T` from the close-time snapshot:
   `abandon-resume intercept want=0x0814186E got=0x080033B6 (thumb=1)`.
4. **One-unwind while a resume is pending** — present-in-place runners
   never unwind on vblank by design, so a wedged post-close flow reached
   no `runtime_dispatch` at all and the intercept could not act (the
   long-standing "no-dispatch stall" variant: guest pc churning through
   the 0x080033xx data region, frames presenting, screen static).
   `runtime_should_yield` now returns true **once** while
   `g_abandon_resume_pc` is armed (`g_irq_nest_depth == 0`): the runner
   redispatches, and the intercept fires. One unwind, one dispatch —
   frame-boundary resume misses are not reintroduced (the redirect
   happens at a dispatch boundary, not an interior pc).

**Evidence:** windowed acceptance (`desktop_accept.py --mode window`)
**PASS** — 39 distinct screens / 4,883 frames, close route, process
alive; the TCP free-run acceptance (`--mode tcp`) 3x PASS (24k frames/35
screens close route; 24k/37 clean route; 19.5k/26); `hangrepro` PASS;
full gate ALL PASS with the new opt-in `desktop-accept` suite
(`check.py --only desktop-accept`; skips without state3/playtest.sav).

**Residual (documented, not fixed):** a rare windowed-path variant derails
the press flow into a corrupted computed jump that lands on BIOS `0x0FF8`
(disarm-verified: a thumb compare-loop, NOT an "ARM routine" as first
noted), triggering the self-heal bridge; the bridge then ran away and hit
the interpreter runaway guard — `SELF-HEAL bridge for 0x00000FF8 exceeded
200000000 instructions without returning to stop_pc=0x08094FCC … Aborting
rather than spinning silently` (acceptance run 2026-10-09). Evidence it is
press-path, not idle: a 60 s no-press idle control on the same state is
clean (zero self-heal; frames advance; screens transition normally), and
the healthy press flows (steppable + tcp free-run, many runs) never reach
`0x0FF8`. The dispatch resolves thumb correctly, so this is NOT the
`0x814186E` mode-coherence issue — it is the same family as the phantom
resumption (a corrupted pc at an indirect transfer). Next step when
prioritized: sweep the steppable press phase for a deterministic repro of
the abort, then ring the transfer that produces `0x0FF8`.

**2026-10-09 evening — the windowed press-path derail: root chain found.**
The rare windowed failure (2/16 in a focused hunt; `SELF-HEAL bridge` abort)
is the game's suspend-save **soft-reset flow**, only reachable in runs where
the post-save completion path executes within the observation window:

1. Save completes → FFTA invokes the BIOS soft reset. The BIOS copies its
   0x200-byte context block (0xB56-0xB9C region) and jumps to the reset
   vector; the boot runs (0x68-0x88) and reaches the **cart-boot trampoline**
   (0x1C-0x64): `stm {r12,lr}` + `mrs spsr/cpsr` + `stm {spsr,cpsr}` at
   0x20-0x2C, boot checks, then 0x54-0x64 restores the pairs and executes
   `msr spsr_cf, r12` + `subs pc, lr, #4` to resume at LR-4.
2. The live LR at that point = `0x08000499` (thumb-tagged; the resume point
   in the crt0 area). Hardware resumes **thumb at 0x498**.
3. Our engine resumes **ARM at 0x494** (2 bytes early, mid-instruction):
   dispatch miss 0x08000494 (recorded `mode="arm"`) → self-heal bridge
   interprets ARM garbage → interpreter Undefined at 0x4EC → loud abort.
   The sibling 0x0FF8 occurrence (thumb-into-ARM) is the same family.

**Pinpointed with a 29-record bridge-entry ring dump** (the only moment the
pre-miss ring still holds generated-code context — the bridge's own
interpreted records overwrite it within ~1 s; new env-gated instrumentation
`GBARECOMP_BRIDGE_ENTRY_FP`/`GBARECOMP_BRIDGE_ABORT_FP`, plus an
unconditional one-line `bridge entry pc/thumb/stop/lr/sp/cpsr` log):
the trampoline executed in **System mode** (the BIOS SWI dispatcher
deliberately switches to System at 0x158-0x160 before calling services —
verified correct vs. the recompiled BIOS source); in that mode the S-bit PC
write `subs pc, lr, #4` performs no SPSR restore in our engine (and in the
reference interpreter — "no SPSR in User/System — exception return is
undefined", external/arm-recomp-core profiles/armv4t_gba/interpreter.cpp),
so `T` stayed 0 and the dispatch went ARM. Hardware behaves as if the
System-mode SPSR roundtrip (`mrs spsr`/`msr spsr` + the return) preserves
the caller's T=1 — which is exactly the published ARM7TDMI System-mode SPSR
behavior the BIOS's boot trampoline relies on.

**Evidence**: `logs/savehang/bridge_entry_fp.bin` (29 records: load → BIOS
copy → reset → boot → trampoline → miss), `GBARECOMP_SWI_TRACE` trace
(banking `0x3F -> 0x93`, `SPSR_svc = 0x3F` — 505/505 LLE, 0 HLE), mode
histogram (`svc` 84 / `irq` 5,110 / `sys` 8,383,414 — services in System is
BIOS-correct), the dispatcher decode (`0x150-0x16C`).

**Open**: arbitrate the System-mode SPSR semantics against the oracle
(mGBA-backed, `gbarecomp/oracle/`): if mGBA restores T here (it must, for
FFTA to save-and-reboot on it), the fix is to align our ARM7TDMI SPSR model
for User/System-mode `mrs/msr spsr` + S-bit PC writes (framework-level,
touches the bank machinery shared with `banked_spsr[ARM_BANK_USER]`), and
this belongs in the upstream conversation (the issue-30 thread's SWI-return
discussion is exactly this area). Until then the derail is reachable
whenever the suspend-save flow runs to completion in-window.

**2026-10-09 late — derail mechanism pinned to a stack-slot slip (evidence).**
The three captured derail transfers all share the same constant context —
`lr=0x08000499` (the savestate's LR), `sp≈0x03007EB8-0x7EC0`, `stop=0x08094FCC`
(the save-flow's ledger frame) — and read IWRAM of the loaded state shows the
miss targets ARE stack words: `[0x03007EBC]=0x080000F0` verbatim (the
`pc=0x080000F0` catch), `[0x03007EB4]=0x08000499`, `[0x03007EAC]=0x0800050B`
(return addrs), `[0x03007EB0]=0x03000FD8`. So the derail = the resumed
save-completion flow popping an ADJACENT stack slot instead of its return
address when the load-time IRQ race perturbs the flow — the popped word
becomes pc → miss (0xF0 IS not a static entry) → bridge → abort (or the
pc=0 walk through the reset vector and the BIOS 0x1C trampoline, whose
System-mode SPSR roundtrip is mGBA-validated correct — see
`reference/gba-bios-boot-and-spsr.md`). The residual (≈12 % of windowed
runs; the other ~88 % are rescued by the abandon-close + intercept) is the
same phantom IRQ/SWI-return interplay issue-30 flagged as "the SWI-return
cancel cascade crosses the IRQ floor boundary" — upstream machinery
territory. New instrumentation: `GBARECOMP_BREAK_FP` (ring dump at a
`set_break_pc` park; works on `--tcp-observe`, which lacks fp_save) —
`logs/savehang/pc0_hunt.py` is the breakpoint hunter.

## 2026-10-09 — Fix: SWI-return continuation ledger (issue #30 R1 containment)

**Root recap.** The phantom-era chain (ring-proven, above): an SWI executed inside
a driven IRQ handler returned to the IRQ-interrupted PC (`BIOS 0x188 ->
0x080033BA`) instead of its own recorded continuation (`0x814186E`, the
`svc; bx lr` veneer's continuation). On hardware this cannot happen — LR_svc is
a banked register the guest cannot touch; the recomp's shared `R[14]` slot was
clobbered by the drive-loop's stack churn before the BIOS epilogue consumed it.

**Fix** (`tools/patches/swi-return-ledger.patch`,
`gbarecomp/src/armv4t/runtime_arm.cpp`):
- **Ledger.** A stack-ordered continuation ledger: `runtime_swi`'s LLE entry
  pushes `return_address` (the SWI site + instruction width — what a legal
  epilogue returns to); every SVC-mode exception return pops + validates.
- **Validation points.** `runtime_exception_return` (generated epilogues) when
  `old_mode == 0x13`, and `runtime_note_interpreted_exception_return` (bridged /
  force-interp epilogues, called by `runtime_arm_default_aborts.cpp` right after
  the interpreter's internal SPSR restore with `g_cpu` synced) — on mismatch the
  recorded continuation is kept (loud log line
  `SWI-return ledger override: SVC return wants pc=… but the SWI at … recorded
  continuation …`). `R[14]` is deliberately NOT written: the legal post-return
  LR comes from `bank_in`, and the continuation can be a `bx lr` site — writing
  it into `R[14]` would self-loop that branch.
- **Lifecycle.** The ledger is host bookkeeping, not emulated state: cleared at
  every machine reset / savestate-load origin (`runtime_fp_reset`, which both
  `reset_recomp_cpu` and `do_savestate_load` call). SoftReset (SWI 00) legally
  never returns — its stale entry is dropped by the clear. No new serialized
  state.
- **BIOS epilogue shape pinned** (disarm on `gba_bios.bin`): the SWI dispatcher
  at `0x140` pushes `{fp,ip,lr}`, switches to System mode for the service
  (`0x160 msr cpsr_fc`), restores SVC (`0x174-0x178`), then
  `0x184 pop {fp,ip,lr}` / `0x188 movs pc, lr` — the epilogue is an
  SVC-mode `movs pc, lr`, LR_svc sourced from the SVC bank. On hardware the
  popped LR is always the entry continuation (System-mode services cannot touch
  the SVC bank) — the ledger invariant is architecturally sound.

**Result (2026-10-09).** Deterministic state3+A repro: zero ledger overrides —
the save-routine SWIs (`0x814186A`/`0x814186E`, `GBARECOMP_SWI_TRACE`) all
return cleanly at their recorded continuations today; the ledger is dormant
containment on this path (the abandon-close + intercept still handle the
phantom's fallout earlier). `cycle.py` PASS (attract byte-identical);
full `check.py` **ALL PASS (13/13)** — hangrepro +40 steps alive, desktop-accept
TCP free-run PASS (close route), routes G/K FULLY_STATIC.

**Harness fixes rolled in with this session:**
- `tools/hangrepro.py`: default port moved to 19880 — under `check.py --jobs 8`
  the concurrent `hangrepro` (19878) and `desktop-accept` (19878) raced the bind
  and both failed. Serially each passed; with distinct ports the full gate
  passes in parallel.
- `tools/pc0_hunt.py` + `tools/derail_loop.sh`: hardcoded absolute home-directory
  repo paths removed (`pathlib` / `dirname`) — the `unit-py` repo-hygiene gate
  (absolute home paths) went red on them.

**Upstream.** This is the R1 containment for issue #30's suspected-root family
(ledger-recorded SWI continuation validated at SVC-return) — small,
self-contained, no guest-visible behavior on a legal return. The
abandon-close (its consumer) stays FFTA-conditional per the audit
(`tools/patches/README.md` § Upstream priority).

## 2026-10-09 — CI tier-1 hardening: pristine-checkout conditions (3 fixes)

Asking "will .github/workflows/ci.yml break?" surfaced three breaks — all
latent, all only visible on a **fresh checkout with pristine submodules at the
pin** (the runner's condition; locally the submodule dev trees carry the
uncommitted framework edits, so every local run masked them). Found by a
faithful fresh-clone simulation (`git clone` + pristine-at-pin submodule
archives + CI's exact suites), not by reading:

1. **Per-feature patches were dev-based, not pin-based** (`e006928`).
   `check.py` `patches` validates each file against whatever tree the runner
   sees: locally the patched dev tree (reverse), on CI the pristine pin
   (forward). The regenerated `irq-handler-abandon-close.patch` +
   `swi-return-ledger.patch` carried interleaved context (ledger/trace lines)
   only present on my dev tree → INVALID on CI. Rebuilt both pin-based; the
   `swi_ledger_push` call moved from the interleaved post-bank block to just
   before `runtime_dispatch(0x08)` (pin-stable context, semantics unchanged:
   push pairs with this SWI's SVC entry).
2. **`check_patches`' replay byte-compare false-reds on CI** (`ecb5540`).
   The replay (pin+consolidated → byte-match the working tree) is a
   local-dev-tree guarantee; a pristine checkout's tree IS the pin, so every
   patched file "differs". The checker now skips the compare when the
   submodule is unmodified (`status --porcelain -uno` empty) — the clean
   apply alone still proves patch↔pin fidelity there.
3. **`unit-cpp` did not compile on a pristine submodule** (`4623e9c`).
   `test_host_stack_guard.cpp` targets the guard APIs from the (local-only)
   `host-stack-guard-desktop.patch` work; the pinned header doesn't declare
   them → 11 compile errors on CI. CMakeLists now probes the pinned
   `mobile_platform.h` for `host_stack_guard_arm_current` and defines
   `HOST_STACK_GUARD_API=1` only where present; the test compiles to a skip
   line otherwise (prints `APIs unavailable (pristine submodule); skipped`).

**Verification matrix (2026-10-09):**

| Condition | unit-cpp | unit-py | patches | android-static |
|---|---|---|---|---|
| Fresh clone, pristine-at-pin submodules (CI) | PASS (guard skip) | PASS | PASS (10× forward-ok + apply-ok) | PASS |
| Local dev tree (patched submodule) | PASS (full guard test) | PASS | PASS (431-file replay match) | PASS |
| Local full gate (all 13 suites) | ALL PASS 13/13 | — | — | — |

**Method note:** the local runs cannot see pristine conditions (the dev trees
carry the edits); the fresh-clone simulation with pristine-at-pin archives is
the only faithful CI proxy. Keep using it after any patch/test-affecting change.

## 2026-10-09 — Cheap test additions (session's break classes, now guarded)

Three additions from the "quick but meaningful" ask — each maps to a failure
class that actually bit this session; total added runtime < 1 s:

1. **`patches` pin-forward validation** (tools/check.py): reverse-ok on the
   local dev tree is NOT the CI condition — a fresh checkout validates each
   per-feature file forward against the pristine pin. A dev-based export
   goes INVALID there (today's tier-1 break). The check now also applies
   every per-feature patch to a `git archive HEAD` tree and fails on
   mismatch: `reverse-ok (applied), pin-forward-ok`. Sub-second, pure git.
2. **TSV guards** (tests/python/test_tools.py, unit-py): `ffta_symbols.tsv`
   (3 fields, hex address, arm|thumb, C identifier) +
   `ffta_data_symbols.tsv` (4 fields, region, hex size, C identifier),
   no duplicate names across both, and the patches README table must list
   exactly the present `*.patch` files. Malformed lines break regen or
   silently mislabel emitted units — the sweep catches them pre-regen
   (negative-tested: a planted bad line fails the suite).
3. **BIOS byte-pin** (test_tools.py): sha1 of `gba_bios.bin` +
   the exact words at every contract point our engine cites (vectors, IRQ
   wrapper epilogue `E8BD500F`/`E25EF004`, SWI dispatcher service-switch
   `E129F00B` + epilogue `E8BD5800`/`E1B0F00E`). This morning's
   0x138-vs-0x184 citation drift in my own comments is exactly what a
   replaced BIOS would do silently. LOCAL-ONLY: the dump is BIOS-derived and
   gitignored by design (`bios/*.bin`), so the test skips on any checkout
   without it — CI included; it guards the local tree, where the engine edits
   cite the contract points.

unit-py runs the file wholesale — no registry change needed. Suites:
unit-py 0.7s, patches 0.6s (was 0.2s); full gate ALL PASS 13/13.

## 2026-10-09 — src/ audit: LZSS guard extracted + tested, setenv guarded, boundary tests

Audited all of src/ (ffta_ram_dispatch.h, main.cpp, game_launcher_boot.*):

- **`ffta_lzss_guard.h` (new):** the LZSS entry guard lived inside an
  anonymous namespace in main.cpp — correct at runtime, but untestable (not
  linkable from the unit binary). Extracted verbatim to
  `src/ffta_lzss_guard.h`; main.cpp registers `ffta::lzss_entry_guard`.
  Unit tests now cover: plausible length → declined (body runs, PC
  untouched), implausible → handled (PC ← LR, thumb bit stripped), and the
  exact 0x100000/0x100001 boundary.
- **`main.cpp`:** the Android-only `setenv("GBARECOMP_MISS_FRAG", ...)` was
  guarded by flow (`on_mobile` is only ever true on Android) but compiled
  on every target — MSVC's libc has no `setenv`. Now `#if defined(__ANDROID__)`
  inside the `on_mobile` block (same code path, explicitly compiled out of
  the desktop/Windows targets).
- **`test_ram_dispatch.cpp`:** added the missing `case2-2early` boundary
  tests — a two-byte-early entry that does NOT byte-match must fall through,
  and one that matches while carrying the loop sentinel (r2 == -1) must pass
  through (never run the body from the top).
- No other findings: `ram_dispatch`'s ordering and guards are correct and
  already evidenced in comments; `game_launcher_boot.*` is a trivial seam;
  `raise_stack_limit()` correctly no-ops where RLIMIT_STACK is absent.

Gates: unit tests PASS (0 failures, new LZSS/boundary lines verified);
full check.py ALL PASS 13/13.

## 2026-10-09 — Citation correction: the BIOS SWI epilogue is 0x184/0x188, not 0x138/0x13C

The ledger's comments and the patches README cited the SWI epilogue as
`0x138 pop / 0x13C subs pc,lr,#4`. Disassembly of `gba_bios.bin` proves those
are the **IRQ wrapper's** return (`BIOS 0x130-0x13C`); the SWI dispatcher
epilogue is `0x184 pop {fp,ip,lr}` / `0x188 movs pc,lr`, with the service
running in System mode (`0x160 msr cpsr_fc`) in between. The
`swi-return-ledger` comments + both exported patch files were corrected
(`e71a86c`); the BIOS byte-pin test now guards the *correct* words
(`E129F00B` at 0x160, `E3A0C0D3` at 0x174, `E8BD5800` at 0x184,
`E1B0F00E` at 0x188) so the citation cannot drift silently again.

## 2026-10-09 — Symbol: swi0c_thunk_tail (0x0814186A)

Sweep of the session's new text for raw-hex citations found one TSV gap:
`0x0814186A` — the SWI 0x0C veneer's `bx lr` continuation (disarm:
`0814186a: 7047 bx lr`) — appeared live in the ledger session's SWI trace
(`swi_imm=0xC ret=0x0814186A`, the save flow's context copy) and is exactly
what the ledger guards, but had no entry while its 0x0B sibling
(`swi0b_thunk_tail`, 0x0814186E) did. Added name-only with the evidence
note (`9d1d044`); verified the seed flows through (`{0x0814186Au, 1u, 0u,
gf_swi0c_thunk_tail}` in the dispatch table), `cycle.py` PASS (attract
byte-identical), full gate ALL PASS 13/13.

## 2026-10-09 — Patch re-audit (late): all 10 necessary, ledger promoted, upstream drift

Re-grounded every patch against the pin, the session's fresh evidence, and
upstream drift (`ecc9c55` 2026-10-03 → ~30 commits since: the web/WASM wave
PR #16, PR #29 opt-in shared-RAM DMA HLE, PR #31 scanline-HLE default).
Verdict: **no patch is unnecessary** — the two `runtime_arm.cpp` patches are
complementary layers over the same ring-proven chain (ledger = containment,
abandon-close = recovery), not duplicates; hangrepro exercises both.
Re-ranked in `tools/patches/README.md` (`912f1a3`): `swi-return-ledger`
promoted above `irq-handler-abandon-close` (the ledger is the principled
fix; the close mops up what it cannot see — an iret lost before any SWI).
**Upstream drift finding:** verified none of our issues are subsumed
upstream (PR #29's `gba_io` rework does not touch `g_mmio_split` recording;
`9be5351` is WASM reporting; `mod_runtime.cpp` untouched), but the same
files moved — so **a pin bump is a deliberate milestone**: rebase/re-export
every patch, re-run the fresh-clone CI simulation, re-verify hangrepro +
desktop-accept on the new pin before committing it.

Coverage snapshot re-measured the same day via
`tools/coverage_report.py` (not inferred): walker **55,102/56,332**,
pool **55,102/55,514** — both denominators moved with the split-loop gap
roll-in (`vblank_wait_loop_cont` merged into its host as a resume alias);
corpus 55,102; executed path 100% FULLY_STATIC. `tests/README.md` snapshot
re-dated and re-measured to match (`ed189bd`).

## 2026-10-09 — tools: disarm.py polish (the canonical evidence tool)

`tools/disarm.py` — cited by AGENTS.md as *the* verification tool ("run
`tools/disarm.py` and cite the address") — still called itself
`tools/dis.py` in its usage line, carried dead code (an
`insn.group(capstone.x86.X86_GRP_JUMP) if False else False` branch that
could never run), and silently accepted nonsense ranges (`end <= start`,
short reads past the ROM end). Fixed (`1a9c669`): usage matches the real
path, both nonsense ranges now fail loudly, examples added. Output for
valid invocations verified byte-identical against the ROM (phase 0
crt0/veneer bytes reproduce exactly).

## 2026-10-09 (late) — Device re-verification: current engine ON the phone + scriptable press acceptance

Connected device: Xiaomi M2102K1AC (Poco X3 Pro), Android 14/API 34,
arm64. Fresh build first — the last APK (08:39) predated every 2026-10-09
engine fix (ledger 21:39, abandon-close/roll-in earlier); **rebuild before
any device claim**.

1. **Fresh APK** (1m40s, arm64-v8a, private ROM embed): content guard 8/8.
   Note: 64.2 MiB vs the 08:39 build's 35.5 MiB — heavier corpus, not the
   junk-blob class (guard's oversize check passed; libmain.so exempt by
   design).
2. **`tools/validate_android.sh` GATE PASSED 5/5** on the fresh build:
   process alive (pid 17250), GbaGameActivity resumed, log reports
   `cpu_backend=static-recompiled`, zero SELF-HEAL lines, crash buffer
   clean. The stale 981-byte miss frag on-device was **yesterday's
   21:20 session** (mtime), not this run — and today's run wrote no new
   misses.
3. **The stale frag audited and discarded (no seed):** its single proposal
   was `0x03005710 arm`, a PC inside an unmapped IWRAM island. Live bytes
   via observe `read_iwram`: `80 0d 00 00 | 30 37 50 ef …` — a ROM-pointer
   table (disarm of the pointed-to 0x08A5BFD2 region: a repeating pointer
   array, `35 30 84 35 34 84 …` sequential pointers), **not ARM code**.
   A dispatch into data, bridged ×1 by the interpreter — honest behavior;
   no corpus entry warranted (ground rule 4: no seed without code
   evidence). Coverage JSON absent on device = clean-run absence, fine.
4. **`tools/android_press_test.py` (new): the scriptable press acceptance.**
   The manual protocol's A-press was thumb-on-glass only; the observe TCP
   carries everything needed (`set_keyinput` press injection, `run_status`
   frames via `ppu.frame_count()`, queued `savestate_load`, screenshot).
   The tool: push+stage `game.state3` → load over observe → assert frames
   advance → press A (bit0 low 0.25 s) → assert post-press advancement →
   scan the pulled app log for ledger/self-heal/guard anomalies → crash
   buffer. Two tool bugs found by first run (counters unwired on the
   windowed-observe context — run_status carries frames; savestate path
   resolves from the chdir'd `files/` cwd, so `saves/` not `files/saves/`).

   **PASS on device:** load (frame 4515) → pre-press 4574→4694 → press →
   post-press 4694→4832, **one legal abandon-close** (the suspend→A chain,
   closed coherently — the exact flow that pre-fix SIGSEGV'd the desktop),
   zero anomalies, crash clean. The historical worst bug class now has a
   scriptable, evidence-producing device acceptance.


## 2026-10-09 (late) — Device lifecycle gate + touch-realism findings

**1. `tools/android_lifecycle_test.py` (new): the OS suspend/kill/relaunch
lifecycle gate — ALL 15 PASS on the Poco X3 Pro.** The engine's mobile-only
contract, end to end: session live → KEYCODE_HOME background (save flushed +
suspend state + `.suspend.pending` marker written, log line asserted) →
`am force-stop` (the real OS kill — marker SURVIVES, battery save present) →
relaunch via AUTOSTART (`suspend_resumed path=… frame=<exact>` logged,
marker cleared) → observe reconnects (fresh socket) + frames advance → zero
ledger/self-heal/guard anomalies → crash buffer clean. Three tool-side bugs
fixed along the way (binary adb read for the flash save; marker-clear race
poll; fresh-socket reconnect after the kill). Bonus finding en route: a
**stale marker from a real background kill resumed unprompted** at the exact
frame (`frame=12768`) on the very next launch — the contract doing its job
before we even tested it.

**2. Touch realism: adb-synthesized taps are OS-filtered on this ROM.**
Driving the REAL pipeline (OS touch → SDL_FINGERDOWN → `pad_buttons_at` →
`host_keyinput` → guest KEYINPUT) via `adb shell input tap`: zero TouchHub
journal events, zero KEYINPUT motion during rapid-poll, zero pixel response
in-app — AND zero effect at the launcher/drawer level, with **zero lines on
the touchscreen's evdev node (`/dev/input/event4`, getevent-capped) during
`input tap`** — while `input swipe` demonstrably works (shade opened). The
phone's ROM drops adb-synthesized tap touches (MIUI/HyperOS-class
restriction; swipes pass, taps filtered). Not an engine or app defect:
the engine's pad path is reachable by physical fingers (and by TCP touch
commands — `touch_back` journaled a gesture on the same session), and the
press/lifecycle gates validate input *effect* via the observe TCP instead.
`tools/android_touch_test.py` is committed as the instrumented check for
when a tap-permissive device (or the emulator, or a physical finger) is
available: it reads the live pad layout from the boot log, taps the A
button, and asserts KEYINPUT + journal + gesture. Its failure mode on THIS
phone documents the restriction honestly (the launcher-level checks are in
the BRINGUP evidence above).

Architecture note (verified in source while here): the TCP touch-script
engine (`touch_tap`/`touch_drag`/…, touch_input.cpp `drain()`) only pumps for
games that install an `input_frame` policy (runtime.cpp:2404+); FFTA's pad is
fed by real SDL fingers (host_window.cpp:2810+ → `pad_buttons_at`), so
TCP-injected scripts queue but never drain in our game. The press tests'
`set_keyinput` bypass is the correct observe-surface for KEYINPUT-level
assertions.

## 2026-10-09 (late) — build.py audit: nested-patch routing bug (found empirically, fixed)

Audited `build.py` end to end. One genuine bug, found by running
`step_patches()` against the current tree rather than reading:

**`step_patches` applied EVERY patch at the `gbarecomp/` root** — but
`arm-recomp-core-local.patch` targets the *nested*
`gbarecomp/external/arm-recomp-core` repo (the tools/patches/README.md
filename-prefix routing convention that `check.py` implements). On this
dev tree the step DIED mid-bootstrap ("patch does not apply:
arm-recomp-core-local.patch" — reverse fails at the wrong root, forward
fails with No such file or directory), and on a fresh clone the same
forward-apply fails. Introduced when the nested consolidated patch
landed; the idempotence claim was true only for the gbarecomp-root
patches. Fix: route each file by its `arm-recomp-core` prefix to the
nested root — verified both ways (dev tree: "all 10 already in place",
correctly routed; fresh-clone sim of pristine pins: all 10 forward-ok).

Everything else checked clean: dumps (size+SHA-1), venv (both branches
converge on the final `import capstone` verification), BIOS freshness
(mtime), regen staleness (mtime sweep of the four inputs), host build,
smoke (GBARECOMP_* env stripped + strict), `--force`/`--no-smoke`/`--jobs`
plumbing, Fail.msg/hint, `submodule_drift`'s `+`/`-` counting. Full
end-to-end idempotent run: DONE in 12.2s, smoke FULLY_STATIC.

## 2026-10-09 (late) — build_apk.py: the Android bootstrap (until the phone UI can load a ROM)

The public app imports the ROM/BIOS through the phone's SAF picker on
first run; until the game shell grows that UI, the practical path is the
private test build (ROM+BIOS embedded). `build_apk.py` wraps the whole
pipeline in build.py's step pattern: **preflight** (JDK 17-26 for Gradle
8.11.1, ANDROID_HOME/SDK auto-discovery + NDK presence, the engine SDL
submodule — initialized on demand —, dumps size+SHA-1, and a fresh
`generated/` corpus, since an Android build consumes it but cannot
produce it) → **gradle** (`:app:assembleDebug -PgbaAbis -PgbaNativeJobs
-PprivateRom -PprivateBios`) → **content guard**
(`tools/android_apk_check.py --expect private` — payload byte-match +
embedded ROM/BIOS hash pins) → **install + device gate** (`adb install -r`
+ `tools/validate_android.sh --no-install`; default on when exactly one
device is ready). Flags: `--abi` (arm64 default, x86_64 for emulator),
`--jobs`, `--no-install`, `--no-gate`, `--skip-check`.

Verified end to end on the connected phone: preflight ok (JDK 21, SDK,
SDL, corpus), gradle BUILD SUCCESSFUL, content guard 8/8 (private,
arm64-v8a, 64.2 MiB), install + **GATE PASSED**. One tooling bug caught
by the run itself (missing `time` import → NameError) and a draft closure
plumbing cleanup before the first green run. README § Setup +
§ Repository layout and android/README § Build now point at it.

## 2026-10-09 (late) — APK slack-junk class: second form found, guard closed

Checking the android/README "Known behavior" claims against tonight's
build found the 64.2 MiB APK (vs the morning's 35.5) — initially read as
a heavier corpus. Entry-level analysis said otherwise: all 15 entries
compress to 37.3 MB, **30 MB of slack sits between the last zip entry and
the APK signing block** — a complete stale copy of the prior build's
entry data (5 local headers + 15 central entries in the gap, first bytes a
0x3f-length local header = the game.toml variant filename), entropy 7.96
(compressed). The README's incremental-repackaging junk class, second
form: the first observation was a junk *entry*; this one is junk
*slack* — invisible to `infolist()`-based checks, so the APK content
guard passed the bloated build.

- **Guard closed:** `check_packaging` now bounds the APK file size by the
  sum of compressed entries + header/signing overhead + 1 MiB slack.
  Negative test (the real bloated APK): FAILED with the diagnostic
  ("28.7 MB of unaccounted slack"); clean rebuild: 35.5 MiB, 8/8 PASS.
- **README updated:** the junk-blob entry now documents both forms and
  that the slack form needs the file-size check (not just entry walking).
- **Remedy unchanged:** `rm -rf android/app/build` (native objects under
  `android/app/.cxx` preserved) — verified: 3.9 s rebuild, 35.5 MiB.

Lesson: entry-list audits miss slack. Any future zip-based artifact guard
bounds the container, not just the inventory.

## 2026-10-09 (late) — Playbook skill updated with this session's portable lessons

Reviewed `.agents/skills/gbarecomp-recomp-playbook/` (SKILL.md + 5 references,
committed 2026-10-07) against the 2026-10-09 session's lessons; four gaps
found and folded in (skill discipline: fold new portable lessons into its
references, project specifics stay out):

1. **debugging.md — new section** "Abandoned handlers and corrupted SVC
   returns": the IRQ abandon-close (handler that never irets → depth stuck →
   guard dies; close coherently = recovery tool, log loudly, root-cause) and
   the SVC continuation ledger (validate every SVC-mode exception return
   against the recorded continuation; deliberately do NOT repair the return
   register — banked restore is the legal source, a `bx lr` site would
   self-loop; clear at reset/load origins; soft resets leave stale entries).
2. **verification.md — junk-slack form**: the incremental-repackaging class's
   second observed form (30 MB stale bytes between last entry and signing
   block, invisible to `infolist()`) — bound the container by the entry sum
   + overhead; byte-wise gap diagnosis names the prior build via the stale
   local header; clean-and-rebuild remedy.
3. **verification.md — on-device driving**: press/lifecycle flows over the
   observe TCP (not synthesized touch; key-register writes + queued loads +
   run-status counters — check which the observe context wires), adb-tap
   OS-filtering signature (zero evdev lines; verify at the launcher), binary
   private-storage reads need `exec-out` binary mode, fresh sockets after a
   kill.
4. **tooling-and-pitfalls.md — two pitfalls**: the misrouted patch-directory
   bootstrap (route by filename prefix; test idempotence *empirically* —
   dev tree + fresh-clone sim — the claim rots one nested patch later) and
   the Android-consumes-desktop-corpus preflight (presence *and freshness*).

SKILL.md router labels updated (debugging: abandoned handlers + corrupted
SVC returns; verification: shipped-artifact guards; tooling:
bootstrap/idempotence). Gates: unit-py PASS.

## 2026-10-11 — Event-Editor + Engine-Hacks symbol import (131 VM handlers, 26 data cells, 11 EH functions)

User-requested deep dive on LeonarthCG/FFTA_Event_Editor (new source,
GPL-3.0) and LeonarthCG/FFTA_Engine_Hacks (delta vs the 2026-10-06 study,
which had taken 2 names + 5 game.toml notes). Clones kept in /tmp (never in
git); attribution-only per public-repo hygiene (THIRD_PARTY_ATTRIBUTION.md
updated: Event Editor = GPL-3.0, reference only, code never copied).

- **EUR trap (would have seeded 131 wrong addresses):** the editor's in-code
  handler addresses (`ffta_common.py` `#4 0x8126625` comments) and its
  old_scripts table offsets (0x3ACEBC / 0x370F94) are EUR-ROM. Located the
  same structures in our USA ROM by searching for the editor's opcode-size
  sequence: scene VM table **gSceneOpcodeTable @0x083A7EE4** (114 valid x6 B:
  u16 size + u32 thumb handler; entry 0x72 garbage) and conditionals table
  **gCondOpcodeTable @0x0836D5A4** (17 x6 B). Size columns match the editor
  114/114 and 17/17; every handler carries the thumb bit; spot-disarmed
  (scene op 0x00 @0x08122B14 = `push {r4,lr}` stream reader indexing the
  table at x6 stride; cond op 0x00 = bare `bx lr`; cond op 0x01 = u16 branch
  -> script PC). Data cells verified by direct word reads: gEventList
  @0x08A19970 (234x4, pad 0 in all 234), cells @0x08009A20/@0x081223C0/
  @0x0800A148/@0x08009A88 point at the right tables, gSceneBanks relative
  scheme sampled 5/5 in range, gTextBankEn is RELATIVE u32 offsets (not
  absolute pointers), gConditionalTypeList 8xu16 -> per-type lists all in
  range. EUR pointer cells (@0x08009AAC etc.) do NOT verify — region
  offsets, correctly excluded.
- **Cross-validations:** scene op 0x52/0x53/0x68 handlers = existing
  evt_healing_case / mission_script_trigger / evt_death_case (§ 5, not
  re-seeded); op 0x4A = 0x08123670 = ffta-decomp's "VM spawn command". Four
  independent sources agree the 0x08122xxx-0x08123xxx region is the
  scene/cutscene script VM; the conditionals VM (0x0800A1A9-0x0800A5A1) had
  zero coverage before. reference/event-vm.md gained a "two VMs" section;
  its stale 0x08122A00 note corrected (it IS scene op 0x70's handler entry
  per the table, not an interior).
- **Changes:** symbols/ffta_symbols.tsv § 19 (111 scene + 17 cond handler
  rows; 3 map to existing § 5 names) + § 20 (11 Engine-Hacks call targets
  via the `ldr/mov lr/.short 0xF800` idiom, each disarmed — prologues cited
  in the header; incl. rng_next @0x08002804, the BRINGUP "Phase 4 LCG",
  previously unseeded); symbols/ffta_data_symbols.tsv § 16 (10 tables/cells
  + 8 per-type cond lists) + § 17 (8 EH RAM cells, extents hedged).
- **Measured regen outcome (corrected mid-session: NOT naming-only):**
  discovery 55,102 -> 55,350 (+248 — seeds reach table-only entries the
  sweep never found; legitimate per gbarecomp/docs/SYMBOL_OVERLAY.md step
  4). Names stick only where the seed wins the finder's first-discovery
  race (`visited_` early-return, function_finder.cpp:483; seed_by_key only
  renames queued, undiscovered seeds): **56/139 applied** (11/11 EH +
  45/128 VM); the other 83 keep `gf_tfunc_*`. No rename pass exists for
  walker-discovered functions — accepted, headers state the outcome, and
  the op->PC map stays readable regardless.
- **Gates:** cycle.py PASS (regen 55350, dispatch sanity, build, attract
  sha256=1EF4C1... unchanged); check.py ALL PASS 13/13 — route_G, route_K,
  user_load all FULLY_STATIC with 0 misses; hangrepro, ws_smoke,
  desktop-accept, units, patches, savecheck, android-static green.
- **NOT seeded (deliberate):** 43 further prologue-verified (`push {..,lr}`)
  Engine-Hacks call targets without usable comments — seeds without names
  add no readability: 0x08001F34, 0x080051C4, 0x08005318, 0x08005B28,
  0x08006FCC, 0x080142DC, 0x08015110, 0x080161BC, 0x08017B68, 0x080269D8,
  0x0802AB64, 0x0802D824, 0x0802D934, 0x080354AC, 0x08035A68, 0x08035D00,
  0x08035E04, 0x08036350, 0x08045668, 0x08071378, 0x08072130, 0x080725B8,
  0x080876F4, 0x0808A268, 0x08099560, 0x080995C0, 0x08099C04, 0x0809F8EC,
  0x080C9540, 0x080C9574, 0x080CA7A4, 0x080CA9E8, 0x080CB1F4, 0x080CB450,
  0x080CB48C, 0x080CB5A8, 0x080CB9E0, 0x080CBA14, 0x080CD50C, 0x080D2F2C,
  0x080D3508, 0x080DDF68, 0x0812AE8C. ~500 remaining ORG sites are interior
  patch points (2026-10-06 conclusion stands).
- **FLAG (not changed, needs live re-verify):** gPartyUnits is based at
  0x02000000 size 0x18C0 (§ 6), but engine-hacks treats party unit data as
  0x02000080-0x02001940 ("first unit" / "last unit" 0x02001838). Noted in
  data-symbols § 17 header; no seed relies on either window until verified.

Conclusion: event system now has full handler + table coverage in symbols;
behavior provably unchanged (pinned hash + strict replays). Commit after
this entry per change-cycle discipline.

## 2026-10-11 (later) — 43-backlog triage (30 seeded as § 21) + party-base resolved + SWI fix

Follow-up to this morning's entry (the two "later items").

- **43 triage:** three parallel read-only analyses (menu/shop, menu/roster,
  battle/learn clusters; sessions ses_*BvS/6Roa/zqSzkE) proposed 30 names;
  I re-verified every load-bearing line myself (prologue halfwords, pool
  literals, bl chains, caller arg setup in the EH .s) before seeding.
  Seeded as symbols § 21 (30 rows with cluster evidence comments).
  Regen: **30/30 names stuck**, discovery flat at 55,350, attract hash
  unchanged — these callees are only reachable via the EH blx-via-lr idiom
  (`.short 0xF800`, opaque to the walker), so each seed won its race.
  Internal consistency: newly-named functions call each other
  (0x08005318->decode_table_entry, 0x080CB450/0x080CB5A8->unit_growth_getter/
  item_data_getter, 0x080725B8->decimal_number_tiles_draw).
- **13 stay UNRESOLVED (single-evidence only, not seeded):** 0x08001F34
  (shop number-draw; callee 0x080016D4 + IWRAM cells unpinned), 0x08005B28
  (buffer-setup veneer, worker 0x08007138 unknown), 0x08006FCC (command-
  buffer init, both callees unknown), 0x0802AB64 (tilemap fill, no
  literals/callees), 0x08035E04 (flag-gated IWRAM writes, cell semantics
  unpinned), 0x08036350 (29x12 B table ID lookup, table + flag cell
  unpinned), 0x0808A268 (window-tile engine, param semantics unpinned),
  0x08099560 (unit-presence query triplets, subject table unpinned),
  0x08099C04 (one-field load + tail call, callee unpinned), 0x080C9540 /
  0x080C9574 (bit test / bit set-clear over the 0x02001F70 bitfield —
  mechanism solid, bit meanings unknown), 0x080CB1F4 (bare [1,0xFC] range
  gate; "weapon" reading from one caller comment only), 0x080D2F2C
  (24-slot occupancy count toggling bit 0x5A7; threshold/bit meaning
  unknown — but its 0x02000000+0x84 loop is party-base evidence, below).
  Follow-up family noted (not seeded, triage evidence already gathered):
  0x080C95A8/0x080C95BE (bit/byte accessors over 0x02001F70/0x02002030),
  0x080CB210/0x080CB24C (inventory table-locator family), 0x08007138 (list
  worker behind 0x08005B28), 0x08005318 (4-arg gfx helper behind
  icon_gfx_load), 0x0808B8E4 (menu row-writer).
- **Party base RESOLVED (E model: 0x02000080):** the JoKyR/GameFAQs
  0x02000000 base was never independently pinned — every § 6/§ 7 live read
  aliased under both framings (models are 0x80-shift-equivalent on all
  slot fields). Vanilla code survey: **34 stride-loop sites** use effective
  base 0x02000080 (mission-end heal 0x0802D824/0x0802D934: pool-verified
  base + 24x0x108 + UnitStat dispatch + 12-enemy loop from 0x02002FC4 =
  gFirstEnemyUnit; roster sort/display 0x08071378/0x08071E90/0x080722F8;
  sprite reorder 0x08087B30; occupancy 0x080D2F2C; battle/event loops) and
  **ZERO** use 0x02000000 as a unit base (the 8 apparent hits all add
  +0x80/+0x84 first, i.e. reach 0x02000080/0x02000084). Cross-checks:
  UnitStat stubs give E-frame offsets directly (idx0 = `ldr r0,[r2]`;
  idx6 level = ldrb +0x09); JoKyR +0x152 speed − 0x80 = EH +0xD2 speed.
  Live EWRAM (world_map.state f51827 over headless --tcp read_ewram):
  [0,0x80) is header/scratch (0x45544646 magic-ish word), not a record.
  gPartyUnits -> 0x02000080 size 0x18C0 (§ 6 comment rewritten with the
  evidence); gInventory @0x02001940 is now exactly array-end continuous,
  and its layout is independently confirmed by inventory_item_consume.
- **SWI parenthetical fix (§ 5):** disarmed the veneer table — 0x0814186C
  = `svc #0xB; bx lr` (table order A/E/C/B at 0x60/64/68/6C). SWI 0x0B is
  **CpuSet** (has fill mode), not CpuFastSet — the old "(CpuFastSet)"
  parenthetical was wrong; batch-C's fill-mode call (r2=0x1000040, 128 B
  zero) corroborates. Fixed in-file.
- **Harness notes:** --tcp-observe serves TCP only in windowed mode;
  headless --tcp serves the full TcpDebugServer (read_ewram works);
  --load-state is ignored in --tcp mode — load via the savestate_load
  command (needs parked core; returns pc/frame).
- **Gates:** cycle.py PASS (55350, attract 1EF4C1... unchanged); check.py
  ALL PASS 13/13 (route_G/K + user_load FULLY_STATIC, 0 misses).
- **Proposed, awaiting user go-ahead:** TsvGuardTests extensions (alignment
  + duplicate-allowlist) and a ROM-truth unittest class pinning this
  session's ROM reads (dispatch tables, pointer cells, party-base literals,
  SWI immediates) — EUR-trap and base-regression guards.

Conclusion: the 43-backlog is closed (30 named + applied, 13 documented);
party-base flag resolved with the base corrected. Commit after this entry.

## 2026-10-11 (tests) — TsvGuard extensions + RomTruthTests pin the import

User asked for additional tests; implemented both proposals from the prior
entry (tests/python/test_tools.py only — no regen/build impact):

- **TsvGuardTests +2:** test_thumb_arm_alignment (even thumb / 4-aligned
  ARM — the cycle.py dispatch sanity, now at the source) and
  test_no_duplicate_symbol_addrs with a 4-entry allowlist. The allowlist
  correction is a finding in itself: besides 0x085680DC there are THREE
  deliberate cross-file overlaps (0x080C7EA4/0x080CCD50/0x0812ED98 =
  function seed doubling as data-table label, § 3) — first inventoried
  here; any fifth duplicate now fails.
- **RomTruthTests (new class, 6 tests; LOCAL-ONLY, skips without game.gba
  per the SaveCheckTest/BiosBytePinTests precedent):** VM table hash
  (sha256 over both dispatch regions — one EUR handler swap breaks it,
  verified with a tampered-copy negative control), TSV handler membership
  (all 128 scene_/cond_ rows resolve into the ROM tables; scene_gfx_load
  excluded by design), USA pointer cells, event-list pad bytes (234/234),
  party-base literals (0x0802D878/0x0802D9E4 + enemy +0x2F44 + UnitStat
  table base + index-0 stub), SWI veneer immediates + bx lr tails.
- **Two test bugs caught by running (both mine, fixed):** `bx lr` is
  0x4770, not 0x7047 (byte-order slip — the disassembler prints bytes);
  the duplicate allowlist needed all four overlaps, not one. Suite is
  27/27 OK (19 existing + 8 new); check.py --only unit-py PASS.
  Full-gate re-run unnecessary (no symbols/config/src change since the
  13/13 gate on the identical tree).

Conclusion: the EUR-trap, party-base, and CpuSet pins are now permanent
regression guards. Commit after this entry.

## 2026-10-11 (issue #6) — saves + states to the user-visible app dir

Issue #6: `.sav` and save states are invisible at
`/sdcard/Android/data/org.gbarecomp.fftarecomp` — everything lived in the
app-private `files/` tree (`files/saves/ffta_us.sav` via game_android.toml
`[save].path ../../saves/ffta_us.sav`; slots/suspend derived from `args.rom`
as `files/roms/ffta_usa.stateN/.suspend.state/.suspend.pending` in
runtime.cpp), which needs `run-as` and is invisible to file managers/MTP.

- **Fix:** `src/main.cpp` (Android only) resolves the external app dir via
  `SDL_AndroidGetExternalStoragePath()`, one-time migrates app-private files
  outward (`saves/ffta_us.sav`, `roms/ffta_usa.state1-9`,
  `roms/ffta_usa.suspend.state`; copy + size-verify + remove original, only
  when the external copy is absent so player imports win; `.suspend.pending`
  deliberately not migrated), then appends `--save-path` + `--state-dir`
  (CLI wins over the staged TOML; `find_config_arg` needed the new flag in
  `kCliValueFlags`). New layout: `.../files/saves/ffta_us.sav`,
  `.../files/states/ffta_usa.*`. No storage permission needed (app owns its
  external dir); external unavailable -> TOML internal fallback stands.
- **Engine knob (local patch):** `--state-dir <dir>` in runtime.cpp
  (`Args::state_dir`, `state_base()` helper serving slot/suspend/marker
  paths; empty = historical next-to-ROM behavior, desktop untouched).
  Recorded as `tools/patches/android-external-state-dir.patch` (pin-forward
  + dev-reverse verified) + regenerated `gbarecomp-local.patch`; regions
  confirmed clear of the 5 existing runtime.cpp hunks before writing.
  Game `main` links `SDL2::SDL2` on Android (engine builds it shared first).
- **Tests/docs:** `android_static_check.py` gains the issue-#6 wiring check
  (TOML fallback + src tokens + engine knob + lifecycle paths + romFile
  basename pin); `android_lifecycle_test.py` asserts the external locations;
  `android/README.md` gains a Saves & states section (paths, MTP/adb,
  import-while-stopped rule).
- **Gates:** cycle.py PASS (55350 flat, attract 1EF4C1... unchanged);
  desktop `--state-dir` smoke run exit 0 + FULLY_STATIC identical;
  check.py ALL PASS 13/13 (incl. patches replay + android-static 18/18).
- **Pending (no device attached here):** rebuild + reinstall the APK (native
  change), then `android_lifecycle_test.py` and `android_press_test.py` on
  device; confirm MTP visibility + a USB round-trip (pull/push `.sav`).
  `git status` keeps the `gbarecomp` worktree dirty by design (recorded via
  the consolidated patch, applied by build.py on fresh clones).

Conclusion: issue #6 implemented on all three layers (engine knob, game
redirect+migration, gates/docs). Commit after this entry.

## 2026-10-11 (issue #2) — root README slimmed, manual route to docs/

Issue #2: root docs too dense, no simple build/run example with scale+screen
flags (WarioWareTwistedRecomp cited as the better model — structure studied,
no text taken).

- **Root README 323 -> 190 lines.** New Quick start (clone -> dumps ->
  `build.py` -> `tools/play.sh --scale 4`) and Display options (`--scale N`
  1-8/default 3 with pixel math; `--screen` raw/unlit/frontlit/backlit/
  classic with default + TOML/env overrides; widescreen pointer to
  reference/widescreen.md). Flag facts verified against runtime.cpp
  (parse_cli + color_lut.cpp kinds) and a headless `--scale 4
  --screen backlit` smoke run (exit 0, FULLY_STATIC); invalid `--screen`
  values do NOT fail (fall back silently) so no such claim is documented.
  Thanks compressed to one line per credit (all names kept); Contributing to
  5 + AGENTS.md pointer; layout/status/testing pointers unchanged.
- **Overflow bucket:** manual 9-step route + troubleshooting + oracle setup
  moved verbatim to `docs/manual-build.md` (new `docs/` dir, layout table
  row added). Stale-pointer sweep: `build.py:207` hint now targets
  `docs/manual-build.md § Troubleshooting`; skill verification.md
  "collapsible reference" -> "reference document"; AGENTS.md index gains
  the docs/ row. No other file anchored the moved sections (checked).
- **Gates:** docs-only (no game.toml/src change) so no cycle/check run;
  `tests/python/test_tools.py` 27/27 OK (covers build.py); fence/link audit
  clean (relative links resolved per-file).
- Note: `tools/play.sh` header still says `--view-width` is unsupported for
  FFTA (clamps to 240) — stale vs the validated W1-W3 448 px model, left
  alone as out of scope; README points widescreen readers at
  reference/widescreen.md instead.

Conclusion: issue #2 done — quick start + scale/screen examples up front,
detail one link away. Commit after this entry.

## 2026-10-11 (issue #5) — --launcher ignored: headless short-circuit beat force

Issue #5: `tools/play.sh --launcher` never showed the settings UI.
Live repro (DISPLAY=:0, 25 s timeout): game booted straight through
(`cpu_backend` line, 1459 frames presented) — flag silently ignored.

- **Root cause (engine, launcher_seam.h:660):** `gbarecomp_launcher_preboot`
  classifies `--rom` as a headless flag, and the skip chain reads
  `if (headless || (skip_once && !force) || netplay) return 0` — headless
  short-circuits BEFORE `force_launcher` is honored. `--launcher` only ever
  defeated `--no-launcher`/persisted skip, never headless detection. Fatal
  combination: `play.sh` unconditionally passes `--rom game.gba`, so the
  flag could never take effect through the documented entry point. Nothing
  in-repo passes `--launcher` programmatically (only the play.sh usage
  hint), so no flow depended on the old precedence.
- **Fix (one line + comment):** `(headless && !force_launcher) || ...` —
  explicit `--launcher` forces the UI; without it headless still skips
  silently. Recorded as `tools/patches/launcher-force-ui.patch`
  (pin-forward + dev-reverse verified; launcher_seam.h untouched by other
  patches) + regenerated `gbarecomp-local.patch` + README table row
  (marked Proposal/medium — extends the documented force-past-skip
  contract, behavior change for upstream to take or leave).
- **Live verification (rebuilt via cycle.py):** `play.sh --launcher`, 20 s —
  process sits in the UI (`[launcher]`/`[rui]` lines, 0 `cpu_backend`
  markers, killed by timeout); plain `play.sh`, 20 s — straight boot
  (`cpu_backend`, 1153 frames). No regression either direction.
- **Gates:** cycle.py PASS (55350 flat, attract 1EF4C1... unchanged);
  check.py ALL PASS 13/13 (patches replay incl. the new file, 18/18
  android-static, routes FULLY_STATIC).

Conclusion: issue #5 root-caused and fixed with both-direction evidence.
Commit after this entry.

Follow-up (hygiene): the live `--launcher` verification run wrote
`keybinds.ini` + `rom.cfg` (absolute local ROM path) into the repo root.
Deleted both; `.gitignore` now covers the four launcher sidecars
(`rom.cfg`, `bios.cfg`, `config.ini`, `keybinds.ini`) — no tracked file
matches those names (verified). Committed with this note.

## 2026-10-10 (CI tier-1) — android-static failed on pristine clones (issue #6 check)

CI (`unit-cpp,unit-py,patches,android-static`) failed only
`android-static`: `identity: saves/states land in the user-visible app
dir (issue #6)` — 17/18 passed. Local run was green, so the check was
environment-sensitive.

- **Root cause:** `check_save_external_wiring` read the live working tree
  `gbarecomp/src/runtime/runtime.cpp` for the `--state-dir` knob. That
  knob exists only as a local framework edit (recorded in
  `tools/patches/gbarecomp-local.patch` + reference
  `android-external-state-dir.patch`); pristine CI submodules
  (`git show HEAD:src/runtime/runtime.cpp` — 0 hits) don't have it.
- **Fix:** the engine assertion now accepts the working tree OR the
  recorded patches (same three tokens: `"--state-dir"`,
  `args->state_dir`, `state_base`). Patch<->pin fidelity stays with the
  `patches` suite; this keeps tier 1 fork-safe on fresh clones.
- **Verification:** `git show HEAD:...runtime.cpp` lacks the knob (old
  code must fail) while both patch files carry all three tokens (new
  code passes); `.venv/bin/python tools/check.py --only
  unit-cpp,unit-py,patches,android-static` → ALL PASS 4/4.

## 2026-10-10 (build_apk.py) — hardened after the debug-APK session

Building the latest debug APK hit three script defects (all fixed in
`build_apk.py`, verified live):

- **Env propagation:** preflight auto-discovered the SDK but never exported
  it, so Gradle died with "SDK location not found" on machines without
  `ANDROID_HOME` set. Preflight now exports the validated `ANDROID_HOME`
  and `JAVA_HOME` (setdefault — an explicit user export or
  `local.properties` stays authoritative). Proven by a clean-env run
  (`env -u ANDROID_HOME -u JAVA_HOME ... --no-install` → DONE).
- **Preflight failure didn't abort:** `run_step` returned None but `main`
  barreled into Gradle anyway. Now returns 1 immediately (verified with a
  bogus `ANDROID_HOME` → FAIL at [1/3], no Gradle).
- **Stale-APK acceptance:** an UP-TO-DATE Gradle run was accepted on
  presence alone. The accepted APK must now be newer than
  `FRESHNESS_INPUTS` (corpus, game.toml, src/main.cpp, CMakeLists,
  game_android.toml, build.gradle, payload state.toml), else it dies
  pointing at `rm -rf android/app/build`. Tripwire tested via a
  backdated-APK monkeypatch (dies with the stale message + hint).

Session notes (not script defects): the first native compile hit a
transient ninja failure that passed on retry; the APK then failed the
content guard at 64.3 MiB — the documented incremental-repack junk class
(28.7 MB slack) — fixed by `rm -rf android/app/build` + rebuild → 35.6
MiB, `android-apk: OK (8/8)`. `--clean` flag deliberately deferred (not
requested). Docs: worked save-import example added to
`android/README.md` § Saves & states (`154e06c`).

## 2026-10-11 (issue #8) — audio/fast-clock hunt: producer +4-8% in battle, yield exonerated, codegen-side

Issue #8 (performance feel, audio tied to FPS, quality) + what
`GBARECOMP_AUDIO_DIRECT` does. No fix yet — diagnostics built, root cause
narrowed to per-frame cycle overcharge on the recomp backend.

- **Audio path anatomy (all verified in code):** producer = emulation
  thread, one push per presented frame (~1097 samples @65536 Hz nominal,
  `runtime.cpp:3699,4112`). Default bridge: RAB 32-tap windowed-sinc
  (`recomp_audio_drc.h`), P-servo ±0.5%, 60 ms target, 250 ms boot preroll
  (settles over ~40-90 s — by design, but the loop sits railed that whole
  time). Direct (`GBARECOMP_AUDIO_DIRECT=1`, `host_window.cpp:1915`): raw
  SDL_QueueAudio, no servo/concealment — underrun pauses + rebuilds 125 ms
  (dropout), latency wanders unboundedly (observed 50→218 ms and climbing
  in 25 s on PipeWire). Mixer is mono (`gba_audio.cpp:646`); MP2K shadow
  exists but FFTA runs `shadow=false`; hard clip at ±32767 (peaks ~19k
  observed, not exercised).
- **Measurements (all windowed, battle = `--load-state game.state1`):**
  title/bridge: servo railed +0.5%, fill 250→210 draining, 0 drops.
  title/direct: 0 underruns, queue wandering/growing. battle/bridge:
  overflow_drops 0→92k in 35 s (~2.5k/s ≈ 4% discarded as micro-skips),
  fill pegged ~280 ms, ~1150 samples/push vs 1097 nominal.
  battle/interp (`GBARECOMP_FORCE_INTERP=1`): ZERO drops, servo relaxes to
  ~0.00%, fill holds 60 ms — perfect equilibrium, same state/scene.
- **Exonerated with evidence:** SOUNDBIAS flicker (60 rapid TCP
  `audio_state` reads: all 65536/cps-256/`0x4200`); tick double-paths
  (single `audio().tick` caller); DMA-steal double-drain (`take_` zeroes);
  idle elider (atexit `[idle]` line absent = 0 skips in battle run);
  session-execution (netplay-only); pacer (phase CSV: visits 59.752/s,
  pacer_us med 12.7 ms — absolute cadence exact).
- **Yield-gate probe (new, `tools/patches/yield-gate-probe.patch` + table
  row, default-off via `GBARECOMP_YIELD_PROBE=1`, attract hash unchanged):**
  per-check blocks by term + per-window misses attributed to window-start
  state. Battle result: **1804/1804 windows yielded, multi=0, all miss
  counters 0** — the yield mechanism is exonerated; blocked(nest)=72M is
  just the (correctly non-yielding) vblank-IRQ handler window. The
  earlier "60 double-frame visits" (phase CSV frames/visit=1.0337) are
  consistent with an ~8%-fast master, not skipped yields.
- **Current verdict: the master clock advances ~4-8% fast on the recomp
  backend only** (interp nominal on the same frames) — i.e. ~10-20k
  phantom cycles/frame. Spin-loop audit (`gf_vblank_wait_loop`,
  0x08000418, 82% wall duty): per-iteration charge 31 cycles fully
  explained, all terms (fetch N/S, LDR/LDM + stall, prefetch gate,
  refill) mirrored verbatim between codegen and interpreter — and
  event-terminated spins contribute equal cycles in both backends anyway.
  Remaining suspects: codegen emission on battle-hot (non-spin) code —
  MUL/LDM block costs vs interp loop, or wait-table/prefetch-STATE
  divergence (dynamic inputs, not rules). Next: per-PC cost comparison
  via `GBARECOMP_CYC_LO/HI` full-frame captures under both backends, or
  sampler-directed audit of the m4a/IWRAM hot frames.
- **No new symbols:** every hot spot is already named
  (`gf_vblank_wait_loop`, IWRAM `gf_afunc_030037xx` m4a frames, flag
  `0x03000E10`). The one unnamed site found (sound-reg init at
  0x08FE1370 writing `0x0200` to SOUNDBIAS) lacks naming evidence —
  observation only, not seeded.
- Scratch logs (`/tmp/opencode/audio_*.log`, `phase.csv`, `cyc.log`)
  are not committed; numbers above are the record. Recipe bullet added
  to `tests/README.md` § Recipes.

Conclusion: issue #8's audio symptom is a fast-guest-clock symptom
(bridge floods → overflow micro-skips + dropped presents). Hunt
continues at the codegen cost layer. Commit after this entry (probe +
docs; no game behavior change).

## 2026-10-11 — healed 3 user-playtest battle misses (2 switch tables + 1 func)

Live play hit 3 unnamed functions (frag_prev_20261011_000537;
healed_native=3, all bridged, native_calls=0): 0x080F1858 (x47),
0x080F2680 (x144), 0x08132450 (x3). Misspack + own-ROM verification:
both 080F cases sit mid-run in clean abs32 switch tables (8 entries
@0x0839A59C, 10 @0x0839A8E8 with default-case dups), so seeded as
`table_0839A59C`/`table_0839A8E8` (entries_mode=auto); 08132450 is a
single-callsite helper (calls 0x08131DD4/0x080CDD64) seeded as
`[[extra_func]].
Cycle PASS (discovery 55350 -> 55763, attract 1EF4C1... unchanged);
strict replay of the session trace (`resolve.py --trace
trace_prev_20261011_000537 --load-state game.state1`) PASSED with 0
seeds. Commit after this entry.

## 2026-10-11 — new regression route B: user-played battle movement + actions

Recorded live (`play.sh --scale 2 --load-state game.state1
--tcp-observe 19870`, faithful 240 view): 81-row trace, frames
24722 -> 29816 (5094 f, monotonic, no mid-session reload), D-pad
movement + A/B actions throughout. Frozen local-only in
`saves/regress/` (trace + `battle_move_start.state` =
untouched `game.state1`, sha `2066d61c` + `battle_move.sav`).
Session frag held only the 3 already-seeded PCs — zero new gaps;
`resolve.py` strict replay PASSED with 0 seeds. Wired as `route_B`
in `tools/check.py` via a new `strict_route_state` helper
(`strict_route` is boot-only); self-test
`FULLY_STATIC dispatch_misses=0` in 21.5 s. Commit after this entry.

## 2026-10-11 (issue #8) — FIXED: banked presents ran the guest +5% fast; pacer now paces frames

Root cause, proven to exact counts in a single 74.45 s battle window
(`game.state1`, dummy video, all probes): the present hook only presents
on frame change, and 227 times it ran early enough to see a stale frame —
skipping the present *and its ~12.6 ms pacer wait*. Yields 4675 = rows
4448 + skips 227; framespan +4674 vs 4447 expected = excess 227.
Skips == excess exactly. Each skip banks a guest frame the pacer never
throttles: 62.778 fps (+5.1%), audio-bridge flood in the same window
(221k overflow drops, servo railed +0.5%, fill ~280 ms, ~1150
samples/push vs 1097 nominal). Mechanism: the post-vblank hook usually
lands after the frame wrap but straddles it when handler length varies
(all skips from spin PCs, mode 0x1f) — a tiny handler charge difference
between backends decides the straddle (interp: 59.725 fps, zero drops,
servo +0.035%, zero skips on the same state).
Exonerated with evidence along the way: audio bridge (correctly
wall-clocked), SOUNDBIAS flicker, tick double-paths, DMA steal (24.8k vs
26.2k), idle elider (0 skips), session exec, pacer cadence, yield gate
(4675/4675 windows, zero misses), per-PC charges (681124 ticks identical
both backends over 2M cycles), PPU monotonicity (per-window frame deltas
all exactly 1 — no double-fire). PIP=0 changes nothing (same 227), which
killed the hook-timing theory and pointed at the shared gate.
Fix (`tools/patches/frame-pacer-banked-wait.patch`, upstream-proposed #1):
`FramePacer::wait_for_next_frame(frames=1)` advances the deadline by the
banked count; both present sites pass `frame - last_presented_frame`.
Single-frame path is the old logic exactly; fast-forward (always k=1 per
wait) and the behind-resync are untouched; absurd banks clamp at 16.
Verification: dummy 59.53 fps + zero drops + servo tracking ±0.25% +
fill ~60 ms; real display 59.48 fps, zero drops; full gate 14/14 green
(attract hash unchanged, all strict routes FULLY_STATIC, ws smoke green);
new `tests/unit/test_frame_pacer.cpp` (banked multi-period wait,
default, uncapped, clamp — red-verified against pre-fix behavior,
pristine-CI skips via `PACER_BANKED_API` probe). Device: clean-rebuilt
APK (35.7 MiB, content guard 8/8, gate PASS), on-device battle replay via
new `tools/android_trace_replay.py` (state + trace, frame-driven
set_keyinput) + user manual test — both pass. Residuals: the underlying
handler charge wobble is still unidentified but now harmless (absorbed by
debt pacing); fast-forward multiplier has no gate coverage (logic-only).
Probes (`yield-gate-probe.patch`: yield census, frame deltas, skip counts)
were scaffolding — stripped after the counts closed; proof is this entry.
Commit after this entry.

## 2026-10-11 (issue #3 prep) — BIOS HLE flip: zero-fallback census, 11 seeds, device-verified

**Why:** the release-hygiene story (issue #3) needs the binary free of
translated Nintendo BIOS code. The engine's HLE (mGBA-derived clean-room
SWI services, MPL-2.0) was already in the pin; the game just had to flip
`[bios].hle` and prove no SWI falls back to LLE.

**Census evidence (GBARECOMP_SWI_LOG + GBARECOMP_SWI_TRACE):**
- attract 1200f: 1317/1317 HLE-taken (0x0B CpuSet ×1308, 0x0C CpuFastSet ×9)
- battle route B 5094f: 7341/7341 HLE-taken (0x06/08/0A/0B/0C/0F/11)
- suspend route G 19400f: 11474/11474 HLE-taken (0x0B/0C/0F/12)
- Zero fallback on every route. HLE-implemented set mirrored from
  `bios_hle.cpp` dispatch() in `tools/hle_audit.py` (red-verified both
  ways: HLE-off fails taken counts; dropped-SWI fails coverage).

**Flip:** `game.toml` + `android/game_android.toml` `[bios].hle = true`.
Attract golden stays LLE (`attract_check.py` pins `GBARECOMP_BIOS_HLE=0`):
the attract frame sits mid-intro-movie (timing-chaotic content — same
backend diverges run to run in phase), so the pin guards rendering on
the oracle-faithful path while `hle_audit.py` owns the HLE path.

**Device boot-path seeds (10 units, frag from android-runtime.log):**
0x080D9CF4, 0x080FF180, 0x080FF1D8, 0x0810EA78, 0x0810EC04, 0x0810EF0C,
0x0810FAF8, 0x0810FBF8, 0x0810FC6C, 0x081333B8 — all Thumb, all with
prologue + ROM pointer-table evidence (misspack). The HLE boot skip +
SWI servicing changed the entry pattern the corpus was grown under, so
the first HLE device boot found doors the LLE corpus never walked.

**Gameplay seed (1 unit, frag from user playtest):**
0x080190A8 → `table_0836D7B8` (29-entry abs32 switch, thumb|1, trailing
default-case dups). Same shape as the earlier battle tables.

**Corpus:** 55763 → 56180 units (10 boot + 1 gameplay seed). Full gate
15/15 green on the new corpus (attract pin intact, all strict routes
FULLY_STATIC, hle-audit green, ws_smoke green).

**Device verification:** user playtest on the HLE build — gameplay works,
no issues. The 10 boot-path misses were real gaps (now seeded); the
gameplay miss was the first post-intro code the attract route never
reaches.

**Logging fix (committed separately, 2b4fd12):** external `logs/` dir,
manifest line, engine freopen check, gate log-clear, static wiring
check. The device gate's stale-log reads caused half the confusion
today; the log-clear fixes that class.

**Still pending:** scanline/DMA HLE track (PRs #29/#31 — pin move +
revalidation). The HLE flip is proven on desktop routes; the device
boot path is converged (11 seeds, user playtest clean).

## 2026-10-11 (issue #17) — E2b/c: the emibios swap — linked, seeded, 15/15 green, golden unchanged

**Action.** Swapped the launch BIOS from the retail Nintendo dump to the
committed clean-room emibios (milestone 1 `735084e` committed the bin +
TOML; this milestone linked and pinned it everywhere):

- `game.toml` / `android/game_android.toml` `[bios]` →
  `bios/emibios_gba_bios.bin`, sha1 `0c0d404d…` (emibios `main @c4d5d71`).
- `build.py`: `step_bios` recompiles emibios from the committed material
  (836→837 units after seeds); `step_dumps` no longer asks for a user BIOS
  (ROM is the only user-supplied dump); `step_smoke` repointed. All 21
  harness tools' `--bios` paths repointed (`check`, `attract_check`,
  `hle_audit`, `ws_check`, `hangrepro`, oracle tools, …) — `framediff`
  now hands emibios to the oracle too, so both sides run the same BIOS.
- Engine (recorded in `tools/patches/`, replay-verified):
  `emibios-launcher-pin-set.patch` (`GbaBios::kEmibiosSha1` + the
  launcher `bios_verify` accepts {retail, emibios}; the config
  `[bios].sha1` pin stays the runtime gate),
  `emibios-public-guard-bundled.patch` (Android public-artifact guard
  exempts a 16 KiB `.bin` whose SHA-1 equals the game-declared non-retail
  `biosSha1` pin), `emibios-bios-dispatch-table.patch` (data-only: the
  regeneration overwrites the upstream-provenance retail table — its
  `.gitignore` documents exactly this workflow).
- Android: `biosSha1` manifest pin override, `biosRequired=false`,
  payloadDirs stages the bin at `payload/bios/`, `payloadVersion` 3→4;
  `build_apk.py` drops `-PprivateBios` (the BIOS arrives via payload
  staging; private builds still embed only the ROM).
- Checks: `check_bios_pins` now pins all-emibios (both TOMLs == manifest
  pin == committed bin; upstream template default must stay the retail
  fallback), new `check_emibios_engine_acceptance` (tree or recorded
  patch), `check_emibios_integrity` from milestone 1. 22 checks green,
  red-verified on TOML-pin corruption.

**Two strict-miss seeds, both statically undiscoverable, evidence in the
TOML notes.** The first LLE run of the emibios corpus missed at
`pc=0x3E74` (frame ~264–276 = the final-burn/handoff window):

- `0x3E74` `.vc_irqh` — emibios's own interim VBlank IRQ handler,
  installed into `[0x03007FFC]` at runtime by `boot_final_burn` (0x3DBC),
  reachable only via the `0x128` trampoline's `ldr pc,[r0,#-4]` (a runtime
  pointer, same class as a game handler). Confirmed by ELF local labels +
  non-strict bridge (1 distinct PC, 7 insns) + empty ring reg-scan for
  0x3E74 (no register ever held it — no static reference exists).
- `0x138` `after_interrupt` — the IRQ trampoline epilogue; unreferenced
  statically (the `0x130 add lr,pc,#0` installs it as the runtime return
  target). Retail's `gbarecomp/bios/gba_bios.toml` seeds the identical
  fragment at the identical address — same class, same fix.

The SWI halfword table at `0x194` (dispatch `0x144 ldrb ip,[lr,#-2]` /
`0x148 add fp,pc,ip,lsl#1` / `0x14c ldrh ip,[fp,#0x44]` — emibios reads
the number from bits 23..16, the commercial `swi #(n<<16)` encoding FFTA
uses) needed NO new seeds: every 0x00–0x2A target already had a same-mode
dispatch row. Apparent gaps beyond 0x2A were past-table garbage (the
table is documented 0x00–0x2A), not real targets.

**Result.** Full gate 15/15 PASS with the emibios corpus linked: all
strict routes (user_load, B, G, K) FULLY_STATIC with zero misses;
`patches` replay byte-matches (431-file tree, 15 patch files); **the
attract golden sha256 `1EF4C118…` is UNCHANGED and the hle_audit routeB
frame pin `43D5B3B6…` survived** — emibios hands off on the same VBlank
phase, and everything downstream is pure game code, so a full BIOS swap
renders bit-identically at both pinned frames. No repin needed; the
unchanged hashes are the phase-equivalence evidence.

**Conclusion.** The binary no longer contains translated Nintendo BIOS
code and users supply only the ROM. The retail dump's remaining role is
the launcher's accepted alternative (pin-set patch) and the local-only
`BiosBytePinTests` (retail-contract documentation). Still open for E3+:
device gate + APK guard rework (public builds must CONTAIN emibios, forbid
ROM/retail), LGPL compliance (LICENSES/, attribution row), and the upstream
proposal (launcher pin-set + public-guard exemption — the config-driven
shape preferred over the hardcoded constant).

## 2026-10-11 (issue #17) — E3/E4: device-verified, APK guard reworked, LGPL done

**Action.** Closed the emibios milestone on device and in packaging:

- **APK content guard reworked** (`tools/android_apk_check.py`): the
  bundled clean-room BIOS is *staged material, byte-verified in every
  build* — public included; ROMs are the only private assets left.
  Red-verified against the pre-swap stale APK (failed: missing
  `emibios_gba_bios.bin` + retail `gba_bios.bin` flagged as extra — a
  retail dump is no longer acceptable payload material). Green 8/8 on
  both the new private build and the new public build.
- **Engine public-guard exemption live**: the public `assembleDebug`
  (no `-PprivateRom`) ran `verifyNoPrivateAssets` with the emibios
  staged in the payload — passed via the declared-pin exemption
  (`emibios-public-guard-bundled.patch`); without it the build fails on
  the 16 KiB `.bin`. The public APK is `app-debug.apk` (distributable
  name), ROM-free, emibios hash-verified: the R3 "bring your own ROM"
  artifact exists.
- **LGPL compliance**: `LICENSES/LGPL-3.0-or-later.txt` (the FSF
  combined LGPL-3.0 + GPL-3.0 text emibios ships; verbatim copying of a
  license document is permitted by its own terms — same class as the
  GFDL exception), a `THIRD_PARTY_ATTRIBUTION.md` § "Bundled clean-room
  BIOS" row (unmodified upstream binary, source link, rebuild path), and
  `bios/README.md` (what it is, the pins, the rebuild recipe).
- **Device validation** (30c1f958): private build gate GATE PASSED
  (4/4 build_apk steps; reworked guard green). Then a **fully wiped
  install** (uninstall → gate): GATE PASSED 5/5, fresh boot log 17 lines,
  **zero bridges, no frag written**, `cpu_backend=static-recompiled` —
  payloadVersion-4 re-extract, emibios load under the TOML pin (the
  runtime hard-fails on sha mismatch, so a green boot is the pin proof;
  the mobile banner carries no bios_loaded line), HLE boot skip, no SAF
  prompts of any kind (`biosRequired=false` + embedded ROM).
- **Harness fix found during this**: the recompiler preserves mtimes for
  byte-identical output, so corpus-file mtimes cannot date a regen —
  build_apk.py's freshness gate and build.py's up-to-date check both
  misfired ("corpus is stale" forever after a content-neutral game.toml
  touch). Fix: `generated/.regen_stamp` (gitignored), written by
  build.py step_regen and cycle.py; the freshness gates compare inputs
  against the stamp.
- **Docs**: tier-1/tier-2 wording (BIOS is repo material now; CI tier 1
  verifies the pin; tier 2 needs no BIOS), README/AGENTS/manual-build
  run commands repointed, CI header comment, .gitignore comment.

**Discovered (not emibios, follow-up):** resuming the pre-swap
mid-play suspend state (frame 45171) surfaced **4 game-corpus gaps** —
`0x080EDC08`, `0x080EDC7E`, `0x080F543C` (×216 — hot bridged loop),
`0x080F54B6`, all Thumb, no dispatch rows on desktop either. These are
playtest-reachable game paths no strict route covers — classic
healing-loop debt, orthogonal to the BIOS swap (same corpus before and
after; the fresh-boot gate writes no frag). Next healing session should
harvest + triage them.

**Conclusion.** Issue #17's swap is device-verified on both boot paths,
packaging-verified on both build modes, and legally documented. The
emibios work is complete; what remains under issue #3 is the release
pipeline (make_release.py, tag-triggered CI, first tagged release) plus
the 4-miss healing session above.

## 2026-10-11 (late) — healing loop: gAbilityAnimationTable batch (+6,954 units)

**Source.** The E3/E4 device gate run — the first to auto-resume a
mid-battle suspend state (frame 45171) from the ~12-min unharvested phone
playtest. Bridge evidence (4 PCs): 0x080F543C x216 (hot per-frame
animation-command loop), 0x080EDC08 x1, interiors 0x080F54B6 x1 /
0x080EDC7E x1, plus 0x08133618 x1 (bridge-log only — NOT in the session
frag; journal gap noted).

**Root cause — why a "well-trodden" subsystem was uncovered.** The
ability-animation command interpreter dispatches handlers via
`bl 0x08142250 -> bx r3` (register-dispatch, disarm-verified) with the
handler pointer read from gAbilityAnimationTable @0x083947D8 — 218
`{u32 thumb ptr, u32 packed params}` records, 137 distinct handlers,
region 0x080E4000..0x080F7xxx. Register-indirect + table-fed = invisible
to the static walker; nothing short of executing an animation command
covers its handler. Every battle touches this system — but each ability
animation script uses only a few of the 218 command words, so coverage
grows per-command-executed, not per-system. The frozen routes + desktop
playtests had exercised ~28; the phone playtest (never harvested) hit
more; the rest belong to abilities nobody had played. Not emibios: game
ROM code, corpus byte-identical across the BIOS swap.

**Seeds** (game.toml § device-resume batch): one [[jump_table]] over the
whole registry (stride 8, count 218, format abs32, **entries_mode=auto**
— the raw interworking pointers carry the thumb bit; a "thumb" mode
leaves bit0 unmasked and dispatch-sanity fails on 5350 odd rows, caught
and fixed same day), plus [[resume_range]] over the two observed
handlers' extents (entry..exclusive end, covering whole switches not
just hits), plus one [[extra_func]] for 0x08133618 (event-callback leaf,
bl 0x08131DD4/0x080CDEC8, disarm-verified).

**Validation.** cycle PASS: regen 57299→**63134 units** (+6,954 — the
registry handlers pulled their whole call trees), dispatch sanity OK,
build OK, **attract golden unchanged** (1EF4C118...). Coverage lenses:
walker 97.8%→**98.7%**; pool proxy 99.3%→**94.8%** — honest reading: the
pool denominator grew (speculative literal harvest now maps 3,485 more
units), so the drop is a *map of the next frontier* (more dispatch
families behind other tables in the same region), not a regression;
executed-path lens stays 100% FULLY_STATIC, which is the acceptance
that matters.

**Process fixes (the "keeps getting missed" lessons, same date).**
(1) Symbol-table step added to every healing-loop doc — playbook
SKILL.md merge step, AGENTS.md workflow B step 2, tests/README.md § the
healing loop, android/README.md § device playtests: naming-only
ffta_symbols.tsv entries for new functions + measured-size
ffta_data_symbols.tsv entries for new tables (replace the 0x0
placeholder), in the same session as the seed merge. Applied now:
Section 20 (3 functions), Section 18 data (gAbilityAnimationTable
placeholder → measured 0x6D0 + the two sub-switch tables 0x20/0x28);
TSV guards 27/27. (2) Device-playtest journals must be harvested in the
same session (the unharvested phone journal was the silent debt that
made this batch invisible until a gate resume).

**Follow-up.** The pool-lens drop points at ~3,485 pointer-reachable
units in the same handler region behind other tables — triage next
session (misspack/oracle protocol, PRINCIPLES first). 0x08133618's
journal gap (bridge-log line but no frag entry) noted for the
selfheal-journal reviewer.

## 2026-10-11 (late 2) — unlocked test paths: the committed BIOS is now CI-pinned

**Prompt.** "We have BIOS in source control now — surely some test paths
are unlocked?" Yes — and they had not been taken. The android-static suite
had gained the integrity/acceptance/pin checks in the E2 milestones, but
`tests/python/test_tools.py` still only had the LOCAL-ONLY
`BiosBytePinTests` (skips on CI — the retail dump is gitignored). The
emibios bin being committed repo material means its contract points can
be byte-pinned in a test that runs EVERYWHERE.

**Added** (both CI tier 1, red-verified each):

- `EmibiosBytePinTests` (8 tests): sha1/size pins; exception vectors
  (0x00→0x68, 0x08→0x140, 0x18→0x128 — mirroring retail — and 0x1C→0x1FC,
  emibios's own reserved handler); the IRQ trampoline words incl. the
  0x130 `add lr,pc,#0` (installs 0x138 as the runtime return target) and
  0x134 `ldr pc,[r0,#-4]` ([0x03FFFFFC] mirror); the SWI dispatcher words
  (0x140 push, 0x144 `ldrb ip,[lr,#-2]` — the `swi #(n<<16)` bits-23..16
  read FFTA uses, 0x160 System-mode switch, 0x174/0x188 epilogue); the
  0x194 halfword table as a 44-halfword blob hash (43 entries + the
  boundary word — a size/extent change fails; bounds-check covers the 43
  real entries, an off-by-one the red-run itself caught); the `.vc_irqh`
  body at 0x3E74; and the TOML seed inventory (addr+name pairs — deletion
  fails with the name attached). Missing bin = broken checkout: FAIL,
  never skip.
- `RegenStampContractTests` (2 tests): the `.regen_stamp` token agrees
  across the three scripts (build.py + cycle.py writers, build_apk.py
  reader), and `FRESHNESS_INPUTS` never regresses to emitted-corpus
  mtimes (the 2026-10-11 mtime lesson).

`BiosBytePinTests` docstring updated for its changed role: local-only
RETAIL REFERENCE (the launcher-accepted alternative + the oracle's
default), no longer the launch BIOS.

**Explicit non-unlock:** a BIOS-corpus coverage test cannot run on CI —
tier 1 checks out pristine submodules (patches validated, not applied)
and does not build `gba_recompile`; the corpus files are gitignored. The
TOML seed inventory + bin byte-pins ARE the CI-able form of corpus
coverage.

**Result.** unit-py 27→37 tests, fast gate 6/6, attract golden unchanged.

---

## 2026-10-11 (late 3) — docs: README restructured to the WarioWare model; folder READMEs; dangle clean sweep

**Prompt.** "The README is still awful. Make it as close to the
WarioWareTwistedRecomp README as possible. Everything else gets put in a
README under a folder that makes sense for the information in there."
Follow-ups: `play.sh` is testing-only (play = the self-built binary);
remove the Status section; "clean up all the dangles as well — clean
sweep"; then log and commit.

**Action.** Root README rewritten section-for-section after
mstan/WarioWareTwistedRecomp (experimental-preview blockquote, one-liner,
ROM-not-included/BIOS-bundled note, Quick start Desktop-Linux/Android,
Features, Controls, Building from source, License, Legal, R.A.I.D.
footer). Deltas from the model are fact-driven only: BIOS bundled
(emibios) instead of user-dumped, Select = Backspace (the real keymap),
source-only quick start (no releases yet), "built on gbarecomp" not
"byproduct of developing gbarecomp". Status section removed from the
root and moved to docs/README.md. Play is the self-built binary
(`./build/FFTARecomp` — launcher or `--bios/--rom`); `tools/play.sh`
demoted to the instrumented testing entry everywhere it was framed as
the play route (root README, docs/manual-build.md, tests/README.md,
tools/README.md).

Displaced content → new folder READMEs: `docs/README.md` (status,
what-this-is, running/display options as binary flags, manual-build
pointer, repository map, contributing essentials), `tools/README.md`
(the harness table), `reference/README.md` (study-notes index, sources,
thanks).

Clean sweep (every `README`/`§` citation audited; two PRE-EXISTING
broken § citations found and fixed):
- `AGENTS.md`: codebase-map tools row + reference index → the new folder
  READMEs (was "README § Repository layout").
- `build.py`: § Setup/§ Requirements hints → § Quick start /
  § Building from source; oracle hint → `reference/oracle-harness.md`.
- `build_apk.py`: § Setup → § Quick start; PRE-EXISTING "§ Build
  prerequisites" (not a heading) → § Build (2×).
- `tools/cycle.py`: PRE-EXISTING `AGENTS.md` § "Validation discipline"
  (no such heading — AGENTS was restructured 2026-10-08) → § Workflows
  "A. Change cycle".
- `ci.yml` + `tests/python/test_tools.py`: "README setup" →
  `docs/manual-build.md`.
- `docs/manual-build.md`: play step binary-first; SHA-1 pointers split
  (ROM: root README § Building from source; BIOS: `bios/README.md` —
  only the ROM SHA-1 lives in the root now); "root README Requirements"
  → § Building from source.
- `tests/README.md`: intro now points running/display options at
  `docs/README.md`.

BRINGUP history entries referencing old README sections left untouched
(append-only log). Verified no tracked ROM-derived clutter at root
(screenshot, savestates, hang logs all untracked).

**Result.** One-off link/anchor checker over all 36 repo .md files
(every `[text](target)` resolves; every `#anchor` matches a GitHub-style
heading slug; submodules/.venv/build excluded): **0 broken**. § citations
verified against real headings (android/README § Build/§ Known behavior/
§ Mods state/§ Decisions/§ On-device suspend/resume protocol; tests/README
§ Continuous integration/§ healing loop; THIRD_PARTY § Bundled clean-room
BIOS; gbarecomp PRINCIPLES/DEBUG/docs/TOML_SCHEMA exist). `py_compile`
green (build.py, build_apk.py, cycle.py, test_tools.py); unit-py 37/37
green. Docs-only change — no game.toml/src/generated/ touched, so no
cycle.py gate required.

## 2026-10-11 (late 3) — R-track start: R1 release packager (issue #3)

**Landed** `tools/make_release.py` — the distributable desktop zip, built
from an ALLOWLIST (never copy-the-tree): stripped binary, `assets/`,
`mods/`, `game.toml`, the pinned clean-room BIOS + `bios/README.md`,
`LICENSE`, `LICENSES/`, `THIRD_PARTY_ATTRIBUTION.md`, and a generated
self-contained zip README (requirements, run, hash-verify, widescreen,
file layout, legal — no dead links into unshipped repo folders).

**Design decision — the sweep is content-pinned, not name-pinned.**
`sweep_stage()` (pure function, unit-tested) rejects: ROM bytes under ANY
name (sha1 == ROM pin), a `.bin` that is not the emibios pin (a retail
dump renamed to `.bin` fails), forbidden extensions (.gba/.agb/.sav/
.srm/.apk), symlinks, a de-exec'd binary, and a missing required file.
`.gitignore`d `release-stage/`.

**Freshness gate — first shape was wrong.** Binary-vs-regen-inputs mtime
comparison tripped on the *current* tree: the 7c0d2e3 pull rewrote
`game.toml`/`symbols/*.tsv` mtimes at 19:45 with identical content (git
checkout smudge — the same mtime-lies class as the `.regen_stamp`
lesson). Mirrored `build_apk.py`'s proven gate instead: stamp exists →
inputs vs **stamp** → binary vs **corpus mtimes** (the recompiler
preserves mtimes for byte-identical output, so corpus mtimes are exact).
One `tools/cycle.py` run clears a smudged tree; the gate never packages a
maybe-stale tree.

**Zip determinism + portability.** Fixed 1980-01-01 timestamps, sorted
entries, forward-slash names, unix `create_system` so `external_attr`
carries the mode; `verify_zip` reads back (count, portability, exec bit).
Two independent packaging runs → byte-identical sha1 `5549e2ff…` — a
release job can hash, users can diff. Boot smoke from a bare /tmp
extraction: **FULLY_STATIC, dispatch_misses=0, interpreted=0**, exec bit
intact, runtime sidecars (`rom.cfg`, `recomp_cache/`) created beside the
exe as documented.

**Tests + wiring.** `ReleasePackTests` (10 tests, `tests/python/
test_tools.py`): sweep accept/reject on synthetic stages (gba, unpinned
.bin, disguised ROM hash, retail-BIOS bytes, symlink, exec bit, missing
README) + zip determinism/portable read-back — CI tier 1, no build tree
needed. `check.py` suite `release` (opt-in: needs a built+fresh tree,
never the ROM — its sweep would reject one). unit-py 37 → 46.

**Docs.** Root README § "Using a release binary" (R6 — the binary-first
path for download-and-play users, ahead of the from-source quick start);
generated zip README; `tools/README.md` table row; `tests/README.md` CI
tiers note.

**Result.** Fast gate 6/6; `--only release` PASS; R1 + R6 done (issue #3
R-track: R3/R4/R2/R5 remain — APK artifact, `release.yml` tag trigger,
Windows stretch, first tagged release).

## 2026-10-11 (late 4) — R-track: R3 public APK release artifact (issue #3)

**Landed** `tools/make_release.py --apk`: the public (ROM-less) Android APK
as a release artifact, staged beside the zip.

**Flow**: preflight reuses `build_apk.py` (JDK/SDK/NDK discovery, SDL
submodule, dump verify — the release runner carries the ROM for the
bootstrap anyway) but its own gradle call (`build_apk.step_gradle` bakes in
`-PprivateRom`). **Clean repackage always**: `android/app/build` removed
before gradle — native objects under `android/app/.cxx` survive (compile
stays cached) but the packaging restarts from scratch. Then the
`android_apk_check.py --expect public` gate, then staging as
`FFTARecomp-<version>-android-arm64-v8a.apk`.

**The live run found both traps:**
1. `build_apk.newest_apk()` globs the `*-PRIVATE-rom-included` marker only —
   it can never find a public build; the public APK is always at AGP's
   `android/app/build/outputs/apk/debug/app-debug.apk` (the engine's rename
   deliberately applies only to private builds).
2. The guard's packaging-sanity check rejected the first artifact:
   65.7 MB APK vs 35.1 MB of entries — **29 MB of incremental-repackaging
   slack** stranded from prior builds, invisible to infolist (the exact
   junk class that check exists for). The clean repackage above is the
   structural fix; the guard stays as belt-and-braces.

**Result**: zip `c41267b4…` (45.7 MB) + public APK `e81303d5…` (35.1 MB,
guard 8/8 `--expect public`), both `release-stage/` (gitignored).
`assembleDebug` is debug-signed — the release-key (`gbaKeystore`) decision
stays flagged open for R5 on issue #3.

## 2026-10-11 (late 5) — R-track: R4 tag-triggered release workflow (issue #3)

**Landed** `.github/workflows/release.yml`: `v*` tag push → bootstrap
(`build.py`) → full gate → package (`make_release.py --apk`) → attach.
`workflow_dispatch` runs everything except the attach (rehearsal that
publishes nothing — dispatch is branch-named, the attach step is
`startsWith(github.ref, 'refs/tags/')`-gated).

**Posture** (tier-2, per tests/README.md § CI): tag pushes require write
access (forks can't trigger — no exfiltration surface); the ROM comes from
the runner's `FFTA_ROM` env var (path outside the workspace, configured on
the runner, never in the repo) and is copied in after checkout for the
corpus regen only; every attached file is content-guarded BEFORE the
release exists (zip: make_release sweep; APK: `--expect public`). Attach
by exact deterministic filename (`FFTARecomp-<tag>-linux-x64.zip` +
`-android-arm64-v8a.apk`) — at a tag, `git describe` is exactly the tag,
and a bare `release-stage/*.zip` glob would also attach stale zips from
earlier local runs.

**Open items** (R5): the release signing key (`gbaKeystore` — debug-signed
until decided), notes content beyond `--generate-notes`, and the runner
label (`self-hosted` assumed — adjust to the actual label if different).

## 2026-10-11 (late 6) — R-track: R5 — first tagged release v1.5 (issue #3)

**Live**: <https://github.com/james2doyle/ffta-recomp/releases/tag/v1.5> —
the first public APK release. Artifacts (both built by `tools/make_release.py`
from the exact tree, both content-guarded before upload):

- `FFTARecomp-v1.5-linux-x64.zip` — sha1 `da7d04db23365ef736fff4e26299c2fa5b9bcc56`,
  45,727,168 B (ROM-less, bring-your-own-ROM)
- `FFTARecomp-v1.5-android-arm64-v8a.apk` — sha1
  `bcc12b1f65b56d6cbcc7b1ed316f7fbc1a15b2e8`, 35,081,167 B (ROM-less, SAF
  setup at first launch; guard `--expect public` 8/8; **debug-signed**)

**Path taken — manual cut, not the workflow**: no self-hosted runner is
registered (`actions/runners` empty), so the `Release (tag)` job from the
v1.5 tag push sits **queued**; the release was cut from this tier-2 machine
where the full pipeline is green. The workflow's attach step was made
idempotent first (`release view || create`, then `upload --clobber`) so the
queued run can never conflict with a manual cut.

**Pre-tag fix (found by reading the runner's flow, not by failing)**:
`build.py` applies framework patches to the submodules, so `git describe
--dirty` inside the job yields `v1.5-dirty` — the attach step's exact
filenames would never match. The package step now pins
`--version "$GITHUB_REF_NAME"`: the tag IS the release version. Also
`-PgbaVersionName` → the installed app's manifest reads `1.5`.

**Determinism, proven twice**: the zip rebuilt after the pull+merge (fresh
checkout-smudged tree) is byte-identical to the pre-merge build
(`da7d04db…` both sides).

**Open decisions carried forward**: APK release signing key (`gbaKeystore`
vs debug key — v1.5 ships debug-signed, so v1.6+ updates need the same key
or a reinstall), runner registration (`FFTA_ROM` env + label
`self-hosted`), R2 Windows stretch (time-boxed, unstarted).

**Result**: fast gate 6/6 pre-tag; release live with both assets
`uploaded`; tier-1 CI on main+v1.5 green-path (same suites the local gate
ran); R2 the only unchecked R-track item.

## 2026-10-11 (late 7) — R-track: R2 Windows exe, built here, attached to v1.5 (issue #3)

**Landed** (the APK flow, verbatim: local toolchain → guard → manual
attach — no CI, no asset repo, nothing over the network): a static
Windows exe (`FFTARecomp-v1.5-windows-x64.zip`, `cf0b5abd…`, 43.5 MB, live
on the v1.5 release alongside the Linux zip and the APK). Zero DLL
dependencies; the launcher boots beside the exe and picks the player's
ROM (issue #3 "bring your own ROM").

**Toolchain** (same-machine cross): `mingw-w64-toolchain` from pacman
(x86_64-w64-mingw32-gcc 16.2.0). MSYS2 is Windows-only and Arch ships no
mingw binary library packages, so `tools/win_cross_deps.py` builds the
static prefix from pinned sources: zlib 1.3.2 + freetype 2.14.3 + harfbuzz
14.6.0 + SDL2 2.32.10 (tarball sha256-pinned, idempotent markers,
`cross-prefix/` + `cross-build/` gitignored). Itches found and encoded:
zlib's own option names (`ZLIB_BUILD_*` — the standards don't apply),
harfbuzz 14.x dropped `fontconfig`, meson NEEDS `--prefix` (its default
`/usr/local` would have poisoned nothing but failed loudly here),
`prune_dynamic()` after every install (zlib builds a shared libz.dll even
with `BUILD_SHARED_LIBS=OFF — an import lib in the prefix would make
freetype link `zlib1.dll` and silently re-add a DLL).

**Game configure**: `tools/mingw-x64.cmake` toolchain file + the engine's
own static-release machinery — `GBARECOMP_STATIC_RELEASE=ON`,
`GBARECOMP_MINGW_PREFIX_UNIX=<prefix>`, and `-static -static-libgcc
-static-libstdc++` via `-DCMAKE_EXE_LINKER_FLAGS` (the engine's comment
says subdir `add_link_options` cannot reach the parent exe; configure-time
cache is the sanctioned path). `FFTA_BUILD_TESTS=OFF`; the 63k-unit corpus
is reused as-is (host-independent C++).

**Determinism — proved twice, failed once.** Failed first: rebuilds moved
(1 byte-field each) because GNU ld stamps TimeDateStamp with the link
time; `--no-insert-timestamp` fixed the header (objdump reads epoch).
Failed again: the **staged** exe moved anyway — `binutils strip` rewrites
the PE `TimeDateStamp` with the *current* time on every run (COFF header
+ debug-dir words; two strips back to back agreed, strips minutes apart
didn't — the fake "strip is deterministic" probe caught). Structural fix:
`-s` at LINK time, never post-link; the zip now reproduces byte-for-byte
across wipe-rebuilds (exe `1ce4117d…`, zip `cf0b5abd…`; the pre-fix
`ab72951f…` / `53b3d225…` / `0c2d6a…` attachments are superseded — v1.5
carries the reproducible one). Cache probe invalidates on flag changes
(`win_configure_needed` lists `--no-insert-timestamp -s`).

## 2026-10-12 — issue #22 research: FFTA hacks/mods/cheats survey (no code change)

Action: web survey of community hacks, ROM patches and cheat sources for
FFTA (USA/AFXE) to scope "Support hacks and cheats" (issue #22). Result:
catalog compiled; comment posted to the issue with user sign-off
(issuecomment-6128615602; Tools/ecosystems section dropped per request).

Findings:
- Every mainstream patch targets the No-Intro USA (AUS) dump — SHA-1
  `4AC05441…` = our pinned `game.gba`. Patch formats in the wild: IPS
  (Lunar IPS), UPS (upset), BPS (beat). Support = patch-apply step ahead
  of recomp + relaxed launcher identity pin for known-good patched
  outputs (the ROM hash-verify at launch currently rejects them).
- Major hacks (all RHDN, game page 1419): Maeson (9373 — full rebalance,
  BPS main + IPS optionals, built on LeonarthCG engine hacks), Secret
  Starters / R-Editions (9062) + Secret Starters Vanilla (9339), TV Mode
  Default (8559 — palette fix, directly relevant to non-GBA displays),
  Advanced Battle (4438 — monster-tame overhaul, UPS), Minor Tweak Pack
  (2078), Anarchy (law remover; RomHackPlaza mirror), FFTA2 music
  insertion (654). Classic forum mods: Grim Grimoire (beta 0.993) and
  Long Night (v0.64) via ffhacktics thread 11997 hub; FFTA X (insane
  difficulty) — host dead, archive.org only.
- Tooling: LeonarthCG/FFTA_Engine_Hacks (Event Assembler buildfile → UPS),
  TojiKitten/FFTA-randomizer, MultiworldGG FFTA apworld (BizHawk),
  spiiin/FFTAUtils, Darthatron editors + Law Remover (ffhacktics 11996).
- Cheats: GameHacking.org (game 4576) GameShark/AR/CodeBreaker DBs; code
  compendia already swept into `reference/ffta-gamefaqs-code-guides.md`
  (verified `gMoney` 0x02001F64 etc.). Cheats are RAM pokes → runtime code
  handler, ROM-hash-independent, but addresses are vanilla-specific.
- Caveat: total conversions relocate code/data → our address-specific
  corpus + game.toml seeds would need per-hack overlays (self-heal covers
  misses but the frozen gates assume vanilla). Hygiene unchanged: link to
  patches, never commit patch/ROM bytes.

Conclusion: support splits into (a) pre-recomp patch application with
format detection, (b) identity handling for patched ROMs, (c) runtime
cheat-code layer keyed to the vanilla RAM map.

## 2026-10-12 (late) — cheat-page deep dive → new symbols (issue #22 fuel)

Action: deep-dived AlmAR CodeBreaker (+22 sub-pages), AlmAR AR,
gamehacking.org/4576, SuperCheats for address-bearing codes; decoded the
raw CodeBreaker/Xploder scheme (`8AAAAAAA VVVV` = 16-bit write to
0x0|AAAAAAA; `42…/0000NNNN YYYY` = multi-write stride YYYY), then
verified candidates by offline GBAS reads (offset +0xFC per the
jokyr-hack-guide live-read note) of state2_prev_20261007_114607 (gMoney
5000), ws_fixtures/world_map (4700) and ws_fixtures/battle_overview.

Results:
- VERIFIED: XP byte = unit-record +0x8A old / +0x0A corrected (slot0
  lvl3/XP18; closes §7's "0x8A — likely XP?"); gMoney 0x02001F64 re-tracks
  5000→4700. REFUTED: AlmAR's 0x02001F54 "money" pair (zero in field while
  money varies). PLAUSIBLE: gTotemaUnlocked 0x02001FB6 u16 bitfield
  (0x0007→0x0807 with progress); gClanSkills 0x020021B6 = 8×u16 — the 8
  "Max Appraise…Track" codes are 8 encrypted writes into it (names set-level;
  order unverified; SuperCheats confirms "smithing" is a dispatch skill).
- NEW SYMBOL: gBattleEnemyUnits 0x02002FD8, 7 slots × 0x108, name-ptr
  aligned, party-identical record layout — pins the battle unit framing
  (EH's gFirstEnemyUnit 0x02002FC4 = same slots framed +0x14). Cheat
  cross-refs: "Instantly Win Battle" zeroes u32+0x14 (=1 everywhere;
  semantics open), "Weaken Enemies" hits +0x04/+0x05 (byte +0x05 ≈ atk
  power: party 80, enemies 10–45). Name-mode +0x186 dispatch re-verified
  on enemies (mode 0 → name-table-B).
- UNVERIFIED (no shop-scene fixture): shop cluster 0x020273C9/CC,
  0x0202745C/60, 0x02024434, 0x02001F6C, mission-info 0x02024A38 — scene
  scratch (0 in field states), code-derived leads only; +0x182 "No Cards"
  reads 0 on all slots (semantics open).

Changes: reference/ffta-gamefaqs-code-guides.md extended (source table,
decode scheme, verdict table); symbols/ffta_data_symbols.tsv §7 notes
amended (XP resolved, +0x94/+0x182 fields, clan-skill names) + §19 added
(gBattleEnemyUnits, gTotemaUnlocked). Validation:
tests/python/test_tools.py TsvGuardTests — 6/6 OK. Symbols are
debug-name-only (no codegen impact); no regen required.

## 2026-10-12 (late 2) — live shop probes pin the shop-stock system (issue #22)

Action: user ran a windowed --tcp-observe session (19870) and transacted
in a shop (buy potion −50, sell bandage +100) while I probed read-only.
Sequence of verdicts — worth recording because two got overturned:

1. First store read: all six "Shops Sell Everything" cells zero →
   hypothesized cheat-private scratch; backed by an exact-address ROM
   literal scan (0 hits; 0x080CEA58 was embedded data). WRONG — the menu
   was closed (only the storefront browse state), and the scan is blind
   to base-relative access.
2. 0x02024420 block looked like a live shop descriptor (count 9, ptr
   0x02024464, fn 0x08017E81) → disasm: blinker/draw UI machinery
   (0x08017F04 toggles +0x11, draw 0x08017E80 reads the 0x02002180
   halfword table). Correct rejection — that block is scene-scratch UI.
3. Post-transaction probe flipped the shop cells live: 0x0202745C = 100
   (sold item price), 0x02027460 = 14×4 {id u16, count u8, pad} stock
   working copy, 0x020273CC = 3 (menu page; cheat conditional gates on
   page 4), 0x02024434 = list length (9 buy menu → 4 after). gMoney
   4700→4750 exact; party inventory slot0 tracked the buy.
4. Decisive disasm: canonical stock array at literal 0x02001EE4
   (= gInventory + 0x5A4); stock-full predicate @0x08061E1C (count==0x63,
   14 slots) and has-stock @0x080680B4. Base-relative access — the exact
   scan never had a chance.

Result: NEW SYMBOLS gShopStock 0x02001EE4 (14×4), gShopMenuStock
0x02027460, gShopMenuPage 0x020273CC, gShopMenuStockCount 0x02024434,
gShopPrice 0x0202745C (symbols § 20). Issue #22: "Shops Sell Everything"
is writable live cells — no injection needed. Method lessons in
reference/ffta-gamefaqs-code-guides.md (superseding section kept for the
record): single-scene reads can't settle engine-vs-scratch; exact-address
literal scans miss base-relative cells — scan region-window bases.
Validation: TsvGuardTests 6/6 OK. Probe discipline held (read-only,
no quit — after the earlier observe-quit mistake).

## 2026-10-12 (late 3) — gMissionInfoPrice verified live; pub work table decoded

Action: user opened the pub mission list (card store story-locked at
gStoryProgress 3 — noted; the "Access Card Shop" cheat bypasses by
opening the UI directly). Hovered "Travel Aid" (400 gil): 0x02024A38
read exactly 400 → **gMissionInfoPrice VERIFIED**, and the value
persists after menu close (last-quote cache — the $1/free cheat
pre-stamps it). Gossip/rumors are free (cell stayed 0 there; user
corrected my menu assumption — the paid menu is mission info).

Also: two full-EWRAM snapshots (menu open / closed) via a recv-loop
client (single recv() fails on 256 KB responses — noted for future
probe scripts). Diff (376 runs) mostly scene render churn; the block
0x02024A40.. decodes as the pub scene's runtime pointer table:
~16 mission-record ptrs (0x020021C8-0x02002378), party-unit ptrs
0x02024A80.. (0x02000290 + i×0x108 = gPartyUnits slots 2..23),
gMissionItems ptrs — scene scratch, rebuilt per scene, unnamed by
design. Byte 0x02024A2D (01→02 on close) = single-transition lead.

Changes: symbols § 20 (gMissionInfoPrice entry + stale-lead note);
reference/ffta-gamefaqs-code-guides.md section. TsvGuardTests 6/6 OK.
Remaining uncovered: 4 (+0x182 cards, clan-skill order, u32 +0x94,
byte +0x05, multi-write slide → battle/roster-scoped next).

**Gates** (all live, all green): objdump import table = 29 system DLLs
only (forbid-list: SDL2, libstdc++-6, libgcc_s_seh-1, winpthread, freetype,
harfbuzz, zlib DLLs — none present); sweep (same ROM/BIOS/binary hash
rules, exe-named); deterministic zip; wine boot smoke from the bare
extraction: FULLY_STATIC dispatch_misses=0 interpreted_insns=0. ReleasePackTests
+4 (windows sweep roundtrip + static-guard core): 44 → 48.

**Limits, stated**: no CI (the ROM stays on this box — the standing
posture; the GitHub-CI variant stays feasible via the scene-standard
private-ROM-repo checkout whenever that policy changes); wine is a boot
smoke, not a device-verified run (a real Windows launch on a player's
machine is the one remaining untested mile).

## 2026-10-12 (late 4) — TojiKitten/FFTA-randomizer survey → symbols §22 + data §21

User asked: survey https://github.com/TojiKitten/FFTA-randomizer (MIT
Electron tool that patches retail AFXE at hardcoded file offsets; their
offset + 0x08000000 = our GBA address) for facts useful here. Cloned to
/tmp, three parallel read-only subagents (data tables / engine hooks /
history), then every candidate re-verified in-repo: prologue disasm with
tools/disarm.py, table bytes + boundaries against game.gba. Evidence lives
in the symbols-file §22 header and the data-file §21 header.

Folded in (all verified):
- 9 function names (§22): 0x080C9574 job_discovery_flag_set — resolves the
  §21 backlog item (bit set/clear at EWRAM 0x02001F70, bit = id&7, from
  their discoverJobMemory + our disasm); 0x080C9340 new_game_job_discovery
  (their hook NOPs its 16-id retail sweep); 0x08030044 location_state_set;
  0x081426B8 signed_divide; 0x08097704 battle_animation_setup_helper;
  0x080CA078 party_level_scan; 0x080CF7F4 clan_record_scan; 0x08043F90
  world_map_flag_set; 0x08021004 character_animation_set_get.
- 9 data symbols (§21): 5 race-ability tables 0x0851BB6C..0x0851CA9C
  (8 B rows, sizes 0x460/0x260/0x2F0/0x2A0/0x2B8 — rows field-checked,
  blocks tile exactly); gAllowedWeaponTypeMasks 0x0851D0F4 (0x8C; ends
  exactly at item_data_getter base 0x0851D180); gItemAbilitySets 0x08520080
  (0x76C, 95 rows by row-structure scan — lower bound); gTextItemNames
  0x08526680 (753 ptrs, all in-ROM, [753]=0); gBattleFormations 0x0854D1A0
  (0x40B0, 414 records field-validated; [0].memberPtr = gStartingParty
  0x0852CDE0).

Gotcha logged: a --symbols name LOSES to an existing [[extra_func]] seed at
the same address (seed_by_key keeps the first entry; the finder only adopts
a seed's non-empty name). Fix: name the extra_func in game.toml — done for
0x08021004; keep this in mind when a §-added name fails to appear.

Result: cycle PASS — 63134 emitted, unchanged; check.py ALL PASS 15/15 with
FULLY_STATIC dispatch_misses=0 on route_B/G/K + user_load, ws smoke ok;
attract hash unchanged (1EF4C118…). All 9 names + 9 data symbols present in
generated/symbol_map.cpp + data_symbol_map.cpp. Names are metadata only —
no behavior change observed, as expected.

Caveats: item-ability row count is a lower bound (first non-conforming row);
the 414-formation count is their table-map value (all rows validated, end
boundary not independently confirmed); randomizer table offsets are file
offsets — cite as +0x08000000. Their ROM check is only "AFXE" at 0xAC (no
hash/version branch); our strict SHA-1 identity gate stays.

## 2026-10-12 (late 5) — clan-menu scan: clan counters staged in the save record

User opened the clan menu ("clan points: 85, freed areas: 7, missions:
71"); full-EWRAM scanning + save-stage mapping found no clean live cluster
in low EWRAM, but the save staging window carries them:

- stage+0x2037 (0x02003CB0+0x2037 = 0x02005CE7) = 0x55 (85) — clan-points
  candidate (byte; stable across two snapshots).
- stage+0x203E (0x02005CEE) = 0x07 — freed-areas candidate (byte).
- neighbours open: stage+0x2036 = 0x01, +0x203F = 0x06, +0x2041..0x2044 =
  03 07 00 26.
- Older fixtures (state2, world_map) read 0 there — values appear only
  after a save-load (staged copy); live-vs-copy unresolved.

"missions: 71" unresolved: every clean 71 hit was a per-mission record
field (mission-record area 0x02002350+); count may be derived (bit-popcount)
or stored elsewhere — open.

## 2026-10-12 (late 6) — live class-change diff: unit-record fields + gInventory equipped byte (issue #22 fuel)

Marche changed class in the running session (Soldier -> Thief); read-only
TCP probes (port 19870) diffed full-EWRAM snapshots before/after. Snapshots
kept in the session /tmp only (ROM-derived; not committed).

Exactly 14 bytes changed across all 24 unit records — every one in slot 0
(record base 0x02000080, stride 0x108; offsets record-relative):

- +0x07: 0x02 -> 0x05 — active job id. Names decoded via the ROM name
  table (job record +0x00 name id -> 0x08526680): 0x02 Soldier, 0x05 Thief.
  Decomp doc: "the job-change routine always writes the selected job here".
- +0x2A..+0x33: five equipped-item u16s cleared to 0 — Silver Sword 0x0002,
  Gold Armor 0x0124, Choco Shield 0x0106, Headband 0x0118, Battle Boots
  0x0153. Inventory side: exactly those five gInventory entries' +3 byte
  decremented by 1; count byte unchanged.
- +0x35: 0x02 -> 0x18 — mirrors the new job record's +0x10 (decomp:
  "A-ability index"); holds 24/24 slots, both snapshots.
- +0x45: 0x8C -> 0x0C — one byte of the ability-state array (bit 7
  cleared); semantics open.
- +0xFE..+0xFF: 0x02/0xFD -> 0x03/0xFC — movement profile tail [.., J, ~J];
  J = effective jump = job+0x29 + sum(equipped item +0x17); ~J = bitwise
  complement; both 24/24. (+0xFC=01, +0xFD=02 constants.)

Cross-checks (live roster, two snapshots; against charlie-troy/ffta-decomp
docs, same ROM): +0x04 type (1 ordinary path; 2 Marche / 8 Montblanc),
+0x05 base job (story units hold 0x50/0x52 proxy records; generic ==
active; unchanged by the change), +0x06 race (1..5 = Human/Bangaa/Nu Mou/
Viera/Moogle), +0x34 race ability count (0x8E/0x4D/0x5F/0x55/0x58 =
142/77/95/85/88; decomp "Human's 142 entries").

gInventory live-refined: stride-4 {id u16, count u8, equipped u8}; the +3
byte == copies equipped across the roster (exact for every entry, 0
mismatches) and -1 per copy unequipped. 143 entries in use at capture;
trailing zeros to gShopStock @+0x5A4. (Corrects the § 17 "14x4" line; a
working cap at 0x1AD0 had hidden slots >100.)

All other diff hits were menu/UI work areas and the shared save-stage
scratch window — no other unit-record or inventory bytes changed.

Leads: (a) all five equipment slots cleared — incompatibility-filter vs
full strip unresolved (second class-change sample needed); (b) +0x45
bit-7 semantics; (c) exact 0x108 record mirror at 0x02010F9C (zero before
the change) + preview block ~0x020110A4 — purpose unverified, not
symbolized; (d) § 21 race blocks: start-to-next-start spans are one row
(8B) longer than the listed sizes (Human two) with a zero last row; +0x34
counts match the spans — flagged, sizes left as imported.

Files: symbols/ffta_data_symbols.tsv (§ 7 + § 17); symbols/ffta_symbols.tsv
(accessor comment). TsvGuardTests 6/6 OK. Comment-only — no codegen impact.

## 2026-10-12 (late 5) — Issue #11 speed toggle: Assist surfacing + touch pill latch

Request: virtual touch button + physical button for speed boost, optionally a
settings value. Locked decisions with user (via question tool): keep physical
defaults (`Tab` + `2` + right-trigger), keep `4x` / `2-10x`, fast-forward
only (no Rewind), FFTA-local overlay pill with tap-to-latch, minimal engine
seam. Investigation report + step plan posted to the issue; plan comment:
#11#issuecomment-6132105925.

Findings that shaped the work: the engine already implements fast-forward
(pacer bypass, 1/N presents, audio mute; `runtime.cpp` assist block) with
TWO hold paths (Tab `[KeyMap] Turbo` + Assist `2`/RT) and a latch + speed
UI — all hidden because FFTA never set `expose_assist_tools`. The touch pad
only carries the 10 GBA inputs (`pad_buttons_at`), and pad touches never
reach TouchHub (consumed first), so a new control needs its own hub-observed
surface. A draw-only `host_overlay` cannot drive the pacer — hence the seam.

Changes:
- Phase 0 (`src/main.cpp`): `opts.expose_assist_tools = true` — launcher
  Assist page (bindings + speed slider) + in-game Fast-forward latch/speed
  rows. Rewind suppressed (`rewind_history_seconds` stays 0). Known wart:
  the launcher still lists a Rewind binding row (engine hardcodes both
  rows); the binding is inert without history.
- Seam (`gbarecomp/src/runtime/runtime.h` + `runtime.cpp`, carried as
  `tools/patches/speed-toggle-ff-seam.patch`, consolidated re-exported):
  `RunOptions::fast_forward_request` polled once per pump and ORed with
  hold/menu latch under the shared Assist gate. Null elsewhere: byte-identical
  path. Patch verified forward-on-pristine-pin + reverse-on-dev (check.py
  `patches` enforces both).
- Pill (`src/ffta_speed_boost.{h,cpp}`, wired in `main.cpp` + both CMake
  game targets): top-center "FF" pill (15x5.5 mm, clear of L/R shoulders),
  press-to-toggle on new-pointer Down edges via `TouchHub::points()`, gold
  fill while latched, 15 s hub-idle hide mirroring the pad (Android starts
  visible; desktop appears on first touch), latch clears after a 5 s present
  gap (background/suspend never wakes boosted), 15 ms haptic tick on toggle.
  Pure geometry/edge logic is header-inline and unit-tested
  (`tests/unit/test_speed_boost.cpp`, aggregated in `test_ram_dispatch.cpp`).
- Drive-by fix (`build.py step_patches`): consolidated `*-local.patch`
  files apply first. Fresh-clone bootstrap was broken — per-feature files
  applied before the consolidated patch, after which it no longer applied
  forward (reproduced against a pristine archive). Reordered application
  simulated clean: consolidated applies, all 15 others in-place skip.

Gates: `cycle.py` PASS (63134 emitted, unchanged; attract `1EF4C118…`
unchanged); `check.py` ALL PASS 15/15 (unit-cpp PASS incl. new tests;
patches replay byte-matches 431-file tree; routes B/G/K + user_load
FULLY_STATIC; hangrepro/desktop-accept/hle-audit green).

Remaining: device feel pass (pill placement/size under thumb, haptic
sanity) + a windowed launcher Assist-page screenshot; both need a
phone/GUI session, not done headless. Long-press on the pill still opens
the settings menu (unclaimed gesture, same as any screen tap) — accepted.

## 2026-10-12 (late 6) — Issue #11 device validation: pill PASS on phone

Device: user's Xiaomi (codename `mars`, panel 1440x3200@560 — note: NOT the
Poco X3 Pro the codename suggests; all geometry driven live off `wm size` +
boot log, so the mismatch cost nothing). Private ROM-included APK rebuilt
with the #11 work (`build_apk.py` DONE 162.8 s: build + content guard +
install + boot gate, all green), then a fresh observe session
(`debug-args.txt --tcp-observe 19888` via run-as quoting
`adb shell "run-as … sh -c '…'"` — bare `adb shell run-as … sh -c` gets its
quotes stripped and lands in `/`).

New gate: `tools/android_pill_test.py` (device-only, like the other
android_* tests — not in `check.py`): screenshot + `run_status` frame-rate
state machine over the observe TCP. **PILL-TEST PASS 7/7**: boot dark pill
@60/s → tap pill: GOLD pill @174/s (latch engages) → tap pill: dark
@58/s (latch releases) → control tap away: still dark (no spurious edge).

Test-method findings (all folded into the script's docstring):
- Scripted `touch_tap` never releases on policy-less games: steps drain
  through `run_touch_policy`, installed only when `opts.input_frame` is set
  (FFTA: none) — taps sat in `script_pending` forever. Immediate
  `touch_down/up` (direct `hub.submit`, no drain needed) is the working
  path. Same reason gesture recognition/long-press timers don't advance
  without a policy — pre-existing engine behavior, out of scope.
- Holds must stay SHORT (0.25 s): a 1 s hold crossed the 450 ms long-press
  threshold and opened the runtime menu, which then ate later taps modally.
  (That failure incidentally proved Phase 0 on-device: the menu shows the
  new Assist Tools section.)
- Geometry must come LIVE from `touch_status` (`px_per_mm` 20.267, insets
  137,105,0,112): the boot log prints pre-JNI density (22.05) and unsettled
  insets (0s). The pill honoring live safe insets is correct behavior.
- `adb shell input tap` unneeded throughout; TCP injection bypasses the
  ROM's OS tap filtering entirely.

Visual: gold "FF" pill top-center confirmed on-device screenshot (clear of
L/R shoulders, pad + game scene behind); user's own verdict: "the pill
seems fine". Remaining #11 items: launcher Assist-page windowed screenshot
(desktop GUI session) and the noted Rewind-row wart (upstream proposal).

## 2026-10-12 (late 7) — Issue #14: left analog stick doubles as the D-pad

Request (issue #14): allow the left analog stick to also act as the D-pad
(standard emulator courtesy; every GBA game is d-pad driven).

Prior state: gameplay controller input was a fixed SDL button list in
`gbarecomp/src/runtime/host_window.cpp` (`HostWindow::pump`'s `pad_map`:
A/B/Back/Start + DPAD + shoulders) with no analog path. Keyboard binds come
from keybinds.ini; recomp-ui's per-GUID pad store is SNES/N64/PSX-only (the
GBA profile explicitly has no analog vocabulary). The only stick→d-pad
precedent in the tree was the dev frontend
`gbarecomp/tools/gbaref/frontend.cpp` (DZ=16000), never linked into the game.

Changes (framework carried as `tools/patches/stick-to-dpad.patch`;
`gbarecomp-local.patch` re-exported, 431-file replay byte-match):
- `gbarecomp/src/runtime/input_synth.h`: new pure
  `stick_to_dpad(axis_x, axis_y, deadzone)` → active-high GBA d-pad bits;
  SDL axis convention (-32768..32767, up/left negative); a direction fires
  strictly beyond `deadzone`; diagonals set two bits.
- `gbarecomp/src/runtime/host_window.cpp`: the controller block now ORs the
  stick directions into the active-low KEYINPUT mask (25% deadzone = 8192),
  additive with the physical d-pad, keyboard and touch. 25% ignores worn
  stick drift while staying menu-responsive (mGBA-style default); gbaref's
  16000 is a dev-tool threshold, too stiff for gameplay.

Evidence:
- Unit: `tests/unit/test_stick_dpad.cpp` (deadzone boundary semantics,
  cardinals, diagonals, custom/zero deadzones, axis extremes) aggregated
  into `ffta_unit_tests` behind the usual pristine-checkout probe.
- Physical controller: user-verified in a windowed session with this build
  ("works perfectly" — stick drives menus/movement, d-pad unaffected).
- Synthetic-pad e2e attempt (uinput pad with Xbox 360 IDs +
  SDL_GAMECONTROLLERCONFIG, `/tmp`-only tooling): SDL enumerated/opened it
  and a live SDL probe read the axes, but an in-game
  `GBARECOMP_INPUT_RECORD` trace showed no KEYINPUT changes — unresolved
  quirk of the synthetic path only (the physical pad works). If a future
  harness wants uinput input tests, start from that known gap.

Testing note: an earlier user session (real pad, launched with
`--view-width 320` — the open issue #23 area) appeared hung and was closed
before read-only probing; no crash dump, not attributed, not part of this
change. The verified run was without widescreen.

Gates: `cycle.py` PASS (63134 emitted, unchanged; attract `1EF4C118…`
unchanged); `check.py` ALL PASS 15/15 (unit-cpp PASS incl. the new test;
patches replay byte-matches the 431-file tree; routes B/G/K + user_load
FULLY_STATIC; hangrepro / desktop-accept / hle-audit / ws_smoke green; the
windowed acceptance skipped on the concurrent-run lock, as designed).

## 2026-10-12 (late 8) — R-track: v1.6 cut (issue #3; carries #11 + #14)

Tag `v1.6` = `789fac6` (the issue #14 commit), pushed; a **draft** release
("FFTARecomp v1.6") was cut on james2doyle/ffta-recomp with curated notes
(speed boost #11 incl. the FF pill, analog stick #14, Controls docs, #22
symbol research, #3 release tooling). The tag-triggered workflow is still
runner-less/queued, so this is a manual tier-2 cut like v1.5; the workflow's
`release view || create` + `upload --clobber` remains idempotent against it.

Artifacts built from the tagged tree by `tools/make_release.py` (all
content-guarded ROM-free; assets attached to the draft, hashes in its notes):

- `FFTARecomp-v1.6-linux-x64.zip` — sha1
  `92a4eb9f9ed34b28cc32b3af29f5e554ea0ed067`, 45,745,653 B
- `FFTARecomp-v1.6-windows-x64.zip` — sha1
  `d95641736716523f66dc376fc6665a2d88a80897`, 43,553,223 B (static
  imports=29; built-in smoke FULLY_STATIC)
- `FFTARecomp-v1.6-android-arm64-v8a.apk` — sha1
  `f8f17191a80568fee996a790254198d8d4538066`, 35,078,819 B (guard
  `--expect public`; manifest `versionName='1.6'` confirmed via aapt;
  still **debug-signed** — v1.5→v1.6 updates need the same key or a
  reinstall)

**Determinism, re-proven**: the `--apk` pass rebuilds the Linux zip first —
byte-identical sha1 `92a4eb9f…` both times.

**Not in the repo**: the cut used throwaway orchestration scripts in `/tmp`
(three `make_release.py` calls + a notes-table formatter); the canonical,
tested machinery stays `tools/make_release.py` (+ guards). Release left as
a draft for publish review.

---

## 2026-10-12 (late 9) — Issue #16: `.recomp.json` (recomp.board identity file)

Added `.recomp.json` at the repo root, per https://recomp.fyi/spec
(schema v1; readers fetch it from the default branch root). recomp.board
currently lists this repo with a script-guessed row ("Final Fantasy
Tactics Advance / GBA / recomp / Gbarecomp", no project, status or
targets) — the file is the project's own word and supersedes the guess
once it is on `main`.

- `game` "Final Fantasy Tactics Advance"; `project` "FFTA Recomp"
  (matches the repo slug `ffta-recomp`; same name AGENTS.md uses);
  `wikidata` Q1072868
  (Wikidata search API 2026-10-12: "Final Fantasy Tactics Advance", 2003
  video game); `system` "GBA"; `type` "recomp"; `original` {region USA,
  serial AFXE, sha1 `4ac05441…`} — all pinned in `game.toml` (§ Phase 0).
- `status` "released" (public v1.5/v1.6 builds, still maintained);
  `targets` ["Windows", "Linux", "Android"] (the three v1.6 release
  assets); `toolchain` "gbarecomp"; `maintainers` J. Doyle (GitHub link);
  `links` releases page + repo + R.A.I.D. Discord (owner selection).
  `help` omitted by owner decision (no "wants help" marker on the board).
- `original.revision` omitted deliberately: software-version byte 0xBC = 0
  (direct byte inspection 2026-10-12 — initial release), but the project
  has not adopted a community revision label; per spec a missing field
  means "not said", never "none".
- Validation: `jsonschema` (draft 2020-12) against `schema/v1.json`,
  pass; `.venv` lacks the package, system python3 used.
- Metadata-only: no `game.toml`/`src/`/`generated/` change, so workflow A
  is not invoked; the `tools/make_release.py` allowlist is untouched (the
  file is repo identity, not a release artifact).

---

## 2026-10-12 — Issue #20: .sav picker on Android (desktop parity)

The desktop launcher has a battery-save row (Import SRAM save, `*.srm`/`*.sav`);
Android's setup screen offered only ROM + BIOS, so a player with a desktop /
emulator save had to `adb push` to the external saves/ dir by hand. The setup
screen now offers an optional third card, "Save data (optional)", through the
same SAF picker.

Engine (shared shell, carried as `tools/patches/android-save-picker.patch`;
`gbarecomp-local.patch` re-exported, 431-file replay byte-match):

- `platform/android/gbarecomp-app.gradle`: optional `saveFile`/`saveSize`
  game keys → manifest placeholders `gbaSaveFile`/`gbaSaveSize` (empty = no
  card; pinned size e.g. 65536, else any non-empty ≤128 KiB).
- `platform/android/AndroidManifest.xml`: `gbarecomp.save_file`/`save_size`
  meta-data.
- `platform/android/java/org/gbarecomp/GbaGameConfig.java`: `saveFile`/`saveSize`
  fields (safe parse, defaults ""/0).
- `platform/android/java/org/gbarecomp/GbaSetupActivity.java`: `PICK_SAVE`,
  `hasSaveImport()` gate, third asset card, `refreshStatus()` checks
  app-private `saves/` OR external `saves/` for validity, `setBusy()` covers
  the new button, and `installVerifiedSave()` size-validates (exact when
  pinned) then dual-writes to app-private + external `saves/`. Dual-write is
  the point: the runtime (issue #6) reads `--save-path` in external storage,
  so an internal-only write would strand every re-import after the one-time
  outward migration. A failed external mirror is non-fatal (internal still
  migrates on next launch). `ready()` never consults the save — PLAY stays
  one tap for a fresh start.

Game side:

- `android/app/build.gradle`: `saveFile: "ffta_us.sav"`, `saveSize: 65536`
  (basenames match `game.toml`/`game_android.toml` `[save]`; enforced).
- `tools/android_static_check.py`: new `check_save_picker_wiring` (pins across
  build.gradle + both TOMLs, engine tokens in tree-or-recorded-patch,
  `ready()` must not gate on the save, dual-write `copyFile` present).
- `android/README.md` § Saves & states: setup-import paragraph; `tools/patches/
  README.md`: new patch row.

Gates: `android-static` 23/23 PASS (incl. the new check), `patches` PASS
(per-feature forward-ok to the pin + consolidated 431-file replay match).
No `game.toml`/`src/`/`generated/` change, so workflow A is not invoked;
device verification is the standard `validate_android.sh` + a manual
CHOOSE SAVE → REPLACE SAVE → PLAY pass on next device contact.

---

## 2026-10-12 (late 10) — Issue #20 device-verified: .sav picker works

User-verified on the M2102K1AC (Android 14): after `pm clear`, the public
debug APK's setup screen shows the third card, "Save data (optional)";
CHOOSE SAVE on a 64 KiB save flips it to `● Verified and ready` / REPLACE
SAVE, and PLAY boots into the save ("worked perfectly"). PLAY stays ungated
without a save (fresh start), as designed.

Test path notes (for the next device contact):

- The **private** ROM-embedded APK can never show the card:
  `hasBundledPrivateAssets()` short-circuits setup straight into the game.
  Testing used the **public** `app-debug.apk` (`assembleDebug` without
  `-PprivateRom`; `android-apk --expect public` OK) + `pm clear`, with
  `game.gba` and a 64 KiB `game.sav` pushed to Download for the SAF picks.
  The merged manifest confirms `save_file="ffta_us.sav"` / `save_size="65536"`.
- `build_apk.py`'s device gate flaked on the first post-install run (launch
  race: pidof empty, game activity not resumed) and then passed **5/5 GATE
  PASSED** on re-run with no changes — same class as the known
  install-settle race, not the save code (a manual AUTOSTART launch in
  between also passed cleanly).
- Preflight note: `build_apk.py` refused the first build (`generated/ corpus
  is stale` — `android/app/build.gradle` is a freshness input newer than the
  stamp). The corpus inputs (`game.toml`, symbols) were untouched, so the
  recompiler was re-run directly (byte-identical output, no tracked diff)
  and the stamp touched, rather than faking freshness.

---

## 2026-10-12 (late 11) — Issue #24: overlay list scrolling (nav follow + touch drag)

Player report: with a controller the overlay's menu does not scroll as the
selection walks down it, and on mobile a swipe does not scroll (you have to
drag the bar on the right). Root-caused to the **recomp-ui** runtime settings
menu, not the FFTA host, by reading the presentation and then measuring it:
`recomp-ui/src/common/backends/imgui/runtime_ui_imgui.cpp` builds the two
list children (`##sections`, `##items`), the host owns the selection
(`recomp_runtime_ui_handle_input` from `host_window.cpp` `runtime_ui_event`),
and the menu runs `ImGuiWindowFlags_NoNavInputs` so ImGui's own nav never
scrolls. Nothing else did — a list child scrolls only from the wheel or by
dragging its scrollbar, and recomp-ui's SDL backends hand fingers to ImGui as
a mouse, so a swipe was a click-shaped no-op.

Reproduced at the ImGui level with a standalone driver (`/tmp`, not committed;
same geometry as the real menu — 2400x1080 touch-friendly, 7 described rows in
"Assist Tools", list inner 745 px, `ScrollMax.y=284.4`): six D-pad DOWN presses
("row 0 → row 6") left `Scroll.y` at 0.0 the whole way (the last two rows sat
`284 px` below the fold), and a 240 px finger drag moved `Scroll.y` by 0.0.

Fix, carried as `tools/patches/recomp-ui-local.patch` (215-file replay
byte-match; per-feature forward-ok against the pin `cac2b8f`):

- **Follow the selection** (`follow_selection`): when the selection actually
  moved, scroll by the least amount that brings the row into view — both the
  section sidebar and the rows list, both layouts, both presentations'
  selection sources. Only on change, so a player who scrolled away keeps
  their position; `recomp_runtime_ui_open` forgets the last follow so the
  opening frame can bring the selection back.
- **Touch drag-scroll + fling** (`begin_list_drag`/`end_list_drag`, enabled
  only for `RECOMP_RUNTIME_UI_PRESENTATION_TOUCH_FRIENDLY`; a desktop drag
  stays a click and keeps the wheel): 10 px threshold, velocity coast with
  `exp(-5/s)` decay. While a drag owns the pointer the rows ignore hover and
  clicks, so a swipe cannot activate the row it started over; presses on
  `-`/`+`, the edit field, `< Back` and the scrollbar strip are left to their
  own widgets, and any new press stops a coasting list.
- Presentation state lives in the model (`RecompRuntimeUi::list`,
  `-1` = none) rather than a file-static, since the model is already where
  `editing_text` lives; `recomp_runtime_ui_create/close` reset it.

Three ImGui details that cost iterations and are worth keeping (all verified
in this pin, `1.91.9b`):

1. `IsWindowHovered()` is **false** at the end of the child on the press
   frame — the row under the finger has just become `g.ActiveId`, and the
   default flags return false when an active item blocks. The claim needs
   `ImGuiHoveredFlags_AllowWhenBlockedByActiveItem`.
2. Inside a *scrolled* child, `GetCursorScreenPos()`/`GetContentRegion*` mix
   scroll and screen space (measured: cursor y 893 in a child whose window
   rect is `[148..893]`), so the list's scrollable band is measured from
   `GetWindowPos()`/`GetWindowHeight()`.
3. A `SetScrollY` lands in the child's **next** frame
   (`Begin`→`CalcNextScrollFromScrollTargetAndClamp`), i.e. one frame of lag;
   tests must render two frames per press before asserting.

Tests/gates: new suite `ui-tests` (`tools/ui_check.py`, 2 binaries, ~12 s
cold / instant cached, needs only a compiler — added to `FAST`, to the
`patches` doc rows and to the CI subset in `.github/workflows/ci.yml`).
`recomp-ui`'s `tests/runtime_ui_imgui_test.cpp` gained `list_scroll_case`
(nav follow + wrap back up, 120 px swipe scrolls without activating, coast
then stop, a tap still toggles) and `desktop_nav_scroll_case` (nav follow;
a desktop drag must NOT scroll). Fresh-clone simulation: with the changes
stashed, `ui_check --force` passes on the pristine pin (12.2 s), so CI stays
green; the patched behavior is covered locally. `check.py --only
unit-cpp,unit-py,ui-tests,patches,android-static` ALL PASS (5/5), and the
**full `check.py` ALL PASS (16/16)** on the rebuilt binary — attract hash
unchanged (`1EF4C118A8438CADE6E5847DC6716A7A800D157A568DECB272F2F7052EF321C1`),
all four strict route replays FULLY_STATIC, `ws_smoke` PASS (6 cases x 3
widths), `hle-audit` OK, `desktop-accept` PASS (the windowed twin skips
under the acceptance lock, as designed). `FFTARecomp` rebuilds clean against
the patch.

Device: the release APK built from this commit
(`tools/make_release.py --apk`, `FFTARecomp-v1.6-6-g521fba7-dirty-android-
arm64-v8a.apk` sha1 `16902cbf57bc5e82e698b49b5301f9cf3ba69266`, guard
`--expect public`) was installed on the M2102K1AC (device `base.apk` sha1
matches the host artifact byte-for-byte) and the boot gate passed
(`tools/validate_android.sh --no-install`: 5/5 assertions, evidence in
`android/artifacts/last-run`). **Player-confirmed on the device: the
settings overlay now touch-scrolls** (issue #24 closed behaviorally; the
pre-fix build needed the scrollbar). Release note: `build_apk.py`'s
preflight refused the first attempt — `android/app/build.gradle` is a
freshness input and the issue-#20 edit left it newer than
`generated/.regen_stamp`; `tools/cycle.py` cleared it (regen 63134 units,
byte-identical, attract hash unchanged) as in the issue-#20 session.

Landing: not upstreamed. `recomp-ui` upstream master is 39 commits ahead and
still has no scroll handling, so the patch is not subsumed; the README
records it as a `mstan/recomp-ui` PR candidate alongside the `gbarecomp` set.

## 2026-10-12 (late 12) — Render-path cadence audit: NO compute-at-60/read-at-30 split (symbols § 23)

Question (issue #9 follow-up, MKSC route): does ffta's render path have a
compute-at-60/read-at-30 split — state computed at 60 Hz but only read into
the presented frame every other frame (the MKSC shape: its track-60fps
manifest says "Updates the affine-rendered track every frame instead of
every other frame") — so that a ~15-byte ROM patch would unlock 60 fps
presentation? **No. The render path is 60 Hz end to end; there is no
every-other-frame read gate to patch.**

Render path (disasm, all thumb, tools/disarm.py):

- Scheduler: `crt0_frame_loop` 0x08000364 -> gate 0x08003A2 -> spin on the
  tick flag 0x03000E10 (set unconditionally at the tail of `vblank_callback`
  0x080004B0) -> `game tick` 0x08003F10 + `frame_step` 0x08000460. One
  iteration per VBlank = 60 Hz.
- OAM staging double buffer: composers write 8-byte entries into
  parity-indexed slots (accessor cluster 0x08001BBC-0x08001CC6:
  `table[parity]` get/set + `base + parity*stride` base getters; strides
  0x180/0x400/0x100/0x80 -> the four gOamStage* families). `frame_step`
  resets the slot (`oam_stage_reset_a/b` 0x08001194/0x08001244: plant
  `count` hidden OAM records 0x00F800A8/0x00000000, zero the counts, thunk
  call through `bx_r2_veneer`) and toggles BOTH parities
  (0x08001CD0/0x08001CE0, eor #1). `oam_stage_apply` 0x080012BC (per
  VBlank) fills 0x07000000 with 0x80 hidden records then DMA-copies the
  composed entries of the OPPOSITE slot (1^parity) into OAM (SAD = slot
  entry, DAD = OAM+off, CNT = 0x84000000|words, busy poll).
- Display regs: the BG scroll is written straight into `gDisplayRegShadow`
  0x03000942 through per-BG {cnt,hofs,vofs} pointer descriptors
  (0x03000E60/0x03000E80, init 0x0800323C) and committed by
  `display_regs_commit` 0x08000718 (Section 13) every VBlank — gated only
  by `if tick != 0 -> skip` at 0x080004C8-0x080004D4 (lag guard; the OAM
  apply right after it is unconditional).

Evidence (live, `--tcp` run_frames n=1 + reads; game.state1 battle-overview
pan with Right held; probe scripts /tmp/opencode/cadence_probe.py +
cadence_sweep.py — candidate tools/ additions):

- parities toggle 0.99/step and gVblankCounter 0x03000EB4 +1/step: every
  stage runs once per VBlank.
- BG2HOFS/BG3HOFS move 0x12 px per frame, MONOTONIC every frame (no
  A,B,A,B double-write); BG0VOFS drifts on a sub-pixel accumulator
  (1,2,2,2,1... steps = 60 Hz fixed-point animation).
- Per-address update-cadence sweep of IWRAM+OAM+PAL (159 steps) and VRAM
  (129 steps): ZERO bytes at exact 0.5 cadence. Near-0.5 hits are eased
  motion with pauses (value traces show runs, not alternation).

Conclusion for issue #9: option 3 (game-side render-rate decoupling) is
moot — ffta already presents at 60 fps; interpolation/blending (options
1/2) remain the levers. The only conditional on the present path is the
lag guard above (cmp+bne, 4 bytes at 0x080004CC) — unconditional commit is
a 4-byte NOP patch, only meaningful under main-loop lag, and it is NOT a
30 Hz split.

Symbols (names-only): ffta_symbols.tsv § 23 — `oam_stage_apply`,
`oam_stage_reset_a/b`, `vblank_task_service` 0x08000438 (runs the priority
4/1 queues: vblank_task_runner(0x03000880,4)+(0x030027E0,1)); the parity
toggles renamed the § 1 `sub_08001CD0`/`sub_08001CE0` rows in place.
ffta_data_symbols.tsv § 22 — gOamStageParityA/B (renames of the § 1
gUnk_03000028/gUnk_03002F58 placeholders), the eight gOamStage* count/
slot buffers (sizes measured from the accessor strides), gVblankCounter
0x03000EB4 (u16, +1/vblank; read 0x0813AFA8), gBg0RegPtrs/gBg2RegPtrs
(BG1/BG3 unlocated; 0x03000990 takes the BG3 triple at 0x08003282 but has
~300 refs — deliberately unnamed). Suggested duplicates dropped:
`rand_next`/`bx_r2_veneer` already exist as `rng_next`/`bx_r2_veneer` § 21
(new facts folded into the § 23 note instead: rng_next runs once per
frame_step at 0x08000476 and is the Phase-4 LGC 0x41C64E6D/12345 over
gRngState). Pre-existing defect flagged, NOT touched: ffta_data_symbols.tsv
lists 0x085680DC twice (gTextRandomUnitNames § 1 vs gNamePtrTableB § 12,
2026-10-08 resolver tables — same bytes, two views; the TsvGuardTests
allowlist already tolerated it). Resolved in the next entry.

Acceptance (names-only): `tools/cycle.py` PASS — regen discovered 63134 /
emitted 63134 (corpus unchanged), dispatch sanity OK, build OK, attract
gate PASS frames=1200 sha256 1EF4C118A8438CADE6E5847DC6716A7A800D157A568DECB272F2F7052EF321C1
(byte-exact vs pin). `check.py` not re-run (names cannot change codegen;
cycle covers regen+build+attract) — run with the next behavior-touching
change. Unnamed leftovers from this audit, for a later pass: the composer
0x08001CF0 (8-arg, parity-indexed writes; body unpinned), the game tick
0x08003F10 (scene dispatcher; role partly pinned), and the seal/compose
interleave question (the reset fill runs on the slot the composers write —
order vs the compose call is unpinned).

## 2026-10-12 (late 13) — Both audit threads closed: 0x085680DC dedup + cadence_probe as a gate

**Thread 1 — the 0x085680DC double-listing, ruled.** The two rows were
`gTextRandomUnitNames` (§ 1, ffta-decomp import 2026-10-07) and
`gNamePtrTableB` (§ 12, the 2026-10-08 name-resolver tables — NOT the
TojiKitten import as late 12 said; corrected there). TsvGuardTests already
tolerated it in its 4-entry duplicate allowlist ("same bytes, two views").
Ruling: **`gNamePtrTableB` wins, the decomp's name stays as an alias.**
Evidence: the consumer `name_ptr_resolve` 0x080CA1BC dispatches on
record+0x106 (mode 1 -> TableA[field], mode 0 -> TableB[field], else the
party name buffer), so the A/B pair naming is load-bearing; § 12 has the
measured size; the decomp's descriptive name is kept in the §-1 comment
for attribution. Resolution: §-1 row folded into § 12 (alias comment
left in place), allowlist 4 -> 3 (three deliberate cross-file accessor
overlaps remain; any 4th duplicate now fails). **Size fix while there:**
gNamePtrTableB walks **725 name-text pointers (0xB54)** before its
terminator word — the recorded 0x800 (512) contradicted § 12's own stated
walk method (re-measured here: entries 0..724 all point into the
`gTextNames` blob 0x08566A00+, entry 725 = 0x8000ff01 terminator);
gNamePtrTableA's 107 entries re-confirmed. Size row 0x800 -> 0xB54.

**Thread 2 — `tools/cadence_probe.py` promoted to the harness + gate.**
The /tmp audit scripts are now `tools/cadence_probe.py` (probe + sweep in
one tool; auto-port so concurrent check.py suites cannot collide, temp
save copy, GBARECOMP_* scrubbed) and are wired as check.py suite
`cadence` (default run, NEEDS_EXE; docs in tools/README.md +
tests/README.md § Verification). Gate: 60 Hz scheduler invariants (the
frame_step staging parities toggle every VBlank and stay equal,
gVblankCounter +1/step >= 95%) + `--strict` = zero every-other-frame
consumers on the PRESENTED surfaces (io/oam/pal/vram + the
gDisplayRegShadow window). State fixture `game.state1` (local-only, exit 2
when missing — ws_smoke precedent).

**Calibration findings (methodology amendment to late 12):** the weak
"change ratio ~= 0.5" detector has two false-positive shapes —
static-then-live transitions (hidden OAM entries (y=0xA8) appearing
mid-run then updating EVERY frame land at 0.51 by window luck) and
double-buffer slot writes. The real 30 Hz signature is STRICT ALTERNATION
(gaps of exactly 2 between change steps), and even that needs scope:
IWRAM staging alternates legitimately (slot A written on even steps,
slot B on odd) — on game.state1 the gOamStageSlotA1 pair shows exactly
that (73 bytes at 0x030002xx/0x030006xx, phases 35/38). So the gate reads
the presented surfaces only, where every frame is a full rewrite; added
the `io` region (the committed 0x04000008.. display regs) as the true
presented signal. Late 12's "ZERO bytes at exact 0.5 cadence" was true
under the weak detector; the refined detector confirms the same verdict
on the presented surfaces and explains the staging alternation as the
double buffer — the conclusion (no compute-at-60/read-at-30 split;
nothing for a 15-byte patch to unlock) is unchanged.

Acceptance: `check.py --only unit-py,cadence` ALL PASS (2/2 — TsvGuard
allowlist tightened AND the new suite green, 1.2 s); `tools/cycle.py`
PASS — regen 63134 discovered/emitted (corpus unchanged), dispatch
sanity OK, build OK, attract gate PASS frames=1200 sha256
1EF4C118A8438CADE6E5847DC6716A7A800D157A568DECB272F2F7052EF321C1.
Commit after this entry.

---

## 2026-10-14 — Raylib backend: runtime test, CI headless, and one RAB layering fix

Not a recompilation milestone: the recomp corpus, attract golden and all
route fixtures are untouched (`1EF4C118A8438CADE6E5847DC6716A7A800D157A568DECB272F2F7052EF321C1`
re-verified after every step below). Recorded because two changes reach outside the
experimental tree: a new CI job, and a library split in `gbarecomp-raylib/`.

### Finding 1 — a default launch would have opened an invisible window

`RaylibBackend::open()` contained `if (!rp.linear_filter) SetWindowState(FLAG_WINDOW_HIDDEN);`.
`linear_filter` **defaults to false** (`window_open_params.h`: `linear_filter && !sharp_filter`,
default `false`) and the SDL backend has no equivalent. Nothing ever cleared the flag, so
the default raylib window was hidden forever — every other signal reporting "running".
`set_fullscreen(0)` ("windowed") had the same inversion: it set `FLAG_WINDOW_HIDDEN` instead of
clearing `FLAG_FULLSCREEN_MODE`. Both fixed; both now pinned by an assertion.

It compiled clean, passed the 48/48 completeness guard, and passed 20 unit tests. Only
*running* it found this — which is the argument for the rest of this entry.

### Finding 2 — the single-instance audio invariant is now observed end-to-end

`audio_slot.h` (previous entry's work) makes the raylib callback's single-owner rule
*enforced* rather than documented. The integration test closes the loop by calling `close()`
then **reopening**: that succeeds only if `close()` released the slot, otherwise the second
open would silently come back without audio.

### Finding 3 — raylib 6 `LoadImageFromTexture` mislabels the stride

For a texture created from `PIXELFORMAT_UNCOMPRESSED_R8G8B8`, raylib 6 returns
`PIXELFORMAT_UNCOMPRESSED_R8G8B8A8` (4 bytes/px) while the buffer is **3** bytes/px.
Measured: stride 4 → 114744 mismatches, stride 3 → 0. Trusting the format label reads the
image as a skewed gradient with no error raised. Not live today (nothing reads back from the
GPU — `copy_presented_frame()` serves the CPU staging buffer), but it is a landmine for the
first thing that does. Pinned in the test, which tries both strides and requires an exact
match on at least one so it survives raylib fixing the label.

### Change 1 — RAB extracted from `host_window.cpp` into `gbarecomp_audio_drc`

**Why:** the integration test could not run in CI. `generated/` is gitignored, so
`GAME_GENERATED_SOURCES` globs to nothing on a fresh checkout and anything linking
`gbarecomp_runtime` fails on undefined `kDispatchTable`. The test linked `gbarecomp_runtime`
only to reach `host_make_backend()`. `nm` on `raylib_backend.cpp.o` showed the real
dependency set is raylib + `rab_*` + pthread; the only thing pulling it into the runtime was
that RAB's implementation was compiled *inside* `host_window.cpp` via
`#define RECOMP_AUDIO_DRC_IMPL`.

`recomp_audio_drc.h` documents itself as "define RECOMP_AUDIO_DRC_IMPL in exactly ONE
translation unit" — that unit was the *windowing* file, which inverted the layering for a
component that is pure DSP (resampler + ring buffer, zero SDL, zero raylib). Now
`src/runtime/recomp_audio_drc.cpp` → `gbarecomp_audio_drc`, linked by both
`gbarecomp_runtime` and `gbarecomp_raylib_backend`. `host_window.cpp` still includes the
header, it just no longer implements it.

The test now builds `RaylibBackend` directly and links raylib +
`gbarecomp_raylib_backend` only (verified: no SDL in `ldd`, zero `kDispatchTable`
references). Factory wiring stays covered by ctest `backend_select` in both app configs.

### Change 2 — new `raylib-backend` CI job

`ubuntu-latest` has no GPU, no `/dev/dri` and no X server. The gate
(`tools/check.py --only raylib-compile`) now finds a display itself: real display preferred,
else `xvfb-run -a` with `LIBGL_ALWAYS_SOFTWARE=1` / `GALLIUM_DRIVER=llvmpipe` /
`MESA_GL_VERSION_OVERRIDE=4.5`, else skip. llvmpipe advertises GL 4.5/4.6 vs raylib's 3.3
core requirement. The job installs `xvfb` + `libgl1-mesa-dri` and runs that gate.

**Inert while `gbarecomp-raylib/` is untracked** — gate reports
`skipped (no gbarecomp-raylib tree)`, exit 0, so it cannot redden the build before that tree
is committed. raylib has no true windowless mode (discussion raysan5/raylib#4857 segfaults
without `InitWindow`); a virtual X server is the cheapest context.

### Acceptance

`check.py --fast --only unit-cpp,unit-py,android-static,raylib-backend` 4/4 PASS;
`check.py --only raylib-compile` PASS (real display) and correctly SKIPs with `DISPLAY`
unset and no `xvfb-run`; `ctest` SDL 3/3, raylib 4/4; framework raylib-related 15/15;
`tests/python/test_tools.py` 50 tests OK; attract golden unchanged. `patches` still fails
pre-existing (untouched submodules). The 625 `host_window.cpp` errors in the standalone
framework build are the known pre-existing `GBARECOMP_RUNTIME_UI`-off breakage — confirmed
unrelated (all `TouchPoint`/`kTau`, zero `rab`/`audio_drc`).

Validated locally on real AMD hardware **and** on llvmpipe software GL. Not reproducible
here: Xvfb itself (no root), so whether a virtual X server satisfies GLFW is the one thing
first exercised on CI.

**Remaining:** `RaylibBackend::pump()` is still a stub (keys/gamepad/touch → `Events`), so
"renders" is proven and "plays" is not.

---

## 2026-10-14 (late) — Raylib pump(): the last big stub is real input

`RaylibBackend::pump()` returned `Events{}`. It now polls keyboard / gamepad /
mouse gyro / lifecycle through the pure `input_translate.h` (snapshot in, Events
out), with `raylib_keymap.h` porting the ini vocabulary to raylib KeyCodes.
`load_input_config()` reads the same `keybinds.ini` / `config.ini` files as the
SDL backend (including SDL-scancode-integer assist keys, converted). Touch reads
as disabled until the pad is wired.

New pure headers + tests: `input_translate.h` (47 assertions) and
`raylib_keymap.h` (96 assertions), both display-free, both in the framework
`ctest -R` set (now 17/17 with the rest). `raylib_backend.cpp` carries a
`static_assert(kRayKey* == KEY_*)` per letter/digit/function key, so a raylib
renumber breaks the build, not the player's controls. Integration test gains a
live pump section (idle baseline, no re-fire on second pump, `pump_events`
agreement, real-files config load incl. missing/null dirs).

Two findings, both verified rather than assumed:

1. **SDL gamepad path is inverted** (`host_window.cpp:3216`,
   `keys &= ~gamepad_to_keyinput(pad)` where the callee returns active-low).
   Pad connected + nothing pressed yields keyinput `0x0000` — every button
   mashed. Never showed: attract uses no pad, playtesters use keyboard. The
   raylib backend implements the corrected form; the SDL line is LEFT
   UNTOUCHED pending a decision since fixing it changes shipped behaviour.
   Negative control (introducing the inversion into the raylib backend) fails
   the live baseline exactly as predicted, via this machine's phantom pads.

2. **GLFW phantom pads**: keyboards' consumer-control interfaces, the ELAN
   touchscreen and the Synaptics touchpad all present as raylib "gamepads"
   (4 reported, no physical pad). The test asserts presence *agreement*, not
   absence; the all-released baseline proves no phantom button reads held.

Acceptance: framework 17/17, raylib-config ctest 4/4, SDL-config ctest 3/3,
`check.py --fast` 4/4, `raylib-compile` PASS (real display), llvmpipe PASS,
attract golden `1EF4C118A8438CADE6E5847DC6716A7A800D157A568DECB272F2F7052EF321C1`
unchanged (SDL path untouched). `patches` still fails pre-existing.

Remaining raylib stubs: touch-pad wiring, `interp_display_tick()`, host chrome
(pad/FPS readout), sharp-prescale pre-pass.

---

## 2026-10-14 (evening) — Raylib stubs wrapped up: zero TODOs left

`raylib_backend.cpp` had 8 `TODO(raylib)` markers; it now has none. Four
slices, each validated before the next. The attract golden never moved
(`1EF4C118A8438CADE6E5847DC6716A7A800D157A568DECB272F2F7052EF321C1`,
re-verified at the end); the SDL backend's behaviour is unchanged except
thin-wrapper rewiring onto shared headers (same code, new home).

### Slice A — LUT, surfaces, foreground, FPS, haptics

`color_lut.cpp` extracted to `gbarecomp_color_lut` and linked by both the
runtime and the raylib backend (removed from runtime sources to avoid
duplicate symbols). Grading proven both directions live (frontlit alters
bytes, Raw identical). `set_surface_size` recreates the streaming texture
(readback follows dims). `wait_for_foreground` is true-when-open on desktop.
FPS readout ported with `GetTime()`. `haptic_pulse` rides the gamepad motors
(no SDL_Haptic equivalent; no pad = documented no-op).

### Slice B — interp pacing + sharp prescale

`interp_display_tick` ports the SDL body against Impl state with the shared
`interp_pacing.h` policy (vsync assumed from VSYNC_HINT, period probed +
re-probed every 600 ticks). Sharp prescale via `RenderTexture2D` with the
Y-flip the storage convention requires, falling back to direct on any
failure; linear-clears-sharp mirrors SDL. Engagement verified arithmetically
(700x500 -> factor 2, 480x320 -> 0) with the test resizing to exactly the
engaging size.

### Slice C — touch input (two more shared headers, one more lib)

`touch_pad_layout.h` (geometry + predicates, extracted verbatim, SDL rewired
via thin wrappers, 31 test assertions) and `touch_pad_draw.h` (draw functions
as layout+held+density values, 11 assertions against a recording fake).
`touch_input.cpp` extracted to `gbarecomp_touch_input` so the lean test links
TouchHub without the ROM runtime. Pump polls raylib points + emulated-mouse
finger through the SDL-identical pad/toggle/routed life cycle, with
`[Touch]` rewrite semantics matching SDL (verified converging to one
section). `open()` mirrors touch defaults + safe-insets env.

### Slice D — chrome

`RaylibOverlay` maps every `HostOverlay` primitive to raylib shapes
(text unsupported, matching `SdlOverlay`; rounded-rect outline thickness and
arc direction documented as approximate). `present()` gates hook+pad+toggle
like `render_host_layers` minus the menu. The user overlay hook is proven by
a counting overlay (once per present, silent after removal).

### Deliberately not ported

Engine long-press ring + settings menu (no runtime-UI plumbing yet; actions
drained, never lost), frame blending (SDL-renderer-side), Android vibrator
(desktop haptics use pad motors).

### Acceptance

Framework 22/22 (incl. 3 new suites), raylib-config ctest 4/4 (present suite
now 73 assertions), SDL-config ctest 3/3, `check.py --fast` 4/4,
`raylib-compile` PASS (real display), llvmpipe PASS, `test_tools.py` OK.
`patches` still fails pre-existing. `gbarecomp-raylib/` still untracked, so
the new CI job stays inertly green.

---

## 2026-10-14 (night) — Dead keyboard on first manual run: two causes, backend exonerated

Symptom: raylib build boots, plays the intro, audio works, but no keyboard
response. The backend was cleared first: a live probe driving the REAL
`RaylibBackend` (open/pump/present) while ydotool held X at the uinput layer
showed `IsKeyDown` true and `keyinput` clearing to `0x3FE` with a clean
release — polling and translation both correct (user focused the window
manually after xdotool was rejected in favour of ydotool).

Real causes:

1. **Spaced modifier names.** Default `keybinds.ini` ships
   `select = Right Shift` (the file's own header documents SDL spellings).
   `raylib_key_from_name()` accepted `rshift` but not `Right Shift`, so
   Select was unbound for every default user. Fixed + pinned by whole-file
   regression tests using the exact shipped lines (verified failing without
   the fix). The ini appliers are now pure (`apply_keybinds_line` etc. in
   `raylib_keymap.h`), `load_input_config()` only reads files.
2. **Exe-anchored config.** `runtime.cpp` loads `keybinds.ini` from
   `argv[0]`'s dir. The user's Start=D/Select=Q rebinds live in
   `build/keybinds.ini`; `build-raylib-only/` had no ini files, so D/Q were
   unbound there by construction. Copied `build/keybinds.ini` into
   `build-raylib-only/` for the manual test. Not a code bug — documenting
   the one-copy-per-build-dir rule instead.

Acceptance: keymap suite green (incl. new whole-file + D/Q cases),
`check.py --fast` 4/4, `raylib-compile` PASS, present suite 73/73.

---

## 2026-10-14 (night 2) — Manual run passes; plan updated; stub-build break fixed

The user confirmed keyboard input works after the D/Q + spaced-names fixes,
so the first manual desktop run is fully PASS (boot, intro, audio, input).
`RAYLIB_PLAN.md` updated to record it: new progress-table row, validation
counts corrected to the verified **22/22** framework suites (the file still
said 15/15 with a stale suite list), a "First manual desktop run" subsection,
a learned-habit entry, and the stale "remaining work is the backend itself"
sentence replaced (remaining: menu plumbing + Android + two open decisions).

The plan update's verification pass caught a REAL break: `raylib_backend.cpp`
no longer compiled in the stub (SDL-config) build. Slice B/C helpers were
declared inside `#if defined(GBARECOMP_USE_RAYLIB)` but called from
unguarded setters, and pure `pad_layout_inputs` read guarded `last_layout`.
Fixed by making declarations unconditional (all signatures raylib-free),
guarding bodies internally, and moving plain-data members out of the guard.
Both trees rebuild; ctest 3/3 + 4/4; attract golden unchanged.

Acceptance: framework 22/22, ctest SDL 3/3 + raylib 4/4, `check.py --fast`
4/4, `raylib-compile` PASS, attract
`1EF4C118A8438CADE6E5847DC6716A7A800D157A568DECB272F2F7052EF321C1`.

---

## 2026-10-14 (night 3) — raylib-compile gate now builds the stub half too

Closed the hole the plan update caught: `check_raylib_compile` configures a
second dir (`build-raylib-stub/`, `-DGBARECOMP_USE_RAYLIB=OFF`, its own dir
because a build dir caches its flag set) and builds `gbarecomp_raylib_backend`
there. The stub half is offline-cheap (no raylib fetch with the flag off).

Verified both directions: green on the fixed tree (24.1s cold with fresh stub
configure, 2.8s cached), and FAIL with tonight's exact `no declaration
matches` error when the `#if` guard is reintroduced around the declarations
(5.1s), header byte-identical after restore. `build-raylib-stub/` is covered
by the existing `build-*/` gitignore line.

Acceptance: `check.py --only raylib-compile` ALL PASS (1/1) with the new
`backend compiles (ON+OFF)` message.

---

## 2026-10-14 (night 4) — SDL gamepad inversion fixed

One-line fix in `host_window.cpp`: `keys &= ~gamepad_to_keyinput(pad)` became
`keys &= gamepad_to_keyinput(pad)`. The helper returns active-low; the `~`
double-inverted, so a connected-but-idle pad produced keyinput `0x0000`
(everything mashed). Comment at the site explains the polarity and why the
touch line below keeps its `~` (active-high bits — correct). The stale
"left untouched pending a decision" NOTE in `raylib_backend.cpp` updated to
past tense. No other call sites use the helper, so this was the only instance.

Why it hid, verified live: an SDL probe on this machine finds exactly one
joystick (Keychron System Control) with `SDL_IsGameController` false, so the
branch never executes here — it needs a real standard-mapped pad. No live
behavioral verification possible; verified by helper contract + arithmetic +
symmetry with the keyboard merge and raylib usage instead.

Acceptance: SDL-tree + raylib-tree FFTARecomp build clean, attract golden
unchanged (`1EF4C118...F321C1` — expected, attract uses no pad), gamepad_map
+ assist_pad tests pass, `check.py --fast` 4/4, `raylib-compile` (ON+OFF)
PASS. No behavior change for keyboard players; pad players go from
everything-mashed to working input.

---

## 2026-10-14 (night 5) — Gamepad fix verified live; two corrections to the story

`keyprobe.py` over the TCP debug surface, 8BitDo Lite 2 in X-input mode,
fixed SDL build: idle `0x3ff`, pad A `0x3fe`, A+Right `0x3ee`, release back
to `0x3ff` with no stuck bits. Buttons, combinations, and release all exact
— the inversion fix is proven against real hardware.

Two corrections to the night-4 entry. First, the pinned `gbarecomp/` tree
has different, older gamepad code with no `gamepad_to_keyinput` call at all
(grep confirms): the bug lived ONLY in the raylib tree's refactored helper
path, and an early before/after run against the pinned build was discarded
as an invalid comparison. Second, the pad's wrong mode pegs its stick hard
up-left at rest (raw SDL: constant -32768/-32768 on both axes, zero buttons)
— correctly reported as Left+Up, not a backend fault; X-input mode is clean.
A surprise benefit of that wrong mode: the invented "SDL-style inversion"
negative control would have failed the live baseline even harder there.

Also learned this session: `pkill -f` with a bracket trick still matches your
own shell when the literal text contains the unbracketed substring elsewhere
(`./build-raylib/FFTARecomp` matched `[F]FTARecomp`). Record game PIDs via
`$!` to a file and kill that instead. And: keyprobe prints only on CHANGE,
so a quiet 60s window means no input, not a dead monitor. And SDL builds go
native Wayland here while raylib/GLFW picks X11 — force `SDL_VIDEODRIVER=x11`
when both windows must appear in the same place.

---

## 2026-10-14 (night 6) — Raylib pad selection + mapping quirk, both proven live

First live gamepad test on the raylib build was dead while the same pad
worked on SDL minutes earlier. Two stacked causes, both diagnosed by probe
before any code changed:

1. **Slot cap.** raylib caps MAX_GAMEPADS at 4; GLFW enumerates every evdev
   joystick, so phantoms (Keychron consumer-control, 2x ELAN, Synaptics)
   take raylib slots 0-3 while the real 8BitDo sits at GLFW slot 4,
   unreachable through any raylib call. Fixed by selecting through GLFW's
   standard-mapping layer (first present standard pad of 16 slots, read via
   glfwGetGamepadState), desktop-only, reached via forward declarations.
   Rumble uses the selected pad's raylib slot when visible, else skips.
2. **DB disagreement.** Same physical pad: SDL maps `a:b0` (positional),
   GLFW maps `a:b1` (Nintendo labels) — both strings read live. Fixed by a
   GUID-scoped A/B+X/Y quirk (`glfw_pad_quirks.h`, pure, unit-tested with
   synthetic indices); SDL backend stays the reference.

Live proof over TCP keyprobe: SOUTH `0x3fe` (A, matching SDL), EAST `0x3fd`
(B), Start works, clean releases, game exited gracefully
(FULLY_STATIC, 2430 frames). A wrong-mode stick peg (constant -32768 both
axes) is correctly reported as held Left+Up, not masked — X-input mode reads
clean. Docs: plan gained "Pad selection" + "Pad mapping" sections and got
its eaten "Found live" header restored; quirk rule documented (exact GUID +
both strings + live two-stack probe, or it doesn't go in).

Acceptance: framework 22/22, ctest raylib 4/4 + SDL 3/3, `check.py --fast`
4/4, `raylib-compile` (ON+OFF) PASS, attract golden unchanged. Present suite
73/73 (gamepad agreement check now asserts against the GLFW standard layer,
passing padless in CI and with the 8BitDo here).

## 2026-10-14 (night 7) — First real shader: LCD subpixel grid on raylib

The spin-off goal ("what SDL2 could not do") gets its first working proof:
a screen-space LCD shader on the raylib backend, ported from Shadertoy
"LCD Post Effect" (ldBfDd, via its Godot port — Shadertoy itself 403s all
fetches). RGB subpixel mask, period 3 screen pixels (blue/red/green column
order kept verbatim), even rows flattened dark, levels pb=0.4 / sclV=0.25.

Design (seam untouched, still 48/48 both backends):

1. **Pure helper** `gbarecomp-raylib/src/runtime/lcd_shader.h` (22nd):
   `lcd_pixel_mask()` CPU mirror (floor-mod, negative coords wrap),
   env/config resolution, and the GLSL330 source as `kLcdShaderFragment330`.
   Pinned by `lcd_shader_tests` (new CMake target, same pattern as the rest).
2. **Backend methods are non-virtual** `RaylibBackend::set_lcd_shader()` /
   `lcd_shader_enabled()` — SDL has no equivalent, so no seam widening and
   the completeness guard never sees them. `set_` returns path liveness
   (compiled + ready), which is what the integration test asserts.
3. **Enablement**: `GBARECOMP_LCD_SHADER` env (set wins incl. "0", same
   convention as touch) over `config.ini [video] lcd_shader`. Default off,
   so attract/verify never see it. Env read at `open()`; config at
   `load_input_config()` (skipped when env overrode).
4. **Present placement**: only the final screen blit runs under
   `BeginShaderMode` — never the sharp prescale pass, never the overlay.
   `LoadShaderFromMemory(nullptr, frag)` takes raylib's default vertex
   shader. Effect is GPU-side only: `copy_presented_frame()` serves the
   pre-shader staging buffer, so readback is exact with the shader on.
5. **Android**: logged skip (GLSL330 has no GLES spelling yet), stays off.

Two implementation traps, both the known kind: file-local load/unload
helpers naming the private `Impl` (same error the sharp-target helpers
taught us — made them private statics), and open() initially persisting a
stale flag across reopen (now resets to off when env is unset; config
re-enables at load).

Proof: pure tests PASS; `raylib_present` 73 → 89 (shaded presents exact,
program reused, config enables, env beats config both ways, guarded by
`unsetenv` for hermeticity); stub (OFF) build compiles; guard 48/48;
`check.py --fast` 4/4 + `raylib-compile` PASS. Windowed game boot with
`GBARECOMP_LCD_SHADER=1`: `Fragment shader compiled successfully` +
`LCD shader enabled`, no errors. Try it: `GBARECOMP_LCD_SHADER=1
tools/play.sh`. Public-repo note: the GLSL is an original ~15-line port of
the reference's documented logic (attributed above), not verbatim third-party
text.

## 2026-10-14 (night 7, cont.) — LCD brightness: gain rejected, floors lifted

Live feedback: the faithful reference levels read as dim, and the first fix
(pre-mask boost 1.5x) blew out the image. Mechanism: the full-strength
subpixel multiplies the texel by 1.0, so any gain clips every texel channel
above 1/gain into flat white — large clipped areas, detail gone. Reverted to
unity gain (the uniform + `[video] lcd_boost` tuning stay, default 1.0) and
lifted the mask floors instead: base 0.4 -> 0.6, dark row 0.25 -> 0.5
(~0.62x throughput, grid contrast intact). Highlights are identical to
unshaded by construction — nothing in the path can exceed the source. Lesson
recorded in `lcd_shader.h`: gain clips, floors do not. Pure suite stays 50
assertions (values updated), present suite 89/89, live boot compiles clean.

## 2026-10-14 (night 7, cont. 2) — LCD research: luma-scaled grid adopted

Researched the community's LCD shaders (libretro handheld set, Retro Game
Corps guidance) for anything genuinely smarter than the Shadertoy triad.
Verdict: one adoption, three honest rejections.

Adopted — **luma-scaled grid** from simpletex_lcd's GRID_BIAS (jdgleaver, via
zfast_lcd lineage): `mask = mix(vec3(1.0), mask, luma)`. A uniform grid
darkens everything equally, which is the root of the dim complaint; scaling
by luminosity keeps black black, uncrushes shadows, and keeps the full grid
on whites. Two GLSL lines, pure mirror `lcd_bias_mask()` + 6 new assertions
(suite now 56). Live boot compiles clean.

Rejected: (1) `gba-color` 3x3 correction matrix — our CPU color-LUT grading
already owns panel color; applying both would double-correct. (2)
motionblur/interframe blending — needs previous-frame history, i.e. the
deferred frame-blend track, not a shader tweak. (3) The polynomial
rounded-cell grid (`y = 48*(x^4 - 8/3*x^6)`) — prettier cells, but a bigger
look change needing a source-size uniform, and it drops the RGB triads the
user already approved. Concept credited in `lcd_shader.h`; no code taken, so
no license surface (simpletex/zfast are GPL — noted here so a future port
knows to check).

## 2026-10-14 (night 7, cont. 3) — Luma bias reverted: wrong for RGB triads

Live feedback (saturated colors look wrong) killed the GRID_BIAS adoption the
same session it landed. Mechanism, now understood: mixing the mask toward
white by luminosity unmasks hues differentially — pure red (luma 0.30) loses
70% of its grid, pure blue (0.11) loses ~90% — while white keeps all of it,
so primaries render flat and bright against fully-gridded whites. The
technique is sound for the monochrome cell grids it was designed for
(simpletex_lcd/zfast); applied to a chromatic triad mask it becomes a
hue-dependent desaturation. Lesson recorded in the plan: luma tricks assume
an achromatic mask. Reverted to the uniform mask + lifted floors (0.6/0.5);
helper, GLSL lines and 6 assertions removed (suite back to 50), present
89/89, live boot clean. No stacking issue on the CPU side — game.toml already
runs `screen = "raw"` passthrough, verified before touching anything.

## 2026-10-14 (night 8) — Frame blending on raylib: reuse, not rewrite

Option #1 built: the raylib backend blends CPU-side with the SAME
`recomp_frame_blend.c` the SDL backend compiles in — no new math, no new
seam methods, no menu work (the Graphics/LCD ghosting toggle drives the
pre-existing flag). The old "stays SDL-renderer-side" deferral misread the
primitive: it needs cached memory, never a renderer, and present() already
holds the frame on the CPU.

Wiring: `GBARECOMP_HAVE_FRAME_BLEND` CMake gate on the backend target
(absent in the framework standalone build → flag recorded, never applied);
grade → blend → upload mirrored verbatim incl. fresh/hold/reset/close
lifecycle. One documented divergence: raylib honors the flags without
GBARECOMP_RUNTIME_UI (its existing interp convention); both agree wherever
the menu exists. Readback serves blended bytes like SDL — correcting an
earlier pre-blend suggestion that would have split the backends' observable
behavior.

Proof: upstream `frame_blend_test.c` covers the primitive (not duplicated);
`raylib_present` 89 → 101 with exact per-byte averages from the documented
formula (advance, interp-reset, hold-against-unchanged-history, explicit
reset, off-uploads-raw); ON+OFF builds compile, guard 48/48.

## 2026-10-14 (night 9) — Bayer dither for BGR555 banding

Background gradients contour because the source is BGR555 (32 levels/channel)
and no later stage can un-bake that. Added Bayer-4 ordered dither pre-mask in
screen space (±½ LSB at strength 1.0): position-based, no texture or history,
feeding the framebuffer's own 8-bit quantization. `uniform float dither` +
`[video] lcd_dither` (0–2, default on), same pattern as boost. Pure suite
50 → 66 (16-permutation proven by the exact -0.5 cell sum, which confirms the
compact `fract(x·0.5 + y²·0.75)` form is a true Bayer-16); present 101/101;
live boot compiles clean. Two asserts were fixed on paper before running
(cell (0,0) steps down, the 16-level mean is 7.5/16 not 0.5) — caught by working the math first.

## 2026-10-14 (night 10) — LCD settings like the frame options (54-method seam)

The non-virtual LCD design held exactly until it met its first real consumer
— and settings are one: flags/menu drive through HostWindow, which only
speaks the seam. So the six LCD methods joined the interface (48 → 54, both
backends enforced, SDL explicit no-ops), with the render path staying fully
backend-private as before. The "don't widen" rule was always scoped to
test-only methods; a settings surface is the bar it named.

Surface: `--lcd-shader 0|1`, `--lcd-boost 1.0..3.0`, `--lcd-dither 0.0..2.0`
(validated fail-loud, registered in kCliValueFlags). Precedence, pinned and
documented: set GBARECOMP_LCD_SHADER pins on/off above all callers (in-tree
env-beats-CLI convention, cf. GBARECOMP_SCREEN); otherwise CLI (tracked via
given-bools, applied after load_input_config) beats config.ini [video],
which beats defaults. Menu rows deferred to the rlImGui work — but the six
methods they will drive already exist, and rows showing on SDL would be
no-ops, so gating belongs with that phase too.

Along the way the dither split landed (standalone pass, grid-independent —
each knob now works alone) and one void/bool seam mismatch was caught by the
compiler on first build. Proof: pure 68, present 105 (incl. dither-only and
combined passes), backend seam + closed-window tests extended, ON+OFF+stub
builds compile, guard 54/54, live boot via FLAGS (no env):
both programs compiled, both enabled. Gates re-run at the end.

## 2026-10-14 (night 11) — Dither amplitude: match the source step, not the display

Live report (dither 0 vs 2 indistinguishable) diagnosed as wrong amplitude,
not broken plumbing (the pass compiled and ran — boot log proved it).
Textbook Bayer amplitude (±½ display LSB) assumes gradients quantized at
display depth; BGR555 bands are ~8 LSB apart, so ±1 LSB of noise cannot move
them. Strength 1.0 now means ±4 LSB (half a source step): bands re-average
into intermediate tones, flat fields pay visible grain — the inherent 15-bit
trade, tunable 0..2. Lesson recorded at the site. Pure + present suites
green, no plumbing changes needed.

## 2026-10-14 (night 12) — Deband via visual regression, not eyeballing

Built the vertical adaptive deband (own program, own `--lcd-deband` 0..16
setting default off, seam 54 → 56) and proved it with screenshot measurement
on a synthetic gradient card through the real backend (new /tmp harness,
TakeScreenshot-free synchronous readback — ImageMagick `import` cannot
capture under XWayland; raylib's own screenshot path can).

Findings, all measured: dither confirmed running (diff std 4.6, max exactly
±8); the LCD dark rows stripe mid-grey by 30 LSB (the likely "horizontal
banding" — softened to 0.7 separately); ±1 deband taps net zero across edge
neighborhoods (identical big-row numbers exposed the metric, not the code —
wider-window energy showed the truth); ±2 melts 22% with patch boundaries
bit-identical, so ±2 shipped. Also caught pre-run: a post-target
double-release thrash in the A→B chain ordering, and a void/bool seam
mismatch the compiler found first. Lesson repeated twice tonight: measure
pixels, not previews (downscaled screenshots alias fine stripes into wide
bands that do not exist).

## 2026-10-14 (night 12) — Raylib backend runs on Android (rungs 1–2)

Rung 1: `gbarecomp_raylib_backend` cross-compiles standalone for arm64-v8a
(API 34, NDK 28.2) against real raylib-Android (PLATFORM=Android, GLES2) —
all `__ANDROID__` guards hold, only third-party sign-compare warnings.

Rung 2: minimal NativeActivity spike APK (`/tmp/opencode/raytest-android/`,
uncommitted) drives the real backend on the Poco X3 Pro: open → present →
pump → close, **12/12 PASS** over logcat. Drawable 480x320 live, CPU readback
exact, idle pump all-released with no re-fire, `gamepad_connected=0` (no pad
attached — correct). One FAIL on first run was a wrong test expectation, not
a backend bug: `lcd_shader_enabled()` reports request-intent (pinned by
desktop tests), so it reads true on Android while present's `flag && ready`
gate keeps the frame unshaded — the exact frame after requesting all three
shaders is the real decline proof. Gradle notes: needs CMake ≥3.25 (SDK's
3.30.3), Java 21 for Gradle 8.11 (system Java 27 breaks it), `sdk.dir` via
local.properties. Next rungs: audio (RAB over OpenSL ES), GLES shader
variants, then the full-game APK shell (NativeActivity, not SDLActivity).

## 2026-10-14 (night 12) — Touch fast-forward pill (hold-to-run)

The touch pad had no fast-forward: Tab / right-trigger hold had no touch
equivalent. Added an FF pill left of Select in the shared geometry
(`touch_pad_layout.h`: `PadLayout::ff` + `pad_ff_at`, both orientations),
teal-at-rest/gold-while-held drawing (`touch_pad_draw.h`), and hold tracking
in both backends' touch paths (down inside opens an ff track, move
re-queries so sliding off releases, up erases; `ev.fast_forward` ORs the
held flag). First cut was tap-to-toggle — wrong: FF is level-triggered
("held = uncap") everywhere else (Tab, Assist trigger), so the pill holds
too. No seam change (all internal); pure layout/draw asserts; both app
builds compile, present/closed suites pass, attract golden unchanged.

## 2026-10-14 (night 12) — Android audio flows; reopen doesn't (platform law)

Rung 3 PASS: with audio enabled, the spike opened the real device (AAudio
stream OK, routed `audio-ull-playback` to speaker at 48 kHz), pushed 440 Hz
sine at emu cadence for 600 frames (~10 s, progress in logcat), stayed
alive, and closed cleanly ("Window closed successfully").

The reopen probe then hung inside the second InitWindow — root-caused in
raylib's `rcore_android.c`, not the backend: `InitPlatform()` blocks in
`while (!CORE.Window.ready)` for `APP_CMD_INIT_WINDOW`, and the OS never
re-sends it because the activity's window was never destroyed. `ClosePlatform`
only resets global state when `destroyRequested != 0` (process death). So
Close→Init in one activity is unsupported by raylib itself; desktop reopen
works because GLFW re-creates real windows. Design consequence for the
full-game APK: on Android the window is OS-owned — backgrounding must go
through the TERM_WINDOW/INIT_WINDOW rebind path (which raylib handles
internally), never `CloseWindow`; that is the `wait_for_foreground`
suspend/resume seam's job. Underrun tuning still awaits a human listener.

## 2026-10-14 (night 12) — GLSL ES shaders engage on device (rung 4)

Wrote `#version 100` twins of all three passes (same formulas; highp, not
mediump — the Bayer hash squares gl_FragCoord, overflowing mediump's 65504),
selected per-platform, and dropped the Android decline stubs. Pure asserts
pin the dialect markers + selector; desktop behavior unchanged (330 served,
all suites green, 56/56).

Device proof needed a calibration first: the first screenshot round looked
impossible (LCD brighter than off). Tags settled it — one combo tag per
capture (B channel 10/20/30) proved each shot holds its own combo, and the
a/b pairs are bit-identical: off is clean (alt-row 0.53), LCD shows the
triad signature (blue 20→15 through the mask, rows 2.45), all-passes adds
dither see-saw (rows 3.89). The early confusion was Adreno triple-buffering:
captures lag ~2 presents, so 2 settles read pre-combo pixels and 4 read the
right ones. Spike 15/15, CPU readback exact throughout. Lesson for the
device gate: tag every capture and settle ≥4.

## 2026-10-14 — raylib-Android intro lag (visuals + audio)

- Symptom (device, Poco X3 Pro): severe lag in the intro, picture and music.
- Isolations: `--lcd-dither 0` via debug-args changed nothing (dither
  fullscreen pass ruled out); gfxinfo is blind to NativeActivity surfaces
  (0 frames reported) so it can't measure this app.
- Device facts: 120Hz panel, 1440x3200 drawable. Present path stacked three
  clocks: GBA frame pacer (59.7Hz, owns timing on SDL) + raylib
  `SetTargetFPS(60)` + vsync block in `EndDrawing`, plus `FLAG_MSAA_4X_HINT`
  (pure resolve cost at 1440p — we blit textured quads, nothing to AA).
- Fix (raylib backend only, Android-scoped): no MSAA on Android, no
  `SetTargetFPS` on Android (pacer owns timing, as on SDL); vsync stays
  (tearing guard + caps uncapped presents). Desktop untouched.
- Measurement: permanent quiet Android present-rate log (1 line/~10s,
  same precedent as the interp-tick log) — rate≈59-60 = pacing fixed,
  rate<55 = look at GPU/emulation next. Awaiting device numbers.

- Present-rate with MSAA/target-limiter removed (dither still off): 52-57/s
  vs 59.7 target, wandering per 10s window — a beat pattern, not a steady
  offset. Root cause identified: SDL runs vsync-OFF by default (pacer owns
  timing, `SDL_RENDERER_PRESENTVSYNC` only with `GBARECOMP_VSYNC=1`), while
  raylib-Android forced `FLAG_VSYNC_HINT` on — every present stacked up to
  one 120Hz period onto the pacer wait. Fix: no VSYNC hint on Android
  (pacer-only, tearing exposure = SDL default). Rebuilding to verify.

- Vsync-off verification: pacer-only presents run 58-59.5/s (target 59.7)
  with occasional 53-56 dips under intro load, vs 52-57 wandering before.
  User confirms intro feels much better (visuals + audio together, as
  predicted — one clock fixed both). Residual dips are next only if they
  bother: candidates are intro-content spikes or GPU headroom with dither
  re-enabled (debug-args still carries `--lcd-dither 0` from the isolation
  test — restore default and re-check rate before calling this done).

## 2026-10-14 — intro-lag fix validation + test locks (nightcap)

- Full ctest sweep in build-raylib-only: 100% (66/66). Excluded:
  bios_smoke (pre-existing link break — undefined ImFontAtlas symbol from
  imgui_impl_sdlrenderer2, untouched by tonight's diff; fails identically
  without it).
- New locks, both in gbarecomp-raylib/tests (the raylib tree):
  - idle_elision_tests (tests/recompile/idle_elision_test.cpp): synthetic
    Thumb ROM; branchy vblank-spin shape nominates its back-edge probe,
    call-in-body does not, straight-line still does. Negative-controlled:
    reverted classifier fails the branchy case (exit 1), restored passes.
  - audio_drc_tests += DC wraparound: 8000-level signal lapped 4x past ring
    capacity holds level (worst-dev/mean-dev bounds, zero underruns) —
    locks the mask==modulo ring-index change.
- Fix placement (raylib-version requirement): classifier + RAB live in both
  copies in sync (submodule side re-exported to
  tools/patches/gbarecomp-local.patch, replay matches); pacer phase-lock,
  -Bsymbolic-functions, swap-interval/MSAA/limiter are raylib-side-only
  (Android-gated or backend code — no submodule counterpart). Desktop-only
  gates all green (attract golden bit-identical 1EF4C11...,
  check.py 17/18 with only the pre-existing patches-suite items red).
- Device state: intro "seems better" per user with phase-lock; widescreen
  (--view-width 384) + full shader stack verified on-device by screenshot
  (LCD/deband/dither all compile on Adreno; W3 wrap visible on title as
  designed). Remaining device thread on next session: tick/yield fast paths
  if residual hitches still bother (profile-ranked, behavior-identical
  candidates), else bank the win.

## 2026-10-14 — Window-backend V2 Phase 0: baseline, S1 headless proof, S2 inventory

- Plan: `.opencode/WINDOW_BACKEND_V2_PLAN.md` (agent-executable; the freeze is
  the next, sign-off-gated step). No production code changed; the S1 harness
  lives outside the port tree at `spike-s1/` (untracked).
- Baseline gates recorded (all four build dirs; exact invocations now in the
  plan §0):
  - builds: `build`, `build-raylib`, `build-raylib-only`, `build-raylib-stub`
    all EXIT 0 (FFTARecomp / `gbarecomp_raylib_backend`).
  - ctest: `build-raylib-only` 66/66; `build-raylib` 65/65 **after** building
    the framework test binaries by name — they are `EXCLUDE_FROM_ALL` (the
    FFTA tree adds the engine with `EXCLUDE_FROM_ALL`), so a plain
    `cmake --build` never produces them and ctest reports "Not Run".
  - attract golden byte-identical in both configs:
    `1EF4C118A8438CADE6E5847DC6716A7A800D157A568DECB272F2F7052EF321C1`.
  - `check.py --fast` green; `ws_check` green; completeness guard 56/56 both
    backends; `raylib-compile` green.
  - `patches` suite red (expected pre-freeze — replays local patches against
    worktree-modified submodules). `bios_smoke` link break confirmed
    pre-existing in both port-tree configs (ImGui/ImFontAtlas symbols).
  - `build/` cache still points at the `gbarecomp/` submodule (stale vs the
    tree's auto-preference): its port-era tests cannot compile there
    (`test_host_window_closed.cpp` includes `host_backend_factory.h`, which
    only exists in the port tree). Recorded, not chased; Phase 4/7 retires
    that config.
- **Spike S1 (headless) — PASS.** Route found: raylib 6's CMake already
  supports it — `-DPLATFORM=Memory` (`cmake/LibraryConfigurations.cmake` maps
  it to `PLATFORM_MEMORY` + `GRAPHICS_API_OPENGL_SOFTWARE`, exported PUBLIC
  by `CompileDefinitions.cmake`). No injected defines, no second build tree.
  Harness `spike-s1/` compiles the real `RaylibBackend` + its four tree
  sources (+ a truthful no-gamepad GLFW stub — Memory has no input system)
  and runs `open → present → readback → close → reopen` with `DISPLAY` and
  `WAYLAND_DISPLAY` unset: **16/16 assertions, exit 0**. The red state it
  closes: `ffta_raylib_present_tests` prints `SKIP (no DISPLAY/...)`.
  Findings: `LoadImageFromScreen()` returns 480x320 RGBA top-down frames that
  change with the presented frame; `swGetColorBuffer()` returns **BGRA**
  (`SW_FRAMEBUFFER_OUTPUT_BGRA`) — use LoadImageFromScreen in tests; shader
  loads fail softly under rlsw ("dither shader failed to compile", no crash —
  matches plan §4.1); audio still initialized via PulseAudio here (runners
  without a sound server must tolerate no-audio); monitor-refresh queries warn
  (interp falls back to 16.67ms). GLFW gamepad calls are the one link
  dependency Memory cannot satisfy — concrete input for Phase 2's `RaylibApi`
  seam.
- **Spike S2 (SDL footprint) — done.** `host_window.cpp` 3,774 lines: SDL
  region 46-3232 (≈84.4%, delete), shared `HostWindow` delegation 3233-3774
  (≈542 lines, survive) — after deletion ~550-600 lines. Three shared globals
  live inside the SDL block (`g_haptic_window`, `g_settings_menu_requested`;
  already duplicated for non-SDL). Deletion checklist includes CMake discovery
  (62-167), `GBARECOMP_STATIC_RELEASE` SDL FATAL_ERROR, `SDL2.dll` staging,
  the factory branch, and `service_events`'s lone `SDL_PumpEvents`
  (3653-3654). Largest non-mechanical loss: runtime-UI/settings menu
  (ImGui-SDL renderer) — Phase 3's generic menu is the replacement.
- **Patch roll-in verified (Appendix C):** no MISSING rows. `arm-recomp-core`
  live diff +14/−2, sha1 `ed2557660d21276945ea5e1b373a89eda505eff2`, 2 hunks,
  reverse-applies clean, byte-identical to the recorded patch. Corrections:
  `gbarecomp-local.patch` has 28 diff headers (plan said 27); recomp-ui
  staleness is 8 dirty files (plan said 6; patch touches 4);
  `bios_dispatch_table.cpp` lives at `src/runtime/generated_bios/` (5333
  `{0x` rows, sha1 `5d272a8555540aced7557fd83ced6549076b9f8f`, identical to
  the dev tree). Gotcha: the global git config (`diff.external=difft`)
  corrupts bare `git diff` — freeze tooling must pass `--no-ext-diff
  --no-color`.
- Carry-forward findings (not Phase 0 blockers): `ffta_host_window_tests` and
  the framework `host_window_closed_test.cpp` call `w.resize_driven_view()`,
  which no header declares — Release builds compile because `NDEBUG` erases
  `assert(...)`, so that test is vacuous in Release (give it explicit
  `check()`s when ported); `host_gamepad_supports_rumble()` is declared but
  never defined (latent link break); raylib `gamepad_supports_rumble()`
  returns false while `gamepad_rumble()` works (V2 `Caps` fixes);
  `pump_events`/`pump` base defaults disagree.
- Next: freeze (rename → `gbarecompx/`, submodule re-materialization, CI
  workflow in the first commit, `git init` + push) — **awaits explicit
  sign-off** per the plan's stop list.

## 2026-10-14 — Phase 0 freeze executed: gbarecompx is its own repo

- Tree renamed `gbarecomp-raylib/` → `gbarecompx/`; FFTA references updated
  (root CMakeLists auto-preference, `tools/check.py`,
  `tools/check_raylib_backend_complete.py`, `.github/workflows/ci.yml`,
  `tests/README.md`, `spike-s1/`, in-tree `gbarecompx:` message prefixes).
  `gbarecompx/` is gitignored here until the Phase 7 repoint.
- Submodules re-materialized as independent clones from the public upstreams
  at the pinned SHAs (they previously resolved into FFTA's module store via
  gitfiles): arm-recomp-core `15fc7b7` (+ local patch), rbengine `2a03e73`,
  recomp-net `c58f125`, SDL `8e28503` (transitional; retired in Phase 4f).
  The arm-recomp-core diff (+14/−2, sha1 `ed2557…`) was captured
  byte-identical to the recorded patch into
  `tools/patches/arm-recomp-core-local.patch`; `ignore = dirty` keeps it out
  of status; a configure-time guard fails loudly with the exact apply
  command (red-first: verified failing with the patch stripped, passing
  restored).
- Screenshots deleted (15 webp + README embed blocks — no game pixels in the
  history); freeze commit `4cc306b` (482 files, 4 gitlinks) pushed to
  `git@github.com:james2doyle/gbarecompx.git`.
- Three findings surfaced by the freeze's own verification, fixed in
  follow-up commits:
  1. `617e9e6` — CI red on the first push: `**/generated/*` swallowed the
     monolith-guard fixture
     (`tests/cmake/runtime_monolith_guard/generated/recompiled.cpp`), so
     fresh clones had an empty fixture. Negation added + fixture committed.
  2. `dd99353` — the fresh-clone proof found `host_window.cpp` failing to
     compile with SDL2 present and recomp-ui absent (a plain dev machine):
     `interp_display_tick`'s closing brace sat inside
     `#if GBARECOMP_RUNTIME_UI`. Fixed to the file's guard shape (`#else`
     no-op, brace outside); the CI stub job now installs `libsdl2-dev` so
     the SDL region is compiled on every push (the runner had no SDL2, which
     is why CI missed it).
  3. `10aa5c2` — hygiene audit: upstream's `F:\Projects` machine paths
     (inherited verbatim; one a functional default in `oracle/gba_cosim.py`)
     genericized to `C:\`; `1f3b5fe` — README's R.A.I.D. badge committed
     (upstream parity; the `*.png` rule had hidden it).
- Post-freeze gate (FFTA side): three configs reconfigure/build green;
  `build-raylib` 65/65, `build-raylib-only` 66/66; attract golden
  byte-identical in both (`1EF4C118…`); `check.py --fast`, `raylib-compile`,
  `ws_check`, completeness guard green; `bios_smoke` link break unchanged
  (pre-existing, FFTA-side recomp-ui config, not a registered test). Two
  stale-cache artifacts of the rename were fixed during the gate:
  `GBARECOMP_GENERATED_BIOS_DIR` (cached old path → BIOS output "absent" →
  strict attract abort) and the monolith fixture's cached source path.
- Fresh-clone proof (delegated): clone → submodules pinned exactly → patch
  applies → standalone stub build 231/231 with SDL2 present → ctest 61/61 →
  guard red-state reproduced. CI on `10aa5c2`: all three jobs green (stub
  2m35s incl. SDL2 coverage, raylib 3m18s, guard).
- Next: Phase 1 (V2 types and interfaces, additive — no behavior change).

## 2026-10-14 — V2 Phase 1: types, interfaces, facade (gbarecompx `b2713bf`)

- `window_backend.h` now hosts both generations: the flat 56-method class
  (contract untouched) and the V2 types (`OpenParams`, `Caps`, `Err`/
  `Result`, `FxSettings`, `TouchConfig`), the five concern interfaces
  (`Video`/`Audio`/`Input`/`Fx`/`Overlay`), and the facade — introduced as
  `WindowBackendV2` until Phase 4 deletes the flat class and the name goes
  plain (4b records the rename).
- `Events` moved to seam scope with a member alias on the flat class, so
  `WindowBackend::Events` and `HostWindow::Events` still name the same type
  (the V2 facade returns it too; Phase 4 then has nothing nested to
  untangle). All references verified intact (input_translate, host_window,
  raylib_backend, dispatch tests).
- New test `tests/runtime/backend_v2_types_test.cpp` (plan §5.2 item 1):
  defaults, `Result::ok`, interface purity (virtual dtor + abstract), and
  the no-op-implies-false-cap rule via a fully no-op backend. Red-first:
  written before the types existed (compile-red captured), then green;
  three negative controls (Caps default, Result::ok, OpenParams default)
  each observed failing and restored byte-identical. Uses the always-active
  CHECK macro — the Release/`-DNDEBUG` vacuous-assert trap is real in this
  tree (the older `tests/runtime/*` suite still uses bare `assert`;
  flagged, not fixed).
- Checker `tools/check_raylib_backend_complete.py` scoped to the flat class
  body — it scanned the whole file, so the V2 section would have polluted
  the 56-method contract. Still 56/56 raylib + SDL; self-tests pass.
- Verification: standalone stub ctest 62/62 (SDL2 present); FFTA
  `build-raylib` 66/66 and `build-raylib-only` 67/67 (+1 each = the new
  test); attract golden byte-identical in both configs; `check.py --only
  raylib-backend` green; CI on the phase commit (see run for `b2713bf`).
- Next: Phase 2 (raylib backend conversion, concern by concern — Video →
  Audio → Input → Fx → Overlay → lifecycle; `Clock` + `RaylibApi` seam).

## 2026-10-14 — asserts live in tests: the vacuous-assert trap closed

- Found by the Phase 1 audit + confirmed by spike: Release's `-DNDEBUG`
  erased every bare `assert()` in the assert-based suites — 21/31
  `tests/runtime` files (and FFTA's `test_host_window_closed` with 39
  asserts) were passing vacuously, in the gates and in CI alike.
- Fix: `-UNDEBUG` appended after the build-type flags. `remove_definitions
  (-DNDEBUG)` does NOT work: NDEBUG comes from `CMAKE_CXX_FLAGS_RELEASE`
  (a flags string), not `add_definitions()`. Framework: one
  `add_compile_options(-UNDEBUG)` at the tests banner (verified: test TUs
  get it; `gbarecomp_runtime` / `gba_recompile` do not). FFTA: per-target
  on `ffta_unit_tests` / `ffta_host_window_tests` /
  `ffta_backend_select_tests` / `ffta_raylib_present_tests`.
- Spike with asserts live: the framework suite went 57/62 → five real
  failures, each triaged to a root cause:
  1. `gamepad_map_test:61` — test-side operator-precedence bug (`==` binds
     tighter than `&`, so the expression was always false). Parenthesized.
  2. `assist_pad_binding_test` — expectations used the wrong polarity
     convention (even = positive); upstream encodes odd = positive on both
     encode and decode (verified against the pristine `gbarecomp`
     submodule: `100 + code*2 + (positive?1:0)` / `(encoded & 1)`).
     Corrected to 109/111/101/100/103 — config compat unchanged.
  3. `interp_pacing_test` — two inverted `should_hold` expectations vs the
     helper's documented contract (fixed), which unmasked a third: the
     helper's `interp_advance_tick_ns` diverged from upstream's do-while in
     the cursor-ahead case (kept the cursor; upstream advances one period).
     Restored upstream semantics — the helper is the shared policy BOTH
     backends use, so it must reproduce the SDL reference; the deadline
     clamp governs the sleep either way. Bounded loop retained.
  4. `raylib_backend_test` — asserted the touch pad could show with
     `touch_controls` off; the gate is intentional ("must not claim a pad it
     cannot deliver"). The test now exercises the gate, then configures
     touch emulation and asserts the round-trip. That unmasked two more in
     the same file's window section (never reachable before): it opened two
     `RaylibBackend` instances at once (raylib has ONE global window — the
     second `InitWindow` re-initialized it under the first, heap corruption,
     `double free`), and it had no display guard (CI's raylib job runs
     headless). Fixed: one live instance at a time; the window section
     self-skips without DISPLAY/WAYLAND_DISPLAY (stub builds always run it).
  5. `window_backend_virtual_dispatch_test` — `is_open()` omitted its hit
     count (the carry-forward finding). Fixed.
- `test_host_window_closed.cpp`: `assert(!w.resize_driven_view())` called a
  getter that was never declared anywhere — the assertion is gone (the
  setter's closed-window no-op is exercised with the other mutators);
  widening the seam for a test is against the plan's §7 traps.
- Verified: standalone stub ctest 62/62 with asserts live; FFTA
  `build-raylib` 66/66 and `build-raylib-only` 67/67 (framework test targets
  rebuilt for real); the raylib-ON test self-skips headless (exit 0);
  attract golden byte-identical in both configs (production behavior
  unchanged); `check-fast` green (incl. `unit-cpp` against the pinned
  submodule).
- Policy: new tests keep using the always-active `CHECK` macro; `-UNDEBUG`
  is the belt-and-braces for the legacy assert-based files (the Phase 4
  rewrites migrate them).

## 2026-10-15 — V2 Phase 2 infra: RaylibApi + Clock, all raylib calls routed

- `raylib_api.h/.cpp`: the raylib surface (65 methods, raylib's exact names
  and signatures) behind one interface; `real_raylib_api()` forwards 1:1
  (`::`-qualified against member-name recursion). All 154 raylib call sites
  in raylib_backend.cpp route through it (`impl_->api->` in methods,
  `impl->api->` in the static helpers, `api_->` in RaylibOverlay) — the
  Phase 5 failure-injection fake needs no backend changes.
- `host_clock.h/.cpp`: the backend's time source; real impl = raylib
  `GetTime()` in raylib builds, steady clock in stubs. The three GetTime()
  sites (input snapshot now_ms, Android rate log, FPS readout) route
  through it. FakeClock arrives with the §5.2 item 3 fakes.
- `RaylibBackend(RaylibApi* api = nullptr, Clock* clock = nullptr)`:
  injectable, defaulted — existing construction unchanged.
- Stale "skeleton/stub" commentary replaced (the header's STUBS section +
  both file tops).
- Verification: both configs build; FFTA `build-raylib` 66/66,
  `build-raylib-only` 67/67; attract golden byte-identical in both configs
  (the routing is behavior-preserving); the completeness checker 56/56; a
  scanner (same masker as the routing transform) confirms zero unrouted
  raylib calls remain. `bios_smoke`'s link break is unchanged (the known
  FFTA-side ImGui set — no new symbols).
- Note: the routing was applied by a reviewed Python transform
  (string/comment masking, range-based receivers, abort-on-unranged); the
  one-shot script is recorded at /tmp/opencode/route_raylib.py, not
  committed.
- Next: concern conversions in order (Video → Audio → Input → Fx → Overlay
  → lifecycle), each with a red-first V2-accessor test; then the fakes +
  the display-free contract slice.

## 2026-10-15 — V2 Phase 2, Video concern (gbarecompx 685f05a)

- First concern conversion. `RaylibBackend::VideoImpl` (nested; declared in
  raylib_backend.h, defined in raylib_backend.cpp) implements the V2 `Video`
  interface over the same Impl state; all 18 flat Video methods (per plan
  §3.5) are now one-line forwarders through `impl_->video->…`.
- Bodies moved verbatim (`impl_.get()` → `impl_` only) — verified
  token-for-token by a move-checker (present 11,143 tokens, interp 2,087,
  surface 1,406, …: 0 mismatches). Nested so the private static helpers
  (sharp/post targets, shader programs, interp mode) stay reachable.
- `refresh_hz()` is new: `1e9 / interp_period_ns`; the field is guarded at
  its only writer (`hz > 0 ? … : 16666666`), so no division by zero.
- The `video()` accessor lands as a plain method now and becomes the
  `WindowBackendV2::video()` override when the facade lands at the end of
  Phase 2. Staging rule discovered here: the V2 base cannot land earlier —
  pure-virtual interfaces make a partially-converted backend abstract, and
  the production factory instantiates it.
- Red-first: `tests/runtime/raylib_backend_v2_test.cpp` written against the
  missing accessor → observed compile-red ("no member named 'video'") →
  green. Negative control: clamp 8→7 mutation → observed the exact CHECK
  fail → restored.
- Verification: stub ctest 63/63; FFTA `build-raylib` 67/67,
  `build-raylib-only` 68/68; attract golden byte-identical in both;
  completeness checker 56/56. Note: the first FFTA sweep raced the
  mutation-check window (two tests compiled against clamp 7) — rebuilt
  cleanly and re-ran; green. Lesson: never mutate while a background sweep
  is compiling the same tree.
- Next: Audio (claim/release + push/volume/enabled), then Input, Fx,
  Overlay, lifecycle/facade.

## 2026-10-15 — V2 Phase 2, Audio concern (gbarecompx 71ac038)

- `RaylibBackend::AudioImpl` (nested, same pattern as VideoImpl):
  `claim()` refuses when the device did not come up at open ("audio device
  unavailable") or when a claim is already held ("audio already claimed") —
  Err::AudioDevice with static-lifetime detail, per plan §3.3; `release()`
  clears it (single owner). Reset by open() and close(). The device
  lifecycle itself is unchanged (still open()/close()); claim is a
  handshake, not a second init path, and `push()` keeps the flat behavior
  (no claim gate), so existing callers are unaffected.
- push/set_volume/volume/set_enabled/enabled moved verbatim; the five flat
  methods (push_audio_samples, set_volume, volume_percent, set_audio_enabled,
  audio_enabled) forward.
- `audio_ready`/`audio_dev_open`/`bridge_ready` moved out of the raylib
  guard in Impl (plain-data rule) — claim() is unguarded and must refuse
  identically in the stub build.
- Red-first: audio contract tests added to raylib_backend_v2_test.cpp
  (compile-red "no member named 'audio'"); negative control: volume clamp
  100→99 mutation observed failing the exact CHECK. (First mutation attempt
  ran a stale binary because the build had failed — re-ran after the fix.)
- Verified: stub 63/63; FFTA build-raylib 67/67, build-raylib-only 68/68;
  attract golden byte-identical in both configs. Audit of the Video step
  (independent subagent): no blocking/notable findings; its two nits
  (refresh_hz sanity range, test coverage both directions) landed in
  6c62fc6.
- Next: Input (read/load_config/bindings/gamepad/rumble/haptic), then Fx,
  Overlay, lifecycle/facade.

## 2026-10-15 — V2 Phase 2, Input concern (gbarecompx 0778f84)

- `RaylibBackend::InputImpl`: read() is the snapshot fill (levels only) that
  used to sit at the top of pump(); it resets the snapshot (and the FF flag)
  when the window is not ready, and records `touch_ff_held` in Impl for the
  pump's post-translate overlay. The flat pump is now the §3.2 composition —
  `translate_input(read(s), bindings(), edges)` — plus that overlay, exactly
  the shape the SDL sibling uses for its touch FF pill. Behavior note: the
  old pump early-returned Events{} when not ready; the composition
  translates an empty snapshot against edges that reset on open/close, so
  reachable states are identical (the transient open-but-not-ready case
  emits at most release edges for keys held across the transition —
  unreachable in practice, noted for the record).
- load_input_config splits: the input half (assist/ff seeding, bindings
  reseed, keybinds/keymap/Launcher scans) is InputImpl::load_config; the
  [video] LCD block stays in the flat method (env/dir guard restructured)
  until the Fx step. bindings() returns the live table;
  assist_tools/fast_forward_multiplier move as one-liners;
  gamepad_connected/rumble/haptic_pulse move verbatim.
- Caught by the raylib-ON build only (stub build passed): the moved read()
  called the flat member `set_touch_pad_visible` — impossible from a nested
  class with no backend object. Extracted the body to the private static
  `apply_touch_pad_visible(Impl*, bool)` (the save_touch_config pattern);
  the flat setter forwards to it. **Lesson:** the per-concern accept MUST
  include the ON build — raylib-guarded bodies are not compiled in the stub
  config, and a token-faithful move can still be context-invalid.
- Red-first: input contract tests (compile-red "no member named 'input'";
  also caught kRayKeyX's namespace qualification). Negative control:
  ff-clamp 10→9 mutation observed failing the exact CHECK.
- Verification: stub 63/63; FFTA build-raylib 67/67, build-raylib-only
  68/68; attract golden byte-identical in both configs; body-move
  token-verified (pump→read 10,764 tokens; the split's call census exact).
- Next: Fx (settings/apply + the LCD config block), then Overlay, then
  lifecycle/facade.

## 2026-10-15 — V2 Phase 2, Fx concern (gbarecompx 215b765)

- `RaylibBackend::FxImpl`: settings() assembles the FxSettings snapshot;
  apply() writes it change-detected and drives the private per-field
  transitions (the moved bodies: clamps, live shader load, post-target
  releases, blend-history resets); reset_frame_blend is the third interface
  method. Per plan §3.5 the flat Fx methods go through settings()/apply() —
  the interface is the only channel (no concrete-pointer back doors).
- The flat setters compose settings()+apply(); set_frame_interp/
  set_frame_blend keep their unconditional blend-history reset explicitly
  (apply() fires it only on a real toggle). The flat getters read
  settings(). frame_blend is a bool under the hood — values round-trip as
  0.0/1.0 (documented in the class comment).
- load_input_config's parked [video] block became the private static
  `load_video_config(Impl*, dir)` (parses the ini, transitions the LCD flag
  through fx->apply()); load_input_config is now a two-line composition.
  Dropped: the old no-op calls' spurious post-target re-release
  (set_lcd_dither/deband(0) when already 0) — idempotent waste.
- Wiring mistakes caught in-step: (1) a first cut exposed public "extras"
  reached through the unique_ptr<Fx> interface pointer — impossible;
  corrected to private helpers + interface composition (which is what §3.5
  prescribes). (2) the moved reset_frame_blend lost its `override` (the
  move script missed the keyword) — restored; the token verifier caught it.
- Red-first: fx contract tests (compile-red "no member named 'fx'");
  negative control: dropping lcd_clamp_boost observed failing the exact
  CHECK (clamp 3.0).
- Verification: stub 63/63; FFTA build-raylib 67/67, build-raylib-only
  68/68; attract golden byte-identical in both configs; body-move
  token-verified (7/7 transitions; LCD block census exact).
- Next: Overlay (host overlay hook, touch config, pad visibility), then
  lifecycle/facade (open(OpenParams), caps, suspend/resume, the V2 base).

## 2026-10-15 — V2 Phase 2, Overlay concern (gbarecompx 3b2f4b9)

- `RaylibBackend::OverlayImpl`: the host overlay hook, the touch policy as
  the TouchConfig value struct (configure_touch unpacks the struct into the
  flat body's parameter names — the body moves verbatim), the touch config
  dir (ini [Touch] scan verbatim), and pad visibility (touch_pad_visible;
  the transition stays the private static apply_touch_pad_visible, shared
  with InputImpl::read()'s tap handling). The drawing side stays
  RaylibOverlay, constructed by VideoImpl::present per frame.
- Flat forwarders: set_host_overlay / configure_touch (builds the
  TouchConfig) / set_touch_config_dir / set_touch_pad_visible /
  touch_pad_visible_value.
- Red-first: overlay contract tests (compile-red "no member named
  'overlay'") covering the pad state machine (default -> configure_touch
  emulation -> saved choice wins) and null-safe dir/hook calls; negative
  control: the inverted pad_default check observed failing. The move script
  again missed `override` on the moved interface methods — caught by a grep
  of the generated class before the build.
- Verification: stub 63/63; FFTA build-raylib 67/67, build-raylib-only
  68/68; attract golden byte-identical in both configs; body-move
  token-verified (3/3 bodies; pad-visibility routing checked).

## 2026-10-15 — V2 Phase 2, lifecycle/facade (gbarecompx df141d9) — conversion complete

- The last conversion step: `RaylibBackend` now carries both generations
  (`public WindowBackend, public WindowBackendV2`); one state behind both.
  All five concerns were already sub-objects; this step added the V2
  lifecycle surface.
- `open(OpenParams)`: AlreadyOpen on a second open; Err::Unsupported for
  Mode::Headless unless PLATFORM_MEMORY; Err::Window (InitWindow) /
  Err::Renderer (streaming texture) on failures; Mode maps onto the flat
  fullscreen modes after init (set_fullscreen 1/2). The 9-arg flat open
  forwards, preserving its historical idempotent-true for AlreadyOpen
  (deleted in 4b); the params-struct overload still forwards to the 9-arg.
- `caps()`: build/platform statics — window/input/touch true on GLFW,
  headless true on PLATFORM_MEMORY, shaders true except under rlsw — plus
  live state: audio from audio_ready, vsync_report from the new
  vsync_probed flag (set by both monitor probes), multi_monitor from
  GetMonitorCount (added to RaylibApi). rumble/haptics/menu false (raylib
  has no rumble query; the old predicate returned false — recorded as the
  open question for Phase 4: a host gating rumble on caps would lose
  desktop rumble; input().rumble() itself no-ops safely). reopen true on
  desktop only.
- `suspend()/resume()`: desktop no-op true (no lifecycle to suspend, no
  device teardown); the Android port (Phase 4f) grows the real pause/rebind.
- The five accessors gained `override`; close/is_open/pump/set_runtime_ui/
  wait_for_foreground already satisfied both bases (same signatures).
- Red-first: facade contract tests (config-aware caps via the PUBLIC
  GBARECOMP_USE_RAYLIB define, headless refusal, AlreadyOpen, close/reopen,
  accessor identity). The compile-red was not observable (base + test are
  one change) — the headless-gate mutation was observed failing instead.
- Verification: stub 63/63; FFTA build-raylib 67/67, build-raylib-only
  68/68 — the raylib run exercises the FULL lifecycle (real window, audio
  device, reopen) on a display; headless CI takes the Err::Window branch;
  attract golden byte-identical in both configs.
- Phase 2 remaining: the §5.2 item 3 fakes (RecordingVideo, ScriptedInput,
  TappingAudio, FakeClock, FakeBackend) + the display-free slice of the
  lifecycle contract test.

## 2026-10-15 — V2 Phase 2 tail: fakes + contract slice (gbarecompx e3be683) — PHASE 2 COMPLETE

- `tests/runtime/support/fake_backend.h` (§5.2 item 3): `RecordingVideo`
  (records presents, serves readback from the last frame), `ScriptedInput`
  (scriptable snapshot + observation), `TappingAudio` (single-owner claim
  incl. `refuse_claim` injection, push recording), `FakeClock` (settable
  `now_s`), `FakeBackend` composing them behind the V2 facade (knobs:
  `open_fails`, `caps_override`, `suspend_ok`/`resume_ok`; pump =
  `translate_input(scripted read, edges)` with the clock stamping `now_ms`).
  `FakeFx`/`FakeOverlay` are the minimal storing companions the facade needs
  (the plan names five fakes; Fx/Overlay have no observable behavior to
  fake). Component members are named after their fake types — a member may
  not share a name with the accessor methods.
- `tests/runtime/backend_contract_test.cpp` (§5.2 item 2, display-free
  slice): one contract suite run against (a) the FakeBackend (strict; the
  full scripted checks incl. readback fidelity, audio claim, fx/overlay)
  and (b) the real RaylibBackend (generic lifecycle; a display-less box
  early-outs on `Err::Window`, which the suite accepts). Phase 3's menu
  host-loop test and Phase 5's `RaylibApi` fake build on these.
- Red-first: the contract suite is new test code; the negative control
  (TappingAudio ignoring its second claimant) was observed failing the exact
  CHECK, then restored.
- Verification: stub 64/64; FFTA build-raylib 68/68, build-raylib-only
  69/69 (the raylib run executes the contract against both the fake and the
  real backend — real window open/close on a display); attract golden
  byte-identical in both configs.
- **Phase 2 complete** (all five concerns + lifecycle/facade + the tail).
  Next: Phase 3 — the generic menu (`menu_model.h`, the `Menu`
  presentation, the host-loop test on the fakes).

## 2026-10-15 — V2 Phase 3a: the pure menu model (gbarecompx c7cd371)

- `src/runtime/menu_model.{h,cpp}` (`gbarecomp_menu_model`): the plan §3.4
  model, ported SEMANTICALLY from recomp-ui's `runtime_ui_test.c` (not its
  code): two-level list (sections then rows), Confirm drills in, Left/
  Right/Confirm adjust the selected row (Confirm = +1 with activate),
  Back leaves the section then closes, Toggle flips direction-independently,
  StepInt/Float clamp at min/max, Choice cycles with wrap. Values live in
  the model (host-seeded at open, host-read after `changed_row`); no
  callbacks, no host pointers, no clock (the host decrements the status/
  toast frame counts).
- V2 policy additions over recomp-ui: disabled/invisible rows are skipped
  (and sections with nothing selectable); the pointer mutator selects on
  first press and activates on a second press on the same row; the model
  never sets status itself — the host applies `MenuResult` (the separation
  §3.4's mutator list implies).
- API notes: `menu_value/menu_set_value` became the int/float pair (the
  kind-dependent storage is not losslessly one float);
  `menu_input_from_keyinput` gained a bool return for the none-case (the
  plan's single-arg form cannot express "no input"); `editing` is
  recomp-ui's `in_section` (the drill-in state), documented in the header.
- Red-first: compile-red observed (empty stub header -> the compiler listed
  the whole demanded API). Mutation controls: skip-disabled and
  choice-wrap→clamp caught immediately; **the wrap-direction mutation
  initially slipped** — with two sections, +1 and -1 mod 2 are
  indistinguishable — the test was strengthened to three sections/rows and
  the mutation then fired the exact CHECKs (section and row wraps). This is
  the workflow's second leg doing its job: the red-first compile only
  proved the API existed; the mutation found the blind spot.
- Verification: stub 65/65; FFTA build-raylib 69/69, build-raylib-only
  70/70; attract golden byte-identical in both configs (the model is
  unwired — the differential leg proves nothing else moved).
- Next: 3b (the `Menu` seam interface + `Caps::menu` + the RaylibBackend
  presentation over HostOverlay), then 3c (host wiring + the host-loop test
  on the fakes), 3d (the open trigger).

## 2026-10-15 — V2 Phase 3b: the Menu seam + shared presentation (gbarecompx 68df8d5)

- The seam: `class Menu` in window_backend.h (`available() == Caps::menu`;
  `MenuResult present(MenuModel&, const PointerState&)`), the facade
  `menu()` accessor, and menu_model.h included by the seam. **Recorded
  deviation:** the plan's sketch said `void present(...)`; the pointer path
  (the presentation hit-tests and calls the mutators) needs the resulting
  MenuResult to reach the host, so it is returned — the comment says the
  host applies it exactly like menu_navigate()'s.
- `src/runtime/menu_draw.h` (pure, header-only, the touch_pad_draw.h
  pattern): `menu_compute_geometry` / `menu_hit_test` / `menu_draw` over
  HostOverlay primitives — panel, section list / row list (labels + values
  On-Off / int / %.2f / choice), selected highlight, disabled dimming,
  status line, toast (draws while closed), touch position marker. The
  geometry is computed once per frame and shared by hit-test and draw so
  they can never disagree (even across a resize). At the top level a press
  on a section line maps to its first selectable row, so the press drills in
  through the shared pointer mutator.
- `RaylibBackend::MenuImpl`: present() computes geometry + hit-test (the
  result is immediate — no one-frame latency) and stashes the frame;
  `draw_pending_menu()` (private static) consumes it inside
  VideoImpl::present's Begin/EndDrawing, after the pad chrome — the topmost
  layer, never inside a shader/scale pass; ONE-SHOT, so no model pointer
  survives a frame. `caps().menu = true` (raylib builds; available() agrees).
- RaylibOverlay text is real: text_supported/text/text_width over
  RaylibApi's new `DrawText`/`MeasureText`, aligned via MeasureText, scaled
  through view_scale.
- Fakes: `FakeMenu` (records the model + pointer, scripts the result);
  FakeBackend + NoopBackend implement `menu()`; the contract test checks
  accessor stability and `available() == caps.menu`.
- **Link fix only the raylib-ON config could catch:**
  `gbarecomp_raylib_backend` now links `gbarecomp_menu_model` — the stub
  build compiles the menu calls out, so the standalone config stayed green
  while FFTARecomp failed to link. Same lesson as the Input step: the ON
  config is the one that sees the guarded code.
- Red-first: `menu_draw_test.cpp` (a recording HostOverlay — the plan's
  "assertable with a recording overlay") written against the missing header
  (compile-red) + the v2 test's `caps.menu` expectation flipped first
  (compile-red for `menu()`). Mutation controls: hit-test invisibility
  caught immediately; **the header-offset and editing-highlight mutations
  initially slipped** — relative hit points move with the geometry bug, and
  the editing highlight had no check at all — both tests strengthened with
  absolute-y checks, then the mutations fired.
- Verification: stub 66/66; FFTA build-raylib 70/70, build-raylib-only
  71/71; attract golden byte-identical in both configs (the menu is closed
  by default — nothing draws, nothing moved).
- Next: 3c (host wiring: build the model from settings on open, apply
  MenuResult to Fx/Audio/Video, persist, derive suppress_game_input; the
  host-loop test on the Phase 2-tail fakes), 3d (the open trigger).

## 2026-10-15 — V2 Phase 3c: host wiring + the host-loop suite (gbarecompx 384dac2)

- `src/runtime/host_menu.{h,cpp}` (`gbarecomp_host_menu`): the §3.4/3c host
  wiring. Owns the MenuModel; build() seeds the default rows from the
  backend's current settings (Display: Fullscreen/Window scale/Linear
  filter/Show FPS; Graphics: LCD ghosting, Frame interpolation, the LCD
  shader group when caps.shaders; Audio: Audio/Volume; System: Resume game —
  labels mirror recomp-ui's standard catalog); open()/toggle() rebuild then
  open; frame() maps newly-pressed keyinput edges to menu_navigate plus the
  backend.menu().present() call; apply() maps changed_row through a per-row
  Bind table to Fx/Audio/Video with read-back reseeding (backend clamps
  win); Resume game is framework-owned; set_rebuild_hook lets games
  re-append rows on every build; set_apply_hook carries persistence and
  game-owned rows/actions; suppress_game_input() derives from model.open.
- **The B1 flaw the first audit caught (and the fake suite could not):** the
  backend masks Events::keyinput while the menu is open (its
  suppress_game_input derives from the presented model), so a host menu
  navigating from keyinput freezes on the first open frame — the delivered
  wiring and the delivered suppression were mutually exclusive. Fix:
  `Events::menu_keyinput` (the pre-suppression levels, set by
  translate_input next to the masked keyinput) + a pump-path regression
  test (scripted suppress_game_input: the game sees 0x03FF, the menu still
  navigates). Lesson (same family as the raylib-ON-only catches): the
  integration seam the fakes never exercise (pump) is where the contract
  breaks; the host-loop suite now goes through pump().
- menu_model: menu_add_row() — the safe append (returns -1 at capacity);
  the documented game-append idiom previously walked rows[] out of bounds.
- RaylibBackend: MenuImpl::present derives impl_->menu_open from the
  presented model; InputImpl::read reports it as suppress_game_input (raylib
  + state-only stub branches); close() resets it with the edges (the single
  reset point — a closed read reports nothing; an open-side reset was
  dropped as mutually redundant, which the mutation control confirmed).
- Second audit verified the fixes; its remaining findings were closed:
  menu_add_row, the window_backend.h menu_keyinput comment (precise
  invariant; the flat SDL generation predates the field), the close()
  comment accuracy, rebuild-hook re-entrancy documented, and
  input_translate_test now pins the raw/masked split at the source.
- Verification: stub ctest 67/67; FFTA build-raylib 71/71, build-raylib-only
  72/72; attract golden byte-identical in both configs (menu closed by
  default). Mutation controls: 12/12 main battery + 4/4 follow-up (the 4th
  needed the right grep — input_translate_test's helper prints FAIL, not
  "CHECK failed"). One restore snippet had new/old swapped and left a
  mutated tree while a sweep was launching — killed the sweep, repaired,
  re-verified (recorded: `pkill -f` self-matched and killed the fixing
  shell; use `ps -eo pid,args | awk` filters).
- Next: 3d (the open trigger + cue: the engine long-press ring moves
  host-side) closes Phase 3; then Phase 4 (the switch) with human sign-off.

## 2026-10-15 — V2 Phase 3d: the open trigger + cue + FFTA wiring (gbarecompx f6b4dee)

- `long_press_ring.h` (pure): the engine long-press cue —
  `collect_long_press_rings` (held/unmoved/not-fired pointers; hidden for the
  first 150 ms; progress = elapsed/long_press_ms clamped; wrap-safe
  arithmetic) + `draw_long_press_ring` (7 mm radius, 1.2 mm stroke,
  {80,210,255,200}, clockwise from 12 o'clock, drawable space) — the exact
  semantics of the SDL `draw_engine_long_press`. Suite:
  `long_press_ring_test.cpp` (recording overlay + collector rules).
- RaylibBackend: the chrome block draws the ring (same gating as SDL: touch
  enabled, unclaimed long-press, hidden while the V2 menu is open); the
  backend no longer drains TouchHub host actions (the host policy consumes
  them). The v2 test asserts a submitted ThreeFingerTap survives
  `input().read()` with touch enabled (the drain sits behind that gate — the
  first version of the test passed pre-fix because touch was off).
- `HostWindow::backend_v2()` (dynamic_cast; nullptr on SDL) + the runtime.cpp
  host policy: per pump, drain TouchHub host actions — any engine action
  opens the generic menu (and `cancel_all` stops the triggering finger), Back
  closes it; a PointerState from the first hub point drives row taps;
  `host_menu.frame()` presents; the opening frame masks `ev.keyinput` too.
  Persistence deliberately unwired (the legacy menu did not persist either;
  the apply hook is the seam).
- E2E acceptance (windowed, `--touch-emulation`, TCP-driven; no xdotool —
  window discovery via xprop, input via the product's own TCP touch surface):
  long-press → ring visible (cyan delta ~490 px) → panel drawn (35602 px of
  exact panel color; 0 before, 183 after) → Back closes; then touch-driven
  navigation (drill into Display, select Show FPS, activate) → the window
  title gains " — 59.8 fps" (the applied Video setting), sticky after close.
  Script: `/tmp/opencode/e2e_3d.py` (recreatable, not committed). Lessons
  from the E2E: raw pixel diffs are polluted by the pad/pill appearing on
  touch activity — detect the panel by its exact fill color instead; the
  center-luma check is scene-dependent (the attract scene varies at pause).
- Verification: stub ctest 68/68; FFTA 72/72 + 73/73; attract byte-identical
  in both configs; 6 mutation controls (5 ring + the drain). Recorded debt:
  the ring-draw call site in present() and the runtime.cpp host policy are
  E2E-covered only (no unit test).
- Note: the `build/` tree is configured against the **gbarecomp submodule**
  (`GBARECOMP_ROOT=…/gbarecomp`), not the fork — its test targets cannot
  build fork-only files (`host_backend_factory.h`) and its bios_smoke ImGui
  link failure is the submodule's. The fork configs are `build-raylib` /
  `build-raylib-only` (+ the framework standalone build).
- **Phase 3 accept complete:** model suite green headless; presentation
  covered by a recording fake; FFTA's raylib build opens and applies the
  display menu; attract golden unchanged (menu closed by default).
- Next: Phase 4 (the switch: V2 live, SDL deleted) — needs human sign-off.

## 2026-10-15 — V2 fix: menu flicker under frame interpolation (gbarecompx e14eefc)

- Playtest finding (user): "when LCD shader is enabled, the menu is
  flickering" — follow-up narrowed it to **frame interpolation** (the LCD
  association was coincidental).
- Root cause: the decoupled display clock (issue #9 3a) subdivides a guest
  frame's wait into extra display-paced presents — `interp_display_tick`
  calls the full `present()`. The menu draw was stashed once per pump and
  consumed by the first present ("one-shot"), so the extra interp ticks in
  that wait rendered the game WITHOUT the menu → the flicker.
- Fix: `draw_pending_menu()` no longer clears the stash; it lives until the
  next `menu().present()` (which clears and re-sets it at its start), so
  every present of the frame carries the menu. `close()` clears it with the
  rest of the derived menu state.
- Observation lesson (recorded): window pixel probes via `import` on this
  compositor race the GL buffer swap — ~1-3% of grabs return near-black or
  partial buffers (mean 0.002) at a rate that scales with the present rate,
  masquerading as menu-less frames (the interp correlation was an artifact
  of that). Minimum discipline for this class: recapture immediately to
  classify; the playtest is the real acceptance.
- Verification: stub 68/68; FFTA 72/72 + 73/73; attract byte-identical in
  both configs (interp off by default; the fix only changes the menu stash
  lifetime).


## 2026-10-15 — audio "ticking" report triaged: path healthy, tool added

- Report (user, playtest): metronomic ticking in the audio, ~1-2/s, "always,
  regardless of settings"; suspected new sound effects. Follow-up: "seems
  new, but we never ran the game after the audio changes were done" — the
  exact shape of a real regression, so it got a full triage.
- Ruled out by inspection: **zero sound-effect calls in the runtime** (no
  PlaySound/LoadSound anywhere in `gbarecompx/src/`), and no recent commit
  touches audio (the flicker fix is one draw function; Phase 3d is the
  trigger/cue; the intro-lag audio work was Android-gated, "desktop
  untouched").
- Live triage (two ~40 s attract sessions + one 25 s validation run, raylib
  build, TCP sampler at 20 Hz + FIFO trace at 4 Hz + sink-monitor
  recording):
  - producer 65544 Hz vs 65536 nominal (**+0.013%**; -0.03..-0.17% on
    short/boot-inclusive windows);
  - frames 59.71/s, no guest stalls (largest poll gap = the 50 ms poll);
  - **0 broadband transients** in ~75 s of recording (strongest modulation
    2.8 Hz = the attract music's beat, present in every run);
  - FIFO-empty sample events (`count==0 && remaining==0`, where the
    emulation emits silence) only during boot silence and in small bursts
    every ~5 s — the attract's music gaps at scene changes, **not**
    starvation; DMA refill level cycles 0-7 words exactly as designed
    (`fifo_needs_dma` = `count < 4`).
- Conclusion: no emulation- or host-side tick pattern. The user's tick
  vanished and correlated with another video sharing the audio sink —
  external to the game. Recorded anyway: "seems new + never ran since the
  audio changes" is how a real regression presents, so the method (and its
  numbers) are now a baseline.
- Tool added: `tools/audio_session.py` — one command around a play session:
  live sampler + monitor recording + end-of-session report (pure Python, no
  numpy). Validated live end-to-end (two runs). Complements
  `GBARECOMP_AUDIO_PROBE=1` (SDL path only) and the TCP
  `audio_state`/`audio_trace` commands; listed in `tools/README.md`.
- Tooling note (verified, small debt): TCP `quit` ends only the debug
  connection — in a windowed `--tcp-observe` session the server runs in a
  side thread and `want_quit` is local to its connection loop, so the game
  keeps running (observed alive 5 s after `{"cmd":"quit"}`); `host_quit` is
  fed by window events only. `quit.py`'s clean close therefore applies to
  the headless `--tcp` path (where the server *is* the run loop); the
  practical stop for observe sessions is closing the window / SIGTERM.

## 2026-10-15 — V2 Phase 4a: HostWindow delegates to the V2 facade (gbarecompx 6df93f6)

- Change: every HostWindow method prefers the V2 facade when the backend
  implements it (cached at open, cleared at close); the flat generation is
  the fallback for the SDL config until 4b deletes it. Public surface
  unchanged. The seam gained `Fx::load_config(dir)` — the [video] block's V2
  home (Input::load_config is the input half), so the config pair survives
  the delegation switch; the flat forwarder's private static moved into
  FxImpl.
- Red-first: new app-side test `ffta_host_window_delegation_tests` (both
  app configs) asserts "with a V2-capable backend NOT ONE flat method is
  reached" — flat calls == 0 across the whole public surface, with the V2
  fake recording every effect. Observed failing at `spy.v2.open_calls == 1`
  before the rewrite (HostWindow called the flat open). The flat-only case
  proves the fallback AND the spy coverage (flat count == expected), so the
  zero-flat assertion cannot be vacuous. Same-signature collisions
  (close/is_open/pump/wait_for_foreground/set_runtime_ui) are one final
  overrider by C++ rules — the two paths are indistinguishable there by
  construction; the test asserts the recorded call instead.
- Mutations (4/4 caught, each a distinct assertion): set_volume→flat,
  set_title→flat, lcd_boost→wrong Fx field, open()'s flat fallback removed.
- Differential: ctest 73/73 (SDL config) + 74/74 (raylib); attract byte-identical in both
  configs (`1EF4C118...`); ws_check PASS (6 cases x 3 widths); the framework
  stub config 68/68; the known pre-existing `bios_smoke` link failure is
  unchanged (submodule ImGui link break).
- Next: 4b (delete the flat generation + the SDL backend; rename
  WindowBackendV2 → WindowBackend; retire GBARECOMP_USE_RAYLIB as a
  backend-selection flag; the flat fallback branches in HostWindow go with
  it).

## 2026-10-15 — V2 Phase 4b: the switch — flat generation + SDL deleted (gbarecompx 8cadb3b)

- window_backend.h: the flat generation (`WindowBackendOpenParams` + the
  56-method class) deleted; the facade renamed `WindowBackend` (the
  historical `using Events` alias kept so every `WindowBackend::Events`
  reference stays valid); `set_runtime_ui` deleted from the seam.
- host_window.cpp: the SDL backend region (~3.2k lines: the inline
  `Backend`, its helpers, SDL/ImGui includes) deleted — the file went from
  164 KB to ~19 KB of single-branch delegation (impl_ is the facade) plus
  the no-backend stub. `service_events` is a no-op; `set_runtime_ui` is a
  compile-compat shim.
- host_backend_factory: the SDL branch gone; `GBARECOMP_USE_RAYLIB` is no
  longer a *backend* selector (ON = RaylibBackend, OFF = nullptr stub).
- raylib_backend: V2-only (flat forwarders, the flat open overloads,
  `set_runtime_ui`, the `runtime_ui` field and its dead suppression read all
  deleted; the runtime-UI include dropped). `OpenParams::Mode` now applies
  through `Video::set_fullscreen`.
- CMake (framework): SDL discovery/static-release/staging/define/link and
  the ImGui-SDL-renderer runtime-UI adapter deleted (the app-side launcher,
  Track L, keeps its own SDL2 — its `find_package` is app-scoped).
- Red-first: the completeness guard rewritten for the single-generation seam
  — (1) single generation (no `WindowBackendOpenParams`, no
  `host_make_sdl_backend`, no `GBARECOMP_HAVE_SDL2` in the runtime, no inline
  `Backend` struct), (2) every interface method pure (`= 0`; a defaulted
  body is the silent-inheritance bug class that bit once), (3) every
  interface method overridden by the raylib backend sources. Observed
  failing against the pre-4b tree (flat present, SDL present, WindowBackend
  impure) and green after. Self-tests rewritten (15 cases incl. the impure
  method, the flat marker, the SDL factory/define/struct markers and the
  per-interface scan; the constructor false-positive the rewrite surfaced was
  fixed).
- Tests: the four flat-seam tests deleted (`window_backend_test`,
  `window_backend_dispatch_test`, `window_backend_virtual_dispatch_test`,
  `raylib_backend_test` — 4d ports the per-interface tier);
  backend_v2_types, fake_backend, raylib_backend_v2, host_window_closed and
  the FFTA present test updated for the single generation; the FFTA
  delegation test is now the host→facade wiring contract (every HostWindow
  method reaches its concern) plus the open-failure ownership case.
- Verification: ctest 70/70 (raylib-only) + 69/69 (OFF) + 64/64 (framework stub); attract
  byte-identical in both configs (`1EF4C118...`); ws_check PASS; android-static
  PASS; guard + self-tests PASS; `nm` on the runtime archive: 0 SDL refs;
  mutations: the guard caught a re-added flat marker, the delegation test
  caught lcd_boost writing the wrong Fx field.
- Note (the Accept's `ldd` line): the *runtime* is SDL-free (`nm` on
  `libgbarecomp_runtime.a` reports zero SDL references — now a failing gate
  in the sweep); the app's `ldd` still shows SDL because the recomp-ui
  launcher (`game_launcher_ui`, Track L) links it — retired by 4e/7, not a
  4b blocker.
- Next: 4c (flip FFTA's default build to raylib; play.sh/check.py/CI naming).

## 2026-10-15 — V2 Phase 4c: raylib is the default build (gbarecompx 07ee5fe)

- Root CMake declares the product default:
  `option(GBARECOMP_USE_RAYLIB ... ON)` before add_subdirectory. option()
  never overwrites an existing cache entry, so the framework's own OFF default
  still governs standalone framework builds and `-DGBARECOMP_USE_RAYLIB=OFF`
  still opts out (verified). `build/` — the dir every app suite (attract,
  routes, ws_smoke, hle-audit, unit-cpp) already runs from — was wiped and
  reconfigured from scratch: it is now the raylib product build.
- Framework (gbarecompx): the option text lost the "experimental/scaffolding"
  framing, and the OFF branch now `unset(GBARECOMP_RAYLIB_ENABLED CACHE)` — a
  stale INTERNAL=ON used to survive a flip to OFF in the same build dir, which
  would make parents add raylib-only targets and would falsely pass the new
  default probe (verified both directions on a scratch dir).
- Red-first: a default (no-flag) configure must select raylib. Pre-flip:
  "RaylibBackend built stub-only", `GBARECOMP_USE_RAYLIB:BOOL=OFF`, no
  effective flag → RED. Post-flip: "linked against raylib 6",
  `GBARECOMP_RAYLIB_ENABLED:INTERNAL=ON` → GREEN.
  The check is permanent:
  - `check.py --only backend-default` (new; cheap; in FAST): asserts build/'s
    effective flag and runs `ffta_backend_select_tests` expecting "raylib=1";
  - `check.py --only raylib-compile` now configures `build/` with NO flag and
    asserts the effective flag before building the backend/present test (the
    present-test target only exists when raylib was actually fetched).
- Naming: `tools/play.sh` defaults to `build/FFTARecomp` and `--sdl` was
  retired (exit 2 with a message); `check.py`'s raylib-compile suite dropped
  `build-raylib-only` (now redundant); `.github/workflows/ci.yml` comments
  updated (the raylib job is the product gate; tier1's configure is inert
  until Phase 7 repoints GBARECOMP_ROOT at the published tree).
- Android unaffected: the Gradle build uses the pinned submodule by default
  (no raylib target, ignores the flag) — the SDL shell stays until 4f; a
  `-PgbarecompRoot=<fork>` build now defaults to raylib, which is the 4f
  direction.
- Verification: fresh product build from zero; ctest 70/70 in build/; backend_select PASS
  (raylib=1); attract byte-identical (`1EF4C118...`); check.py --fast 8/9
  (only the pre-existing patches-suite items red — the recomp-ui drift
  files carry Oct 13-14 mtimes and 4c touched neither submodule);
  raylib-compile PASS; ws_check PASS; android-static PASS; runtime SDL
  refs 0; windowed smoke of the switched build: raylib 6/GLFW init,
  present-in-place, 600 frames presented, clean close, FULLY_STATIC.
- Mutations: M1 (build/ flipped OFF → the probe FAILS; back ON → PASSES), M2
  (`--sdl` exits 2). Attract golden byte-identical on the switched build.
- Next: 4d (port framework/app tests to the per-interface surfaces; rewrite
  the completeness guard's per-interface tier), then 4e (release packaging:
  SDL2 pin → raylib cross-build), 4f (Android scaffold swap).

## 2026-10-15 — V2 Phase 4d: per-interface guard + dispatch walk (gbarecompx ecda458)

- Guard rewrite (`tools/check_raylib_backend_complete.py`): attribution is now
  per interface — every method of each of the 7 surfaces must be overridden at
  ITS OWN impl site (the facade in the `RaylibBackend` class body, the five
  concerns in their nested impl classes). The old union scan over both backend
  files accepted a method implemented in the WRONG impl class; the new scan
  catches it. Mutation (real tree): moved `VideoImpl::refresh_hz`'s definition
  into `AudioImpl` — the old guard still printed "window seam complete", the
  new one names "MISSING override: Video::refresh_hz() — not overridden in
  RaylibBackend::VideoImpl". Restored → PASS.
- Guard self-tests: 18 cases (parser regressions + the 4b checks + three new
  attribution cases: wrong-class, cross-interface collision, facade-in-wrong-
  site). The three new cases were RED against the old union scan before the
  rewrite.
- Restored the deleted flat dispatch tier in per-interface form:
  `tests/runtime/window_backend_dispatch_test.cpp` — a surface walk that drives
  EVERY method of EVERY interface through its interface type (`WindowBackend&`,
  `Video&`, `Audio&`, `Input&`, `Fx&`, `Overlay&`, `Menu&`) against the §5.2
  fakes and asserts each call lands on the composed implementation (59 methods
  across 7 surfaces). Accessor-identity checks make a broken accessor fail.
  Mutation control: `FakeBackend::video()` returning a different object → the
  walk fails at the identity check; restored → PASS. Registered as
  `window_backend_dispatch_tests`.
- App tier: fully ported (4b/4c — delegation/closed/present/select); no stale
  transition references remain outside history.
- `check.py`'s guard docstring updated (the 56/56 flat-era wording → the
  per-interface contract).
- Verification: guard self-test 18/18 + real tree (59 methods across 7 surfaces) +
  the real-tree mutation caught (the old union scan false-accepted);
  dispatch walk PASS + accessor-identity mutation caught; ctest 71/71
  (FFTA build/, +1) and 65/65 (framework stub, +1); attract
  byte-identical (`1EF4C118...`); check.py --fast 8/9 (only the
  pre-existing patches-suite items red); raylib-compile PASS; ws_check
  PASS; android-static PASS; runtime SDL refs 0; off-app-config +
  stub-backend builds green.
- Next: 4e (release packaging: the SDL2 pin → raylib cross-build, remaining
  SDL references), 4f (Android scaffold swap to raylib/NativeActivity), then
  Phase 5/6/7.

## 2026-10-15 — V2 Phase 4e: release packaging off the SDL2 pin (gbarecompx c7e9852)

- The Windows release no longer fetches raylib: `tools/win_cross_deps.py` gains
  a pinned raylib 6.0 dep (tarball sha256 `2b3ee1e2...`; same release as the
  framework's FetchContent SHA `dbc56a87...`), installed into the cross prefix
  (`libraylib.a` + `include/raylib.h` + `lib/cmake/raylib/*`). The FFTA root
  CMake prefers the prefix when cross-building (`if(MINGW)
  find_package(raylib CONFIG QUIET)`, with a message naming the path), and the
  framework's raylib block now only fetches when no `raylib` target exists.
- Red-first: pre-4e the cross configure pulled raylib via FetchContent
  ("gbarecompx: building raylib 6.0 (dbc56a87...)", "Using raylib's GLFW");
  post-4e it prints "ffta: raylib from the cross prefix (...)" with no fetch.
  The release preflight now requires the raylib prefix marker.
- Packager: dropped the stale `-DGBARECOMP_MINGW_PREFIX_UNIX` flag (the
  framework stopped consuming it in 4b); raylib added to the prefix
  completeness check; `LICENSES/ZLIB-raylib.txt` staged (verbatim upstream
  license) with the attribution table's raylib row and the Windows-DLL note
  updated. `tools/README.md`'s prefix row updated.
- Desktop unaffected: `build/` still takes raylib via FetchContent (verified:
  reconfigure + rebuild + `backend_select raylib=1` + guard green).
- Verification: cycle.py PASS (cold regen 63,134 fns, build, attract byte-identical
  `1EF4C118...`); ctest 71/71 (build/) + 65/65 (framework stub); check.py
  --fast 8/9 (only the pre-existing patches-suite items red); the
  Windows release: static imports=29 (all system DLLs), wine smoke
  FULLY_STATIC (`FFTARecomp-v1.6-29-g8e74633-dirty-windows-x64.zip`
  sha1 369f2552..., 43.6 MB); the Linux packager PASS; ws_check PASS;
  android-static PASS (23 checks); runtime SDL refs 0.
- Mutations: M1 (hidden raylib marker → the release preflight fails with
  "cross prefix incomplete: raylib"; restored → present), M2 (the cross
  configure takes the prefix; no FetchContent line).
- Next: 4f (Android scaffold swap to raylib/NativeActivity — the last SDL
  stronghold), then Phase 5/6/7.

## 2026-10-15 — V2 Phase 4f: the Android scaffold is raylib/NativeActivity (gbarecompx c2b2cf1)

- The SDL shell is retired: the SDL submodule
  (`platform/android/third_party/SDL`) and its `.gitmodules` entry are gone;
  the native root (`platform/android/cpp`) builds the game project directly
  (`PLATFORM=Android`; raylib via the framework's FetchContent — the same pin
  as desktop); `GbaGameActivity` moved off SDLActivity onto
  `android.app.NativeActivity` (the manifest carries `android.app.lib_name =
  main`; the vendored `native_app_glue` runs `android_main` on its 256 MiB
  thread); `GbaSetupActivity`/`GbaNative` stay. The Gradle plugin lost
  sdlRoot/the SDL Java srcDir and pins the proven NDK 28.2.13676358. The
  raylib spike was promoted and deleted (its material is the scaffold now).
- FFTA: the Android Gradle project prefers `gbarecompx` (mirroring the
  desktop CMake); `src/main.cpp`'s SDL branches (the storage lookup +
  `SDL_main`) are gone — the user-visible dir comes from the baked
  applicationId; the root CMake dropped the SDL2 link block; the README was
  rewritten for the new base.
- Red-first: the new `android-static` scaffold check (no SDL submodule
  entry/gitlink, no SDLActivity, no SDL CMake subproject, no sdlRoot, no SDL
  tokens in the scaffold's code/docs) — observed failing with the full
  offender list pre-4f and green after (24/24 checks). The save-external
  check now asserts the baked-applicationId mechanism (it encoded the SDL
  call).
- Catch on the first APK build: raylib 6 requires CMake >= 3.25; the scaffold
  pinned the SDK's 3.22.1 (the pre-4f shell's version), so the Gradle
  configure failed ("CMake 3.25 or higher is required"). The pin moved to
  3.30.3 — the version the on-device spike used.
- Verification: cycle.py PASS (cold regen 63,134 emitted units, build, attract
  byte-identical `1EF4C118...`); ctest 71/71 (build/) + 65/65 (framework
  stub); check.py --fast 8/9 (only the pre-existing patches-suite items red);
  ws_check PASS; android-static PASS (24/24); runtime SDL refs 0; the NDK
  clang syntax pre-check green.
- Platform law (BRINGUP night 12): raylib-Android cannot close→reopen in one
  activity; the port pauses/rebinds and never calls `CloseWindow`
  (`caps.reopen` encodes it).
- Device debugging (first divergence, root-caused): the first private build
  installed and launched, but the game exited immediately. Root cause: the
  NativeActivity storage path needs `GBARECOMP_ANDROID_PACKAGE`
  (mobile_platform.h) and the scaffold never passed it — the pre-4f shell got
  the path from its own accessor, so nothing had ever needed the define.
  Without it `mobile_internal_storage_path()` is null → no chdir → the
  engine's log open fails (native stderr stays on /dev/null) → the relative
  ROM path never resolves → the runtime exits silently (no crash entry). Fix:
  the Gradle template passes `-DGBARECOMP_ANDROID_PACKAGE=<applicationId>`
  (PUBLIC on gbarecomp_runtime, so both the framework's chdir and the game's
  baked external dir resolve).
- Second device finding: the Java shell's JNI bridge
  (`GbaNative.setSafeInsets`/`setDisplayDpi`) lived in the retired shell's SDL
  region, so the NativeActivity build exported nothing ("No implementation
  found"). Ported into `mobile_platform.cpp` (an atomics store — JNI calls
  arrive on the UI thread, the runtime reads on the glue thread) and consumed
  live by the raylib backend (insets per frame; the panel density through the
  same 4..60 px/mm sanity window the SDL path used). This also fixes
  `px_per_mm`, which had been stuck at the desktop 96/25.4 constant on
  Android.
- Third device finding: with the launcher off for raylib Android
  (`GBAGAME_RECOMP_UI`), the game's bundled-ROM check became reachable — the
  pre-4f shell compiled it out (launcher on), so nothing had ever passed
  `GBAGAME_BUNDLED_ROM`. The template now maps `-PprivateRom` to
  `-DGBAGAME_BUNDLED_ROM=ON` (private builds boot; the ROM is staged in the
  payload). The check's public arm also refused outright, which would have
  broken the public APK's post-import boot: it is now a ROM-presence check
  (`roms/ffta_usa.gba` beside the app files dir), restoring public parity
  with the old builds.
- Fourth device finding (link): `recomp_runtime_ui_*` was undefined — the
  framework defines `GBARECOMP_RUNTIME_UI` whenever the recomp-ui tree
  exists, and the runtime-UI symbols are carried by the launcher target,
  which is off for raylib Android. Matches the plan's own statement that
  recomp-ui's UI is not ported to the raylib path: the FFTA root now clears
  `GBARECOMP_RUNTIME_UI_ROOT` for raylib Android (before the framework's
  add_subdirectory), so the define and the dead references both go.
- FetchContent guard lesson: the module CACHES its default base dir on the
  first configure, so the initial `if(NOT DEFINED ...)` guard never fired for
  existing config dirs (the cache still held the `.cxx` path). The scaffold
  now replaces only the default value and respects an explicit
  `-DFETCHCONTENT_BASE_DIR`.
- Widescreen regression (user-reported: "worked in the SDL version"): the
  shell rendered fullscreen (the drawable = the display), so the Android
  TOML's `resize_view = true` expanded the view. The raylib window opened at
  the scaled request (720x480), which raylib letterboxes into the surface —
  the resize-driven view then saw a 3:2 drawable, its width resolved to 240,
  and the height-growth branch clamped at `max_resize_view_height` (default
  160) left the geometry unchanged. Fix: the Java shell writes the display's
  real size to `files/display.ini` before `super.onCreate` (the native thread
  starts there) and the backend opens the window at that size — screen ==
  render == display, matching the old shell. Also added a one-line
  resize-view decision record (`resize_view/opts/max/window`) and un-gated the
  applied-geometry line, so a silent 240 view is diagnosable on device.
- The JNI port alone wasn't enough (user-reported: the touch controls shrank
  after the widescreen fix — the pad is sized in millimetres from px_per_mm):
  NativeActivity loads libmain.so in its own linker namespace, which the
  native-method lookup does not search, so the calls failed with "No
  implementation found ... is the library loaded, e.g. System.loadLibrary?"
  (the Java catch hid it; the *symbols* were exported — verified with
  `nm -D`). The retired shell's SDLActivity did an explicit
  `System.loadLibrary("main")`, which registers the library with the
  classloader. GbaNative now does the same in a static block. Effect:
  px_per_mm 3.78 (desktop default) -> the device's real ~20.3 px/mm (SDL
  logged 22.05), so the touch pad returns to its SDL-era physical size, and
  the real cutout insets arrive.
- Touch pad size knob (user: "a bit large now. is there a step down?"): the
  millimetre layout had no scale input. Added `TouchConfig::pad_scale` (the
  seam), `HostWindow::set_touch_pad_scale` (additive; applied by the next
  `configure_touch`), `--touch-pad-scale` / `[touch] pad_scale` (0.5..1.5),
  applied at the pad consumers only (layout inputs, pad/ring drawing, the
  presentation's `drawable_px_per_mm`, gesture thresholds) — the seam's
  `Video::px_per_mm()` still reports the physical panel density. The Android
  TOML ships `pad_scale = 0.85` (payloadVersion 5); `debug-args.txt` gives
  live tuning on device.
- Follow-up (same round): the generic menu lost the retired recomp-ui UI's
  view-mode control — no View row, and on Android the TOML was the only
  lever. Adding a View choice row (Native / Adaptive / 16:9).
- Lesson (Android-only code): the desktop and stub builds compile the
  Android-gated blocks out, so an Android-only compile error slips past both
  (observed: the JNI-refresh helper named the private `Impl` from a free
  function — it needed to be a private static member like its siblings).
  Cheap pre-check before the ~8-minute Gradle build: a syntax-only NDK clang
  invocation of the touched TUs with the same flags (seconds).
- Device gate: 5/5 (GbaGameActivity resumed, cpu_backend=static-recompiled,
  crash buffer clean) + user acceptance 2026-10-15 (widescreen correct in the
  move state after the margin fix; the touch pad at the real panel density
  with the 0.85 step; saves/states/suspend live).
- Next: Phase 5 (the headless tier / standalone render proof), 6 (docs pass),
  7 (the repoint to the published framework).

## 2026-10-15 — Widescreen margins: withdraw the layer skip (move-state break + summon clip)

- Report: on the device the wide-view margins "turn off" while a unit is in the
  move/targeting state; the same state on the desktop looked correct.
- Measured (same state both sides, in the move state): device margins are the
  exact 256-px tilemap wrap (mean |diff| 1.68 against the native view's columns
  +256; 36-40 against anything else) — the aliased seam, with map content
  clipping at the native 240 span. Desktop margins are true off-screen ring
  content (neither wrap nor continuation), steady over 20 samples; live
  registers: BG0/BG1 256-px wide at 0x5000/0x5800, BG2/BG3 the 512-px field
  ring at 0x6000/0x7000.
- Mechanism: FFTA swaps layer roles in the move state (the ring moves to
  BG2/BG3; the 256-px UI layers to BG0/BG1). The plugin's margin provider
  hard-coded "BG2/BG3 = UI -> skip in margins" (correct only for the W1-W3
  validated config, ring on BG0/BG1) and therefore skipped the ring itself.
  The desktop hid it because build/mods/state.toml had the feature disabled
  (the engine's never-touched default; android/payload/mods/state.toml already
  works around that trap with an explicit enabled = true).
- Red-first: flipping the desktop's build/mods/state.toml to enabled = true
  reproduced the device break on the desktop (user-confirmed: "desktop is
  broken now with that change. it matches the broken mobile").
- Fix, interim (src/main.cpp): the skip derived per frame from the BGxCNT size
  bits (256-px-wide tilemaps never paint margin columns). This fixed the move
  state but was withdrawn after the Totema summon report.
- Summon investigation (user: "the totema summon ... is clipped during the
  animation"): a deterministic replay from state1 driving the session's own
  input trace (frames 44025-44229, the summon; set_keyinput per event, then
  120-frame sampling) shows the summon window is PIXEL-IDENTICAL with the
  feature enabled (both fix variants) and disabled — the margin skip and the
  sprite clip change nothing there. The visible "clipping" was
  presentation-side (a fresh session after the rebuild reads "much better");
  the replay stays as the A/B harness.
- Fix, final: the BG margin skip is withdrawn entirely (no provider, no
  authored-margin bypass) — the engine's window-controlled sampling stands,
  which is the behavior the feature-off desktop always had and which the move
  state renders correctly (the ring wins the compositing). Kept: the
  world-map pillarbox (W3). The sprite clip's parked test was refined to an
  origin rule (gba_ppu.cpp: parked = the origin off the native 240 span,
  `sx < 0 || sx >= 240`; an in-view sprite may extend into the margins) and
  then withdrawn for FFTA in the pan follow-up below. The framework spec
  stays asserted by ppu_smoke (gbarecompx 69b07b6; the extent-overlap
  variant leaked parked sprites — CI failure on 5dc8e86).
- Verification: the skip-withdrawn build passes ws_check 6 cases x 3 widths
  (ring scenes 100% margins, pillar scenes flat, stale guard 81-96%) — the
  engine's window-controlled sampling fills the ring scenes on its own. The
  interim width-mask build's mutation control (the inverted width rule) failed
  the suite on the stale guard (0.0% idle-vs-pan change); the withdrawn-skip
  build passes it unchanged. Android APK rebuilt + installed (device log:
  policy + sprite clip installed, 356x160 margins 58/58); the install
  cold-boots the app — player saves/states persist.
- Mods packaging: the widescreen package bumped 1.0.0 -> 1.0.1 (manifest +
  both state.tomls + payloadVersion 6) so installed payloads re-stage; the
  version chain is load-bearing (strict lookup in mod_runtime.cpp).
- Pan follow-up (user: "the wide view is not revealing them though ... when the
  camera moves and pans, those characters are clipped out even though the
  level and background are still drawn"): the sprite-level clip hid sprites
  whose extent lay entirely outside the native span — but a camera pan puts
  *real* units there (they stand on the map, revealed by the wide view). The
  OBJ clip is therefore withdrawn too (`g_ws_obj_native_clip` stays 0).
  Result (user): no artifacts or odd rendering in the margins — the clip
  stays gone. The off-viewport units are nevertheless still clipped with the
  clip off; the OAM probe of the pan session (deterministic replay, per-frame
  `read_oam`) answers it: the guest itself culls — it parks a sprite run at
  exactly x=248 (off the native span) for the whole session and never emits
  an OAM entry at a margin position. A game-side culling widening is the
  fix; tracked as issue #26 (discovery + tips), not implemented.
- Open: View menu row (Native / Adaptive / 16:9) still pending; desktop runs
  the feature enabled (build/mods/state.toml); device move state renders
  true ring margins on the final build (screenshot check, clip off +
  mods 1.0.1).

## 2026-10-16 — V2 Phase 5 COMPLETE (headless tier + fakes; CI proof pending push)

Slices (framework `bd8acbc` pre-work excluded — Delete/menu-trigger reliability
landed first as its own commit): 5.1 FakeRaylibApi+injection (`ea0c906`),
5.2 headless variant+smoke (`b18036b`+`ff2a392`), 5.3 present tier-3
(`104d26f`, FFTA-side), 5.4 gate+CI (FFTA `f2cfd76`, framework `2d644b5`),
5.5 docs/accept (this entry). Each red-first; mutations M1-M5, H1-H3, T1-T2,
G1 all observed failing their exact guards then restored.

Evidence: stub ctest 67/67; headless full ctest 67/67 with DISPLAY unset
(contract suite takes the full path, no Err::Window early-out); present
PASS tier=rlsw headless and tier=GL display; check.py raylib-headless PASS
4.5 s cached; attract 1EF4C118 byte-identical throughout; yaml parsed
(`stub, raylib, headless, guard`).

Notes: rlsw cannot round-trip VRAM (LoadImageFromTexture garbage) — that
probe stays GL-only by documented design, not a product gap. gl-xvfb
deferred (no verified Xvfb recipe). CI headless job runs on next push.
Remaining Phase 5 accept: CI green proof. Next: Phase 6 docs (5.5 ticked
the headless checkbox; RAYLIB_PLAN stale claims still open).

## 2026-10-16 — Phase 5 CI proof (push complete)

Framework `ci` 38833664107 all success (stub, raylib 6 ON, rlsw headless,
guard); FFTA tier-1 38833598904 success. The headless tier runs green on a
runner with no display. Phase 5 accept fully closed except gl-xvfb
(deferred, no verified recipe).

## 2026-10-16 — Phase 6.2: RAYLIB_PLAN surgical fixes (doc-only)

Corrected the plan-named stale claims in `.opencode/RAYLIB_PLAN.md` (untracked
working-tree doc): SetAudioStreamCallback era (≥4.5, not 6.0-addition),
#3911 status (closed, declined out-of-scope — verified live on GitHub),
windowless notes (rlsw/PLATFORM_MEMORY supersede, GL caveat kept), API-notes
section title, tier-3 table row, and the two `gbarecomp-raylib tree` skip
strings (-> `gbarecompx`, matching check.py). No code touched.

## 2026-10-16 — V2 Phase 6 COMPLETE (docs + cleanup, scoped)

6.1 (`0323617`): removed tracked spike-s1/ + untracked build-raylib/,
build-raylib-scaffold/; kept build-raylib-stub (live gate), both headless
dirs, and the gbarecomp/ fallback (public CI needs it until Phase 7).
6.2 (`41dd9c4`, doc-only): RAYLIB_PLAN stale claims fixed (#3911 verified
closed/declined; era + windowless + tier-3 + skip strings).
6.3 (`3fdd7f3`, framework): minimal README + raylib attribution; full
rewrite trio deferred per scope call. 6.4 (`3a1fa63`, framework): SDL pass
(9 files) + upstream banners; untouched list verified SDL-free.
Deviations from the plan text, all user-approved: fallback kept, README
minimal, gl-xvfb deferred. No code touched after 6.1 (none at all).

## 2026-10-16 — gl-xvfb landed (framework CI, container-proven recipe)

No host Xvfb or root here, so the recipe was proven in a clean
ubuntu:24.04 podman container: contract suite early-outs without
xvfb-run, full real-backend path + v2 suite pass with it (system pkgs:
GL/X11 dev + xvfb + libgl1-mesa-dri). CI job mirrors exactly that,
plus a proof step that fails on the early-out line. CI proof on push.

## 2026-10-16 — gl-xvfb CI proof (first run green)

Framework `ci` 38838258955 all success: stub, raylib 6 ON, rlsw headless,
GL under Xvfb, guard. The virtual-display tier is now covered on every
push; no deferrals remain in Phase 5/6 except the full README trio and
Phase 7 extraction.

## 2026-10-16 — gl-xvfb folded into the raylib CI job

Four test groups was one too many: the standalone job compiled nothing
new (same GL binary), so its Xvfb tier + no-early-out proof moved into
`raylib` (net -44 lines, back to 4 jobs: stub, raylib, headless, guard).
Plan §5.4 table/rules updated. Re-proof on next push.

## 2026-10-16 — Fold re-proof on push (both repos green)

Framework `ci` 38838990626: 4/4 (folded raylib+Xvfb tier green).
FFTA tier-1 38839313117: success (covers the backend-default HEADLESS
guard, 6.1/6.2, fold log). No open CI items.

## 2026-10-16 — LCD grid and dither are now scale-aware (game-space, all stages)

**The bug.** `lcd_shader.h`'s mask indexed `gl_FragCoord` directly with the
Shadertoy reference's periods (3 px, 2 px) hard-wired, so the triad was 3
*drawable* pixels wide no matter how the game was scaled. FFTA is presented at
`layout.width / 240`, so one triad per game pixel only happened by accident at
exactly 3x (the default window); at 6x/8x/9x a game pixel held 2-3 triads with
boundaries cutting across it. Phase was also measured from the screen edge, so
letterboxing (1080p fullscreen: 1620x1080 at x=150) slid the grid relative to
the artwork. On the default chain the grid was applied fullscreen and the
letterbox bars were masked too.

**The audit that widened the scope.** Two of the three GPU passes were affected:
- deband was already correct (`texel = 1/base_w` in source UV is one game pixel
  on both the direct and the sharp-pre-upscale path) — left alone, now pinned
  by `shader_deband_texel_step` + a test;
- dither had the same fault, milder: a 4-px screen cell straddles pixel edges
  at any scale > 4, laying uncorrelated noise inside a single pixel.

**The fix.** One shared `PresentGrid` (origin + scale, resolved from
`compute_presentation_layout` once per frame) uploaded as `uGrid`/`uGameSize` to
the grid and dither programs. The mask is now one triad + one dark row per
**game** pixel, anti-aliased by the fragment's real overlap (fractional scales
are the common case: 1080p fullscreen is 6.75). At 1:1 it reduces to the
reference verbatim, which is pinned by a parity sweep over the whole old table.
Below 3 px per game pixel a triad cannot be drawn, so it collapses to one
stripe per game pixel — the reference's own ratio at 1:1, as chosen.

**Two real bugs caught by probing before the tests existed** (both would have
been invisible in a review): the coverage `width` is the fragment *footprint*
in stripe units (3/scale), not the stripe width — I had it inverted, which
silently broke the sum-to-1 invariant; and my CPU assembly put the blue
stripe's full-strength channel in `r` while the GLSL had it right in `b`.

**Proven.** `lcd_shader_tests` 66 → 135 assertions, all existing ones
unchanged; full framework `ctest` 73/73; `raylib_present` PASS on the real GL
tier (`tier=GL display`, 0 failures). The fake raylib api gained uniform
recording (it previously returned -1 for every lookup, so *no* uniform write was
ever observable) and four new cases prove the backend uploads the current
layout's grid, recomputes it on resize, skips it when off, and degrades cleanly
when lookups fail. Mutation-checked: reverting the upload to origin-0/scale-1
fails the suite at the 8x assertion, and a mutation harness covering all four
mutants reports 10/10 caught, so the tests are not vacuous.

**Not done here.** No screenshot measurement of the new dark-row LSB delta at
8x (the 8-px pitch is a much coarser pattern than the old 1 px) — that needs a
windowed run and stays open. Android ES 1.00 is transliterated, not compiled on
any tier; `glslangValidator` validates all six sources locally and passes.

## 2026-10-16 — Settings audit + persistence (menu rows wired end to end)

User report: "the settings menu's View is there but changing the scale
does nothing." Full audit of every menu row (model → apply → backend →
runtime) found one dead row and two untested layers; all fixed red-first:

- Window scale: adjust_scale only clamped (SDL's resize was dropped in
  the port). Now resizes via RaylibApi::SetWindowSize; Android and
  fullscreen no-op; unchanged-value early-out. Commit fc21259.
- View: policy extracted to pure menu_view_step (host_menu.h) + runtime
  rewire (legacy mode → ViewMode → step). Commit 5db92ba.
- Persistence: menu_settings.h ([Menu] drop-and-rewrite; [video] LCD
  keys merge in place so launcher-owned lines survive; unknown sections
  byte-preserved). Loaded pre-context-seed (View starts from the saved
  mode), applied post-open under given-flag CLI precedence
  (scale/fullscreen/volume/linear/blend/interp/view-width), saved by the
  host apply hook per real change. menu_settings_tests (parse/clamp/
  round-trip/foreign-survival) + P1/P1b mutations observed. Commit
  fca051a. README menu section documents the round-trip.

Evidence: framework 68/68, FFTARecomp builds, attract 1EF4C118
byte-identical after every commit. Open: save-state menu rows; full
README trio. Note: lcd_shader_tests red during the audit belongs to the
separate LCD-grid rework (see its BRINGUP entry), untouched here.

## 2026-10-16 — LCD white screen: the mask was written instead of applied

**Reported from the settings menu**: turning the LCD shader on showed a white
screen; off was fine. Root cause was mine, in `b95eec7`'s game-space rewrite:
the shader computed the mask correctly and then wrote **the mask itself** as
`finalColor` — the multiply by the sampled texel went missing. At 3x the mask
is (0.6, 0.6, 1.0), so the screen became a flat near-white wash that ignored
the frame completely. Fixed in `a170679`.

**Why nothing caught it.** Every existing LCD check asserts `readback()` /
`copy_presented_frame()`, which serve the CPU staging buffer *pre-shader by
design* — so "the shader ran" and "the mask is right" could both be true while
the pixels were wrong. That is a real hole in the earlier evidence, not just a
missing assertion: the night-12 screenshots proved the reference shader (which
multiplied) and I carried the claim forward without re-proving the composition.

**Diagnosis that made it obvious** (worth repeating): present a *level sweep*
through the real backend and read the framebuffer — 40/128/200 all produced
153,153,255, i.e. the output was independent of the input. A single flat frame
can hide this; three levels cannot. The first probe read red and I took
"153,153,255" for an expected value instead of computing what it should be.

**New guard** (`tests/unit/test_raylib_present.cpp`, real-GL tier): read the
framebuffer via `LoadImageFromScreen`, twice per configuration with the same
frame pushed unshaded and shaded, compare only pixels that are stable and equal
to the source in both reads (which makes the check immune to compositor
smearing over the window), and require the shade to equal
`lcd_pixel_mask_game(...) * source` within 2 LSB — plus "nothing may come out
brighter than it went in". Negative control: re-introducing the missing
multiply fails exactly these two assertions; the fix passes them. The pure
tier also asserts the composition textually (`tex.rgb * mask`) in both
dialects, since that is the one-token mistake.

**Measured after the fix** (synthetic flat card through the real backend,
readback via `LoadImageFromScreen`, harness in `/tmp` like the night-12 one):
stripe transitions measure 2.975 per game pixel at 3x/4.1625/6/6.75/8 (i.e.
one triad per game pixel, the 0.025 being the sampling window), dark/striped
bands alternate one per game row, and the dark-row delta on mid-grey (128) is
**4.0 LSB at 3x, 6x and 8x and 3.9 LSB at fractional scales** — so the 0.7 row
level that replaced 0.5 still holds at the 8-px pitch the game-space rows
produce at 8x. That closes the open item from the grid change ("the 8x
dark-row LSB measurement still needs a windowed run"): the pitch got coarser,
the amplitude did not.

**Dither relocation measured live too** (same harness, dither on / grid off):
inside one game pixel every drawable pixel carries the *same* offset (0 of 4 at
3x, 0 of 49 at 8x differ from the block value — the property that only holds
once the cell is indexed in game space), 14 of the 16 cells in a 4x4
game-pixel neighbourhood differ from each other, and the cell mean is 127.6
against a source of 128: the grain moved to the game-pixel cadence with the
brightness preserved.

## 2026-10-16 — On-device crash in the menu apply hook (dangling HookCtx)

**Reported**: the private APK crashes when turning on ANY graphics setting
(SIGSEGV at 0xe48, Thread-2). Not the LCD change: the tombstone's frame #00
symbolized (unstripped libmain.so, llvm-nm/llvm-objdump) to the menu-settings
apply-hook lambda `run_game::$_388::__invoke`, faulting at +0x24 on
`ldr w25, [x22, #0xe48]` with x22 = 0 — `model().row_count` through a null
`host` pointer. That pointer comes from `HookCtx`, which `fca051a` declared
INSIDE the `if (menu_available)` block that registers the hook; the captured
`&hook_ctx` outlives the block by the whole run. arm64's stack-slot reuse
zeroed it (deterministic crash); x86-64 left the original valid bytes (desktop
appeared fine — the UB was there all along, silently dereferenced on every
settings change since the persistence commit). Fixed in gbarecompx `be257ef`
by moving `HookCtx`/`hook_ctx` to function scope; registration stays gated.

Rebuilt the private APK (38.3 MiB, guard 8/8), installed, `validate_android.sh`
GATE PASSED. Lesson: symbolize against OUR unstripped build (the APK is ours,
so offsets resolve) before reading the backtrace shape — the 200 identical
`gf_tfunc_080003A2` frames were unwinder noise from the guest crt0 loop and
nearly sent the investigation at the frame loop.

Packaging note, second occurrence: rebuilding without cleaning
`android/app/build` leaves 32.1 MB of unaccounted zip slack (the
incremental-repackaging junk class) and the APK guard rejects it; a clean
`app/build` (native `.cxx` survives) rebuilds in ~50 s and passes. The guard
is doing its job; expect this every time Gradle repackages over a stale dir.

## 2026-10-16 — Baseline: RAYGUI_LAUNCHER plan start (drop recomp-ui)

Plan `.opencode/RAYGUI_LAUNCHER.md` created (Phase 0–7, contract + raygui
first backend + tinyfiledialogs picker). Phase 0 baseline frozen:
- `build/` (raylib ON, recomp-ui still ON): app tests ram_dispatch /
  host_window_closed / backend_select = 3/3 pass.
- `build-raylib-stub` (raylib OFF): gbarecomp_raylib_backend target builds.
- Attract golden byte-identical: `1EF4C118A8438CADE6E5847DC6716A7A800D157A568DECB272F2F7052EF321C1`
  (frames=1200, PASS) — referee for the whole removal; never --repin.
- Box art: Justme488 USA box art selected for `recomp/launcher/boxart.png`
  (license unknown — sign-off given; commit records source URL + SHA-256 +
  EmuMovies credits, no license text staged).
- Launcher is a contract (`src/launcher.{h,cpp}`) with raygui as the first
  backend (`src/launcher_raygui.cpp`).

## 2026-10-16 — Phase 1 Step 1.0: Launcher contract (complete)

- `src/launcher.h` — abstract `LauncherBackend` interface (`run() → LauncherResult`),
  `LauncherConfig`, `create_launcher_backend()` factory; no raygui include.
- `tests/unit/test_launcher_contract.cpp` — mock-backend test for Skip/Launch/Quit,
  wired into `test_ram_dispatch.cpp`'s `main()` driver. PASS (0 failures).
- gbarecompx/CMakeLists.txt: `gbarecomp_tinyfiledialogs` static target vendored
  (v3.21.2, zlib); attribution recorded in gbarecompx/THIRD_PARTY_ATTRIBUTION.md
  with SHA-256 pins.

## 2026-10-16 — Phase 1 Step 1.2: raygui vendored (complete)

- `src/vendor/raygui/raygui.h` + `LICENSE` (v5.1-dev / v5.0, zlib,
  SHA-256 `8b19249c…`); attribution in gbarecompx/THIRD_PARTY_ATTRIBUTION.md.
- CMakeLists.txt: `ffta_raygui_links_tests` target (links raylib via
  `gbarecomp_raylib_backend`), registered as `raygui_links` ctest.
- `tests/unit/test_raygui_links.cpp` — `#define RAYGUI_IMPLEMENTATION` +
  `GuiButton` link check + `GuiGetStyle`/`GuiSetStyle` style accessors.
  **PASS (exit 0)**, links raylib/OpenGL. Runs headless.

## 2026-10-16 — Phase 2 Step 2.1: asset_picker dialog-seam test (RED observed)

- `gbarecompx/tests/runtime/asset_picker_test.cpp` written against the target
  seam shape (includes `asset_picker_seam.h`, overrides
  `asset_picker_seam::pick_with_dialog` / `show_dialog`).
- `gbarecompx/CMakeLists.txt`: `asset_picker_tests` target (standalone recipe:
  asset_picker.cpp + crc32 + sha1 by source, no engine link).
- **RED observed**: `fatal error: asset_picker_seam.h: No such file or directory`
  — the seam header does not exist yet, so the test cannot compile. This is the
  expected failure; Step 2.2 adds the seam.

## 2026-10-16 — Phase 2 Step 2.2: seam added, runtime RED observed

- `gbarecompx/src/runtime/asset_picker_seam.h` — inline function-pointer seam
  (`pick_with_dialog`, `show_dialog`), null in production.
- `asset_picker.cpp`: real impls renamed to `pick_with_dialog_impl` /
  `show_dialog_impl`; seam-checked wrappers `pick_with_dialog` / `show_dialog`
  route through the seam when set, else fall back to the impl.
- `asset_picker_tests` now compiles + links (added `host_platform.cpp` for
  `read_file`).
- **Runtime RED observed** (Linux): `Assertion 'g_dialog_offered' failed` —
  resolve_asset early-returns before offering the dialog on non-Windows. This is
  the expected behavioral RED; Step 2.3 ungates the dialog loop.

## 2026-10-16 — Phase 2 Step 2.3: dialog loop ungated, tinyfd wired (complete)

- `asset_picker.cpp`: removed `#if defined(_WIN32)` / `#else` around the dialog
  loop and the non-Windows early return; all platforms now run
  argv → cache → dialog(→warn) → loop.
- Replaced Win32 `GetOpenFileNameA`/`MessageBoxA` impls with unified
  **tinyfiledialogs** impls (`tinyfd_openFileDialog` / `tinyfd_messageBox`) for
  all platforms. `kAssetDialogError`/`kAssetDialogWarning` constants replace the
  Win32 `MB_OK|MB_ICON*` flags.
- `gbarecompx/CMakeLists.txt`: `gbarecomp_tinyfiledialogs` linked PUBLIC into
  `gbarecomp_runtime`; Windows link set updated to `comdlg32 ole32 winmm`
  (tinyfd needs Ole32 on Windows).
- `asset_picker_tests` **PASS** (exit 0): dialog offered + picked path +
  hash-mismatch warn + cancel error. Test removes stale `rom_seam_test.cfg`
  from prior crashed runs and sets `persist_cache=false` so the cache path
  never short-circuits the dialog.
- `FFTARecomp` links clean with tinyfd in the runtime.

## 2026-10-16 — Phase 3 Step 3.1: launch-screen state model test (RED observed)

- `tests/unit/test_launch_screen_model.cpp` written against the target model
  shape (includes `launch_screen_model.h`, drives the state machine through
  RomPicked/RomDropped/PlayPressed/QuitPressed, validates via real
  `gbarecomp::resolve_asset`).
- `CMakeLists.txt`: standalone `ffta_launch_screen_model_tests` target
  (asset_picker.cpp + host_platform.cpp + crc32 + sha1 by source, links
  `gbarecomp_tinyfiledialogs`), registered as `launch_screen_model` ctest.
- **RED observed**: `fatal error: launch_screen_model.h: No such file or
  directory` — the model header does not exist yet, so the test cannot
  compile. Expected failure; Step 3.2 adds the model header.
- Model shape encoded in the test (signed off via the test):
  - States `{NeedRom, Ready}`; inputs `{RomPicked, RomDropped, PlayPressed,
    QuitPressed}`; outputs `{None, PickRom, Launch, Quit}`.
  - Fresh → NeedRom; PlayPressed in NeedRom ignored; RomPicked/RomDropped
    valid → Ready; PlayPressed in Ready → Launch; QuitPressed → Quit;
    invalid pick → PickRom (stays NeedRom); bios_path surfaced unchanged.
- **MUT:** `src/launch_screen_model.h` — header-only state machine (no raylib).
  Model test **PASS** (exit 0): all 8 cases green. Model shape signed off
  (question tool, 2026-10-16).
- Test hang fix: `resolve_asset` on the invalid-path case opened a real tinyfd
  dialog (stdin block). Injected `asset_picker_seam` (fake_pick returns empty =
  instant cancel) so the dialog loop exits cleanly headless.

## 2026-10-16 — Phase 3 Step 3.2: raygui backend (complete, unwired)

- `src/launcher_raygui.cpp` — concrete `LauncherBackend` impl per the Step 1.0
  contract. raylib window (720×480), box art texture (PNG), raygui Play/Select
  ROM buttons, gamepad nav (d-pad + face buttons), drag-and-drop (.gba filter),
  first-boot auto-open of the ROM picker. Drives `LaunchScreenModel` for
  state; `run()` returns `LauncherResult` (Launch/Quit). No raygui types leak
  past the contract boundary.
- `src/launcher.h` — `LauncherConfig` extended with `argv0` (cache root) +
  `staged_bios` (resolved BIOS path).
- `CMakeLists.txt` — `src/launcher_raygui.cpp` added to `FFTA_HOST_SOURCES`
  when `GBARECOMP_USE_RAYLIB`; `gbarecomp_raylib_backend` linked + define +
  `src/vendor/raygui` include dir.
- **DIFF:** model test PASS (exit 0); asset picker test PASS; ffta_unit_tests
  PASS (0 failures); FFTARecomp links clean; attract golden unchanged
  (`1EF4C118…`) — the unwired leg proves nothing else moved. No `main.cpp`
  wiring yet (Phase 4).

## 2026-10-16 — Phase 0 Step 0.2: tinyfiledialogs spike (confirmed)

- `tinyfiledialogs` v3.21.2 (zlib, Guillaume Vareille) fetched to
  `/tmp/opencode/smallfd_spike` (throwaway, not in repo).
- **No compile macro exists** to disable console fallback — `tinyfd_forceConsole`
  is a runtime global. Mechanism is the `tinyfd_query` probe:
  `tinyfd_openFileDialog("tinyfd_query", ...)` never shows a dialog; it sets
  `tinyfd_response` to `zenity`/`kdialog`/…/`no_solution` and returns NULL on
  console/no_solution.
- Empirical result on this dev box (no zenity/kdialog/matedialog/yad/xmessage):
  `tinyfd_response='no_solution'`, `ret_ptr=NULL` → fail-fast path confirmed;
  headless/CI will never block on stdin.
- Plan `Constraint 2` and `Step 0.2` corrected to describe the probe pattern
  (replacing the erroneous "compile macro" language).

User manual test on the Poco X3 Pro (M2102K1AC, Android 14/API 34) with the
fixed private APK: no crash on any graphics toggle (the be257ef hook fix),
and all three shader passes compile AND present on-device — runtime log shows
`dither shader enabled`, `LCD shader enabled`, `deband shader enabled`
(ES 1.00 variants on Adreno 740, previously never compiled outside
glslangValidator). Crash buffer clean, no miss journal produced (no bridges,
consistent with report-only self-heal + no dispatch misses). That closes the
"Android ES 1.00 transliterated, never executed on a device" caveat from the
game-space grid change — every path in the change is now verified end to end
on both platforms: desktop (real-GL tier + measurements) and Android (device
gate + manual pass).

---

## 2026-10-17 — Phase 5 removal sweep (recomp-ui gone)

- Removed the `recomp-ui` submodule (deinit + git rm + .gitmodules entry); recomp-ui is no longer a dependency. Launcher is the raygui screen in `gbarecompx/src/runtime/`.
- Root `CMakeLists.txt`: dropped `RECOMP_UI_ROOT`, cleared `GBARECOMP_RUNTIME_UI_ROOT` to `""` (doc-only), removed stale SDL2 comment; Build no longer references `GBAGAME_RECOMP_UI` (already removed in Phase 4.3). No `SDL2` references remain.
- Removed `game_launcher_ui` from the three host test link lists; host window delegation test expectations updated to the no-runtime-ui result (interp calls 0), matching the new reality.
- Patch re-baseline: deleted `tools/patches/launcher-force-ui.patch` and `tools/patches/recomp-ui-local.patch`, dropped the `recomp-ui` replay target, stripped the recomp-ui bios-verify half from `emibios-launcher-pin-set.patch`, remaining only `gba_bios.h` kEmibiosSha1.
- Stale `frame-pacer-banked-wait.patch` removed (current tree has evolved beyond its context); README row dropped.
- `tools/check.py`: dropped `ui-tests` suite and `check_ui_tests` (and reference); deleted `tools/ui_check.py`. CI workflow apt list and gate command pruned for SDL/freetype/harfbuzz & ui-tests.
- Dead-code audit: `RECOMP_LAUNCHER`/`RECOMP_UI_*` defines are not referenced in product code; netplay CMake does not depend on a recomp-ui UI. Framework files (launcher_seam.h etc.) left for later framework cleanup, per rule 5.8.
- Verify: `check.py --fast` ALL PASS (8/8); attract hash `1EF4C118A8438CADE6E5847DC6716A7A800D157A568DECB272F2F7052EF321C1` unchanged.


---

## 2026-10-18 — Phase 6 packaging

- `tools/win_cross_deps.py`: cross-prefix recipes dropped to raylib only (SDL2, freetype, harfbuzz, zlib removed); status shows only raylib 6.0.
- `tools/make_release.py`: required set no longer includes `assets/fonts`, `assets/img`; harfbuzz/SDL2 license staging and `SDL2.DLL` guard removed; mod manifest path updated to 1.0.1; release succeeds (`check.py --only release` PASS).
- Wine smoke already passes explicit ROM via `--rom`, so bare-extraction seeding is documented in the runner.
- Verify: `check.py --fast` ALL PASS; attract hash unchanged `1EF4C118…`.

---

## 2026-10-16 — Launcher public/product close-out (Phase 6 + fixes)

- Product runtime now ships only the raylib/raygui launch surface; recomp-ui is gone.
- COMMISSION CODE / NEEDED: Launcher ROM cache fast-path bug: `resolve_asset(force_pick)` default behavior meant Select ROM/keys/gamepad silently no-op when a valid `rom.cfg` existed. Added `force_pick` to `gbarecompx` and route all explicit pick actions through it; first-boot auto-open keeps sidecar-cache fast path.
- Regression test added in gbarecompx: forced re-pick bypasses a valid cache and calls the picker seam.
- Phase 7 asset (box art, attributions, screenshots) unchanged; launcher UI now has status/error reporting after each pick.
- Verify: `.venv/bin/python tools/check.py --fast` ALL PASS (8/8); asset picker tests PASS; attract hash `1EF4C118A8438CADE6E5847DC6716A7A800D157A568DECB272F2F7052EF321C1`.
- Nested framework repo backed up and committed separately as `launcher: raygui contract, repick cache fix, asset picker tests`.

---

## 2026-10-18 — Phase 7 close-out: docs, attribution, definition of done (launcher track complete)

The launcher track (`.opencode/RAYGUI_LAUNCHER.md`) is complete through
Phase 7. Phase 7 commits: `fbe0366` (7.1a box art + attribution/license
set + release staging), `f9b3ca5` (7.1b docs sweep), `95e61c5` (7.1c
CI/tooling text + dead-option cleanup), `74d614e` (7.1d patch
re-baseline); the nested gbarecompx comment fix is `78d28af`, pushed
(`05b8a2f..78d28af main`).

**Plan erratum (user-corrected, recorded):** the launcher was always
meant to be framework code in the gbarecompx fork — the plan's
`src/launcher.{h,cpp}` / `tests/unit/...` paths were written as game-repo
paths. As built (and now documented): contract `gbarecompx/src/runtime/launcher.h`,
backend `gbarecompx/src/runtime/launcher_raygui.cpp`, model
`launch_screen_model.h`, tests `gbarecompx/tests/runtime/`. Game
`src/main.cpp` includes the framework header via
`${GBARECOMP_ROOT}/src/runtime` and calls the contract only
(`launcher_should_skip_screen` + `create_launcher_backend`).

**After-shots (the §5 requirement), product build `build/FFTARecomp`:**
- `ldd build/FFTARecomp | grep -iE 'sdl|imgui|freetype|harfbuzz|zlib|raylib'`
  → empty. Full dynamic set: libc, libm, libstdc++, libgcc_s, and the
  GL/X11 stack only (libOpenGL/libGLdispatch/libGLX/libGLU, libX11/libXext/
  libxcb/libXau/libXdmcp/libICE/libSM/libuuid). Zero SDL, zero ImGui, no
  freetype/harfbuzz/zlib.
- `nm -C build/FFTARecomp | grep -icE 'imgui|ImFont'` → 0.
- Windows exe: the objdump import-table guard (static imports=29 at v1.6)
  remains the PE-side proof; `STATIC_FORBIDDEN_DLLS` keeps the freetype/
  harfbuzz/zlib names as regression guards.

**Prefix delta:** `cross-prefix/` is raylib-only (SDL2, freetype, harfbuzz,
zlib recipes deleted; the unreachable meson builder removed) — Phase 6.1,
re-verified here: `tools/win_cross_deps.py` docstring + `tools/README.md`
now state it.

**Release hash delta:** the staged content set changed in 7.1a —
`assets/img/boxart.png` ADDED to both desktop layouts (the launch screen's
art actually ships now; previously only dev builds had it via CMake
`stage_boxart`), `LICENSES/ZLIB-tinyfiledialogs.txt` +
`LICENSES/ZLIB-raygui.txt` added, `LICENSES/ZLIB.txt` + `FTL.txt`
removed, README template rewritten. The v1.6 pins
(linux `92a4eb9f…` 45,745,653 B / windows `d9564173…` 43,553,223 B) are
therefore superseded: the next tagged cut re-pins (gate run today:
linux zip sha1 `9c3a38c7b021bafa7dfa1640db94afcf0ac378f5`, 44,055,918 B,
built from a dirty tree — expect a different hash from the clean tag).

**Gates (pasted from the runs):**
- `tools/check.py --fast` → ALL PASS (8/8): backend-default (raylib=1),
  savecheck, unit-cpp (0 failures), raylib-backend, unit-py (54 tests),
  patches (all reverse-ok + pin-forward-ok; `gbarecomp-local replay:
  431-file tree matches`, `arm-recomp-core-local replay: 35-file tree
  matches`), android-static (24 checks), attract
  `sha256=1EF4C118A8438CADE6E5847DC6716A7A800D157A568DECB272F2F7052EF321C1`
  — unchanged through the entire track.
- `tools/check.py --only release` → PASS (see hash above; zip verified to
  ship `assets/img/boxart.png` + the new LICENSES set, no stale ones).
- `tools/cycle.py` → PASS (regen 63,134 units, dispatch sanity OK, build
  OK, attract gate OK) — run because the CMakeLists option removal is a
  regen input; corpus byte-stable.
- emibios boot end-to-end: the attract gate itself boots through the
  pinned emibios BIOS on the product build — that is the §5 verification.

**Step 7.1 sweep detail:** the RED grep
(`rg -n "launcher|recomp-ui|ui_check|libsdl2" README.md docs/ tools/
reference/ .github/`) now returns only intentional text: the deliberate
gbarecompx-repoint contributor notes, current launch-screen docs
(dev-gotchas § Pre-boot launch screen), Android `launchable-activity`
checker terms (Android app-launcher concept, unrelated), frozen patch
content (diff records — `SKIP_LAUNCHER_ON_BOOT` is the Android setup-flow
flag; `RecompFrameBlend` mentions are historical diff context), and the
static-link guard's forbidden-DLL names. Sweep fixes worth calling out:
`tools/README.md` still listed the deleted `ui_check.py`;
`make_release.py`'s release README still told Linux users to install
SDL2/freetype/harfbuzz and said "launcher state" for config.ini; ci.yml
still apt-installed the three dead dev packages (the 2026-10-17 "pruned"
entry was wrong — the ccache commit `2ad4a33` restored the list);
`win_cross_deps.py` still carried the dead harfbuzz meson builder.

**Attribution decision (sign-off class, logged):** the license set now
equals the linked set — tinyfiledialogs (zlib, © Guillaume Vareille) and
raygui (zlib, © Ramon Santamaria) texts added verbatim; the orphaned
zlib-lib (`ZLIB.txt`) and FreeType (`FTL.txt`) texts deleted. The
Appendix A manifest listed only MIT-harfbuzz/ZLIB-SDL2 for deletion
(both gone in `3a0e3aa`); ZLIB.txt/FTL.txt fell out the same way once
6.1 dropped the libraries — the covering unit test
(`test_license_bundle_covers_licenses_dir`) forces the equality either
way. Box art posture: unknown-provenance cover art shipped under the
2026-10-16 sign-off, disclosed with source URL + SHA-256 + EmuMovies
credit in `THIRD_PARTY_ATTRIBUTION.md`; the screen degrades to its text
fallback if the file is absent.

**Known divergences / open items (recorded, not silently dropped):**
1. **gbarecompx repoint (the remaining launcher-track item).** The game
   binary does not compile against the pinned `gbarecomp` fallback: the
   launch-screen contract (`src/runtime/launcher.h`) exists only in the
   gbarecompx fork, and `src/main.cpp` includes it unconditionally. Fresh
   clones therefore cannot build FFTARecomp until the build repoints
   `GBARECOMP_ROOT` at the published remote (the `.gitignore` deferral).
   CI stays green because tier-1 never builds the game binary and the
   raylib-backend job skips cleanly while gbarecompx is untracked.
   Deferred by decision 2026-10-18 (docs close-out only); the plan §5
   checklist carries it as the one open box.
2. Framework-side follow-ups (filed, not dropped): dead launcher files in
   the gbarecompx tree (`launcher_seam.h`, `launcher_profile.h`,
   `launcher_netplay_seam.h` and the `RECOMP_LAUNCHER`/`RECOMP_UI_*`
   defines are referenced by nothing in the product); the Flatpak/XDG
   portal file-chooser item (tinyfd cannot speak it; documented in the
   plan §4).
3. Pre-existing release-track remainders (unchanged by this track): APK
   release-signing key (still debug-signed), runner registration for the
   tag-triggered release workflow, offline-push re-trial, f6000+ contact
   sheet, upstream note on the bridge stop-contract.
4. Plan §4 divergences stand as written (no Flatpak portal support in
   tinyfd; no clipboard on the launch screen; keybind vocabulary
   untouched; `--launcher`/`--no-launcher` flags removed — release-notes
   material for the next cut).

**§5 Definition of done:** all boxes ticked in
`.opencode/RAYGUI_LAUNCHER.md` except the repoint (item 1 above), with
the after-shots and hash deltas recorded here. The launcher track is
hand-back ready.

## 2026-10-18 — The fork becomes the framework: gbarecompx rename + repoint, emibios default, patch-suite retirement

**Action.** Three entangled structural changes, landed as one migration
commit (`0d6b0c1`) plus this entry:

1. **Submodule rename + repoint.** `git mv gbarecomp gbarecompx`;
   `.gitmodules` section + path renamed, URL = the published
   `james2doyle/gbarecompx.git` (https, for CI/fresh clones); gitlink =
   `8144ab2`. Mechanics beyond `git mv`: the module gitdir moved
   (`.git/modules/gbarecomp` → `gbarecompx`), the submodule `.git`
   pointer file and all three nested submodule gitdir pointers
   (arm-recomp-core, rbengine, recomp-net) re-pointed by hand, the
   stale `submodule.gbarecomp` config section replaced via
   `submodule init`/`sync`, and the leftover untracked
   `platform/android/third_party/SDL` skeleton from the transient
   `ecc9c55` checkout deleted. Post-state: `gbarecompx` @ `8144ab2`
   initialized, clean, on `heads/main`; nested arm-recomp-core @
   `cd010b5`.
2. **emibios default (fork-side `baf31ab`).** Runtime pin, asset-picker
   fallback, netplay lockstep gate (`kEmibiosSha1`), Gradle templates
   ×2 + `GbaGameConfig.java`. Game side: `android_static_check` now
   expects the emibios template default (`RETAIL_BIOS_SHA1` constant
   removed). The game's own `[bios]` config was already emibios since
   issue #17 — this closes the framework half.
3. **Patch-suite retirement.** `tools/patches/` (17 files) deleted —
   feature-by-feature audit first proved the fork subsumes all of them;
   the `patches` suite removed from `check.py` (registry/FAST/help);
   `build.py` step_patches removed; CI gate string →
   `unit-cpp,unit-py,android-static`; recorded-patch fallbacks deleted
   from `android_static_check`; the patches-parity unit test deleted;
   the unit-test guards (`host_stack_guard`, `frame_pacer`,
   `stick_dpad`) reworded to reference the fork as committed code.

**Supporting moves.** `GBARECOMP_ROOT` resolves straight to the
submodule (no in-tree preference); `.gitignore` carve-out removed;
Android engine root defaults to `gbarecompx/` (dead `-PrecompUiRoot`/
`RECOMP_UI_ROOT` plumbing deleted); CI tier-1 pins the stub
(`-DGBARECOMP_USE_RAYLIB=OFF`) so the cheap gate stays cheap while the
raylib-backend job now runs LIVE against the fetched fork (its "inert
until committed" comment retired; `hashFiles('gbarecompx/CMakeLists.txt')`
cache key finally true); ~45 `gbarecomp/` path references flipped across
build/docs/tools — `gbarecomp::` namespace, `# gbarecomp-keyinput-v1`
trace header, `gbarecomp_*` target names, `org.gbarecomp`, skill name,
and upstream URLs deliberately unchanged.

**Fork-side commits (this session):** `78d28af` (gba_bios.h comment),
`baf31ab` (emibios default), `52c73d9` (nested pin → cd010b5),
`9a862e8` (retire the fork's own frozen patch machinery — its CI's
"Submodule patches" step stopped applying once the pin carried the
work), `8144ab2` (tail-transfer macro contract, below). Fork CI green
through `8144ab2`; fork ctest 72/72.

**The cd010b5 codegen contract catch.** The nested bump carries upstream
`a8802bb` (guaranteed tail transfers emitted as `GBARECOMP_TAIL_CALL` /
`GBARECOMP_TAIL_DISPATCH` / `_WITH_EXCHANGE` / `_TAIL_SWI`) and
`c626f4e` (far-branch BLs lowered frameless through the tail form).
Upstream defines those macros in the CONSUMER's `runtime_arm.h`
(`7aad900` + `b3e7789` thread-local slot) — the fork had never adopted
them, so every generated TU failed (`GBARECOMP_TAIL_DISPATCH was not
declared in this scope`); the two runs in between were cancelled/failed
early, so no compile signal surfaced until the CI fix run. Ported
verbatim into `gbarecompx/src/armv4t/runtime_arm.h` (+ the
`g_runtime_tail_arg` slot and three `void(void)` tail entry points in
`runtime_arm.cpp`); native expansion is the historical `call; return`
text. Also fixed the fork's stale `link_branch_test.cpp` far-BL
assertion (`runtime_dispatch(0x08000100u);` →
`GBARECOMP_TAIL_DISPATCH(0x08000100u);`) to the current contract.

**Result.** `cycle.py` PASS — regen 63,134 functions (count unchanged),
dispatch sanity OK, build OK, **attract `1EF4C118…` unchanged** (the
referee holds: the codegen change is behavior-preserving on real
frames, as upstream's token-for-token claim predicted). `check.py
--fast` ALL PASS 7/7. `--only release` PASS. The android-static suite
caught one real migration bug: a mass path-flip over-turned the Java
package segment (`java/org/gbarecompx/` → the fork's actual
`java/org/gbarecomp/`) — fixed, 24/24. Lesson recorded in dev-gotchas
§ Submodules together with the dev-box github-https hang workaround
(repo-local `url.insteadOf` → SSH) and the orphaned-`ninja` trap (a
killed build's ninja child kept running and raced the next cycle's
build, losing one parallel batch of `.o` files at link — 27 of 32
shards present, exactly 008–015 missing).

**Corrections to the sweep worth remembering:** (a) a bare-string path
(`set(GBARECOMP_ROOT ... "/gbarecomp"`) has no trailing slash, so a
slash-anchored sed misses it — the configure failure caught it;
(b) an audit grep whose exclusion pattern (`GBARECOMP_`) also matches
the same line hides exactly the bare-path miss on that line; (c) the
same exclusion hides over-flips (`org/gbarecomp/` package dirs) because
the flipped line contains the desired `gbarecompx` too. Audit greps
after mechanical renames need patterns that match the TOKEN, not the
line.

**Supersedes.** The v1.6 release artifact hash pins in the release-track
entry (`92a4eb9f…`/`d9564173…`) — the framework identity changed; the
next tagged release re-pins. The launcher-track entry's open item 1
(gbarecompx repoint) is CLOSED by this entry; items 2–4 stand.

**Open items (unchanged set):** framework-side dead launcher files in
the fork; Flatpak/XDG portal; APK release-signing key; runner
registration for the tag workflow; offline-push re-trial; f6000+ contact
sheet; upstream note on the bridge stop-contract. Stale build dirs
(`build-headless`, `build-raylib-stub`, `build-raylib-headless`,
`build-win`) hold caches pointing at the pre-rename path — reconfigure
lazily on next use.

## 2026-10-18 — The View row vanished again: a dead define ate the Oct-15 fix (user report, closed same day)

**Report.** "The View with the Native, Adaptive, and Fixed is missing in
the settings overlay again." The Display section of the settings overlay
had no View row.

**Root cause (one line).** The View row's endpoint wiring —
`host_menu.set_view_mode_endpoint(...)` — sat INSIDE
`#if defined(GBARECOMP_RUNTIME_UI)` in `runtime.cpp`, and no build has
defined that macro since recomp-ui retired (the game CMake pins
`GBARECOMP_RUNTIME_UI_ROOT` empty on purpose): the entire hand-off, and
therefore the row, compiled out of every product build. The Oct-15
episode ("the generic menu lost the retired recomp-ui UI's view-mode
control — adding a View choice row") fixed the SYMPTOM in the right
place (the generic menu) but wired it inside the dying guard; the
guard then died with the recomp-ui removal and took the row with it.
The `#if` block even carried a leftover `[dbg] startup:` fprintf from
that session — debugging evidence fossilized in the dead branch.

**How it eluded every gate (the part worth remembering):**
1. No automated gate opens the settings overlay: attract hashes
   attract-loop frames; the ws smoke drives view geometry through CLI
   flags and fixture state, not the menu; the strict route replays are
   gameplay routes. A row's PRESENCE in the product menu is exercised
   by no frame-level referee.
2. The menu-class unit test (fork `host_menu_test.cpp` §22) pins the
   right CLASS contract — endpoint set → row present, endpoint unset →
   row absent — but it SETS the endpoint itself, so it cannot observe
   that the product's `run()` stopped calling it.
3. Every build — fork ctest included — compiles with
   `GBARECOMP_RUNTIME_UI` off, so the dead wiring is dead everywhere;
   there was no configuration in which a test could have caught the
   product wiring being skipped.

**Fix (fork-side `f2ba1b5`, game gitlink `19f59ef`).** Decoupled the
view hand-off from the retired recomp-ui: `RuntimeViewContext`
(`opts` + `gbarecomp::ViewMode view_mode` + dirty flag) is
unconditional; the recomp-ui era EXTENDS it under the define (item
callbacks, `.ui` pointer, extras vector — all dead-but-compiling since
`recomp_runtime_ui.h` exists only in a removed checkout; they join the
fork's dead-code follow-up for deletion). `view_mode` now holds
`gbarecomp::ViewMode` directly, retiring the `RECOMP_RUNTIME_UI_VIEW_*`
indirection at every use site; `sync_resize_driven_view`'s
legacy→framework switch collapses to a pass-through. The endpoint call
is unconditional (runtime availability still gates the row:
`opts.resize_driven_view && opts.max_resize_view_width > 240` — the
widescreen opt-in, same as before). The `[dbg]` fprintf is gone.

**The net (fork-side `1462915`, per user direction: framework
invariants live in framework gates).** The fork's `guard` CI job — a
placeholder since the port — now runs
`tools/check_menu_view_wiring.py`: a preprocessor-conditional scanner
over `runtime.cpp` with PRODUCT semantics (`defined(GBARECOMP_RUNTIME_UI)`
evaluates false — the scanner initially had this inverted and its own
self-test caught it before first real use), asserting the endpoint call
is NOT behind that macro and passes the real availability expression
(not a stubbed `true`). Self-test covers gated / ungated /
stubbed-availability snippets. Game-side registration was drafted and
then removed — the game repo keeps behavioral referees only.

**Result.** Fork ctest 72/72; fork CI on `1462915` (guard job live);
game `cycle.py` PASS with **attract `1EF4C118…` unchanged**;
`check.py --fast` ALL PASS 7/7. User to confirm the row visually on
next launch.

**Lesson.** A fix that lands inside a conditional guard inherits the
guard's lifetime — when the guard's condition is a retired subsystem,
the fix dies with it, silently. Anything that must always exist goes
OUTSIDE the gate; and a class-level test cannot see product wiring —
only a wiring-level check (source shape or an overlay-opening smoke)
can.

## 2026-10-18 — tools/ audited: the framework-protocol tools move into gbarecompx (user direction)

**Report.** "Make sure the scripts in tools are actually FFTA-specific
and not just gbarecompx tools in the wrong place" — the same
misplacement class as the menu-wiring guard, at directory scale.

**Method.** Every tool classified by WHAT IT SPEAKS, not by where it
lives: docstrings + argument surfaces + hardcoded-constant counts +
the caller graph (code callers vs docs-only mentions). The dividing
line: a tool that talks a FRAMEWORK format or surface (the mGBA oracle,
the self-heal loop/fragments/cache, `GBARECOMP_FP_SAVE` rings,
`# gbarecomp-keyinput-v1` traces, the runner's TCP close/watchdog
protocol, generic GBA disassembly/engine detection) is framework
content; a tool that talks FFTA (attract corridor, ws catalog, route
fixtures, the save/truth audits, device gates, release identity,
bring-up probes pinned to FFTA RAM layout) stays.

**Moved (11, fork `2d7c2d7`):** framediff, dualrun (oracle drivers —
the oracle itself already lives fork-side), resolve + misspack +
cache_harvest (the playtest→healing loop the playbook calls portable),
ringscan, trace_split (framework artifact formats), quit, livewatch
(runner TCP protocol), disarm, m4a_detect (generic GBA analysis).
Path semantics made explicit in each: the GAME checkout = the cwd
(game.toml/game.gba/bios/generated/logs defaults), the FRAMEWORK root
= the tool's own location (the oracle binary). That rework also fixed a
latent rename bug: dualrun's oracle default still pointed at the
pre-rename `gbarecomp/build/...` path — deriving framework paths from
the tool's own root kills the whole bug class.

**Kept (FFTA-specific):** attract/ws/route/savecheck/truth suites, the
Android gates, cycle/check/play, release packaging + cross-prefix,
coverage_report (the FFTA accuracy-burndown presentation), and the
bring-up probes — including hangprobe, whose "generic-looking" TCP spin
dump actually reads the FFTA vblank wake flag (0x03000E10) and IRQ
vector (0x03007FF0): game forensics, stays.

**Wiring.** Fork: `tools/tests/` (trace_split/cache_harvest/misspack —
6 tests, stdlib unittest) run by the guard job, which now installs
capstone==5.0.7; `tools/README.md` documents the set + the
run-from-game-checkout convention. Game: the 11 files deleted; AGENTS
(ground rule 1's disarm path, the commands table), tools/README (rows
out, a framework-tools pointer in), tests/README, reference/*
(oracle-harness, dev-gotchas, event-vm, widescreen), the playbook
skill's references, cycle.py/play.sh hint strings, and
tests/python/test_tools.py (the three moved classes removed; the suite
is now capstone-free, so CI tier 1 dropped its pip install).

**Result.** Game `check.py --fast` ALL PASS 7/7 (attract unchanged);
the moved tools verified live from the game root (`disarm` decodes the
real crt0 branch; misspack/ringscan load + parse). Fork CI green
through `2d7c2d7` (guard job exercising the new tests). Old
`release-stage/` snapshots mentioning the old paths are UNTRACKED
historical artifacts — deliberately untouched.

**Lesson.** "Whose tool is this?" is answerable by protocol, not by
residence: if the tool parses a format the framework defines or drives
a surface the framework exposes, it belongs to the framework — and its
tests move with it. Consumer repos keep the tools that encode THEIR
content (routes, identities, RAM-layout forensics, release identity).

## 2026-10-16 — Android launcher session: four device findings, the pure-Android launcher, a parallel-session fork tree

Device: Xiaomi Mi 11 (mars, 3200x1440), public release APK (`--expect
public`), manual QA. Goal: test the launcher track on Android.

**Findings (each fixed where it belonged):**

1. **The C++ launch screen was un-skippable on Android.** The skip check
   classified the RAW argv — but a NativeActivity's argv is raylib's
   synthetic `{"raylib"}`; every appended flag (`--no-launcher`, the staged
   TOML, debug-args entries) is invisible to it. Fix (fork): vector-based
   classification (`launcher_should_skip_screen(args)` + `--no-launcher`
   skip + `--launcher` force), unit-tested (boot classification 19 cases).
   Guarded game-side (`android-static`: classification must use the
   mutated vector).
2. **`run_game` died on `--no-launcher`** ("unknown argument" is fatal) —
   the launcher track retired the old seam parser without re-homing the
   flag; every PLAY looked dead (the game activity exited instantly and
   Android fell back to the setup screen). Fix (fork): the parser tolerates
   the flag as a no-op; the skip decision stays in the classification layer.
3. **tinyfiledialogs on Android**: no backend there, and the no-backend
   path prints a "missing software!" banner and blocks on a stdin read
   (once per dialog attempt). Fix (fork): on `__ANDROID__` the picker never
   reaches tinyfd — a clean log line instead; desktop behavior unchanged.
4. **`rom.cfg` cache-form miss**: a cached `/data/data/<pkg>` path can fail
   `fs::exists` from the app domain (`/data/user/0` spelling). Fix (fork):
   cache-candidates retry; new picks keep writing the observed form.

**Dead end, retired:** a SAF pick bridge behind `asset_picker_seam` was
built and device-tested; it demonstrated (a) a modal pick across the SAF
sheet starves the NativeActivity event pump (the window goes unresponsive;
`onActivityResult` can never run) and (b) post-and-exit relaunch races the
process out of memory. User decision: **the pure-Android setup activity is
the Android pre-boot surface; the raygui launch screen is desktop-only.**
The bridge was reverted; the fixes above were kept.

**Landed instead:** `GbaSetupActivity` restyled into the desktop launch
screen's layout (box-art panel, title, ROM path status, PLAY / SELECT ROM /
save import, skip checkbox); BIOS card retired (`biosRequired=false` — the
clean-room emibios always applies); `setBusy` null-guards the retired
views (an unguarded deref crashed SAF result delivery on device). Debug
`debug-args.txt` is now **one-shot** (a forced flag persisted across
relaunches otherwise). Box art rides the engine template's
`launchBoxartRes` mechanism (drawable, getIdentifier — supersedes the
game-local staging task).

**Tests:** fork boot-classification cases extended (vector overload, force
flag); `tools/check_launch_screen_wiring.py` (fork guard job: mobile
posture + one-shot + parser tolerance + retired-view hygiene, self-tested);
game `android-static` 26/26 (three new checks: skip classification,
boxart wiring, plus the save-import needle update). Manual QA passed on
device (pick → import → PLAY → boot).

**Parallel-session hazard:** the fork working tree also carries a
menu-engine refactor from another session (pluggable MenuEngine,
`raygui_impl.cpp`, `menu_engine_test`, `launchBoxartRes` template
generalization) — complete and 73/73 green on the Android path, but the
desktop target does not compile (`menu_engine_raygui.cpp:70` `SPINNER` not
declared), which blocks `cycle.py`/attract and any gitlink bump. Per user
decision the fork is hands-off pending coordination; this commit lands
game-side only, gitlink unchanged. Open item: land both fork workstreams
as separate commits after coordination, then bump the gitlink and run the
full gate.

**Resolution (same day, continued):** the parallel menu-engine session's
work was finished and landed with the user's go-ahead ("finish off that
unfinished work — move the settings overlay into full raygui").

- The fork's earlier "green" desktop build was **vacuous**: the fork
  standalone configure has `GBARECOMP_USE_RAYLIB=OFF`, so none of the
  raygui TUs (`raygui_impl.cpp`, `menu_engine_raygui.cpp`) had ever
  compiled anywhere — the game build was their first real compile.
- Three vendored-raygui defects surfaced in sequence, all in the 5.1-dev
  snapshot the launcher track committed (e779ab8): (1) the menu engine
  used the `SPINNER` control id — raygui 5.x removed it (the spinner
  draws through BUTTON + VALUEBOX properties); (2) `GuiFontIconBaking`
  was defined unguarded while its constants live in the
  `!RAYGUI_NO_ICONS` block; (3) `GuiGetTextWidth` was defined INSIDE the
  `!RAYGUI_NO_ICONS` block while its 20+ callers are not — NO_ICONS
  builds failed to link. (2) and (3) are LOCAL PATCHes in
  `src/vendor/raygui/raygui.h`, each with an in-file comment; the
  NO_ICONS path had never been exercised before (raygui_impl.cpp is new).
- **Lesson (process):** uncommitted work bypasses every gate — the fork
  CI `raylib` job exists and would have caught all three on push; the
  tree sat uncommitted for a day. Land early, land often.

Landed: fork `06c0669` (menu engine + vendor patches + `launchBoxartRes`
template) and `e15020a` (launcher fixes + guard), pushed to
james2doyle/gbarecompx main; game gitlink bumped to `e15020a`;
`check.py --fast` green; attract golden unchanged (`1EF4C118...`,
cycle `attract_verify=PASS`).

Remaining: APK repackage + device QA (`launchBoxartRes` boxart on the
setup screen — the settings overlay itself is desktop-only, so the
device artifact changes only by the boxart drawable).

**Follow-up (same day): the settings overlay stopped rendering on Delete.**

First regression from the menu-engine landing. Root cause: MenuImpl's
constructor assigned its own PRIVATE engine member; draw_pending_menu() —
a free function that cannot reach MenuImpl's privates — read
Impl::menu_engine, which nothing ever assigned. The menu OPEN path ran
completely (model open, `suppress_game_input` flipped, guest input
masked) and the null guard silently skipped the draw: Delete opened an
invisible menu. Found with the TCP KEYINPUT observer (input masked on
Delete, no visible overlay), confirmed by a grep for the member's
assignment. Fix: `52c04c7` — Impl owns the engine; the null draw path
fails loudly (one-shot stderr) if ever re-broken.

**Why the tests missed it (the user asked; recorded here so the answer
survives):** every layer was tested in isolation and the seam between
them had no executable coverage. `menu_engine_tests` drives the engine
over a recording overlay — never RaylibBackend. The host-loop suites run
fakes — never the real backend. The raylib CI job compiles the real
backend but its tests cannot reach the draw path (present() early-outs
without a live window; draw_pending_menu runs inside a real frame
context). The one end-to-end gate that runs the real binary — the
attract golden — never opens the menu. And the process failure on top:
~800 lines landed including a rewrite of that glue, pushed without
pressing Delete once.

**What now catches this class:** (1) structurally, the engine is owned in
one place (MenuImpl ctor assigns the Impl member) and a null draw path
fails loudly instead of silently; (2) functionally,
`menu_render_contract_tests` walks the real-backend menu seams through
the contract — available(), real-backend readback fidelity (previously
only pinned for the fake), and the plan §3.4 no-upload-leak invariant —
display-gated like backend_contract_test. **Honest limit:** the contract
cannot observe the composited screen (readback is the guest-frame upload
by design), so a silent no-draw remains invisible to headless tests.
The pixel-level assertion needs a screen-capture tier: an xvfb CI proof
that screenshots the window while a menu-open present loop holds it up
(mirroring the gl-xvfb job's proof-step pattern). Logged as the open
follow-up.

**Test-tier follow-up (same day): the raygui engine is testable headless
now.** The On/Off wording change exposed the remaining gap — the wording
was pinned for the legacy engine only; the raygui engine could never be
asserted (draw needs a raygui frame context; the real build's raygui is
welded to raylib). `60cf649`: the RAYGUI_STANDALONE path gives the engine
a headless harness — raygui's implementation over recording primitives
(this snapshot bottoms GuiDrawText/GuiDrawRectangle out in DrawRectangle +
per-codepoint DrawTextCodepoint; runs assemble into readable strings).
Five raylib functions the snapshot calls without declaring/defining under
STANDALONE (GetCodepoint, GetGlyphIndex, GetScreenWidth, GetScreenHeight,
UnloadTexture) are bridged; a dummy font is installed into guiFont at
static-init (the STANDALONE path never loads one — measuring a zero font
is a null deref). `menu_engine_raygui_test` pins the toggle wording
(On/Off, both flips), labels, title, chrome, repeat-draw purity, and
closed-silence; `menu_draw_test` gains the Off half of the legacy
assertion. Fork 75/75; all seven menu suites green in the game build.

**Launch-screen restyle (2026-10-16): desktop launcher adopts the Android
setup activity's visual language, semantics included.** Five red-first
sub-steps (fork `2078f30`…`310af0a`, each guard-verified + unit-pinned in
`launcher_style.h`/`launcher_skip.h`, headless-testable by construction):
(1) palette transcribed constant-for-constant from `GbaSetupActivity` +
the shared ROM status line (green path / amber prompt, exact wording);
(2) title row, the placeholder IS the title (`wrap_words` provides the
TextView wrapping DrawText lacks), privacy footnote; (3) action buttons —
`GuiButton` retired from the screen (vendored raygui has no corner-radius
style property), rounded cyan/navy via `DrawRectangleRounded`, focus ring
that survives dimming; (4) the box-art panel card (10px inset, stroke);
(5) the skip checkbox with FULL Android semantics (user's call): same
wording, default ON, read before any window opens — checked + validated
cached ROM returns Launch with no window flash (the cache is validated,
never resolved, so the skip path cannot open a picker). Escape hatch for
the known deadlock: `build/skip_launcher_on_boot` / `build/rom.cfg` are
plain files beside the exe. Guard extension: `check_launch_screen_wiring.py`
now source-pins the shared style (palette hexes, required usages, retired
literals incl. `"FFTA"`/`GuiButton(`/`DrawRectangleRec(`) with self-test
fixtures. Fork ctest 77/77; all launcher suites green in the game build.

**Launcher draw-loop harness (same day, `03ffe92`).** The raygui launcher
TU — compile-checked only until now — runs headless against a recording
raylib stub (`stub_raylib/raylib.h` needs no raylib fetch, so the tier
runs in the DEFAULT ctest run, not just the raylib CI job): recorded
draws, scripted per-frame input, `run()` steppable frame by frame,
raygui's implementation carried in the stub TU. Six scenarios pin the
screen and the loop (skip opens no window; frame-0 full draw incl. dimmed
PLAY; Escape; focus ring; click/Enter launch). Negative-controlled: a
scratch break of the dimmed-PLAY behavior fails at exactly that
assertion. Harness lessons (same as the menu harness): dummy font into
`guiFont` at static-init; raygui draws no space glyphs — the run
assembler reconstructs word gaps. Fork 78/78; launcher+menu suites green
in the game build.

**Launch-screen font fix (same day).** "Font is ugly now / looked better
before": the restyle drew raylib's bitmap default font (native 10px,
POINT filter — verified in the fetched rtext.c) at 22/28px; off-multiple
sizes shear the glyphs ragged. Fix: title + PLAY label 22→20 (uniform
2×), placeholder 28→30 (3×), small text 12/14/16 unchanged. A Roboto TTF
fix was fetched, wired, then removed unlanded after the call to keep the
raylib font. Sizes are NOT test-pinned (taste iteration loop) — wording
pins remain the binding assertions.

**Size pins (same day, user's standard).** "Tests passed after a big
font tweak → coverage insufficient": right — the size fix was
taste-silent. Text sizes are now value-pinned in launcher_raygui_test
(per element + a closed set over every frame-0 record + the checkbox
codepoint size); negative-controlled with the pre-fix 22. Amends the
prior entry's "sizes deliberately not pinned" — overruled.

**Settings-menu dead text after launcher boot (same day).** Root cause:
raygui's once-per-process lazy style init fired inside the LAUNCHER's GL
context; CloseWindow destroyed that font texture; raylib reloads the
default font per InitWindow but raygui never re-copies, so the overlay
sampled the dead texture (shapes fine — the shape texture is re-set from
the CURRENT font each InitWindow — text invisible). Predates the font-
size change; --rom paths never hit it. Fix: the menu engine re-runs
GuiLoadStyleDefault per draw before its theme block (stale binding
healed, current one a no-op, styles land on defaults — also fixes a
latent first-frame style wipe). Pinned red-first in the menu harness via
a font-corruption seam; test dummy fonts now heap-allocated/96-glyph
(the swap path frees recs/glyphs and reads recs[95]). Remaining honest
gap: GL-context lifetime itself is invisible to the recording tier —
pixel truth after context churn still needs the parked xvfb tier or the
user's eyes.

**Menu save/load state slots (same day).** The settings overlay gained
Save state / Load state / Slot rows — a feature the imgui-era menu had
(system.state_slot) that silently vanished when the presentation was
replaced; only the ungated executor + slot-path builder survived in
runtime.cpp, unreachable (the raylib backend has no F1..F9 mapping —
nothing interactive wrote ev.save_slot). Restored on the menu seam per
the in-tree doctrine: actions record-and-close; the host loop drains
pending ops into ev.save_slot/ev.load_slots right after host_menu.frame
(drain_menu_state_ops, pure + headless-tested) and the one ungated
executor runs them at the dispatch boundary; slot persists via config.ini
[Menu] state_slot; executor toasts confirm (drawn while closed). Pinned
red-first in four tiers — model (labels/rows/contract), rendered display
through both engines with HostMenu-built models, persistence round-trip,
and a product-wiring guard (check_menu_state_wiring.py, CI-registered,
self-tested) because the runtime drain call is the one line no headless
test reaches. Menu stub's run assembler now reconstructs spaces (ported
from the launcher harness) so multi-word labels pin exactly.

**C++ lint tier (same day).** clang-tidy 23 was installed locally, nothing
configured — now: `.clang-tidy` (curated: DeadStores, unused
params/usings/aliases, use-override, redundant member init),
`tools/check_clang_tidy.sh` scoped to the first-level src/runtime TUs
(excludes generated_bios/ — 109k recompiled lines, same rule as the game's
generated/ — and vendor/raygui), both CMakeLists export
compile_commands.json, fork CI runs it best-effort (SKIP without
clang-tidy/configure; local is the strict gate). First sweep: 29 warnings
= 15 vendor noise + 14 real, all fixed (netplay dtor override, two chrono
member inits, a tuple init, two unused profiler param names, four dead
cursor stores in the mods manifest parser — the key dispatch re-derives
the cursors per key line, so the section-header stores were unread).
0 warnings / 44 TUs / ~38 s. Dead code measured with the wiring-guard
scanner: 729 lines compile out of every product build behind the retired
GBARECOMP_RUNTIME_UI gate (~0.5% of src/runtime) + the seam headers —
removal is a separate session, the scanner proves each block.

**Android lint tier (same day).** Android Lint (AGP 8.10.1, `:app:lintDebug`)
over the engine-template activities: baseline **12 warnings, 0 errors**, all
documented deliberate choices — the landscape orientation lock (DiscouragedApi
×2, the 2026-10-08 decision), the Gradle 8.11.1 pin, the box-art
getIdentifier() reflection, preferMinimalPostProcessing above minSdk
(×2), plus cosmetic ObsoleteSdkInt/SetTextI18n/UnusedResources. The one real
improvement candidate logged, not done: a dataExtractionRules resource for
Android 12+ backups (a backup-behavior decision). Gate = zero lint ERRORS
(lintDebug fails the build on them); warnings stay visible in the report.
New `android-lint` CI job (game repo, tier-1-safe: no ROM, no private
material; setup-java 21 + gradle cache) + shellcheck `-S warning` over
tools/*.sh — one SC2164 found and fixed in derail_loop.sh, rest clean.

**Stale-device incident + the lock-in gates (same day).** The phone's
"broken touch controls" was the device running an APK installed 15:39:39
whose engine pin (e15020a) sat BETWEEN the menu-seam bug (06c0669, 15:39)
and its fix (52c04c7, 16:04): a long-press opened the menu, input was
suppressed, nothing painted, and the only touch exit was the system Back
key. Diagnosed device-side (installed versionName ↔ fork ancestry via
merge-base, plus a screenshot showing the exact signature); remedied by
rebuild + install (device gate PASSED). Three gates landed so the class
screams next time:
- **Composited-screen tier** (the 2026-10-16 logged follow-up, now real):
  menu_render_contract_tests reads the app's X window by title (root
  captures BadMatch under compositors) and asserts an open menu shows
  PANEL and TEXT pixels — the shapes-without-text dead-font signature —
  then none when closed. Red control demonstrated (draw disabled →
  `CHECK failed: panel > 300`). Skips without X11; CI xvfb runs it.
- **Stale-device guard**: validate_android.sh assertion 1b compares the
  installed versionName with `git describe --tags` (skips when either is
  unknown; fake-adb + fake-git self-test pins the FAIL path — android-static
  27/27), and build_apk.py preflight dies on the mismatch (--skip-stale
  overrides) and warns on an uncommitted submodule pin.
- **Settings-writer merge fix**: save_menu_settings kept the old [video]
  header AND appended a new one per save — the device config.ini hit ~50.
  Readers tolerate it (last section wins) but the file grows unboundedly.
  Now one merged [video] section, foreign lines preserved, LCD keys last,
  byte-idempotent. Red-first: the dupe pin now counts [video] (it only
  ever counted [Menu] — the vacuous-guard shape) + idempotence.
- **The lint tier drew blood on itself**: the c0/c4 "unused" profiler
  params are live under __ANDROID__ only; the desktop compile database
  can't see that, the rename broke the Android build (undeclared
  identifiers), restored with a NOLINT recording the configuration split.
  Lesson: the sweep is per-configuration — check an #ifdef before
  trusting "unused" on a cross-platform signature.
- **Guard follow-ups from its first live run**: the plain build path's
  versionName was the identity block's static "0.1.0" (the stale-device
  reference could never match) — build_apk.py now passes
  `-PgbaVersionName=<git describe>` (the engine template's property wins),
  so the device reports the checkout version (1.6-97-g899c269 at landing)
  and the guard reads clean. Gate 1b's sed missed dumpsys's *indented*
  `versionName=` (it skipped on every real device) — fixed; the fake-adb
  scenario now mimics the indentation. The capture tier joined CI:
  `raylib-compile` builds and runs menu_render_contract_tests on the same
  display recipe (real display locally, Xvfb+llvmpipe on runners).

**Audio toggle was set-but-never-read (same day, user report).** The
menu's Audio Bind was correctly wired — the raylib AudioImpl flipped
`audio_enabled` and nothing ever read it (zero readers since the Phase
4b carve), so the live toggle AND the boot-time [Menu] audio_enabled
application were both silent no-ops. Fix: push() honors mute before any
device gating (device-independent drop; buffered tail drains); the mute
contract is documented on the seam and pinned by audio_mute_contract_
tests — headless (no window or audio device needed; the ctor owns the
seam), red-first via the gbarecomp_audio_drop_stats counter (enabled()
cannot distinguish "flag set" from "flag honored" — the observable IS
the fix's test). 79/79; stub builds skip. A setter sweep for the same
class found no other dead flags: every seam setter's state has live
reads. On-device: ships in the next APK rebuild.

**Menu Save state failed on device: a foreign-owned slot (same day).**
"snapshot: cannot open for write: .../states/ffta_usa.state1" — slot 1
held a state file PUSHED BY ADB during the 2026-10-13 trace-replay
session (owned by shell, group r--), and the old writer opened the
TARGET for trunc (needs the file; the app owns only the directory).
Slot 2 saved fine moments earlier — the path, the dir, and the menu
save flow were all healthy. Fix: snapshot_write_file (temp + fsync +
rename, the mod_state pattern) — self-heals foreign-owned targets,
makes every state write crash-safe (slots AND suspend; the fsync lands
before the slot exists), and is pinned red-first by snapshot_write_tests
(reproduces the device failure literally; runs everywhere). 80/80.
No manual device cleanup needed: the next slot-1 save replaces the
shell-owned file.

**"State loaded" toast rendered forever (same day, device report).**
The slot-loaded toast draws while the menu is CLOSED by design (the
action closes the menu), gated on toast_frames > 0 — but the clock was
never ticked: the model deliberately has none ("the host decrements",
per menu_model_test) and no host code ever did. The identical dead
status clock (settings "Saved" line) was masked by the m.open gate;
the toast is the first visible symptom of the class. Fix: the single
per-frame pump (HostMenu::frame, the only present() driver) ticks both
clocks before presenting. Red-first: toast_and_status_clocks_expire
pins model AND presented-model zero at expiry (engine gate reads the
presented copy). 80/80. Landed with the savestate self-heal in the
same APK.

## 2026-10-16 — UI-layer margin suppression re-landed (chat bubble wrap, user report)

- Report (device session): "the chat text bubbles are wrapping/repeating
  now. They didn't seem to do that before" — the wide margins repeat the
  bubble's edge columns; later the same session: mirrored repeat on the
  right, a bottom bubble overflowing left, and the NOTICE confirm dialog
  overflowing BOTH edges.
- Why "now": the device APK carried the W3-era UI-layer skip until
  tonight's updates; the skip was withdrawn 2026-10-15 (move-state break +
  summon report). The withdrawn engine's window-controlled sampling wraps
  256-px UI tilemaps into the margins.
- Desktop recreation (user session, tools/play.sh --resize-view
  --tcp-observe): four probe captures + a frozen pub fixture
  (/tmp fixture drive; ws_pub_enter route + A,A → "Greetings!" bubble at
  guest 52623, saved as the A/B fixture). Mechanism pinned pixel-exact on
  all five: margins sample tilemap px (x - extra_left + hofs) mod 256; a
  256-px (BGxCNT size==0) panel's border/interior/text repeats wherever its
  scroll lands near the edge. Sprites ruled out (guest windows OBJ out of
  the margins; winout 0x2F everywhere).
- Captured gate disconfirmations (do not re-add without new evidence):
  BLDCNT==0 fails (the pub conversation runs blended, 0x3348, bubble up);
  window-enable bits fail (device conversations 0x1F40 = clear, desktop pub
  0x3F40 = set — same UI, different enable routing; a windows gate would
  have armed NOWHERE on the device). The only stable discriminator is the
  size field — exactly the withdrawn interim rule's condition.
- Re-land rationale: the 2026-10-15 interim width rule was withdrawn for
  the Totema report, but that session's own summon A/B (BRINGUP 2026-10-15)
  shows the summon window PIXEL-IDENTICAL with the rule enabled — the
  report was presentation-side, the rule was refuted-but-innocent. This
  landing is the same suppression (strict subset with the env kill-switch),
  so the summon A/B result carries over.
- Implementation: src/ffta_ws_margin.h (pure decision: size-0 layer mask +
  the -1/0 span contract) applied per frame in ffta_ws_margin_policy
  (src/main.cpp) via the engine's g_ws_bg_x_provider + layers mask; empty
  mask -> provider uninstalled (zero traffic). GBARECOMP_FFTA_UI_GATE=0 is
  the A/B arm and emergency kill-switch.
- Gates: fixture A/B (bubble repeats gone; 4379 px differ, confined to
  x0..23/x296..319 at view 320; center byte-identical; on/off frames
  reproduce bit-exact after the header refactor); ws_margin unit pin
  (captured register blocks incl. the move state's all-size-1 inert case);
  ws_check 6 cases x 3 widths; check.py 17/17 (attract golden byte-exact,
  strict routes FULLY_STATIC).
- APK rebuilt + installed + gate PASSED (1.6-102-g8c3c95c); device
  verification of the bubble fix pending the user's next session.

- Device verification (user, same evening): "just tested. looks good" —
  the bubble fix confirmed on the phone in live play. The install gate's
  6th check (resumed activity) had failed unattended-only; see the
  dev-gotchas entry. All four of today's fixes are on the device APK
  (1.6-103-gae01ddd): audio mute honored, toast/status clocks ticked,
  atomic savestate write, UI-layer margin suppression.

- Symbols follow-up (same day): seeded the talk-op chain reached during the
  bubble session — scene_char_talk_impl 0x0812638C, scene_vm_thread_spawn
  0x08121B8C, scene_talk_vm_callback 0x08125A5C (naming-only; boundaries
  verified with disarm.py; roles from call sites + prologues). The
  per-frame bubble renderer was NOT identified — the IO-snapshot gate made
  the hunt unnecessary; seed it if a future fix needs it. Naming-only
  rows: cycle PASS, attract golden 1EF4C118… held (no codegen shift); APK
  not rebuilt (no behavior change).

- Device confirmation (user, APK 1.6-106-g14cd881): all new settings work —
  Pixel grid renders, Grid opacity adjusts, Sharp scaling persists/applies.
  Sharp shows no visible difference on the phone — expected, not a defect:
  the 2400x1080 panel is a 6.75x fractional fill (prescale factor 6,
  remainder 1.125), where nearest's uneven columns and sharp's blend
  columns are each ~1/9 of a game pixel — below notice, consistent with the
  >3.5x crossover in reference/upscale-shaders.md. Sharp's visible band is
  1.5-3.5x window scaling (desktop drag test). Engagement on-device is
  inferred from the deterministic layout math (fractional at every probed
  inset variant) — the backend has no engagement log line; adding one is a
  cheap triage aid to bundle with the next fork change. Aesthetic follow-up
  candidates for the ">3x doesn't look great" complaint: MMPX 2x edge-
  smoothing pre-pass (style change, every scale) or an integer-scale
  pillarbox layout option on the phone (pixel-perfect, obvious difference);
  awaiting the user's call on which direction they want.

## 2026-10-16 — MMPX edge smoothing (settings toggle, full coverage)

- Build-out of the MMPX investigation (reference/upscale-shaders.md §
  work plan): McGuire & Gagiu JCGT 2021, palette-exact 2x
  reconstruction. New "Edge smoothing" row (Graphics, shader-gated),
  [video] edge_smoothing persistence, no CLI flag.
- Differential testing caught TWO issues pre-merge: the UPSTREAM C99
  clamp bug (`min > max` — never upper-clamps → OOB reads; fixed to the
  documented intent in the vendored test-only copy with a DEVIATION
  note) and a wrong hand-derived pin (line-END corners legitimately
  round per rules 2/4 — interior diagonal blocks are the invariant).
  Mirror matches the fixed reference byte-for-byte over 160 random
  images + structured patterns.
- Backend: first present-chain pass (game tex → 2x POINT RT → the rest
  of the chain); engages at display ≥2x; sharp factor computed against
  the STAGE dims (phone 6.75x → factor 3 vs 640x320 — identical RT size
  to today's); set_linear_filter re-filters the stage. Tap clamping is
  in-shader (the game texture's wrap is REPEAT — noted as the deband
  pass's latent issue too, default-off, unfixed there yet).
- glslangValidator both dialects rc 0 (negative control verified).
  Suites: stub 81/81, headless 82/82, check.py 17/17, attract golden
  1EF4C118… held (readback pre-shader contract).
- Desktop A/B (windowed 4x, off/on): 2.50% of pixels differ,
  concentrated in small features — menu bullet stars reconstructed,
  text curves cleaner, portrait edges smoothed. Assistant-verified on
  the captures; USER manual check pending (desktop + Android).

## 2026-10-16 — MMPX verified by user; grid boot-enable bug fixed; README shader-stack callout

- USER manual checks: MMPX "works. not really my style" (the intended
  outcome for a taste toggle — stays opt-in, default off). Pixel grid
  report: **starting the game with it on does not enable it**.
- Root cause (fork `1cea51c`): `FxImpl::load_config` direct-wrote
  `impl_->lcd_border` before diffing — `settings()` agreed with itself,
  so every later diff-driven path (load_config's own compile block AND
  the runtime boot's menu-settings apply) no-oped silently and the LCD
  program never compiled; present saw the flag on with
  `lcd_shader_ready` false → no grid until an in-menu toggle. MMPX and
  the grille path were unaffected (they diff parsed locals).
- Fix: effect toggles go through `apply()`'s diff exclusively in
  load_config (floats keep direct writes — no transitions attached) +
  defense in depth: present() lazy-compiles the LCD program whenever
  either effect wants it (the dither/deband pattern) — boot ordering
  can never strand a configured-on effect again; open() also compiles
  when border-only is configured.
- Two test-infra bugs found while pinning this (both fixed in the same
  commit): (1) the two-arg `CHECK(cond, "msg")` form is the COMMA
  OPERATOR under the file's variadic CHECK — every two-arg present-level
  pin in raylib_api_fake_test was vacuous (condition discarded, the
  string literal always non-null) — converted to single-arg with the
  message as a trailing comment, making the boot-enable pin TRUE red;
  (2) FakeRaylibApi cleared its uniform-name map on every program load,
  so once the lazy compile put two program loads inside one present,
  post-second-program uploads recorded nameless and every name lookup
  missed — real GL hands per-program locations; the fake now keeps one
  persistent name→loc map.
- New pins: `config_enabled_border_compiles` (the exact boot
  double-apply sequence, true-red verified) +
  `config_enabled_lcd_compiles` (same poison class, grille path).
  Suites: stub 81/81, headless 82/82.
- Desktop end-to-end repro of the user scenario (scratch exe dir,
  config.ini with lcd_border=1 + edge_smoothing=1, cold boot, no menu
  interaction): capture shows grid + MMPX active on first present; both
  programs compile at boot (window capture at /tmp/opencode/boot_probe/).
- APK 1.6-111-g7a93ce0 built + content guard passed; device gate failed
  only the resumed-activity check (phone dozing — the documented
  unattended quirk); install pending an awake phone + USER relaunch
  repro (the regression scenario itself).
- Fork `8503ad1`: README gains "The present-time shader stack" section
  (per-toggle what/engages, chain order, game-space anchoring,
  frame-hash safety) + the Display-effects table row and value bullets
  name the new toggles; THIRD_PARTY_ATTRIBUTION.md gains the MMPX entry
  (JCGT 2021 MIT, algorithm-level port, vendored test-only oracle,
  clamp DEVIATION, opaque-input assumption).

## 2026-10-17 — tier-1 CI red: stale build-dir cache (rename era) + folded backslash continuations

- Symptom: every push since ~01:36 failed. Two failure classes.
- Class 1 (9-10s runs): the submodule fetch — the gbarecompx fork was
  PRIVATE, so `git submodule update --init --recursive` was denied on
  runners (actions/checkout's token only reaches the workflow's own
  repo or public ones). USER made gbarecompx public → resolved; the
  15:41 run shows ✓ Pinned submodules.
- Class 2 (the real bug, run 39007194586): tier1 Configure FATAL
  "GBARECOMP_ROOT is not a gbarecomp checkout: .../gbarecomp" — value
  WITHOUT the x. Root cause: tier1 caches the whole `build/` dir
  (added yesterday, green run 38958229935 = the last green tree
  2ad4a334, which still had `[submodule "gbarecomp"]`); the
  restore-keys prefix fallback (`ffta-build-Linux-`) restores that
  stale CMakeCache.txt past the CMakeLists-hash key, and
  `set(GBARECOMP_ROOT ... CACHE PATH)` never overwrites an existing
  cache entry → the pre-rename path won over the new `gbarecompx`
  default and the checkout guard died. android-lint and raylib-backend
  stayed green — only tier1 caches build/ itself.
- Reproduced locally: a scratch build dir seeded with one cache line
  (`GBARECOMP_ROOT:PATH=.../gbarecomp`) + the CI configure → the exact
  FATAL_ERROR at CMakeLists.txt:20.
- Latent bug found in the same step while diagnosing: the Configure
  `run:` used backslash continuations in a plain YAML scalar — YAML
  folds it to one line, `\ ` becomes an ESCAPED SPACE, and the token
  dump proves ` -DGBARECOMP_USE_RAYLIB=OFF` and
  ` -DCMAKE_CXX_COMPILER_LAUNCHER=ccache` arrived as positionals
  (leading space; CI's "Ignoring extra path" warning). The stub flag
  silently never applied — had the cache been clean, tier1 would have
  configured the PRODUCT (raylib-fetching) config instead.
- Fix (ci.yml, tier1 only — release.yml checked clean for the
  pattern): Configure becomes a `run: |` literal block (real line
  continuations) and does `rm -f build/CMakeCache.txt` first, so any
  restored build dir reconfigures from CURRENT defaults; ccache keeps
  the rebuild fast, restored object files stay reusable. Step comments
  document both traps.
- Verification (scratch dirs, local build/ untouched): poisoned dir +
  fixed script → configures clean, `GBARECOMP_ROOT=.../gbarecompx`,
  `GBARECOMP_USE_RAYLIB:BOOL=OFF`; unit gate built + run there →
  PASS (0 failures).
- Closed: pushed `9cef94b` → run 39046598762 GREEN (tier1,
  raylib-backend, android-lint all success) — first fully green run
  since the rename; first tier1 Configure past the guard since the
  build-dir cache landed.
- Watched annotations (warnings only, no action yet): setup-java v4 →
  v5 migration; actions/cache@v4 + checkout@v4 target Node 20 (forced
  to 24); **ubuntu-latest migrates to Ubuntu 26 from 2026-10-19** — if
  a runner-image change breaks a job, pin ubuntu-24.04 explicitly.

## 2026-10-17 — Android gamepad capture (raylib #5387 device class; AYN Odin)

- USER report (device now the AYN Odin handheld, serial 3961e6e — not
  the Poco): controller buttons dead except "B opens the menu"; wanted:
  face buttons → GBA, KEY_BACK keeps opening the menu, right trigger →
  speed boost, left stick → d-pad (the existing shared behavior).
- Facts gathered (all cited):
  - `adb shell dumpsys input`: "Odin Controller" Classes KEYBOARD |
    GAMEPAD | JOYSTICK; KeyLayoutFile Vendor_2020_Product_0111.kl.
  - The .kl maps BTN_EAST→BUTTON_B (0x131), and a DEDICATED HID 0x9e
    → BACK; `adb shell getevent -lt` live capture (user pressed all 11
    controls in order): A=BTN_GAMEPAD, B=BTN_EAST, X=BTN_NORTH,
    Y=BTN_WEST, L1/R1=BTN_TL/TR, L2/R2=BTN_TL2/TR2 with ABS_BRAKE/
    ABS_GAS analog, Select=BTN_SELECT, Start=BTN_START, and the d-pad
    reports ONLY through ABS_HAT0X/HAT0Y (no BTN_DPAD_* keys).
  - raylib's Android backend (platforms/rcore_android.c, pinned 6.0
    SHA): gamepad KEY branch requires source GAMEPAD/JOYSTICK and NOT
    KEYBOARD; the keyboard fallback table maps every AKEYCODE_BUTTON_*
    to 0. Upstream FIXED this class AFTER our pin (raysan5/raylib
    5e14ac5, 2025-12-26; later refined "trust gamepad keycode, not
    source bits" — the same design we adopted).
  - Menu chain confirmed: KEY_BACK → GestureKind::Back → host policy
    drains → menu toggle (raylib_backend touch section + TouchHub).
- Fix (framework): new `src/runtime/android_gamepad.h` — pure keycode→
  PadButton / axis-id→PadAxis tables (NDK-verified constants), the
  ±32767 scaling (GAS/BRAKE *2-1 like the block it replaces), and an
  atomic AndroidPadState (glue input thread writes, game thread reads).
  `raylib_backend.cpp`: a glue-level onInputEvent hook installed after
  InitWindow via raylib's GetAndroidApp(), CHAINING to raylib's saved
  callback (the glue has ONE slot; returning 0 would drop events for
  raylib too — BACK→menu, launcher nav, touch all preserved). The
  hook trusts the KEYCODE, not the source bits; the Android gamepad
  block in read() now feeds the hook's state through the SAME shared
  mapping (gamepad_map.h) as desktop — stick→dpad inherited via
  stick_to_dpad(), right-trigger fast-forward inherited from the
  assist defaults (raylib_keymap.h assist_pad[1]). gamepad_connected()
  on Android now also reports the hook's state.
- Bounded `pad-census:` TraceLog lines (first sighting per keycode /
  motion source) give on-device logcat evidence for the #5387 source
  question; desktop compiles all of it out.
- Tests red-first: `tests/runtime/android_gamepad_test.cpp` (+ CMake
  registration) — table correctness incl. the two regression pins
  (BACK never a pad button; C/Z/MODE/CENTER unmapped), HAT polarity
  (measured -1 = up), scaling, and the end-to-end snapshot →
  gamepad_to_keyinput path. Stub tier 82/82 (81 + the new suite);
  headless (raylib ON) 83/83; cycle PASS — regen 63134 units, attract
  golden 1EF4C118… held.
- Desktop unchanged by construction (separate #else GLFW branch); user
  manual test planned. Parked: launcher (pre-boot) gamepad nav still
  reads raylib state — dead buttons on this device class until the
  raylib pin takes upstream 5e14ac5; touch works there.
- APK 1.6-117-g8c1e55b (capture path): build+install+gate ran GREEN
  once the glue-header include landed on the right target
  (gbarecomp_raylib_backend, not gbarecomp_runtime — fork 3516f6e);
  two android-ABI compile failures on the way, both invisible to the
  desktop tiers (#if __ANDROID__ code has NO desktop compile gate —
  the APK build IS the gate; also: gradle does not track submodule
  CMakeLists changes, the .cxx configure went stale, touch the game's
  CMakeLists to force reconfigure, which then trips the APK preflight's
  regen-stamp freshness check → cycle.py re-run).
- USER test on the Odin: "android is mostly working. the controller B
  button is still opening the settings menu though" — and the census
  caught the REAL mechanism: keycode=97 (BUTTON_B) at the hook, then a
  KEY_BACK edge ~36ms later, then KEY_BACK edges at keyboard auto-repeat
  cadence while held — with NO BACK event at the kernel level (two
  all-node getevent captures: B=BTN_EAST only). ROOT CAUSE: raylib
  leaves the gamepad key UNHANDLED (#5387 guard + zero keyboard table →
  callback returns 0) → the InputDispatcher synthesizes the device
  KeyCharacterMap's FALLBACK key. Generic.kcm read verbatim on the
  Odin: BUTTON_B→BACK, BUTTON_A→DPAD_CENTER (observed: keycode=23
  +34ms after A), BUTTON_X→DEL (a SECOND menu path via the
  touch-emulated Backspace arm), BUTTON_Y→SPACE, BUTTON_START→
  DPAD_CENTER, BUTTON_SELECT→MENU, BUTTON_MODE→HOME. The menu-on-B was
  never a mapping bug — it was Android finishing raylib's unhandled
  event for it.
- Fix (fork 1d7ad51): `android_key_consumed(keycode, flags)` — (1)
  consume the gamepad-button range 96..110 always (handled events never
  trigger fallback synthesis); (2) defense in depth: consume a
  FLAG_FALLBACK-tagged BACK/DPAD_CENTER (NDK AKEY_EVENT_FLAG_FALLBACK
  = 0x400) — real Back presses carry no fallback flag, so KEY_BACK →
  menu stays. DPAD_* still forward (raylib maps them to arrows — menu
  pad-navigable). Census v3 logs the first THREE sightings per keycode
  with source AND flags. Plus kPadGuide (BUTTON_MODE on Android, GLFW
  GUIDE on desktop) → injects the CONFIGURED HK_MENU key: the pad's
  menu button opens the settings overlay; menu then navigates from
  GBA KEYINPUT levels (d-pad + A/B).
- USER verified on the Odin (APK 1.6-119-g37a6f1c): "it works now. no
  issues" — B=GBA B (no menu, no flicker held), back=menu, A clean.
  Desktop guide-button check next (binary rebuilt).

## 2026-10-17 — sharp scaling: pixel-proven working; inert-at-integer made explicit

- USER challenge: "the sharp scaling toggle does nothing. it is
  imperceptible. even at scale 8. are you absolutely sure it works?" —
  a fair challenge: NO test anywhere pinned the toggle's VISIBLE effect.
  The existing present-test section (resize to 700x500 + sharp on) only
  proved the RenderTexture LIFECYCLE runs — its readback() serves the
  CPU staging buffer, pre-GPU by design, so a sharp path that never
  engaged would still pass it.
- Engagement math (presentation_layout.h, cited): the fit layout
  maximizes at the reduced aspect (3:2 for 240x160), and
  integer_scale>0 only when the layout is a whole multiple of 240x160;
  compute_sharp_prescale_factor returns 0 for integer layouts BY DESIGN
  (every game pixel already spans whole device pixels — nothing to even
  out) and for layouts too small for a factor>=2 prescale. The DEFAULT
  window (960x480 → 720x480 = 3x) and every --scale N window
  (--scale 8 → 1920x1280 = 8x) are exact integers → the toggle is
  silent THERE, correctly. It engages on any window whose 3:2 fit is
  not a whole multiple — any 16:9 window (1920x1080 → 6.75x, the
  phone's case) included.
- NEW PIXEL PINS (tests/unit/test_raylib_present.cpp, GL-only section,
  LoadImageFromScreen = the real framebuffer): at 700x500 (units=233,
  fractional, factor 2) the presented picture MUST DIFFER between sharp
  off and on on a non-uniform pattern (>5% of clean-in-both-reads layout
  pixels, ±2 LSB) — RESULT: PASSES (~the pin is green: the toggle
  changes the picture); at the exact 2x control the outputs must be
  pixel-IDENTICAL (±1 LSB, changed==0) — the designed inertness, now
  explicit. Grounding: the rsn8887/TheMaister sharp-bilinear family is
  a fractional-scale fix ("sharp pixels without pixel wobble", automatic
  integer prescale + bilinear remainder) — integer-scale inertness is
  the recipe's intent, not a local defect.
- Discoverability fix (fork): the menu now SAYS when the toggle is
  inert. Video::logical_size (default 240x160; the raylib backend
  returns its live base — widescreen widths included) + a
  sharp_status_if_inert() helper that runs the SAME
  compute_sharp_prescale_factor over the live drawable, called from
  HostMenu::build (opened onto an inert toggle) and from the
  Bind::SharpScaling apply case (the toggle moment). Status strings:
  "Sharp scaling: inert at exact scale" / "window too small to engage"
  (both < kMaxStatus=48). Test: sharp_inert_status() (red-first: the
  status was empty pre-impl) covers open-on-inert, engaged-silence, and
  the live-toggle case — which exposed that frame() processes input
  only while the menu is OPEN (build() alone ignores presses; open() =
  build + menu_open).
- Verification: stub 82/82, headless (raylib ON) 83/83, GL present
  pins PASS — after one self-inflicted detour: an extra closing brace
  from the logical_size insertion broke the VideoImpl class, and the
  FIRST verification round "passed" on stale binaries (the builds had
  failed; ctest ran old objects). Lesson repeated: a green ctest means
  nothing unless the build before it was clean — read the build's
  exit, not just the tests'.
- CI follow-up (the pixel pins' first CI run FAILED): the raylib-backend
  job runs under **Mesa llvmpipe**, where the pin's original design —
  close/reopen the backend around every grab — turned every
  LoadImageFromScreen read STALE (different patterns read back
  identically; the diff zeroed). Local repro without Xvfb:
  `LIBGL_ALWAYS_SOFTWARE=1` on the real display = the same renderer.
  Root causes, in order: (1) reopen-per-grab → stale reads under
  llvmpipe (the mask check above it reads fine WITHIN one context —
  the reopen was the variable); (2) resize lag — the first
  present/read after SetWindowSize is transitional (old-geometry
  frames masquerading as ~100% "differences"). Fixes: ONE context for
  all grabs (sharp toggles LIVE via fx().apply — the path the fake-api
  suite already pins), different patterns on the two off-reads as an
  explicit READBACK-LIVENESS pin, and a settle present+read after
  every SetWindowSize. Result: real GL 25316/36348 (70%) differ,
  llvmpipe 25262 (69%), deterministic across runs, PASS on both. The
  suite now carries its own environment guardrails: liveness first,
  settle after resize, numbers printed on every run.

## 2026-10-17 — test ownership split: the game's CI tests only the game

- USER question: "why does ffta-recomp run those tests? are they not
  already tested in gbarecompx?" → the audit found 7 of the game's 10
  unit/integration tests tested FRAMEWORK code, because the ORIGINAL
  blockers had silently died: "gbarecomp cannot compile host_window.cpp
  standalone" (recomp-ui removed; the fork's runtime carries in-tree
  generated_dispatch.cpp — raygui_links_tests already linked it) and the
  pristine-submodule API gates (HOST_STACK_GUARD_API / PACER_BANKED_API /
  STICK_DPAD_API — the fork IS the API home).
- Audit verdicts: ram_dispatch/speed_boost/ws_margin = game ✓ kept;
  host_window_closed = a DRIFTED DUPLICATE of a fork file that was
  ORPHANED (never CMake-registered — and it asserted a
  resize_driven_view() getter that does not exist, i.e. broken code
  sitting unbuilt); host_window_delegation = unique coverage (the fork's
  window_backend_dispatch drives the backend interfaces, not the
  HostWindow facade) → moved; backend_select = folded into the
  consolidated host_window_closed test (same factory contract);
  stack_guard/frame_pacer = converted from companions of the game's
  ram_dispatch harness into standalone fork tests; stick_dpad = deleted
  (re-pinned gamepad_map's stick_to_dpad; its header even named the
  wrong file); raylib_present = moved verbatim (llvmpipe-hardened).
- Fork side (ab72068): five tests adopted + registered (the present test
  in the raylib tier only); local verification: stub tier 86/86, the
  raylib scratch tier (FETCHCONTENT_SOURCE_DIR_RAYLIB pointed at the
  game's fetched raylib-src) 88/88, the present test PASS on real GL AND
  LIBGL_ALWAYS_SOFTWARE.
- Game side (4ccc7dc): ffta_unit_tests = ram_dispatch + speed_boost only
  (the framework sources it used to compile directly are gone, with the
  API gates); the four framework test targets removed;
  check.py's raylib-compile = the product-config compile + the Phase 4c
  default-flip assertion (the present + menu-composite runtime tiers run
  in the fork's raylib job — the menu tier was ALSO a framework test the
  game's suite was running); backend-default keeps the cache assertion;
  ci.yml + tests/README comments updated.
- Coverage continuity: the fork's CI runs the moved tests per fork push
  (the game's bump pins that exact commit); the game's CI re-verifies
  its own three per game push. CI watch after the pushes next.

## 2026-10-19 — Steam Deck AppImage + ROM-free release workflow

**Action.** Added a Steam Deck/Linux AppImage path and made the GitHub
release workflow ROM-free:

- `tools/compat_build.py` + `tools/compat/Containerfile`: build
  `build-compat/FFTARecomp` in a pinned Debian 12 container (glibc 2.36
  floor; the produced binary requires `GLIBC_2.35`). The host CachyOS build
  required `GLIBC_2.43`, which SteamOS does not provide. Podman uses a
  private vfs store when the default overlay-on-btrfs storage is unusable;
  Docker uses the same Containerfile.
- `tools/make_appimage.py`: stages the same allowlisted Linux payload,
  pins appimagetool 1.9.1 and the type-2 runtime by SHA-256, and builds
  `FFTARecomp-<version>-linux-x86_64.AppImage`. `AppRun` unpacks the
  payload into `$XDG_DATA_HOME/ffta-recomp/app` (writable sidecars:
  `rom.cfg`, settings, saves) and copies updates over the payload without
  deleting player files. `SteamDeck=1` adds borderless fullscreen +
  resize-driven view unless a display flag was passed
  (`FFTA_APPIMAGE_NO_DECK_DEFAULTS=1` disables it). The finished AppImage is
  extracted and swept for private material, then booted from a fresh data
  dir for a strict 2400-frame FULLY_STATIC smoke.
- `tools/publish_release.py`: local build → verify → upload pipeline for
  the Linux zip, public APK, static Windows zip, AppImage, and
  `SHA256SUMS-<tag>.txt`. `.github/workflows/release.yml` is now
  GitHub-hosted and only creates a draft release shell; it never checks out
  the game tree or asks GitHub for the ROM. The ROM-derived corpus remains
  a local-only input by policy.
- `build.py`: dropped the stale `recomp-ui/CMakeLists.txt` submodule
  marker (it made every fresh bootstrap die) and fixed the step count.
- `build_apk.py`: `device_attached()` returns false when `adb` is absent;
  a headless APK build no longer requires platform-tools.
- `gbarecompx/packaging`: replaced the SDL-era Flatpak/Linux/macOS scripts
  with current raylib-era `package_linux.sh` (portable + AppImage),
  `package_macos.sh`, and `package_release.ps1`; the test now exercises the
  Linux staging/AppDir contract without PyYAML or Flatpak.
- `gbarecompx` `window_backend.h`: `Video::logical_size` is pure again
  (the seam guard had caught the defaulted body introduced in `0efbe87`);
  `RecordingVideo` carries the explicit override.
- `tools/make_release.py`: `--binary` selects the compat executable;
  the freshness gate now also watches `gbarecompx/build/gba_recompile`.

**Evidence.**
- `tools/compat_build.py` → `build-compat/FFTARecomp`, sha256
  `d1987e8914e1080479c68978e1d01a151d13bff80e5c0f9fd9f8415e7532f08a`,
  max `GLIBC_2.35`.
- `tools/make_appimage.py --version v1.7-rc1 --binary
  build-compat/FFTARecomp` → AppImage sha256
  `9fd96b6bfca41f157190a890879875dc5fc0d06b7e9a1dfa314348d91d7d996e`,
  34,695,672 B; host smoke FULLY_STATIC.
- The same AppImage booted inside the Debian 12 container (glibc 2.35)
  for 600 frames: `FULLY_STATIC`, 0 misses — the SteamOS floor proof.
- `gbarecompx` ctest 86/86; `tools/check.py --fast` ALL PASS 7/7
  then the full gate ALL PASS 17/17 (raylib-backend now passes);
  `tests/python/test_tools.py` 56 tests.
- `actionlint` + `shellcheck -S warning tools/*.sh` clean.

**Commits.** `gbarecompx` `7a56fd0` (seam) + `559b1db` (packaging) + `e6138a5` (Windows docs); game `5c8229d` (pin bump) + `c2a27b6` (release/AppImage tooling) + `ee14749` (packaging pin/runtime pin) + `29f4e06` (Windows docs pin).

**Open.** Release signing key still debug; the release branch/pin decision
and the first real tag remain (local publisher requires a clean tree whose
HEAD is the tag).

**CI follow-up (same day).** The pure `Video::logical_size` contract also
required `NoopVideo` in `gbarecompx/tests/runtime/backend_v2_types_test.cpp`
to implement the method; the local `gbarecompx/build` had stale objects and
missed it, while the framework CI's clean build caught it. `bbca5d3` adds
the override (framework ctest 86/86; clean raylib-OFF build 86/86) and the
game pin is `bb0636d`. The game's `android-lint` job then failed once on a
corrupt NDK download (`ZipException: Archive is not a ZIP archive`), not on
the tree; the job was rerun.

## 2026-10-19 — README pass: release-only quick start, Del menu key, Steam Deck

**Action.** Rewrote the branch README for players and moved source-build
material into `docs/manual-build.md`:

- Quick start now covers only release artifacts: the Linux zip, the static
  Windows zip, the Steam Deck/SteamOS AppImage, and the public Android APK.
  Source-build requirements, the `build.py` route, the manual pipeline, the
  Android build, and contributor notes moved to `docs/manual-build.md`.
- Quick start is a single release/requirements table plus one shared
  ROM-pick flow; platform install steps are separate and file locations
  are collapsed under `<details>`. Added old-battery-save import for
  desktop (`saves/ffta_us.sav`, 64 KiB) and Android (setup-screen
  **Save data** card / manual external path).
- The top docblock now names `gbarecompx` — the actively developed fork
  this project builds on — rather than upstream `gbarecomp`;
  `docs/README.md`'s "What this is" follows.
- Corrected the in-game menu trigger from `Esc` to `Del` (`HK_MENU` default
  `Delete`, `raylib_keymap.h`; see also `input_translate.h`). The menu
  navigates with the D-Pad/arrows, A confirms, B goes back; `Del`/Guide
  opens and closes it. The Android note no longer claims `Esc` steps back
  inside the menu.
- Made Steam Deck/SteamOS explicit in the intro, features, quick start,
  and system requirements, including the AppImage's writable XDG unpack,
  Game Mode display defaults, FUSE fallback, and the glibc 2.35 floor.
- Features now lists the present-time shader stack (MMPX edge smoothing,
  sharp scaling, pixel grid, LCD grille/boost/dither/deband) and frame
  enhancements (interpolation, LCD ghosting/frame blending).
- Removed the old SDL2/recomp-ui dependency claims from the player-facing
  text. Note: `origin/main` still carries the pre-raylib README; it updates
  only when PR #29 is merged.

**Evidence.** `gbarecompx/src/runtime/raylib_keymap.h` (default
`HK_MENU` = `"Delete"`), `gbarecompx/src/runtime/input_translate.h`
(`HK_MENU`), `gbarecompx/platform/android/gbarecomp-app.gradle` (minSdk
28), `tools/publish_release.py` (artifact names), `tools/make_appimage.py`
(XDG unpack + `SteamDeck=1` defaults), `game.toml` § `[save]`
(`saves/ffta_us.sav`, flash512/65536), and `GbaSetupActivity`'s optional
save import (size-validated, mirrors to the external `saves/` dir);
`build-compat/FFTARecomp`'s max `GLIBC_2.35` requirement.

**Checks.** Local Markdown link check for the three edited docs; no
`recomp-ui`/`SDL2` tokens remain in `README.md` or
`docs/manual-build.md`; `python3 -m py_compile build.py build_apk.py
tools/check.py`; `git diff --check`.

**Commit.** This change.

## 2026-10-19 — Fast-forward speed exposed in the in-game menu

**Issue.** The README claimed a 2–10x fast-forward speed adjustable in
Assist Tools, but the raygui migration dropped recomp-ui's Assist page and
the generic menu had no speed row. Only the hidden `config.ini [Launcher]`
key and the 4x default reached the backend.

**Action.** Added the missing control:

- `Input::set_fast_forward_multiplier(int)` is a pure seam method (clamped
  2–10) implemented by the raylib backend and test fakes.
- The in-game menu has a new **Assist** section with a **Fast-forward
  speed** StepInt row (2–10). The row updates the backend immediately.
- The value persists in `config.ini [Menu]`; startup applies it after the
  legacy `[Launcher]` loader so the menu's choice wins. Absent `[Menu]`
  leaves the backend/game default untouched.
- README corrected: removed the “latch it from the menu” and in-menu
  key/pad-binding claims; speed is now documented in the Assist section.
- Added `docs/fast-forward.md` — controls, 2–10x tuning and persistence,
  audio/frame behavior, the touch latch's session lifetime, and
  troubleshooting — linked from the root README, `docs/README.md`, and the
  Android guide.

**Evidence.** `gbarecompx` ctest 86/86; `host_menu_tests`,
`menu_settings_tests`, `raylib_backend_v2_tests`, and
`backend_v2_types_tests` pass; seam guard reports 61 interface methods
across 7 surfaces; `tools/check.py --fast` ALL PASS 7/7; `FFTARecomp`
builds.

**Commit.** `gbarecompx` `ace70b3` (menu row + persistence) and
`7c319eb` (capture-safe recomp-ui context update); game pin in this change.

## 2026-10-19 — Menu section: System → Save states

**Action.** Renamed the generic in-game menu section from **System** to
**Save states**. Its rows are unchanged: Slot, Save state, Load state, and
the trailing Resume game action. Updated the product-path menu and renderer
tests to the new title; the old recomp-ui path keeps its historical
"System"/"Assist Tools" labels because it is not the shipping surface.

**Evidence.** `gbarecompx` ctest 86/86; seam guard 61/61.

**Commit.** `gbarecompx` `7c95fac`; game pin in this change.

## 2026-10-19 — Recomp registry metadata refresh (.recomp.json)

**Action.** Added the Steam Deck target and switched the toolchain name to
the fork the project actually builds on (`gbarecompx`). Added feature tags
for widescreen, the shader stack, frame interpolation, LCD ghosting,
fast-forward, save states, controller, touch, Steam Deck and Android; expanded
the notes to cover the launch screen, GBA screen modes, the shader/frame
stack, 2–10x fast-forward, Steam Deck AppImage defaults, and ROM-less release
artifacts.

**Checks.** `.recomp.json` parses and validates against the published
`https://recomp.fyi/schema/v1.json` (draft 2020-12).

**Commit.** This change.

## 2026-10-19 — AppImage settings menu text: raygui same-texture-id font heal

**Report.** Steam Deck/AppImage, launcher → select ROM → open the settings
menu: the panel and widget shapes drew, but no menu text.

**Root cause.** raylib disposes its default font on `CloseWindow` and reloads
it on the next `InitWindow`; raygui's `GuiLoadStyleDefault` rebind guard
compared only the font texture id. When the driver reused the launcher
texture id for the game window's font, the guard short-circuited while
`guiFont.recs`/`glyphs` still pointed into freed launcher-context memory.
Shapes rendered (their texture is re-established by raylib's font load),
text did not. `--rom` reproduces neither window transition, which is why the
same build looked correct on the direct-boot path. Upstream raylib source
confirms the default font's `CloseWindow` disposal; raygui source confirms
the id-only identity check.

**Fix.** `gbarecompx` `8b68302`: the raygui identity guard also compares the
glyph-table pointers and rebinds the live default font. The existing
unload/free path stays behind the different-id condition, so the same-id
dangling tables are never freed a second time. Added a same-texture-id
regression test (`corrupt_font_same_texture`); it fails without the guard
change and passes with it.

**Evidence.** Framework ctest 86/86; negative control fails at the new
same-id assertion; game fast gate 7/7; the product build consumes the new
pin. Upstream references: raylib's `rtext.c` (default font loaded on
`InitWindow`, disposed on `CloseWindow`) and raygui's `GuiLoadStyleDefault`
identity check. Rebuilt Steam Deck AppImage `v1.7-rc2` (sha256
`23d12a5055ae71e2c59978522815a7456431e17c2c12757185083c20972e992b`,
34,699,768 B) from compat binary sha256
`232f04bbd7af57ffaed59e0a73c10de5c4f80c4bc2105ff34023c0f6bed3c9f6`;
guard + strict 2400-frame smoke passed (`FULLY_STATIC`). This artifact also
carries the menu rename and the Assist speed row.

**Commit.** `gbarecompx` `8b68302`; game pin in this change.

## 2026-10-19 — v2.0 release cut

**Tag.** `v2.0` = `8a34783` on `main`, annotated `FFTARecomp v2.0`;
release live at https://github.com/james2doyle/ffta-recomp/releases/tag/v2.0
(draft shell created by the tag workflow, assets built/uploaded locally).

**Gate.** `tools/cycle.py` (63,134 units, dispatch aligned, attract
`1EF4C118…`) then `tools/check.py` **17/17 PASS** on release prep `3810b99`.
The tag moved only over non-binary release-tooling fixes (`c7b6bf9`
workflow repo context; `8a34783` publisher zip-mode preservation), checked
with actionlint/verifier runs; the merged PR's CI was green.

**Artifacts** (SHA-256; `SHA256SUMS-v2.0.txt` uploaded):

- `FFTARecomp-v2.0-linux-x64.zip` —
  `fdfee8c7cd572f66825520e68be178428a6d002e348702970593857562cef24a`
- `FFTARecomp-v2.0-linux-x86_64.AppImage` —
  `25bae8617091369c4a7e58465964d86808fdd998dfc9a43c1a039c0c5d41eb03`
  (34,699,768 B; compat binary
  `232f04bbd7af57ffaed59e0a73c10de5c4f80c4bc2105ff34023c0f6bed3c9f6`)
- `FFTARecomp-v2.0-windows-x64.zip` —
  `bef4b57935d49ae25005a85c56165adf29c2fb6fc46b6aca5482f36b535e639e`
- `FFTARecomp-v2.0-android-arm64-v8a.apk` —
  `09858a46c2ae5a5e1cd2c24f24784403e87b2f5569f6709ac9f52c23d940c245`
  (`versionCode=2`, `versionName=2.0`; debug-signed)

**Release-tool fixes found by the cut.** The tag workflow ran without a
checkout, so `gh release view/create` had no repo context; `GH_REPO` now
fixes both draft creation and dispatch recovery. The publisher's
`zipfile.extractall` dropped Unix mode bits, making valid Linux/Windows
zips look executable-less to `sweep_stage`; `--upload-only` now restores
each entry's archived mode before the sweep. The artifacts themselves were
already correct (`zipinfo` showed `-rwxr-xr-x`).

**Notes.** No ROM or retail BIOS material uploaded; APK remains debug-signed
and is the open release-signing decision.

## 2026-10-20 — controller Y opens the settings overlay

**Change.** Guide (the pad's menu/home button) was the only controller
path into the settings overlay: both backends held the CONFIGURED
`HK_MENU` key while it was down (`raylib_backend.cpp` — Android
`kPadGuide`, desktop GLFW `kGlfwBtnGuide`). Y now opens it too on every
platform through the shared predicate `pad_opens_menu(guide_down,
y_down)` (`input_translate.h`), called from both paths. Y has no GBA
meaning on either map (`kPadMap` gba_bit 0), so no game input is taken;
the existing hotkey edge still gives press-open / press-close.

**Why.** Pads without a usable GUIDE/home button — or whose guide the OS
reserves — otherwise had no controller menu path. Y is the free face
button on the standard layout; the pad's Back button stays GBA Select,
and the Android system Back gesture is untouched.

**Verification.** `input_translate_tests` + `android_gamepad_tests` PASS
(Guide-only, Y-only, both, neither). Cold `tools/cycle.py` PASS —
63,134 units, dispatch aligned, attract `1EF4C118…` unchanged (the
trigger is inert without a held button). `tools/check.py` **17/17
PASS**. Android `assembleDebug` (arm64-v8a) compiles the `__ANDROID__`
path; clean repackage passes `tools/android_apk_check.py --expect public`
(8/8, 32.7 MiB).

**Docs.** Root README controls table/prose, `docs/fast-forward.md`,
`android/README.md`, the repo status block above, the framework README,
and `reference/dev-gotchas.md` (Generic.kcm also maps `BUTTON_Y→SPACE`;
Guide/Y are intentional menu triggers — any other button reaching the
menu is the fallback bug).

**Commit.** `gbarecompx` `fce1781`; game pin + docs in this change.

## 2026-10-20 — issue #30 haptics: phone sink + primary routing (Phases 1+3)

**Scope.** The user selected the ungated engine work only: Phase 1 (Android
phone-vibrator sink) and Phase 3 (primary-modality routing + stable API).
Phase 2 (glue device-id capture), Phase 4 (battle-damage hook), and Phase 5
(settings) remain deferred.

**Phase 0 evidence.** `game.state1` loaded over TCP `savestate_load` is a live
battle (load frame 25283; `[0x0200F4A8] = 0x0200F4E8`). A confirmed Fight
attack fired `0x080A2210` twice: f25545 `r0=0x020034EC r1=79
lr=0x080A3167`; f25546 `r0=0x020030CC r1=96 lr=0x080A3167`; gate
`0x0200F4E8` both. Disasm: the helper sign-extends `r1` and subtracts it from
`[unit+0x18]` (`strh r5,[r6,#0x18]` @0x080A2298), clamping to `[0,maxHP]`;
heals therefore arrive negative (disasm-verified, not live-probed). The
HP↔MP swap call site `bl 0x080A2210` @0x080A337E (LR `0x080A3383`) passes
`curHP-curMP` and must be excluded from damage haptics.

**Change.** Engine-only, host-side:
- `mobile_platform.{h,cpp}`: `android_haptics_pulse(ms, strength)` — JNI to
  `GbaGameActivity.vibrate(IF)V`, attaching the game thread only when needed,
  caching the method id, and clearing/logging the first JNI exception.
- `GbaGameActivity.java`: `vibrate` uses `VibratorManager` on API 31+,
  amplitude control when present, and media/game attributes (API 33+
  `VibrationAttributes.USAGE_MEDIA`, API 26-32 `AudioAttributes.USAGE_GAME`)
  so OEM touch-haptics settings cannot drop the pulse.
- `raylib_backend.cpp`: Android `haptic_pulse()` routes to the platform sink
  (raylib's `SetGamepadVibration` is a stub there); `Caps::haptics` is true on
  Android. `Input::controller_is_primary()` tracks per-pump touch/pad stamps
  (pad wins only when strictly newer; desktop returns false, keeping its
  historical pad-motor behavior). `host_primary_haptic()` routes to
  `gamepad_rumble` or `haptic_pulse`; `host_gamepad_supports_rumble()` is now
  defined in the raylib build (the latent link break).
- Tests: `pad_is_primary` pure cases in `input_translate_test.cpp`; new
  `primary_haptic_test.cpp` fake-backend routing (stub build skips loudly);
  closed-window fallback in `host_window_closed_test.cpp`.

**Verification.** Framework tests PASS in both configs (`input_translate`,
`host_window_closed`, `primary_haptic`; the stub `primary_haptic` SKIPs, the
raylib build PASSes). Cold `tools/cycle.py` PASS — 63,134 units, dispatch
aligned, attract `1EF4C118…` unchanged. `tools/check.py` **17/17 PASS**.
Private arm64 APK builds; `android_apk_check --expect private` 8/8 (38.5 MiB).
Compile traps fixed en route: NDK C++ JNI uses member calls
(`env->GetObjectClass`), and `GetAndroidApp` needs the glue header for
`struct android_app`.

**Limits.** Controller-primary haptics are silent on Android until Phase 2:
`Input::rumble()` still reaches raylib's Android stub. The battle-damage hook
and settings are not wired. Device verification: the attached phone's FF pill
pulses the platform vibrator (user-confirmed 2026-10-20; the pill's existing
`host_haptic_pulse(15, 0.5)` is the first real consumer). No rumble-capable
controller was attached, so the controller-primary path remains unexercised.

**Docs.** `gbarecompx/docs/HAPTICS.md` documents the feature as **fork-only**
(absent from upstream gbarecomp): API, Android API-level/attribute choices,
primary-modality rules, verification, and the deferred controller/damage/
settings scope. The framework README, `gbarecompx/AGENTS.md`, and this
repo's `android/README.md` (which links the page) mark it the same way.
## 2026-10-20 — issue #30 Phase 4: enemy-hit haptics — root cause + popup-synced release

**Report.** "Haptics not working when an enemy gets hit": the user's Air
Render test (device slot 4) landed hits (with occasional misses) but no
haptic and no diagnostics ever fired.

**Root cause (two HP paths).** Instrumented builds proved the hook plumbing
live (enabled, guard reached: synthetic dispatch census) while landed hits
logged nothing. Per-attempt EWRAM diffs located the unit HP field
(gBattleEnemyUnits+0x8; observed drops 61→10/61→9) and ruled the silent
attempts in as misses. `GBARECOMP_ABORT_ON_MEM_WRITE_ADDR` on a landed
desktop hit trapped the writer:

    pc=0x080A3250  strh r1,[r2,#0x1C]   r2 = unit, r1 = clamped new hp

The enemy-unit apply path computes the final HP and stores it directly
(hp@unit+0x1C, max@unit+0x1E; block at 0x080A3240-0x080A3252) — it never
calls the 0x080A2210 delta helper our hook watched (hp@+0x18 layout). The
helper covers the melee/fight family (state5); enemy-targeted ability
damage uses the direct store. Hence: hits with zero hook entries.

**Fix (commit scope).**
- Second damage seam: `[[mod_function_hook]] 0x080A3250` +
  `haptics_hp_store_hook` (delta = old−new at entry; same gate/coalescing).
- Release rework: the pulse no longer uses a fixed 22-frame delay (calibrated
  on the fast state5 melee; Air Render's store→number gap measured at ~240
  frames — the user heard "too early"). New release trigger:
  `[[mod_function_hook]] 0x080A8BF8` — the damage-number popup spawn
  (display-element initializer; split root, both parents tail-call/dispatch
  into it). An armed pulse releases on the popup + 1 frame, for any animation
  length; a 900-frame grace deadline releases late rather than never.
- Stale-state hardening (first device test fired ~1 frame after the apply:
  the release-check line exposed `popup=7935` at `f=7791` — a popup frame
  from the PREVIOUS attempt). Two layers: (a) the frame policy clears the
  haptics pipeline whenever `ExtendedViewFrameInfo::state_epoch` changes
  (every savestate load bumps it; the mods reset callback does not run on
  TCP loads), and (b) the arm-time popup heuristic rejects "future"
  timestamps (`lp <= now`). A two-load regression (load → full action →
  reload → action) releases each pulse at its own popup with `popup=0` in
  the second release-check — locked in BRINGUP evidence, no CI test shape
  yet (needs the two-load harness; candidate for `check.py` later).
- Verified desktop: state5 `popup value=22 kind=0` → PULSE at popup+1;
  slot4 `popup value=50 kind=1` → PULSE at popup+1. Unit tests rewritten for
  the popup-synced state machine.
- A "rapier attack" with no buzz was a miss — correct: no HP change, no
  pulse (the user confirmed the miss).

**Evidence.** Cold `tools/cycle.py` PASS (63,134 units; attract
`1EF4C118…` unchanged); `tools/check.py` 17/17 PASS. Device (fixed build):
`active=4`; landed hits log `entry-store → damage → popup value=NN kind=1 →
PULSE fire → haptics-sink ms=120` with the release one frame after the
popup; misses log `popup value=0 kind=21` with no arm and are silent.
Sink lines 23:54:17 (0.90) / 23:54:51 (0.89). Two-load regression: second
run's release-check shows `popup=0` (epoch reset) and releases at its own
popup. Field note: popup kind 0 = player-array number, kind 1 = enemy-array
number, kind 21 = the miss text.

**Cleanup.** The TEMP boot self-test and the framework `[mod-guard]` census
were stripped after the investigation; the feature keeps its bounded
seams censuses (entry/entry-store/damage/popup/PULSE, ≤64 lines/session).

## 2026-10-21 — CI red on the haptics pin: key census guard + missing test double

**Report.** The tier-1 CI run for `37cf1fb` (issue #30 Phase 4 haptics)
failed its `raylib-backend` job; the gbarecompx fork's own CI at
`2c816e5` failed three of four jobs (stub, raylib-ON, rlsw headless).

**Root cause — two build breaks carried in by the pin bumps; the haptic
feature logic itself was not at fault.**
1. `2cee21f` added the bounded desktop key census (`key_census_key`) but
   left the definition unguarded while its only caller sits inside
   `#if defined(GBARECOMP_USE_RAYLIB)` in `RaylibBackend::Input::read()`.
   The stub build has no `TraceLog`/`LOG_INFO` and only a forward-declared
   `RaylibApi`: `raylib_backend.cpp:1986` errors
   (`LOG_INFO was not declared`, `incomplete type RaylibApi`), failing
   the parent `raylib-compile` gate and the fork stub/rlsw jobs.
2. `cf5b866` added `Input::controller_is_primary` (haptics primary
   routing) without completing the `NoopInput` double in
   `tests/runtime/backend_v2_types_test.cpp` — every job that built the
   test target failed on the abstract type (`backend_v2_types_test.cpp:158`).

**Fix.** Fork `2e07e84` wraps `key_census_key` in
`#if defined(GBARECOMP_USE_RAYLIB)`; fork `2a8bffb` adds the missing
`controller_is_primary() const override { return false; }` (touch
default, matching `support/fake_backend.h`). Pin bumped to `2a8bffb`.

**Evidence.** Parent `tools/check.py --only raylib-compile` PASS
(backend compiles ON+OFF, raylib default still selected) and
`--only unit-cpp` PASS; fork stub build + `ctest` 89/89, fork
raylib-ON build + `ctest` 91/91 locally (Xvfb unavailable on the dev
host — the raylib job's display tier is the post-push CI signal).

## 2026-10-21 — guards for the CI-break classes (stub compile + test doubles)

**Gap.** The 37cf1fb pin carried two breaks that every local gate missed:
the raylib-only key census broke the `USE_RAYLIB=OFF` build (opt-in
`raylib-compile` only), and `NoopInput` went abstract (framework test
doubles compile only in the fork's own test target, which the consumer
never built). Same session, same pin bump — both need consumer-side gates.

**Guards.**
- **`stub-backend` (new, DEFAULT and `--fast`).** Builds the backend with
  `-DGBARECOMP_USE_RAYLIB=OFF` through a shared `build_stub_backend()`
  helper that `raylib-compile`'s OFF half now also calls, so the two
  callers cannot drift. No raylib fetch: configure + one TU, ~0.5 s
  warm. A stub-only compile break can no longer hide behind an opt-in.
- **Seam guard check 4 — test doubles.** `tools/check_raylib_backend_
  complete.py` now scans `gbarecompx/tests/runtime/**` for every class
  deriving directly from a seam interface and requires its full override
  set (the 2026-10-21 `NoopInput` class). It runs in the default
  `raylib-backend` suite and is a source-level consumer-side companion to
  the fork's compile check.
- **Normalization fixes the scan forced:** unnamed function-pointer
  parameters compare equal to named ones (`void (*)(HostOverlay*)` ==
  `void (*overlay)(HostOverlay*)`), and `gbarecomp::`-qualified parameter
  types compare equal to bare ones (`SpyBackend` writes
  `const gbarecomp::OpenParams&`). Both self-tested.
- **CI.** The `raylib-backend` job now runs
  `tools/check.py --only raylib-compile,raylib-backend`, so the test-double
  scan also gates every push.

**Evidence.** Guard self-test PASS (23 cases; new cases: complete double,
abstract-double regression, const drift, unnamed function-pointer,
namespace-qualified type). Guard: 15 doubles / 138 interface methods.
Negative control: deleting `controller_is_primary` from a scratch copy of
`backend_v2_types_test.cpp` fails with
`DOUBLE: test double NoopInput (backend_v2_types_test.cpp) has no override
for Input::controller_is_primary()`; restored tree passes. Gates:
`check.py --only raylib-backend,stub-backend,unit-py` 3/3 PASS,
`--only raylib-compile` PASS (ON+OFF), `--fast` 8/8 PASS (attract
`1EF4C118…` unchanged).

## 2026-10-22 — Totema-summon haptics: grace deadline shorter than the animation

**Report.** "Haptics on damage works, but it didn't work during the totem
attack." A Totema-summon run logged the whole pipeline, but the buzz did not
land with the damage numbers.

**Evidence (user run).** The first hit armed at f=25792
(`entry delta=72 lr=0x080A3167`, strength 0.74, grace 26692). The remaining
Totema hits (the `entry-store` 35→0 and the helper hits 101/104/88/93) all
logged `(coalesced)`. `release-check f=25793 arm=25792 grace=26692 popup=0`,
then `PULSE fire f=26692 strength=0.74 ms=120 (grace)`. The damage-number
popups printed only after that (`popup value=72 kind=0 armed=0`, then 77/1,
101/0, 104/0, 88/0, 93/0). So the popup hook was live and would have synced;
the 900-frame deadline expired first. The first hit's 0.74 strength also won
over later 1.00 hits.

**Scope check.** The Totema hits all reached the existing two seams
(`0x080A2210` helper and `0x080A3250` store). The third direct HP store found
at `0x080A41FE` was investigated as a candidate but is **not** on this run's
path; no third hook was added.

**Fix (host-only, `src/`).**
- `kHapticsFireGraceFrames` 900 → 2400 (40 s at 60 Hz) so long summon
  animations still release on their popup. 900 was calibrated for Air Render
  (~240 frames) and was shorter than the Totema gap.
- Coalesced hits now keep the strongest strength via
  `haptic_merge_strength()`; a multi-target burst no longer under-drives the
  pulse from its first, weakest hit.
- The popup census now logs the guest frame (`popup f=...`) so a future
  long-animation gap is measurable.

**Evidence (gates).** `ffta_unit_tests` PASS (new long-animation case stays
armed past the old 900-frame window and releases on the popup; the 2400-frame
grace still fires; max-strength merge). Cold `tools/cycle.py` PASS — 63,134
units, dispatch aligned, attract `1EF4C118…` unchanged. `tools/check.py`
18/18 PASS (unit-cpp, attract, ws smoke, routes B/G/K + user_load
FULLY_STATIC, desktop-accept, hle-audit). No `game.toml` / `symbols` change.

**Device follow-up.** Rerun a Totema on the phone: the new
`popup f=<frame>` line should land before the 2400-frame grace, and the buzz
should coincide with the numbers.

## 2026-10-22 (later) — Totema haptics: one pulse per damage label

**Report.** After the 2400-frame grace fix, the device run buzzed only on the
first Totema damage label. Device log: popup 84 at f=31725 (arm 30389, gap
1336) → `PULSE fire f=31726 strength=1.00`; then popups 88 (kind 1), 89, 100,
99, 87 at f=31756…31908 all logged `armed=0`, so the later labels were silent.
The user chose per-label haptics.

**Policy (user-selected).** Every damage number gets its own short pulse,
rate-limited to ~120 ms (8 guest frames) so rapid multi-hits on one target
still collapse. The popup element carries only the displayed number, so the
popup strength uses a 100-damage reference
(`0.35 + 0.65 * min(value/100, 1)`); the HP-apply strength remains the
no-popup grace fallback.

**Implementation (`src/`).**
- `ffta_haptics.h`: `haptic_popup_strength()` + `kHapticsPopupPulseGapFrames`
  (8) and `kHapticsPopupReferenceDamage` (100).
- `ffta_haptics_hook.h`: the two damage seams record `last_damage_frame()` on
  every qualifying apply (including coalesced ones). The popup hook accepts
  only kinds 0/1 with a positive value (kind 21 = miss, negative = heal),
  requires a damage apply within the grace window, rate-limits via
  `last_popup_pulse_frame()`, fires `host_primary_haptic()` immediately, and
  disarms the grace fallback. `haptics_reset()` clears the new state.
- Diagnostics: `popup ... fire=0/1` plus one `PULSE fire ... (popup)` line per
  fired number (bounded by the existing 64-line budget).

**Evidence.** `ffta_unit_tests` PASS (popup strength 50/84/100/200, reset
clears authorization; existing long-animation/grace/merge cases). Cold
`tools/cycle.py` PASS — 63,134 units, attract `1EF4C118…` unchanged.
`tools/check.py` 18/18 PASS. No `game.toml` / `symbols` change.

**Device verified (2026-10-22, APK `…-10-g3ee7643`).** State1 loaded on the
Mi 11 (battle ptr `0x0200F4E8`, Montblanc's turn, JP 10); the Totema produced
six per-label pulses: f=28414 0.88 (82), 28445 0.84 (76), 28483 0.98 (97),
28520 0.92 (88), 28559 0.94 (91), 28596 0.93 (90), each with a matching
`haptics-sink` line in logcat. The kind-26 zero popup stayed silent
(`fire=0`); two later single hits each fired one pulse. User: "works
perfectly."

**Playtest harvest.** The device miss frag held two genuine entries, now
seeded with disassembly notes: `0x080D9350` (switch over u16 mode
0/1/0x100/0x101, bridged x1) and `0x08132474` (r1=5 veneer, same shape as the
seeded `0x08132450`, bridged x3); `symbols/ffta_symbols.tsv` updated in the
same session. Cold `tools/cycle.py` now emits **63,156** units (+22 from
discovery), attract `1EF4C118…` unchanged; `tools/check.py` **18/18 PASS**.

## 2026-10-22 — v2.1 release cut

**Version.** Android `versionCode` 2 → 3, `versionName` "2.0" → "2.1".
Tag `v2.1`; the four public ROM-less artifacts are built and verified locally
with `tools/publish_release.py` (Linux zip, public APK, static Windows zip,
Steam Deck AppImage from the pinned Debian 12 compat binary) plus
`SHA256SUMS-v2.1.txt`. No ROM or retail BIOS bytes leave this machine.

**Contents since v2.0.** Android battle haptics (issue #30 Phases 1/3/4):
phone vibrator sink, primary-modality routing, two damage seams with
popup-synced release, per-label pulses (8-frame rate limit), and a 2400-frame
grace for long summons. Device-verified on the Mi 11 with a Totema (six
labels → six pulses, strengths 0.88/0.84/0.98/0.92/0.94/0.93). Also the
controller-Y settings shortcut, key-isolation tests, the CI test-double
guard, 63,156 emitted units, and the two Totema-session coverage seeds.

**Gates.** `tools/cycle.py` PASS (63,156 units; attract `1EF4C118…`
unchanged); `tools/check.py` 18/18 PASS; device log evidence in
`/tmp/ffta_device_perlabel.log` and the miss harvest in
`logs/device_totema_misses.frag`.

**Artifacts.** Names are `FFTARecomp-v2.1-{linux-x64.zip, linux-x86_64.AppImage,
windows-x64.zip, android-arm64-v8a.apk}`; SHA-256 values are in
`release-stage/SHA256SUMS-v2.1.txt` and the published release body.
