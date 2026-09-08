"""SDK-independent, serialized adapter over SuperAstra's existing Toolbox."""
from __future__ import annotations

import base64
from pathlib import Path
import threading
from jsonschema import Draft202012Validator

from .codex_agent import identity


class MCPAdapter:
    def __init__(self, toolbox, definitions: list[dict], *, expected_context: dict | None = None,
                 cancel_file: Path | None = None, max_tools: int = 256):
        if type(max_tools) is not int or not 1 <= max_tools <= 256:
            raise ValueError("Tool budget must be 1-256.")
        self.toolbox = toolbox
        self.definitions = {tool["name"]: tool for tool in definitions}
        self.validators = {name: Draft202012Validator(tool["parameters"])
                           for name, tool in self.definitions.items()}
        self.expected = identity(expected_context) if expected_context is not None else None
        self.cancel_file = cancel_file
        self.max_tools, self.calls = max_tools, 0
        self.lock = threading.Lock()
        self.toolbox.cancelled = lambda: bool(self.cancel_file and self.cancel_file.exists())

    def dispatch(self, name: str, arguments: dict) -> tuple[dict, str | None]:
        if name not in self.validators:
            raise ValueError("Unknown SuperAstra tool.")
        if not isinstance(arguments, dict):
            raise ValueError("Tool arguments must be a JSON object.")
        errors = list(self.validators[name].iter_errors(arguments))
        if errors:
            # Do not echo full arguments (possibly source text or large byte arrays).
            paths = [".".join(map(str, error.path)) or "arguments" for error in errors[:8]]
            raise ValueError("Invalid tool arguments at: " + ", ".join(paths))
        with self.lock:
            if self.toolbox.cancelled():
                raise RuntimeError("This Codex request has stopped. Start a new request to continue.")
            if self.calls >= self.max_tools:
                raise RuntimeError("Tool budget reached. Report progress and ask the user to continue.")
            self.calls += 1
            toolbox = self.toolbox
            if toolbox.context is None:
                toolbox.begin()  # Reads only; identity is checked before any dispatch.
                current = identity(toolbox.context)
                if self.expected is not None and current != self.expected:
                    # Never let a later call bypass a failed initial identity check.
                    toolbox.context = None
                    raise RuntimeError("Game/session/state changed before the command started. Send a new prompt.")
            else:
                try:
                    # Do not swallow heartbeat errors or serve cached notebook/ROM data
                    # against an unverified live state. RPC enforces session/hash/epoch.
                    toolbox.bridge.rpc("inspect", context=toolbox.context)
                except RuntimeError:
                    if self.expected is not None or name != "get_context":
                        raise
                    # A standalone MCP host may explicitly request a fresh context.
                    toolbox.begin()
            if self.expected is not None and identity(toolbox.context)[:2] != self.expected[:2]:
                raise RuntimeError("The running ROM or emulator session changed. Send a new prompt.")
            toolbox.pending_image = None
            result = toolbox.dispatch(name, arguments)
            image = toolbox.pending_image
            toolbox.pending_image = None
            if image:
                prefix = "data:image/png;base64,"
                if not isinstance(image, str) or not image.startswith(prefix) or len(image) > 15 * 1024 * 1024:
                    raise ValueError("Invalid emulator screenshot result.")
                png = base64.b64decode(image[len(prefix):], validate=True)
                if not png.startswith(b"\x89PNG\r\n\x1a\n") or len(png) > 10 * 1024 * 1024:
                    raise ValueError("Invalid emulator screenshot result.")
                image = base64.b64encode(png).decode("ascii")
            return result, image
