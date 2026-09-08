"""Local stdio MCP server. Start via Codex or the SuperAstra UI, not a shell prompt."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import anyio
from mcp.server import Server, ServerRequestContext
from mcp.server.stdio import stdio_server
from mcp.types import (CallToolRequestParams, CallToolResult, ImageContent,
                       ListToolsResult, PaginatedRequestParams, TextContent, Tool)

from astra_snes.mcp_adapter import MCPAdapter
from astra_snes.toolbox import TOOLS, Toolbox
from astra_snes.transport import Bridge


def create_server(adapter: MCPAdapter) -> Server:
    tools = [Tool(name=d["name"], description=d["description"], input_schema=d["parameters"])
             for d in TOOLS]

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

    return Server("SuperAstra MCP", version="0.2.0", on_list_tools=list_tools, on_call_tool=call_tool)


async def serve(adapter: MCPAdapter) -> None:
    server = create_server(adapter)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-context", help="JSON session/romhash/epoch binding for one UI request")
    parser.add_argument("--cancel-file", type=Path, help="Local cancellation marker for this request")
    parser.add_argument("--max-tools", type=int, default=256)
    args = parser.parse_args()
    expected = json.loads(args.expected_context) if args.expected_context else None
    adapter = MCPAdapter(Toolbox(Bridge()), TOOLS, expected_context=expected,
                         cancel_file=args.cancel_file, max_tools=args.max_tools)
    anyio.run(serve, adapter)


if __name__ == "__main__":
    main()
