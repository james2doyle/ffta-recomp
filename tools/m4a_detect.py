#!/usr/bin/env python3
"""Detect the m4a/MusicPlayer2000 (Sappy) engine in a GBA ROM.

Faithful port of Bregalad/loveemu's sappy_detector.c (2012-2015) logic:
find m4a SongMainComponent / SelectSong pattern, validate the song table
it points to, then locate the engine header 16 or 32 bytes before m4a main
and decode its parameters (volume, channels, DAC, rate, song table addr).
"""
import sys

ROM = "game.gba"

SELECTSONG_PATTERNS = [
    bytes.fromhex("00b500 04074a0849400b401883885900c918890089180a680168101c00f0"),
    bytes.fromhex("00b500 04074b0849400b40188288510089188900c9180a680168101c00f0"),
]


def is_gba_rom_address(a: int) -> bool:
    region = (a >> 24) & 0xFE
    return region in (8, 9)


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else ROM
    rom = open(path, "rb").read()
    size = len(rom)

    candidates = []
    for pat in SELECTSONG_PATTERNS:
        i = 0
        while True:
            j = rom.find(pat, i)
            if j < 0:
                break
            candidates.append(j)
            i = j + 1
    print(f"selectsong pattern candidates: {[hex(c) for c in candidates]}")

    selectsong = None
    for off in candidates:
        songtable_addr = int.from_bytes(rom[off + 40 : off + 44], "little")
        print(f"  candidate {hex(off)}: songtable@{hex(songtable_addr)}", end=" ")
        if not is_gba_rom_address(songtable_addr):
            print("not a ROM address")
            continue
        tbl = songtable_addr & 0x01FFFFFF
        if tbl + 8 > size:
            print("out of range")
            continue
        valid = 0
        idx = 0
        while valid < 1 and tbl + idx * 8 + 4 <= size:
            songaddr = int.from_bytes(rom[tbl + idx * 8 : tbl + idx * 8 + 4], "little")
            idx += 1
            if songaddr == 0:
                continue
            if not is_gba_rom_address(songaddr) or (songaddr & 0x01FFFFFF) + 4 > size:
                break
            valid += 1
        if valid < 1:
            print("song table invalid")
            continue
        print("VALID")
        selectsong = off
        break

    if selectsong is None:
        print("No sound engine found (no valid selectsong block).")
        return

    main_off = selectsong
    while main_off > 0 and main_off > selectsong - 0x20:
        if rom[main_off : main_off + 2] == b"\x00\xb5":
            break
        main_off -= 1

    for back in (16, 32):
        o = main_off - back
        if o < 0:
            continue
        data = [int.from_bytes(rom[o + i * 4 : o + i * 4 + 4], "little") for i in range(4)]
        main_vol = data[0] & 0x7F
        polyphony = (data[0] >> 8) & 0xF
        dac_bits = 17 - ((data[0] >> 12) & 0xF)
        sri = (data[0] >> 24) & 0xF
        song_tbl = (data[2] & 0x3FFFFFF) + 12 * data[1]
        ok = (
            main_vol != 0
            and polyphony <= 12
            and 6 <= dac_bits <= 9
            and 1 <= sri <= 12
            and song_tbl < size
            and data[1] < 256
            and (data[0] & 0xFF000000) == 0
        )
        print(f"engine header cand @{hex(o)} (main-{back}): vol={main_vol} poly={polyphony} dac={dac_bits}bits sri={sri} song_tbl={hex(song_tbl)} -> {'VALID' if ok else 'invalid'}")
        if ok:
            print(f"\nM4A ENGINE FOUND: header at file offset {hex(o)} = ROM address {hex(0x08000000 + o)}")
            print(f"  selectsong/m4a main at {hex(0x08000000 + selectsong)}")
            print(f"  song table at {hex(song_tbl)} ({hex(0x08000000 + song_tbl) if song_tbl < size else '?'})")
            print(f"  # song levels: {data[1]}")
            return
    print("Only a partial sound engine was found.")


if __name__ == "__main__":
    main()
