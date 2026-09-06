# v0.3.2 — GitHub preparation

Shortened the tagline to "Change the game." Refreshed the README and desktop
screenshot, added contributor instructions and a clean release builder, pinned
the optional Lua test dependency, and expanded Git ignore and line-ending rules.

# v0.3.1 — Header credit and tagline

Changed the tagline to "Change the game while you play." Added "Magic by"
above the official Spellbook logo in the top-right corner, with Settings below.
The bundled PNG is rendered from the SVG used on spellbook.com, preserving its
colors and proportions. Checked both supported window sizes.

# v0.3 — SUPERASTRA RPG interface

New SUPERASTRA logo integrated into the desktop header, blue RPG dialogue windows,
silver borders, lavender menu buttons, gold prompt action, and a compact side menu.
Removed the numbered setup instructions and long introductory text from the main
screen. Instructions remain in README.md. Existing controls are available in the
new layout; Cast prompt sends a request and Resume continues an investigation.

The generated logo is bundled under assets/superastra-logo.png. The desktop loads
it using Tk's PNG decoder, so no additional Python packages are required. Checked
the actual rendered app at its default and minimum sizes, the settings dialog,
logo loading, and prompt editing. This is a presentation update to the working
bridge and agent. User reported successful connection before this UI update.

# v0.2.1 — Windows Lua launcher fix

Fix folder detection when BizHawk loads the entry script as a chunk named `main`.
Use BizHawk's script working directory when Lua supplies no filename. Preserve
absolute Windows paths, including spaces, and explain missing extracted files.
Added four regression tests for the reported launch failure and path variants.

# v0.2 — Game context and live investigation

This update addresses unfamiliar games and requests that need investigation.

- Retain the goal, working understanding, hypotheses, next steps and success
  criteria per exact ROM, with automatic tool evidence and resumable API history.
- Search larger imported disassemblies and memory maps; retrieve exact source lines.
- Inspect exposed video, palette, object, audio and cartridge RAM domains.
- Save named checkpoints, compare WRAM changes, and run controlled temporary
  experiments that restore the player's pre-experiment state and effects.
- Patch code/data in the loaded cartridge with exact-byte guards and an independent
  rollback journal. The original ROM file is unchanged.
- Add Continue investigation, View game knowledge and a configurable step budget.
- Return restoration epochs atomically to avoid a stale-heartbeat race after Undo.

Validation: 44 automated tests and live SMW behavior/experiment checks passed.
Native BizHawk and live Astra prompting remain unverified in this environment.
See VALIDATION.md for the distinction between live, contract and simulated checks.

# v0.1 — Initial prototype

File-based BizHawk bridge, Astra tool loop, WRAM scans/patches/freezes, generated
Lua routines, basic ROM indexing and notebook, Undo, and optional SMW shortcuts.
