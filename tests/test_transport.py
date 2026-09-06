import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from astra_snes.transport import Bridge, BridgeError, atomic_json
from harness import Harness


class TransportTests(unittest.TestCase):
    def test_real_file_protocol_with_lua_mutation_and_undo(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge = Bridge(directory, timeout=2)
            ready, done = threading.Event(), threading.Event()
            errors = []
            def emulator_thread():
                try:
                    h = Harness()
                    h.engine = h.lua.execute((Path(__file__).resolve().parents[1] / "emulator/engine.lua").read_text())(
                        h.api, h.lua.execute((Path(__file__).resolve().parents[1] / "emulator/smw.lua").read_text())(h.api),
                        bridge.config["token"], "ipc-session", time.time,
                        h.lua.execute((Path(__file__).resolve().parents[1] / "emulator/sandbox.lua").read_text())(h.api))
                    while not done.is_set():
                        ctx = json.loads(h.json.encode(h.engine.context()))
                        atomic_json(Path(directory) / "heartbeat.json", ctx)
                        ready.set()
                        request = Path(directory) / "request.json"
                        if request.exists():
                            data = json.loads(request.read_text())
                            request.unlink()
                            atomic_json(Path(directory) / "response.json", h.handle(data))
                        time.sleep(0.005)
                except Exception as e:
                    errors.append(e)
            thread = threading.Thread(target=emulator_thread)
            thread.start()
            try:
                self.assertTrue(ready.wait(2))
                result = bridge.rpc("routine", {"name": "new", "source": "write(7,123)", "frames": 1})
                self.assertEqual(result["bytes_written"], 1)
                self.assertEqual(bridge.rpc("read", {"address": 7, "length": 1})["bytes"], [123])
                self.assertEqual(bridge.rpc("undo")["undo_count"], 0)
                time.sleep(0.02)
                self.assertEqual(bridge.rpc("read", {"address": 7, "length": 1})["bytes"], [0])
            finally:
                done.set(); thread.join(3)
            self.assertEqual(errors, [])

    def test_timeout_removes_unconsumed_request(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge = Bridge(directory, timeout=0.15)
            atomic_json(Path(directory) / "heartbeat.json", {"protocol": 1, "session": "s", "romhash": "h", "epoch": 0})
            with self.assertRaisesRegex(BridgeError, "may have happened"):
                bridge.rpc("patch", {})
            self.assertFalse((Path(directory) / "request.json").exists())
            self.assertFalse((Path(directory) / "client.lock").exists())


if __name__ == "__main__":
    unittest.main()
