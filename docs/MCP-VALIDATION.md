# Codex UI / MCP validation

Date: 2026-09-08. Target: the `mcp-codex` draft PR, building on `fa0bddc43bcc9ceeb46f0b0028f55de98448b09e`.

## Executed in the development container

| Check | Result | Scope |
| --- | --- | --- |
| `python -m compileall -q astra_snes mcp_server.py tests` | Passed | Syntax compilation; does not import or exercise the MCP SDK |
| `python -m pytest tests/test_codex_backend.py tests/test_mcp_adapter.py -q` | **64 passed** | New Codex runner and adapter boundary tests |
| `xvfb-run -a python -m pytest tests/test_backend_ui.py -q` | **11 passed** | Real Tk UI controls, routing and state handling with fake backends |

**75 new regression cases passed.** This count is not the original upstream emulator suite, and does not include a live Codex/model/BizHawk integration test.

Coverage includes prompt-on-stdin handling (including shell metacharacters and Unicode), escaped TOML paths, allowlisted child environment, forced ChatGPT configuration, explicit per-ROM thread resumption, no API fallback, invalid login/event data, missing completion, nonzero exits, unexpected host operations, concurrent requests, cancellation before/during execution, timeout, process cleanup even when marker writing fails, session/ROM/epoch changes, same-request Undo, serialization, schema validation, screenshot bounds and stale-image handling. Windows executable-resolution layouts and launch flags use simulated fixtures, not a Windows host.

The UI tests instantiate real Tk widgets under Xvfb and substitute test backends for external services. The subprocess tests launch a real child process implementing fake JSONL responses. The adapter tests substitute a fake Toolbox/Bridge. These boundaries are explicit so the results do not imply a successful game modification.

## Not yet executed

- Installation/import and a real `initialize -> tools/list -> tools/call` handshake against the declared MCP Python SDK v2. Dependency installation was unavailable in the development environment.
- Real Codex CLI parsing, browser sign-in, account/model access and `exec resume` behavior with the restricted configuration.
- A Windows process-tree cancellation test, including a running MCP child and an experiment that needs restoration.
- Live BizHawk/Lua/ROM operations, screenshots, expected-value writes, Undo and externally changed ROM/save-state behavior through this complete stack.
- The original upstream Lua/BizHawk engine test suite, which was not available with its dependencies in this partial development checkout.

The CLI flags, JSON-event shape, configuration keys, npm binary layout and MCP SDK callback signatures were checked against current primary documentation/source. Static interface checking is not a substitute for the above runtime tests. Keep the PR draft until the local Windows smoke test succeeds; do not remove restrictive flags just to silence an unsupported-option error.

## Windows acceptance sequence

1. Use a current Codex CLI, install `requirements-mcp.txt` into a virtual environment, and launch `run.py` with that environment's Python. Confirm all three backend choices appear and Codex is selected by default.
2. Use Settings to sign in with ChatGPT and check the sign-in status. With no valid sign-in, Cast Prompt must fail without an API call or a game mutation.
3. Start BizHawk with a SNES ROM and load the Lua bridge from the same checkout. Request **only** game context and a screenshot. Verify the actual response and picture, not just accepted tool requests.
4. Request a small reversible change after reading the current value. Verify it in game, finish the task, then use Undo and verify restoration. Do not start with large ROM patches or new routines.
5. Send a follow-up prompt. Confirm the same ROM/model thread resumes while fresh context is read. Switch ROM or load a different state during a pending request; stale actions must fail rather than target the changed game.
6. Exercise Stop Thinking during inspection and during a temporary experiment. Verify no further calls run, inspect the actual final game state, and check that no live Codex/MCP process remains. Already-applied effects are not automatically undone.
7. Verify missing CLI/MCP dependencies, unavailable model and account-usage failures remain visible errors and never select the API backend. Check API and Local modes separately without mixing controllers against the same checkout.
