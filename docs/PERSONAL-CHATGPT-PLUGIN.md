# Personal ChatGPT plugin

This slice reuses the local stdio MCP server through Secure MCP Tunnel. It adds
server instructions, annotations, a portable plugin manifest and a lifetime
controller lease. No public endpoint, hosted emulator, or public submission.

## Start locally

Keep BizHawk running with the SNES ROM and LOAD-IN-BIZHAWK.lua from this checkout.
The tunnel must run on Windows so it can launch this project's Windows Python.
Configure its stdio command as this argument sequence, with paths quoted using
the tunnel client's supported command syntax:

- Y:\\AI Games\\Super Astra SNES editor\\.venv\\Scripts\\python.exe
- Y:\\AI Games\\Super Astra SNES editor\\mcp_server.py
- --personal-plugin

Use tunnel-client help quickstart to check the installed client's command syntax.
The documented sequence is init --sample sample_mcp_stdio_local --profile
superastra --tunnel-id <your tunnel ID> --mcp-command <quoted command>, followed
by doctor --profile superastra --explain and run --profile superastra.
No concrete profile is generated here: the tunnel ID and runtime credential
belong to the owner's Platform organization. Never place the runtime key in this
repository, a command argument, a transcript, or the plugin bundle. Provision it
securely in the client environment. A tunnel key authenticates transport; the
MCP server does not make model API calls.

The client must remain running. While --personal-plugin owns the controller,
other Bridge RPC callers (including desktop controls and Codex) fail closed.
Stop it before switching back to the desktop controller. Locks release on process
exit, including a crash. Do not delete controller.lock while a process owns it.
This lease excludes competing RPC calls, not manual BizHawk input. Context guards
still reject stale ROM/session/epoch operations. A desktop investigation already
in progress will fail its next RPC if the plugin obtains ownership between calls.

## Connect the personal plugin

1. Create/select a tunnel in Platform tunnel settings. Associate it with the
   intended ChatGPT workspace and grant the owner the required tunnel permissions.
2. Enable ChatGPT developer mode, subject to account/workspace access.
3. In ChatGPT Plugins, select plus, choose Tunnel, and select your tunnel.
   Name it SuperAstra and describe it as personal SNES game investigation/control.
4. In a new chat, select SuperAstra and request context and a screenshot only.
5. Confirm actual game identity and image. Then authorize a small reversible
   alteration, verify it in-game, ask for undo, and verify restoration.

The connection itself exposes server instructions; a separate skill install is
optional. The portable bundle is plugins/superastra. Its skill and logo are ready,
but no registered MCP mapping is fabricated. After ChatGPT creates the connection,
use the real plugin_asdk_app ID with Plugin Creator to attach it to this bundle
and install it as a personal plugin. Do not publish it to the public directory.

## Acceptance and limits

Verify wrong-ROM/save-state rejection, duplicate-controller rejection, timeout
handling, experiment restoration, stop effects and undo in ChatGPT/BizHawk.
Stopping ChatGPT generation, closing the client, or cancellation does not undo
game changes or guarantee cancellation of an in-flight experiment.
The server allows at most 256 calls per process; restart the client when exhausted.
An explicit get_context can refresh a standalone server after a game switch;
instructions require reassessment before any subsequent alteration.
Local evidence/notebook writes can occur during inspection tools. Annotations
classify changes to the game and intentional notebook/scan writes; they do not
replace server validation or confer authorization.

## Sources

- https://developers.openai.com/api/docs/guides/secure-mcp-tunnels
- https://developers.openai.com/plugins/deploy/connect-chatgpt
- https://developers.openai.com/plugins/build/plugins

Consult current docs/client help for account access and command syntax.

## Checkpoint

Base: mcp-codex at 9a818c6621d220ff854f8de3dc16c05e814595d4.
Pre-existing astra_snes/codex_agent.py modification is outside this slice.
Local implementation and verification results are recorded below after checks.
Account tunnel creation, runtime credential provisioning, connection registration,
and live ChatGPT/BizHawk acceptance remain required before claiming a working
connected plugin. Existing desktop and stdio paths remain consumers; none removed.
Rollback: revert this slice's files/changes and stop the personal tunnel client.

### Local verification (2026-10-02)

Windows Python 3.11.16, MCP SDK 2.2.0, pytest 9.1.1, lupa 2.8.
Installed lupa (repository development dependency) and PyYAML (skill validator)
only in the existing project virtual environment.

- PASS: real stdio MCP initialize/list/invalid-call handshake without emulator calls;
  current 29-tool inventory, annotations, and server instructions.
- PASS: exclusive controller conflict, OS lock release after process termination,
  and imported reference line numbers with LF, CRLF and CR input.
- PASS: compilation, skill validator, portable manifest JSON-schema validation,
  referenced logo existence, diff whitespace, and authored-file byte validation.
- Full final suite: 139 passed, 1 skipped, 1 failed, plus 6 passing subtests.
  Failure: tests/test_transport.py::TransportTests::
  test_real_file_protocol_with_lua_mutation_and_undo timed out at undo.
  An earlier final-code full run had 140 passed and the same one failure.
  Isolated transport recheck: 2 passed.
- Delegate/local selected checks: personal plugin + toolbox + transport, 10 passed;
  investigation + transport, 14 passed. These use fake/local Lua environments.
  The full-suite timeout remains unresolved; these passes do not make the full gate pass.
- No authenticated tunnel, ChatGPT connection, live ROM change, or live undo was tested.

The full-suite timeout is not the lock-contention failure path: the controller
lease is acquired before the RPC deadline. A precise timing/worker cause is
unproven. The fixture collects worker exceptions but can report the RPC timeout
before reaching its final worker-error assertion. Do not call this slice fully
validated until that failure and the live acceptance gates are resolved.

The full check also exposed a pre-existing Windows imported-reference bug:
text-mode writes doubled carriage returns and shifted source line numbers.
Import now stores the decoded UTF-8 bytes without host newline translation.
No existing knowledge files were migrated or rewritten; owner-initiated reimport
can refresh an already corrupted cached reference.

Completed local scope: package, authoritative instructions, SDK metadata,
controller lease and the imported-reference correction. The existing desktop
and Codex paths remain supported consumers. No unrelated cleanup or public
publication. After the slice commit, only the pre-existing codex_agent.py
approval-setting edit is expected to remain dirty.

Next authorized work: account-specific personal tunnel setup/registration and
live acceptance. Runtime credentials and actual registered plugin ID must be
supplied through the owner's account setup; never fabricate either.
