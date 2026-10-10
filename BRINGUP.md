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
