# SuperAstra: Codex-backed UI and MCP

This branch keeps Scott Stevenson's SuperAstra window and adds a backend selector:

| Backend | Where you type | Authentication / billing |
| --- | --- | --- |
| **CODEX / CHATGPT** (default) | SuperAstra's **YOUR COMMAND** box | Codex CLI's ChatGPT sign-in; your plan's Codex allowance and limits apply |
| **OPENAI API** | The same SuperAstra box | The original API-key backend; separately billed |
| **LOCAL SHORTCUTS** | The same SuperAstra box | No model call; only the original small set of offline shortcuts |

**You do not need to enter prompts in the Codex app or its terminal UI.** SuperAstra launches the installed Codex CLI in non-interactive mode, streams tool activity into **SESSION LOG**, and displays the answer there. A browser opens for initial ChatGPT sign-in.

```text
SuperAstra UI -> Codex CLI (exec --json; prompt on stdin)
             -> local stdio MCP -> existing Toolbox -> BizHawk / Lua -> SNES
```

The original `astra_snes/agent.py`, toolbox and emulator code remain unchanged. The new path does not call the OpenAI API directly and never automatically falls back to the API backend.

## Windows setup

Use Python 3.11 or newer, the normal BizHawk prerequisites from [README.md](README.md), and an installed current **Codex CLI**. This adapter requires the CLI's documented `exec`, `resume`, `--ignore-user-config`, `--strict-config` and JSON-event support. Unsupported flags or configuration are errors, not a reason to weaken the policy automatically.

In your local fork checkout:

```powershell
git switch mcp-codex
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-mcp.txt
.\.venv\Scripts\python.exe run.py
```

Launch SuperAstra with this virtual-environment Python, not a different global interpreter. Its MCP subprocess uses the same Python and needs the MCP dependencies installed there. The original `Start-Windows.cmd` launcher has not been rewritten.

1. In SuperAstra, open **SETTINGS -> Codex / ChatGPT -> Sign in with ChatGPT**. Finish the browser login. **Check sign-in** verifies it without sending a model request.
2. Open a SNES ROM in BizHawk. Keep the emulator running/unpaused. In **Tools -> Lua Console**, load `LOAD-IN-BIZHAWK.lua` from this same checkout. On the first run, launch SuperAstra before loading Lua so the IPC configuration exists.
3. Select **CODEX / CHATGPT**, type in **YOUR COMMAND**, and click **CAST PROMPT**. Replies and tool names appear in this window.

The executable field can remain blank to find an installed CLI on PATH. Alternatively, enter an absolute path to `codex.exe`. It is a file path, not a command with flags. For standard npm installations, the official `codex.cmd` shim is resolved to the packaged native `codex.exe`; the batch file is not executed. Nonstandard installations may require selecting the native executable explicitly. Native Windows Codex runs without a separate console window.

The Codex model is configurable in Settings. Its availability still depends on your account. A missing model, expired sign-in, exhausted allowance, or missing dependency produces an error; none switches to API billing.

## Login, conversations and local data

SuperAstra uses an application-specific `CODEX_HOME` under `~/.superastra/<installation-id>/codex`. The exact path is shown in Settings. It does not copy credentials from, or rewrite configuration in, your regular `~/.codex` directory. This intentionally requires one additional ChatGPT sign-in even when ordinary Codex is already logged in.

Codex manages its own credentials and transcripts in that profile. SuperAstra stores only a small ROM/model-to-thread-ID index, per-request instruction files and cancellation markers beside it. Subsequent prompts resume an explicit thread for the exact ROM hash and model, never an unrelated `--last` session. **New Codex conversations** clears this index, not Codex's stored transcripts or SuperAstra's retained ROM knowledge.

Prompts, requested game data, notebook excerpts and screenshots are still sent to OpenAI through Codex. This is not an offline model. Do not import confidential source material unless you intend to make it available to the model. The existing full-ROM indexing stays local; bounded tool results can leave the machine.

## Security and correctness boundaries

- **No shell interpolation:** Python launches an argument vector with `shell=False`; prompt text travels through stdin. Shell/batch commands are not accepted as the configured executable. Windows uses the native binary rather than interpolating a command into PowerShell or `cmd.exe`.
- **Explicit subscription mode:** ChatGPT authentication is forced and checked before reading the emulator. The child receives an allowlisted environment without API keys, access-token overrides, provider overrides or unrelated parent secrets. Login diagnostics are not copied verbatim into the GUI.
- **Restricted Codex configuration:** ignore regular user config, validate config strictly, use a read-only host sandbox and reject permission escalation. Shell/unified-exec, connected apps, hooks, subagents, automatic memories/goals and web search are disabled; default computer-use app access is denied. The required MCP server is configured explicitly. Missing support fails instead of enabling full access. Unexpected host-command/file-change events or another MCP server stop the request.
- **No silent game replacement:** a GUI request is bound to the observed ROM, emulator session and initial state epoch. The adapter rejects stale requests rather than silently adopting a changed ROM or external save state. Undo through the same toolbox may update the epoch deliberately.
- **No overlapping GUI commands:** backend selection is locked while a task is running; direct Undo/Stop Effects waits until that task has ended. MCP operations are serialized and still pass through the upstream authenticated, single-flight IPC bridge. Use only one UI/controller for a checkout at a time; this is not a new cross-process whole-session lock.
- **Bounded work and stop handling:** a per-request MCP-call budget, elapsed-time limit and JSON-output bounds apply. Stop Thinking marks the request cancelled, permits a short interval for an in-flight operation/experiment cleanup, then targets only the launched process group/tree. Markers remain so an orphaned MCP process rejects further calls. Stop is not Undo; already-applied effects may remain. Inspect the game before retrying a timed-out mutation.

These controls reduce risk; they are not a claim that arbitrary local software is sandboxed. The installed Codex executable, Python code, MCP server, BizHawk and Lua bridge are trusted programs running as your user. The MCP server intentionally writes game state and local notebook/IPC files outside Codex's read-only host-command sandbox. Local filesystem permissions, OS-specific process cleanup and the underlying software still matter. A full live Windows test is required before calling the integration end-to-end verified.

The Codex path disables built-in web research in this first pass. Use **ADD CONTEXT** to provide trusted reference files; the original API backend retains its separate web-search option. Settings remain in memory for this app session; Codex sign-in and the thread index persist.

## Use the MCP server from another host

The standalone MCP route remains available. It is optional, not needed for the GUI workflow. Configure a local stdio server with your virtual-environment Python and the absolute path to `mcp_server.py`:

```toml
[mcp_servers.superastra]
command = "C:\\absolute\\path\\to\\SuperAstra\\.venv\\Scripts\\python.exe"
args = ["C:\\absolute\\path\\to\\SuperAstra\\mcp_server.py"]
```

Do not run a second controller against the same checkout while a GUI task is active. A standalone server has a 256-call lifetime budget by default (`--max-tools`), and an explicit `get_context` can reconnect it after a game change. GUI-launched servers instead bind to one request and reject that change.

## Verification and development

The new regression suite does not call a model or use credentials. It exercises real subprocess pipes with a **fake Codex executable**, an SDK-independent adapter with a **fake Toolbox**, and real Tk widgets with **fake backends**:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-mcp-test.txt
.\.venv\Scripts\python.exe -m pytest tests/test_codex_backend.py tests/test_mcp_adapter.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_backend_ui.py -q
```

Linux GUI tests require a display; use `xvfb-run -a` when headless. See [docs/MCP-VALIDATION.md](docs/MCP-VALIDATION.md) for results and the outstanding Windows/BizHawk smoke test.

## Interface references

Implementation was checked against these primary references on 2026-09-08:

- [Codex non-interactive mode](https://developers.openai.com/codex/noninteractive/)
- [Codex authentication](https://developers.openai.com/codex/auth/)
- [Codex CLI reference](https://developers.openai.com/codex/cli/reference/)
- [Codex configuration reference](https://developers.openai.com/codex/config-reference/)
- [Official npm launcher / native-binary layouts](https://github.com/openai/codex/blob/main/codex-cli/bin/codex.js)
- [MCP Python SDK v2 low-level server](https://py.sdk.modelcontextprotocol.io/v2/advanced/low-level-server/)
