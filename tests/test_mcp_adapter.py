"""Adapter/Toolbox boundary tests, independent of the optional MCP SDK."""
import base64
from concurrent.futures import ThreadPoolExecutor
import threading
import time

import pytest

from astra_snes.mcp_adapter import MCPAdapter

CONTEXT = {"session": "session-one", "romhash": "a" * 40, "epoch": 1}
DEFS = [{"name": name, "parameters": {"type": "object", "properties": props,
         "required": list(props), "additionalProperties": False}} for name, props in (
    ("get_context", {}), ("write", {"value": {"type": "integer"}}), ("read", {}),
    ("undo", {}), ("screen", {}))]


class FakeBridge:
    def __init__(self):
        self.live = dict(CONTEXT)
        self.offline = False

    def rpc(self, op, context):
        if self.offline:
            raise RuntimeError("Disconnected")
        if context != self.live:
            raise RuntimeError("Stale session, ROM or epoch")
        return dict(self.live)


class FakeToolbox:
    def __init__(self):
        self.context = None
        self.bridge = FakeBridge()
        self.pending_image = None
        self.image = None
        self.calls = []
        self.begin_count = 0
        self.active = 0
        self.max_active = 0
        self.guard = threading.Lock()

    def begin(self):
        if self.bridge.offline:
            raise RuntimeError("Disconnected")
        self.begin_count += 1
        self.context = dict(self.bridge.live)

    def dispatch(self, name, arguments):
        with self.guard:
            self.active += 1
            self.max_active = max(self.active, self.max_active)
        try:
            time.sleep(0.002)
            self.calls.append((name, arguments))
            if name == "undo":
                self.bridge.live["epoch"] += 1
                self.context = dict(self.bridge.live)
            self.pending_image = self.image if name == "screen" else None
            return {"ok": True}
        finally:
            with self.guard:
                self.active -= 1


@pytest.fixture
def pair():
    toolbox = FakeToolbox()
    return toolbox, MCPAdapter(toolbox, DEFS, expected_context=dict(CONTEXT))


@pytest.mark.parametrize("name,args", [("unknown", {}), ("write", {}), ("write", {"value": "1"}),
                                       ("write", {"value": True}), ("read", {"extra": 1}), ("read", [])])
def test_bad_arguments_rejected_before_toolbox(pair, name, args):
    toolbox, adapter = pair
    with pytest.raises(ValueError):
        adapter.dispatch(name, args)
    assert toolbox.begin_count == 0 and toolbox.calls == []


def test_begins_once_preserving_scan_and_notebook_state(pair):
    toolbox, adapter = pair
    adapter.dispatch("read", {})
    adapter.dispatch("write", {"value": 2})
    assert toolbox.begin_count == 1 and len(toolbox.calls) == 2


@pytest.mark.parametrize("field,value", [("session", "new"), ("romhash", "b" * 40), ("epoch", 2)])
def test_changed_identity_before_first_call_never_mutates(pair, field, value):
    toolbox, adapter = pair
    toolbox.bridge.live[field] = value
    for _ in range(2):
        with pytest.raises(RuntimeError, match="changed before"):
            adapter.dispatch("write", {"value": 1})
    assert toolbox.calls == []


@pytest.mark.parametrize("field,value", [("session", "new"), ("romhash", "b" * 40), ("epoch", 2)])
def test_changed_identity_during_request_fails_closed(pair, field, value):
    toolbox, adapter = pair
    adapter.dispatch("read", {})
    toolbox.bridge.live[field] = value
    with pytest.raises(RuntimeError, match="Stale"):
        adapter.dispatch("write", {"value": 1})
    with pytest.raises(RuntimeError):
        adapter.dispatch("get_context", {})
    assert toolbox.calls == [("read", {})]


def test_undo_updates_epoch_without_breaking_same_request(pair):
    toolbox, adapter = pair
    adapter.dispatch("read", {})
    adapter.dispatch("undo", {})
    adapter.dispatch("read", {})
    assert toolbox.context["epoch"] == 2


def test_standalone_can_explicitly_refresh_but_not_silently():
    toolbox = FakeToolbox()
    adapter = MCPAdapter(toolbox, DEFS)
    adapter.dispatch("read", {})
    toolbox.bridge.live["romhash"] = "other"
    with pytest.raises(RuntimeError):
        adapter.dispatch("write", {"value": 1})
    adapter.dispatch("get_context", {})
    adapter.dispatch("write", {"value": 2})
    assert toolbox.begin_count == 2


def test_disconnection_cannot_serve_cached_data(pair):
    toolbox, adapter = pair
    adapter.dispatch("read", {})
    toolbox.bridge.offline = True
    with pytest.raises(RuntimeError, match="Disconnected"):
        adapter.dispatch("read", {})
    assert len(toolbox.calls) == 1


def test_cancellation_blocks_tools_before_dispatch(tmp_path):
    toolbox = FakeToolbox()
    marker = tmp_path / "cancel.flag"
    adapter = MCPAdapter(toolbox, DEFS, cancel_file=marker)
    marker.touch()
    with pytest.raises(RuntimeError, match="stopped"):
        adapter.dispatch("write", {"value": 1})
    assert toolbox.calls == [] and toolbox.cancelled()


def test_budget_enforced_in_adapter_not_model():
    toolbox = FakeToolbox()
    adapter = MCPAdapter(toolbox, DEFS, max_tools=1)
    adapter.dispatch("read", {})
    with pytest.raises(RuntimeError, match="budget"):
        adapter.dispatch("write", {"value": 2})
    assert len(toolbox.calls) == 1


def test_parallel_calls_serialized(pair):
    toolbox, adapter = pair
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: adapter.dispatch("read", {}), range(20)))
    assert toolbox.max_active == 1 and len(toolbox.calls) == 20


def test_png_result_and_no_reused_image(pair):
    toolbox, adapter = pair
    png = b"\x89PNG\r\n\x1a\n" + b"synthetic-header-test"
    toolbox.image = "data:image/png;base64," + base64.b64encode(png).decode()
    _, image = adapter.dispatch("screen", {})
    assert base64.b64decode(image) == png
    _, image = adapter.dispatch("read", {})
    assert image is None and toolbox.pending_image is None


@pytest.mark.parametrize("image", ["data:image/png;base64,??", "data:text/plain;base64,aA==",
                                   "data:image/png;base64,aA==", 123])
def test_bad_image_is_tool_error(pair, image):
    toolbox, adapter = pair
    toolbox.image = image
    with pytest.raises((ValueError, TypeError)):
        adapter.dispatch("screen", {})
