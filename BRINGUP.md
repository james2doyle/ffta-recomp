# BRINGUP.md — FFTA Recomp bring-up log

Decision log for the static recompilation of Final Fantasy Tactics Advance (US)
to native PC via [mstan/gbarecomp](https://github.com/mstan/gbarecomp).
Ground rules live in `ffta-bootstrap-prompt.md` (§Ground rules) and `CLAUDE.md`.

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
