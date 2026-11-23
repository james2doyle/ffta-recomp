# Adding hacks and cheats

Two lanes. Pick by what the hack changes.

| Hack changes | Lane | Example |
|---|---|---|
| Battle/menu state in RAM | Runtime poke (`src/ffta_cheats.h`) | No Laws |
| ROM bytes (data tables, code) | Static patch (pre-recomp) + overlay | Maeson, Secret Starters |

Cheats are ROM-hash-independent; patches are not (see `game.toml` identity pin).
Hygiene: link to patches only, never commit patch/ROM bytes.

## 1. Runtime poke (start here)

1. Add the cheat to `src/ffta_cheats.h`: address constant, enable flag,
   `cheats_apply_*` writer loop. Keep it header-only pure logic (pattern:
   `src/ffta_speed_boost.h`, `src/ffta_haptics.h`) so `ffta_unit_tests`
   links it without SDL/ROM.
2. Register the default in `ffta_mod_reset` (`src/main.cpp`) via
   `ffta::cheats_reset()`.
3. Apply per frame in `ffta_ws_margin_policy` (`src/main.cpp`) — it rides
   the existing per-frame callback, no new seam (same as `haptics_frame_service`).
4. Add the overlay Toggle: append a section + `MenuRowKind::Toggle` row in
   `ffta_menu_rebuild` (`src/main.cpp`, via `RunOptions::menu_rebuild`), flip
   the flag in `ffta_menu_apply`. Framework seam:
   `gbarecompx/src/runtime/runtime.h` (`menu_rebuild`/`menu_apply`),
   chained in `gbarecompx/src/runtime/runtime.cpp` (`set_rebuild_hook` +
   apply lambda). Row labels are the contract between rebuild and apply.
5. Add the mod feature (default-off) in
   `mods/preloaded/packages/ffta.gameplay.cheats/1.0.0/manifest.toml`
   with a `ffta.<name>` activation plugin registered in `src/main.cpp`.

Reference implementation: No Laws zeroes `gBattleLaws` `0x02003C34` as 4x u16
stride-2 (covers CB `42003C34 0000 / 00000003 0002`). Law paths: count loop
`0x0802D764`, action check `0x08027640` (verify with
`gbarecompx/tools/disarm.py 0x0802D764 0x0802D7A0 thumb`).

## 2. Static patch (conversions)

Light data edits (Anarchy-style table zeroing) may self-heal through. Code or
layout moves need a per-hack `game.toml` overlay + regen + `resolve.py` to
`FULLY_STATIC`. The framework already has a verified patch surface:
`launcher_enable_rom_patches` (`gbarecompx/src/runtime/runtime.h`). Vanilla
gates (`tools/check.py`, attract golden) stay pinned; guard new routes as
fixtures per `tests/README.md`.

## 3. Verify

- `cmake --build build --target ffta_unit_tests && ctest --test-dir build -R ram_dispatch`
- `gbarecompx/tools/disarm.py` the touched routines; cite addresses.
- Live: `--tcp-observe` read/poke/advance on a battle fixture; `framediff.py`
  vs oracle for UI-only diffs.
- Record the decision in `BRINGUP.md` (dated entry).

## 4. Sources

- RAM map: `reference/ffta-gamefaqs-code-guides.md`, `symbols/ffta_data_symbols.tsv`
- Mod packages: `gbarecompx/docs/MOD_PACKAGES.md`
- Menu model: `gbarecompx/src/runtime/menu_model.h`, `host_menu.h:112-133`
- Issue scope: `BRINGUP.md` 2026-10-12 issue-22 entries.
