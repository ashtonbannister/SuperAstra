"""Controller ownership and actual SDK metadata, without a live emulator/model."""
import multiprocessing
from pathlib import Path

import pytest

from astra_snes.controller import ControllerLease
from astra_snes.transport import Bridge


def contender(directory, queue):
    try:
        with ControllerLease(Path(directory)):
            queue.put("acquired")
    except RuntimeError:
        queue.put("blocked")


def test_other_process_cannot_own_controller_and_close_releases(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    queue = ctx.Queue()
    with ControllerLease(tmp_path):
        child = ctx.Process(target=contender, args=(str(tmp_path), queue))
        child.start()
        assert queue.get(timeout=15) == "blocked"
        child.join(15)
        assert child.exitcode == 0
        bridge = Bridge(tmp_path)
        # Rejected before heartbeat/request writes, including desktop callers.
        with pytest.raises(RuntimeError, match="controller"):
            bridge.rpc("inspect")
        assert not (tmp_path / "request.json").exists()
    with ControllerLease(tmp_path):
        pass
    queue.close()


def hold_lease(directory, ready):
    with ControllerLease(Path(directory)):
        ready.set()
        import time
        time.sleep(60)


def test_killed_owner_releases_os_lock(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    ready = ctx.Event()
    child = ctx.Process(target=hold_lease, args=(str(tmp_path), ready))
    child.start()
    try:
        assert ready.wait(15)
        child.terminate()
        child.join(15)
        assert not child.is_alive()
        with ControllerLease(tmp_path):
            pass
    finally:
        if child.is_alive():
            child.terminate()
            child.join(15)


@pytest.mark.anyio
async def test_sdk_tools_include_annotations_and_instructions():
    pytest.importorskip("mcp")
    from mcp_server import create_server
    from astra_snes.toolbox import TOOLS

    server = create_server(None)
    result = await server.get_request_handler("tools/list").handler(None, None)
    tools = {tool.name: tool for tool in result.tools}
    assert set(tools) == {tool["name"] for tool in TOOLS}
    assert tools["see_screen"].annotations.read_only_hint is True
    assert tools["apply_bytes"].annotations.read_only_hint is False
    assert tools["undo"].annotations.destructive_hint is True
    assert tools["observe"].annotations.read_only_hint is False
    assert tools["scan_memory"].annotations.read_only_hint is False
    assert all(tool.annotations.open_world_hint is False for tool in tools.values())
    assert "get_context" in server.create_initialization_options().instructions


@pytest.fixture
def anyio_backend():
    return "asyncio"

@pytest.mark.anyio
async def test_stdio_handshake_and_invalid_tool_without_emulator(tmp_path):
    pytest.importorskip("mcp")
    import os
    import sys
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    root = Path(__file__).resolve().parents[1]
    # Real SDK wire protocol; initialization/listing do not access game state.
    params = StdioServerParameters(
        command=sys.executable, args=[str(root / "mcp_server.py")],
        cwd=str(root), env=dict(os.environ),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            initialized = await session.initialize()
            assert "get_context" in initialized.instructions
            tools = await session.list_tools()
            from astra_snes.toolbox import TOOLS
            assert {tool.name for tool in tools.tools} == {tool["name"] for tool in TOOLS}
            result = await session.call_tool("read_memory", {"address": "0"})
            assert result.is_error
            assert "Invalid tool arguments" in result.content[0].text

@pytest.mark.parametrize("newline", [b"\n", b"\r\n", b"\r"])
def test_imported_source_keeps_exact_line_numbers(tmp_path, newline):
    from astra_snes.context import GameNotebook

    source = tmp_path / "reference.asm"
    original = newline.join([b"first", b"HealthUpdate: STA $072A", b"last"]) + newline
    source.write_bytes(original)
    notebook = GameNotebook("AA" * 20, tmp_path / "knowledge")
    meta = notebook.import_source(source)
    stored = notebook.sources_path / (meta["id"] + ".txt")
    assert stored.read_bytes() == original
    assert notebook.read_source(meta["id"], 2, 1)["text"] == "2: HealthUpdate: STA $072A"
