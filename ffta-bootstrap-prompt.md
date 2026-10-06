# FFTA Recomp — Bootstrap Prompt

**Context.** This repo bootstraps a static recompilation of Final Fantasy Tactics Advance (GBA) to a native PC port using the mstan/gbarecomp framework. The ROM is at `game.gba` (repo root). Work autonomously through the phases below. A separate repo will later hold a matching decompilation — record facts here (entry point, m4a version, interrupt handlers, RAM map notes) so they can be reused there.

**Ground rules — never violate:**
1. Never guess. Every claim about the ROM (entry point, function boundaries, code vs data) must come from disassembly you actually ran, with the address cited. If you can't verify, say so.
2. The first divergence is the only one with a root cause. When recomp behavior differs from the emulator, debug the first divergence only — never downstream symptoms.
3. Never edit anything in `generated/`. All curation happens in `game.toml` and `src/`.
4. Every `game.toml` entry needs disassembly evidence: where the function starts and how you know (push roots, `bx lr` leaves, literal-pool boundaries, cross-references).
5. Log every decision in `BRINGUP.md` (date, action, result, conclusion). Commit after every milestone.
6. If a step fails inexplicably 3 times, stop, write up the state in `BRINGUP.md`, and report — don't thrash.
7. If gbarecomp ships a bring-up guide, it supersedes this prompt wherever they conflict.

**Phase 0 — ROM recon (report findings before proceeding):**
1. Confirm `game.gba` exists; record exact size (expect 16,777,216 bytes = 16 MiB; if different, stop and report).
2. Compute SHA-1 and MD5 (these pin `[identity]` later).
3. Read the cartridge header (0xA0–0xBF): title, game code (expect AFXE/AFXJ/AFXP — record which), maker code, version; verify the header complement check. Report all values.
4. Disassemble from 0x08000000 (ARM). Entry is 0x08000000, normally a branch to the crt0 start (often 0x080000C0). Find the actual branch target — that's `entry_pc`. Cite the instruction.
5. Locate the m4a/MusicPlayer2000 sound driver and record its version/offset.
6. Note: FFTA is a standard cartridge — no RTC, gyro, or solar sensor. Save type to be determined empirically later.
7. Add `game.gba` to `.gitignore` (never commit the ROM). Write all findings to `BRINGUP.md`.

**Phase 1 — Framework setup:**
1. Read gbarecomp's README/docs completely before running anything. Learn: the recompiler CLI (binary name and flags), the exact `game.toml` schema, the coverage-report tool, and where miss logs are written. Reference layout: an existing game repo (e.g., DragonBallZLegacyOfGokuRecomp) uses `gbarecomp` + `recomp-ui` as pinned submodules, with `game.toml`, `src/`, `generated/` (gitignored), `mods/`, `inputs/`.
2. Add the submodules, pinned to the versions the docs recommend.
3. Build the framework tools per its docs.
4. Create `CLAUDE.md` containing: the ground rules, exact build/regenerate/run/test commands, current bring-up status, and the next milestone. Keep it current — it is the memory for future sessions.

**Phase 2 — `game.toml`:**
Create it using the schema you learned in Phase 1 (field names must match the framework's parser — do not invent fields). Expected shape, to verify:

```toml
[program]
id = "AFXE"                  # from the header you read
load_address = 0x08000000
size = 0x01000000            # 16 MiB
entry_pc = 0x080000C0        # verify against Phase 0 disassembly
aot_scan_start = 0x080000C0
aot_scan_end = 0x08010000    # initial static scan ~64KB; rest discovered at runtime
static_resume_all = true
codegen_shards = 32

[identity]
sha1 = "..."
md5 = "..."

[bios]
hle = false
```

If `hle = false` requires a BIOS dump, flag it to the user — do not download a BIOS.

**Phase 3 — First recompile, build, run:**
1. Run the recompiler to produce `generated/`.
2. CMake configure + build.
3. Run it. Expect failure or a black screen — that's normal. Capture the miss log and coverage report.

**Phase 4 — The audit loop (repeat until coverage = FULLY STATIC):**
For each miss:
1. Disassemble around the address: `arm-none-eabi-objdump -D -b binary -m armv4t --adjust-vma=0x08000000 game.gba` (or the framework's tooling). Determine whether it's code and where the function starts.
2. Find boundaries: push roots (`stmfd sp!, {..., lr}`), `bx lr` leaves, literal pools (a word that decodes as a plausible instruction but is actually an `ldr` pool entry — check what the `ldr` targets).
3. Add the entry to `game.toml` with a comment citing your evidence.
4. Regenerate → rebuild → rerun → re-check coverage.
5. Update `BRINGUP.md`.

Watch for: (a) data-as-code — jump tables inside functions; if a "function" contains a table of addresses into itself, mark the table as data; (b) ARM/Thumb confusion — check the LSB of branch targets and every `bx`/`blx`.

**Phase 5 — Validation harness (build early, use forever):**
1. Install mGBA; run `game.gba`; record attract-mode reference frames (video or frame dump).
2. Write a frame-diff script: run the recomp binary with a fixed input script for N frames, capture frames, diff against mGBA's. Deterministic inputs only — no manual play.
3. Milestones, in order, never skipping ahead until the current one is frame-stable: boots without crash → logo → attract demo matches → title screen → new game → first map → first battle.
4. Every `game.toml` change → regenerate → rerun the attract diff. It is the regression test.

**Known FFTA facts (use, don't re-derive):**
- 16 MiB ROM; codes AFXJ/AFXE/AFXP; Feb 2003; Square, ex-Quest staff.
- Audio: m4a/MusicPlayer2000 (Sappy) — the framework's runtime already models it.
- Simplest hardware profile in the framework's catalog: standard cartridge, all save types supported.
- Known hard spot: FFTA's scripting/VM system — game logic runs on an in-game interpreter. Expect a large function cluster there; audit carefully.
- Community references: Data Crystal wiki (ROM/RAM maps), LeonarthCG/FFTA_Engine_Hacks (ASM source — use it to name functions), FFHacktics forum.

**Definition of done for this session:**
- Repo contains: `game.toml` (identity-pinned), `AGENTS.md`, `BRINGUP.md`, pinned submodules, `src/` skeleton, `.gitignore` (ROM excluded), frame-diff script.
- The recomp binary builds and runs.
- `BRINGUP.md` records: entry point with evidence, first audit results, current coverage status, next milestone.
