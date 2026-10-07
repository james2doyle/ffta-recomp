# Miss triage: from a PC to a config entry

Load this when a session or a strict replay produced miss PCs and you need to
convert them into reviewed config entries.

## Classify mechanically

For a batch of miss PCs: align to the entry mode (Thumb PCs are even), then
scan each PC for a containing function start. Script it — dozens of PCs per
session is normal. Classify into: exact start / interior of a known start /
no start found.

## Seed policy

- Most misses are **interiors** of one or two functions the walker already
  knows (or can find). Seed the containing start; it covers all of its
  switch cases and branches.
- A dense run of consecutive same-mode misses is almost always the
  **case targets of a computed-jump switch** inside one or two ordinary
  functions — not a data table. Seed the starts first. In practice expect
  **one to a few** adjacent functions (most runs resolve to 1–3); scan
  forward inside the run for further prologues before concluding the run
  is one function.
- An auto-generated proposal's "jump-table candidate" comment is a **hint,
  not a verdict**: classify by prologue scan first. Observed in practice,
  these runs are more often branch-target interiors of ordinary function(s)
  than real tables; heat counts (bridged x hundreds) mark hot in-function
  switch blocks. Size a table only once the dispatcher and its pool table
  are actually located.
- Prefer a sized **jump-table entry** only if a strict replay still misses
  interiors after seeding the start. To size one, find the dispatcher
  (`ldr rT,[pc,#..]; add rT,index<<2; ldr/mov pc`), then read off the table
  base, stride, count and address format from the compare bound and the
  table bytes. Watch for the table sitting inside a literal pool.
- If no start is found within a sane window (leaf functions can lack a
  classic push-root), **seed the PC itself.** Interior entry points are
  legal and honest — shared epilogue blocks reached by a forward branch and
  switch case bodies are common examples; inventing a boundary is not.
- RAM-resident (IWRAM-style) code: map the copied span so the decoder
  decodes it, and register runtime entry PCs inside the span separately.
  Derive the copy destination from live memory dumps and verify by byte
  matching against the image.
- Watch the instruction-set bit everywhere: branch targets, `bx`/`blx`
  operands, and every PC you seed. ARM/Thumb confusion produces garbage
  silently.
- Disassemble in narrow windows anchored on known boundaries; disassemblers
  often stop silently at the first undecodable halfword, so a "clean" long
  listing proves less than it looks.

## Containing-start scan (snippet)

Nearest push-root at or below a PC; if none, seed the PC itself. Tune the
root pattern to the architecture (Thumb shown; for ARM look for
`stmfd sp!, {..., lr}` equivalents).

```python
def thumb_push_root(img, addr):
    hw = img[addr] | (img[addr + 1] << 8)
    return 0xB400 <= hw <= 0xB5FF          # push {..} / push {.., lr}

def find_start(img, pc, max_back=0x300):
    for a in range(pc, max(pc - max_back, 0), -2):   # Thumb PCs are even
        if thumb_push_root(img, a):
            return a
    return None                            # caller: seed pc itself instead
```

Sanity-check the candidate: aligned push-root, plausible body, ends in
a return (`bx lr` / pop-and-return) or a literal pool followed by the next
function's prologue.

## Every entry carries its evidence

The note must let a reviewer re-derive the claim without trusting you:
the prologue instruction and address, what precedes it (previous function's
return, literal pool), how you know it is code, and the miss PC(s) it
covers.

## Batching

- Classify all PCs of a session mechanically into (start, interior, none).
- Merge the deduplicated union as one batch per session with a dated header
  comment; keep per-entry evidence short but exact. Dedupe against the
  config and all earlier batches, not just this session.
- After merging, the strict replay is the judge: it will surface any PC the
  live session never hit (input timing differs slightly). Expect 1–2 such
  resolve-added PCs per session; merge them into the same batch.
