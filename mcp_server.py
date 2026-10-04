"""Local stdio MCP server for Codex, the desktop UI, or a personal ChatGPT tunnel."""
from __future__ import annotations

import argparse
from contextlib import nullcontext
import json
from pathlib import Path

import anyio
from mcp.server import Server, ServerRequestContext
from mcp.server.stdio import stdio_server
from mcp.types import (CallToolRequestParams, CallToolResult, ImageContent,
                       ListToolsResult, PaginatedRequestParams, TextContent, Tool, ToolAnnotations)

from astra_snes.mcp_adapter import MCPAdapter
from astra_snes.controller import ControllerLease
from astra_snes.toolbox import TOOLS, Toolbox
from astra_snes.transport import Bridge


def create_server(adapter: MCPAdapter) -> Server:
    read_tools = {
        "get_context", "see_screen", "read_memory", "read_domain", "read_cartridge",
        "search_cartridge", "disassemble", "compare_checkpoint", "get_saved_routine",
        "search_knowledge", "get_saved_change", "read_source",
    }
    # Inspection may retain local evidence, but cannot change the running game.
    notebook_tools = {"remember", "update_investigation", "scan_memory"}
    tools = [Tool(
        name=d["name"], description=d["description"], input_schema=d["parameters"],
        annotations=ToolAnnotations(
            read_only_hint=d["name"] in read_tools,
            destructive_hint=d["name"] not in read_tools | notebook_tools,
            open_world_hint=False,
        ),
    ) for d in TOOLS]
    skill = Path(__file__).parent / "plugins/superastra/skills/superastra/SKILL.md"
    instructions = skill.read_text(encoding="utf-8").split("---", 2)[2].strip()

    async def list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(tools=tools)

    async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        try:
            args = params.arguments if params.arguments is not None else {}
            result, png = await anyio.to_thread.run_sync(adapter.dispatch, params.name, args)
            content = [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, default=str))]
            if png:
                content.append(ImageContent(type="image", data=png, mime_type="image/png"))
            return CallToolResult(content=content)
        except (RuntimeError, ValueError, OSError, KeyError, TypeError) as exc:
            return CallToolResult(content=[TextContent(type="text", text=str(exc))], is_error=True)

    return Server("SuperAstra MCP", version="0.3.0", instructions=instructions,
                  on_list_tools=list_tools, on_call_tool=call_tool)


async def serve(adapter: MCPAdapter) -> None:
    server = create_server(adapter)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-context", help="JSON session/romhash/epoch binding for one UI request")
    parser.add_argument("--cancel-file", type=Path, help="Local cancellation marker for this request")
    parser.add_argument("--max-tools", type=int, default=256)
    parser.add_argument("--personal-plugin", action="store_true",
                        help="Own the emulator controller exclusively for this process lifetime")
    args = parser.parse_args()
    expected = json.loads(args.expected_context) if args.expected_context else None
    adapter = MCPAdapter(Toolbox(Bridge()), TOOLS, expected_context=expected,
                         cancel_file=args.cancel_file, max_tools=args.max_tools)
    bridge = adapter.toolbox.bridge
    lease = ControllerLease(bridge.directory) if args.personal_plugin else nullcontext()
    with lease as owner:
        if args.personal_plugin:
            bridge.controller = owner
        try:
            anyio.run(serve, adapter)
        finally:
            bridge.controller = None


if __name__ == "__main__":
    main()
