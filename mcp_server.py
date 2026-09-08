"""MCP adapter for SuperAstra.

Exposes the existing SuperAstra toolbox to MCP hosts such as Codex while
leaving the original Astra/API desktop path untouched.

The server uses stdio. BizHawk still communicates with SuperAstra through the
existing authenticated file-based bridge in ``ipc/``.
"""
from __future__ import annotations

import base64
import json
import threading
from typing import Any

import anyio
from jsonschema import Draft202012Validator
from mcp.server import Server, ServerRequestContext
from mcp.server.stdio import stdio_server
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    ImageContent,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
)

from astra_snes.toolbox import TOOLS, Toolbox
from astra_snes.transport import Bridge, BridgeError


TOOL_DEFS = {definition["name"]: definition for definition in TOOLS}
MCP_TOOLS = [
    Tool(
        name=definition["name"],
        description=definition["description"],
        input_schema=definition["parameters"],
    )
    for definition in TOOLS
]

bridge = Bridge()
toolbox = Toolbox(bridge)
_toolbox_lock = threading.Lock()


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _validate_arguments(name: str, arguments: dict[str, Any]) -> str | None:
    definition = TOOL_DEFS.get(name)
    if definition is None:
        return f"Unknown SuperAstra tool: {name}"

    validator = Draft202012Validator(definition["parameters"])
    errors = sorted(validator.iter_errors(arguments), key=lambda error: list(error.path))
    if not errors:
        return None

    details = []
    for error in errors[:8]:
        where = ".".join(str(part) for part in error.path) or "arguments"
        details.append(f"{where}: {error.message}")
    return "Invalid tool arguments: " + "; ".join(details)


def _dispatch(name: str, arguments: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    """Run one synchronous toolbox operation and return any pending image."""
    with _toolbox_lock:
        # Detect a ROM/session replacement without resetting state on every MCP call.
        try:
            live = bridge.heartbeat()
            current = toolbox.context or {}
            identity = (live.get("session"), live.get("romhash"), live.get("epoch"))
            known = (current.get("session"), current.get("romhash"), current.get("epoch"))
            if toolbox.context is None or identity != known:
                toolbox.begin()
        except BridgeError:
            # dispatch/begin will produce the normal user-facing bridge error below.
            pass

        toolbox.pending_image = None
        result = toolbox.dispatch(name, arguments)
        return result, toolbox.pending_image


async def list_tools(
    ctx: ServerRequestContext, params: PaginatedRequestParams | None
) -> ListToolsResult:
    del ctx, params
    return ListToolsResult(tools=MCP_TOOLS)


async def call_tool(
    ctx: ServerRequestContext, params: CallToolRequestParams
) -> CallToolResult:
    del ctx
    name = params.name
    arguments = dict(params.arguments or {})

    validation_error = _validate_arguments(name, arguments)
    if validation_error:
        return CallToolResult(
            content=[TextContent(type="text", text=validation_error)],
            is_error=True,
        )

    try:
        result, pending_image = await anyio.to_thread.run_sync(_dispatch, name, arguments)
    except (BridgeError, RuntimeError, ValueError, OSError, KeyError, TypeError) as exc:
        return CallToolResult(
            content=[TextContent(type="text", text=str(exc))],
            is_error=True,
        )

    content = [TextContent(type="text", text=_json_text(result))]
    if pending_image:
        prefix = "data:image/png;base64,"
        if pending_image.startswith(prefix):
            encoded = pending_image[len(prefix) :]
            # Decode/re-encode once so malformed data cannot cross the MCP boundary.
            png = base64.b64decode(encoded, validate=True)
            encoded = base64.b64encode(png).decode("ascii")
            content.append(ImageContent(type="image", data=encoded, mime_type="image/png"))

    return CallToolResult(content=content)


server = Server(
    "SuperAstra MCP",
    version="0.1.0",
    on_list_tools=list_tools,
    on_call_tool=call_tool,
)


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    anyio.run(main)
