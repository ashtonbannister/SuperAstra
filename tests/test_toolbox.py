import tempfile
from pathlib import Path
import unittest

from astra_snes.toolbox import Toolbox
from astra_snes.transport import BridgeError
from harness import Harness


class EngineBridge:
    """Synchronous test adapter, executing the shipped Lua engine."""
    def __init__(self, directory):
        self.directory = directory
        self.h = Harness(romhash="CF" * 20)
        self.contexts = []

    def rpc(self, op, args=None, context=None):
        self.contexts.append(context)
        if op == "export_rom":
            (self.directory / "cartridge.bin").write_bytes(self.h.rom)
            return {"size": len(self.h.rom)}
        if op == "experiment_result" and self.h.engine.probe:
            self.h.tick(3)
        response = self.h.call(op, args, **({"epoch": context["epoch"]} if context else {}))
        if not response["ok"]:
            raise BridgeError(response["error"])
        return response["result"]


class ToolboxTests(unittest.TestCase):
    def test_context_experiment_live_application_undo_and_cartridge_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bridge = EngineBridge(root)
            t = Toolbox(bridge, knowledge_directory=root / "knowledge")
            self.assertIsNone(t.begin()["profile"])
            bridge.h.ram[23] = 3
            t.dispatch("create_checkpoint", {"name": "scene"})
            branch = t.dispatch("experiment", {"name": "scene", "frames": 3, "buttons": [],
                "addresses": ["0017"], "source": "assert(read(23)==3);write(23,9)",
                "cartridge_segments": [], "trace_cpu_address": None})
            self.assertEqual(branch["observation"]["samples"][-1]["values"], [9])
            self.assertEqual(bridge.h.ram[23], 3)
            t.dispatch("apply_bytes", {"edits": [{"address": "0017", "expected": 3, "value": 9}]})
            self.assertEqual(t.dispatch("read_memory", {"address": "0017", "length": 1})["bytes"], [9])
            t.dispatch("undo", {})
            self.assertEqual(t.dispatch("read_memory", {"address": "0017", "length": 1})["bytes"], [3])
            self.assertEqual(t.context["epoch"], bridge.h.engine.epoch)
            self.assertEqual(t.dispatch("read_cartridge", {"offset": "4", "length": 1})["hex"], "00")
            t.dispatch("patch_cartridge", {"segments": [{"offset": "4", "expected_hex": "00", "replacement_hex": "EA"}]})
            self.assertEqual(t.dispatch("read_cartridge", {"offset": "4", "length": 1})["hex"], "ea")
            t.dispatch("undo", {})
            self.assertEqual(t.dispatch("read_cartridge", {"offset": "4", "length": 1})["hex"], "00")
            self.assertTrue(any(e["tool"] == "experiment" for e in t.notebook.data["events"]))


if __name__ == "__main__":
    unittest.main()
