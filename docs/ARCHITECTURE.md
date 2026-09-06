# Architecture and extension points

The desktop app is a local Python/Tk interface. Its Astra client uses the Responses
API with named tools, preserved reasoning/tool outputs, optional web research,
an explicit investigation budget, and cancellation checks before game operations.
The same tools are usable from `run.py --prompt`.

## Open-ended game learning

`toolbox.py` supplies general read, scan, observation, experiment, disassembly,
cartridge search/patch, freeze and routine tools. `context.py` indexes the cartridge
locally and retains evidence in a notebook keyed by the exact ROM hash. UTF-8
source files and maps are indexed locally, with lexical search and exact numbered
line retrieval. Their text supplies evidence; importing it never executes it.

At the start of a prompt, the model receives the running game's identity, actual
state, header candidates, known findings and a screen capture if supported. It
can then investigate, create a new action, observe the result, undo a failed
attempt, and save the findings. A profile lookup is not required for this path.

The agent maintains five working-context fields: goal, understanding, hypotheses,
next steps and success criteria. Tool evidence is recorded automatically, with
bounded excerpts and session/epoch provenance. A notebook retains up to 1000
findings and 500 events; the latest few appear in the initial context, and the
rest can be searched. No result is automatically promoted to a verified fact.

The API loop preserves complete tool-call cycles and encrypted reasoning items.
It trims old complete cycles to a text budget around 140,000 characters and at
most 24 cycles, retaining the latest user goal. At most two recent tool screenshots
remain in the active tail; screenshots are removed from its disk representation.
The newest user/context cycle is retained even if it exceeds that text budget.
At a budget pause, cancellation or provider error, progress is saved for the next
request. A resumed turn refreshes the live game and sends previous tool outputs
as history; it never automatically replays their operations.

## Frame-boundary mutations

The Python app and BizHawk exchange JSON in `ipc/`. Requests carry a random token,
unique ID, expiration deadline, bridge session, ROM hash and state epoch. Python
serializes requests with a process lease and a thread lock. Lua validates them
before dispatching. It consumes requests once and rejects duplicates and stale
contexts. The protocol has no network listener.

`emulator/engine.lua` performs bounded byte writes between frames. All bytes and
guards are validated before patching. A core save state precedes each mutation;
failure restores it. The emulator's original save-state slots are not used.
Undo histories include previous active freezes and generated routines.

Save states cover core state, not input movie logs or the host UI. Loaded-cartridge
writes have a separate byte journal in `cartridge_patch.lua`, because save states
can omit ROM. Transactions and checkpoints capture that overlay, restore it after
core loads, and verify the restored bytes. A guarded patch can cover up to 4096
bytes across 16 segments; a session journals up to 64 KiB of distinct offsets.
Stopping all effects also removes the overlay. An external state load clears it;
a different ROM discards its journal without writing old bytes into the new game.
No file-system, CPU-register, VRAM or SRAM writes are exposed. A console-memory
allowlist excludes host/Waterbox pages and System Bus. Reads of a whole cartridge
stay local; the API receives only requested windows and search results.

## Controlled experiments

Up to four named checkpoints retain a full core state, cartridge overlay, active
effects and a 128 KiB WRAM baseline. `compare_checkpoint` computes differences
locally and returns counts by 4 KiB region plus up to 128 changed bytes. Narrowing
the range retrieves detail in a selected region.

`experiment` saves the live return state, loads a named checkpoint, applies
optional one-shot Lua and/or guarded cartridge segments, overrides controller
inputs, and advances 1–300 frames. The Lua loop captures branch observations,
WRAM differences and a screenshot at the end, then restores the original live
state and effects. API latency does not prolong the branch after its frame budget.
During a probe, other operations are restricted to status/result/cancel, or Undo
and Stop effects, which cancel it first. Closing the Lua script also attempts to
restore an active probe. A user-initiated external ROM/state load supersedes it.

Experiments share the visible emulator. They can interrupt gameplay and are not
an independent background simulation. Core-state restoration does not restore
host movie logs or audio already played. Named checkpoint restoration creates a
normal Undo, and the new state epoch is returned atomically with that result.

## New routines

`run_routine` accepts Lua source written during an Astra turn. A routine can run
once, for a specified number of frames, or until stopped. It uses a restricted
environment from `emulator/sandbox.lua`:

| Name | Behavior |
| --- | --- |
| `read(offset, width=1)` | Read 1–4 little-endian WRAM bytes; see staged writes |
| `write(offset, value, width=1)` | Stage WRAM bytes for commit after the routine succeeds |
| `rom(file_offset)` | Read one cartridge byte |
| `frame` | Current emulator frame counter |
| `state` | Small persistent plain-data table |
| `math` | floor, ceil, min, max, abs, sqrt |
| Basic Lua helpers | assert, error, ipairs, pairs, next, type, tonumber |

The execution limit is 50,000 Lua instructions per invocation, 512 distinct
written bytes, 20,000 source bytes, and 1,024 state nodes with depth at most eight.
No host references, file/network APIs, module loading, dynamic code loading,
debug API, metatables or protected-call escape are available to generated code.
Instruction-budget failure or a failed assertion discards staged writes. A later
failure disables a running routine and reports it in `last_routine_error`.

A routine's addresses are integer **WRAM offsets**, from `0x00000` through
`0x1FFFF`. The model-facing read/patch tools also accept hex SNES WRAM addresses
`7E0000` through `7FFFFF`. Cartridge offsets and CPU program addresses have separate
tools. Never treat them as interchangeable.

Example of a conditional routine, provided as syntax documentation rather than
a universal memory map:

```lua
-- These are placeholder offsets for a hypothetical game.
-- Replace them using observed structures in the actual cartridge.
if read(0x40) == 3 then
    local hp = read(0x812, 2)
    if hp > 0 and hp < 100 then write(0x812, 100, 2) end
end
```

## Emulator adapters

`emulator/bizhawk.lua` adapts the pure command engine to BizHawk's memory,
save-state, screenshot and debugger interfaces. Another emulator can implement
the same adapter contract. No emulator fork is necessary.

Disassembly and bus callbacks are core-dependent. Observation records bounded
samples across frames. Optional exact-address write callbacks also capture CPU
registers. A memory mirror is a distinct bus address: tracing `7E0019` will not
observe a CPU instruction that writes mirrored address `000019`.

The decoder uses the core's current mode flags. REP/SEP, PLP, interrupt entry,
alternate branch paths and coprocessor code need careful interpretation. Header
parsing offers candidates; it does not assume every cartridge is plain LoROM.

## Built-in Mario examples

`emulator/smw.lua` supplies verified-layout shortcuts. It allocates only free
ordinary sprite slots, clears their state, initializes the six tweaker tables,
sets world coordinates and marks them for the game's normal initialization
routine. It does not overwrite active slots or force an unsupported ROM to use
the SMW layout. Other games can use generated routines instead.

## Boundaries

There is no claim that a language model can immediately solve every alteration
for every SNES cartridge. This version provides concrete evidence-gathering and
execution tools so unfamiliar games can be investigated. It does not implement
a full autonomous decompiler, arbitrary coprocessor debugger, asset generation,
or an exportable ROM-patch system. ROM expansion, generated artwork, arbitrary
special-chip debugging and direct hardware-register writes require additional
capabilities. Loaded-cartridge editing is implemented and separately journaled;
native core support and generated patch semantics still need live validation.
