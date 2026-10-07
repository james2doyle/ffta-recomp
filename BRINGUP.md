# BRINGUP.md — FFTA Recomp bring-up log

Decision log for the static recompilation of Final Fantasy Tactics Advance (US)
to native PC via [mstan/gbarecomp](https://github.com/mstan/gbarecomp).
Ground rules live in `ffta-bootstrap-prompt.md` (§Ground rules) and `AGENTS.md`.

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
  resolve); upstream note on the bridge stop-contract runaway (crashes
  #1/#2). Sessions 1–5 and their batches are logged below.

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
license → reference/quote only; clone /tmp/FFTA_Engine_Hacks; derived
address indexes /tmp/ffta_repo_{org_sites,literal_refs}.tsv — re-clone if
wiped). It is effectively an **address→description index**: 576
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
WarioWareTwistedRecomp (shallow clones in /tmp/refrepos/ — re-clone if
wiped), engine checkout at gbarecomp/platform/android/.

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

### Session 6 hang (2026-10-06, user report "still got a hang"): reproduced + root-caused to a nestable-VBlank × non-reentrant-SoundMain race — TIMING bug, not coverage
- **User report**: interactive playthrough froze; the user pinned the repro
  himself: load `game.state2` (the post-native-save savestate, frame
  115,148), press A (guest frame 115,302) → hang.
- **Reproduction (deterministic)**: headless `--load-state game.state2` +
  `GBARECOMP_INPUT_REPLAY=logs/playthrough.csv` + `--frames N`: for any
  N ≥ ~1200 the run NEVER exits (timeout kill; the guest wedges inside ONE
  never-returning dispatch — a budget-1200 run ran its vblank counter to
  1439+ past its own budget without the runner loop ever iterating again).
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
