# Validation

This is the v0.3.2 source release. The distinction between executed tests and
capabilities that still need broader testing matters for this project.

## Executed checks

**v0.3.2 UI checked in a virtual display:** the exact generated SUPERASTRA logo
loads through Tk's PNG decoder, the prompt supports editing, and the main window
and settings were rendered and inspected. Checked 920x920 and the minimum
800x840 layout. The numbered setup instructions are absent from the main UI.
The user reported the Windows Lua connection working before this visual update.


**Four launcher regression checks passed for v0.2.1**, covering BizHawk's
filename-free `main` chunk, an absolute Windows path containing spaces, a bare
filename, and missing extracted files. See `qa/launcher-tests.txt`. The host's
script-directory behavior was checked against BizHawk 2.11.1 `LuaLibraries.cs`
and `LuaSandbox.cs`. These focused checks validate the launcher fix; they do not
replace the outstanding native end-to-end check below.

**48 automated tests passed for v0.3.2**, using Python 3.12 and an actual Lua runtime.
This includes the four launcher regressions described above.
The tests exercise the same Lua engine shipped with the add-on:

- Guarded writes, type/bounds validation, duplicate/expired requests, wrong ROM,
  session and epoch rejection, and interrupted-write rollback.
- Full-state Undo, checkpoint retention, freezes and conflicting holds.
- Generated one-shot and frame routines, retained state, failed assertions,
  instruction-budget exhaustion, restricted host capabilities and error shutdown.
- A generated routine on an unrecognized ROM identity, without any game profile.
- Memory scanning, unaligned multibyte values, scan invalidation and cartridge search.
- The actual JSON file transport connected to the Lua engine.
- The shipped BizHawk Lua adapter running against a contract fixture, including
  boot, ROM export, memory reads, a generated routine and Undo. This supplements
  but does not replace the blocked native-emulator check.
- Responses tool-loop handling with a simulated API transport, including preserved
  reasoning, cancellation and explicit reporting of partially executed turns.
- Persistent pause/resume across an agent restart, without replaying a mutation;
  bounded history retaining complete function-call/output pairs and the goal.
- Retrieval from a source file larger than the old excerpt limit, exact numbered
  lines, automatic tool evidence, working-context persistence and ROM isolation.
- Repeatable temporary experiments, cancellation, failed-source restoration,
  named checkpoint limits/cleanup, live checkpoint restoration and Undo.
- Cartridge expected-byte guards, partial-write failure rollback, layered ROM/core
  Undo, branch-only patches, and ROM-switch cleanup without cross-ROM writes.
- Hardware-domain reads with host-memory exclusion, checkpoint differences,
  and the Python toolbox connected to the actual Lua engine on an unknown ROM ID.
- The shipped BizHawk wrapper's new domain listing, cartridge patch, experiment,
  branch screenshot and restoration flow against its emulator-API contract fixture.

The complete test output is in `qa/automated-tests.txt`.

**Live game checks passed** using Snes9x 1.63 and the supplied SMW Ice Flower build
with SHA-1 `7265176858DD9E0C905D4DDC69060E173A23BADD`. The Lua command engine was
connected to real running SNES memory and real core save states through a test
adapter. These were not just simulated sprite tables:

- A spawned star initialized normally, fell, and was collected; the star timer
  became nonzero.
- Five Chucks initialized and remained active after 36 frames. The screenshot
  shows all five rendering in the test level.
- Undo restored the full pre-command WRAM after the game advanced.
- A newly supplied conditional Lua routine granted a cape when the coin counter
  increased. The counter increase was injected as a test input, rather than
  claimed as a physical coin pickup.
- Two 30-frame experiments from the same checkpoint produced identical sampled
  powerup/position values. Each temporary one-shot alteration returned to the
  exact pre-experiment WRAM and adapter frame. The branch screen was captured
  before restoring the live state; see `qa/experiment-branch.png`.

See `qa/live-results.json`, `qa/star-spawn.png`, `qa/five-chucks.png` and
`qa/new-routine.png`. `tests/live_smw.py` can repeat these checks with a supplied
compatible core, ROM and level-start save state. It needs the optional test
dependencies `lupa`, `numpy` and `Pillow`. Those binaries and ROM data are not
included in this release.

**Desktop UI checks passed** in a virtual X display: the main window, connection
settings, controls and status/footer layout were rendered and inspected.
See `qa/desktop.png`.

## What these checks do not establish

- Native BizHawk 2.11.1 was launched for an integration check, but its startup
  IPC input thread could not create a named pipe in this environment
  (`System.Net.Sockets.SocketException: Access denied`). The emulator exited
  before the Lua bridge connected. **The native BizHawk adapter therefore still
  needs an end-to-end run on an ordinary desktop.** The live Snes9x checks above
  used the test adapter; they do not establish native BizHawk integration.
- A live OpenAI API request was not made because this build environment had no
  OpenAI API key. The shipped Astra client uses the documented Responses API;
  its call sequencing was tested with a simulated provider. Real model quality,
  API access and paid end-to-end prompting still need testing with your key.
- No claim is made that all games, regional versions, ROM hacks, coprocessors or
  requested alterations have been validated. The general tools permit
  investigation; they do not prove universal success.
- The real-game test ROM was the specific SMW derivative above. The unmodified
  USA shortcut layout was checked against SMW disassembly and ROM identification
  data, but that separate ROM image was not available for an independent run.
- Frame callbacks, screenshot capture, native disassembly and bus-write tracing
  vary with the selected BizHawk core. Unsupported operations report errors.
- Loaded-cartridge patching and rollback passed engine and BizHawk-contract tests.
  The Snes9x live test adapter does not expose writable cartridge memory, so those
  checks do not establish execution of patched code in a native emulator.
- The Lua execution environment limits capabilities, instructions, staged writes
  and retained state. It is not a separate process or an OS-enforced memory
  sandbox; generated routines should remain small.

For an unfamiliar game, first verify a simple bounded change and Undo, then let
Astra investigate a more complex request. Mark notebook findings as verified
only when supported by actual game behavior.
