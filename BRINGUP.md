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
