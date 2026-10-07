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

User recovered the old DataCrystal FFTA wiki pages (Wayback 2021-06-14) to
`/tmp/datacrystal-ffta`; text extractions committed under
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
