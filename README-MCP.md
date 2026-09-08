# SuperAstra MCP adapter

This branch adds an **MCP stdio server** over SuperAstra's existing toolbox so an MCP host such as Codex can drive BizHawk directly. The original desktop/API agent remains intact.

## Architecture

```text
Codex / Astra (ChatGPT sign-in)
        |
        | MCP over stdio
        v
   mcp_server.py
        |
        | existing Toolbox API
        v
 astra_snes.toolbox
        |
        | authenticated file IPC
        v
    BizHawk + Lua
        |
        v
  running SNES game
```

No OpenAI API key is required by the MCP adapter. Model authentication and usage belong to the MCP host (for example Codex signed in with ChatGPT). SuperAstra itself only exposes local emulator tools.

## Windows setup

1. Install the normal SuperAstra/BizHawk prerequisites from the main README.
2. In this repository, create a virtual environment and install the MCP dependencies:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-mcp.txt
```

3. Open an SNES ROM in BizHawk.
4. In BizHawk, open **Tools -> Lua Console** and load `LOAD-IN-BIZHAWK.lua`.
5. Test the MCP server from this repository:

```powershell
.\.venv\Scripts\python.exe .\mcp_server.py
```

It should appear to sit silently waiting. That is correct: stdio is the MCP wire protocol, not an interactive terminal.

## Codex configuration

Configure Codex with a local stdio MCP server named `superastra` whose command is the virtual-environment Python executable and whose argument is the absolute path to `mcp_server.py`.

Equivalent `config.toml` shape:

```toml
[mcp_servers.superastra]
command = "C:\\absolute\\path\\to\\SuperAstra\\.venv\\Scripts\\python.exe"
args = ["C:\\absolute\\path\\to\\SuperAstra\\mcp_server.py"]
```

Restart/reload the Codex session after adding the server. The SuperAstra tools should then appear as MCP tools.

## What is exposed

The adapter exports the existing `TOOLS` definitions without inventing a second API. That currently includes context/screenshot inspection, WRAM and console-domain reads, ROM search/disassembly, memory scanning, observations, guarded writes, cartridge patches, checkpoints, temporary experiments, freezes, restricted Lua routines, retained per-ROM knowledge, undo, and the verified Super Mario World shortcuts.

`see_screen` and experiment screenshots are returned as actual MCP image content so a vision-capable host can inspect the emulator frame.

## Safety / correctness properties preserved

- The existing single-flight bridge remains in control of emulator operations.
- Existing session/ROM/epoch guards remain active.
- Mutations still use expected-value guards and SuperAstra's Undo/checkpoint machinery.
- A timed-out mutation is never automatically retried.
- The original ROM file is not modified by `patch_cartridge`; the overlay remains in the running emulator state.
- MCP argument JSON is validated against the same schemas advertised to the model before dispatch.

## Development status

This is the first MCP pass. It intentionally reuses SuperAstra's current toolbox rather than refactoring the emulator bridge. The next useful step is a live BizHawk smoke test from Codex, followed by tightening any tool-result formatting that Codex finds awkward in practice.
