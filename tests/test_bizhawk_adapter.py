"""Run the shipped BizHawk Lua adapter against a contract fixture, including IPC.

This supplements, but does not replace, native EmuHawk validation.
"""
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
import shutil
import base64

from astra_snes.transport import Bridge
from harness import Harness, ROOT


class AdapterTests(unittest.TestCase):
    def test_shipped_lua_adapter_boot_read_export_routine_and_undo(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / "emulator", root / "emulator")
            bridge = Bridge(root / "ipc", timeout=2)
            done, ready = threading.Event(), threading.Event()
            errors = []
            def run_adapter():
                try:
                    h = Harness()
                    globals = h.lua.globals()
                    globals.memory = h.table({
                        "getmemorydomainlist": lambda: h.table(["WRAM", "CARTROM", "VRAM", "Waterbox"]),
                        "getmemorydomainsize": lambda d: h.size("ROM" if d == "CARTROM" else d),
                        "read_u8": lambda a, d: h.read("ROM" if d == "CARTROM" else d, a),
                        "write_u8": lambda a, v, d: h.write_rom(a, v) if d == "CARTROM" else h.write(a, v),
                        "read_bytes_as_binary_string": lambda a, n, d: bytes(h.rom[a:a + n]),
                    })
                    callbacks = {}
                    globals.event = h.table({"onloadstate": lambda f, name: callbacks.update(load=f),
                                             "onexit": lambda f, name: callbacks.update(exit=f)})
                    def advance():
                        if done.is_set():
                            raise InterruptedError("fixture finished")
                        h.frame += 1
                        ready.set()
                        time.sleep(0.004)
                    globals.emu = h.table({"getsystemid": lambda: "SNES", "framecount": lambda: h.frame,
                                          "frameadvance": advance, "getregisters": lambda: h.table({"PC": 32768})})
                    globals.gameinfo = h.table({"getromhash": lambda: h.romhash, "getromname": lambda: "Contract fixture"})
                    globals.memorysavestate = h.table({"savecorestate": h.save, "loadcorestate": h.load,
                                                       "removestate": lambda key: h.states.pop(key, None)})
                    globals.console = h.table({"log": lambda message: None})
                    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a7Z0AAAAASUVORK5CYII=")
                    globals.client = h.table({"screenshot": lambda path: Path(path).write_bytes(png)})
                    globals.joypad = h.table({"set": lambda values, player: None})
                    try:
                        h.lua.execute((root / "emulator/bizhawk.lua").read_text())(str(root))
                    except InterruptedError:
                        pass
                except Exception as e:
                    errors.append(e)
                    ready.set()
            thread = threading.Thread(target=run_adapter)
            thread.start()
            try:
                self.assertTrue(ready.wait(3))
                self.assertFalse(errors, errors)
                self.assertEqual(bridge.rpc("inspect")["title"], "Contract fixture")
                self.assertEqual(bridge.rpc("export_rom")["size"], 0x80000)
                self.assertEqual((root / "ipc/cartridge.bin").stat().st_size, 0x80000)
                result = bridge.rpc("routine", {"name": "adapter_test", "source": "write(33,91)", "frames": 1})
                self.assertEqual(result["bytes_written"], 1)
                self.assertEqual(bridge.rpc("read", {"address": 33, "length": 1})["bytes"], [91])
                self.assertEqual(bridge.rpc("undo")["undo_count"], 0)
                time.sleep(0.02)
                self.assertEqual(bridge.rpc("read", {"address": 33, "length": 1})["bytes"], [0])
                domains = bridge.rpc("inspect")["memory_domains"]
                self.assertIn("VRAM", [d["name"] for d in domains])
                self.assertNotIn("Waterbox", [d["name"] for d in domains])
                self.assertEqual(bridge.rpc("read", {"domain": "VRAM", "address": 3, "length": 1})["bytes"], [0])
                bridge.rpc("patch_rom", {"writes": [{"address": 30, "value": 7, "expected": 0}]})
                bridge.rpc("create_checkpoint", {"name": "baseline"})
                bridge.rpc("experiment", {"name": "baseline", "frames": 3, "addresses": [23], "buttons": [],
                    "source": "write(23,rom(30))", "rom_writes": []})
                deadline = time.monotonic() + 3
                result = {"done": False}
                while not result["done"] and time.monotonic() < deadline:
                    time.sleep(0.02)
                    result = bridge.rpc("experiment_result")
                self.assertTrue(result["done"])
                self.assertEqual(result["result"]["observation"]["samples"][-1]["values"], [7])
                self.assertEqual(bridge.rpc("read", {"address": 23, "length": 1})["bytes"], [0])
                self.assertTrue(result["result"]["screenshot"])
                bridge.rpc("stop_holds", {"name": ""})
                self.assertEqual(bridge.rpc("read", {"domain": "ROM", "address": 30, "length": 1})["bytes"], [0])
            finally:
                done.set()
                thread.join(3)
            self.assertFalse(errors, errors)


if __name__ == "__main__":
    unittest.main()
