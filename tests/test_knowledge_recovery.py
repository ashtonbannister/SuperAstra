"""Durable hack evidence and reconnect recovery without Lua dependencies."""
import tempfile
from pathlib import Path
import unittest

from astra_snes.context import GameNotebook


class KnowledgeRecoveryTests(unittest.TestCase):
    def test_saved_actions_survive_reconnect_and_failed_writes_are_excluded(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            notebook = GameNotebook("AC" * 20, root)
            context = {"session": "old", "epoch": 3, "romhash": "AC" * 20}
            args = {"segments": [{"offset": "7A91", "expected_hex": "c008",
                                  "replacement_hex": "0010"}]}
            notebook.record("patch_cartridge", args, {"bytes_written": 2}, context)
            notebook.record("apply_bytes", {"edits": []},
                            {"error": "guard failed", "success": False}, context)
            saved = GameNotebook("AC" * 20, root)
            recovery = saved.recovery({"session": "new", "romhash": "AC" * 20})
            self.assertEqual(recovery["prior_action_count"], 1)
            self.assertEqual(recovery["recent_prior_actions"][0]["tool"], "patch_cartridge")
            self.assertIn("7A91", recovery["recent_prior_actions"][0]["args_excerpt"])
            self.assertEqual(saved.recovery(context)["prior_action_count"], 0)
            self.assertEqual(saved.data["changes"][0]["args"], args)
            self.assertEqual(saved.data["changes"][0]["status"], "acknowledged")
            self.assertEqual(saved.get_change(0)["args"], args)
            self.assertTrue(any(m["kind"] == "saved_action"
                                for m in saved.search("7A91")["matches"]))
            with self.assertRaises(ValueError):
                saved.get_change(-1)

    def test_lost_acknowledgement_is_recorded_as_uncertain(self):
        with tempfile.TemporaryDirectory() as temp:
            notebook = GameNotebook("AF" * 20, Path(temp))
            notebook.record("apply_bytes", {"edits": [{"address": "0100", "expected": 1, "value": 2}]},
                            {"error": "No acknowledgement before timeout.", "success": False,
                             "uncertain": True}, {"session": "old", "epoch": 0})
            recovered = GameNotebook("AF" * 20, Path(temp))
            self.assertEqual(recovered.data["changes"][0]["status"], "uncertain")
            self.assertEqual(recovered.recovery({"session": "new"})["recent_prior_actions"][0]["status"],
                             "uncertain")

    def test_older_tool_evidence_is_recovered_without_claiming_active_state(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            notebook = GameNotebook("AD" * 20, root)
            notebook.data["events"] = [
                {"tool": "run_routine", "args": '{"name":"test","source":"write(1,2)","frames":1}',
                 "result": '{"message":"Executed test."}',
                 "context": {"session": "old", "epoch": 0}, "time": 100},
                {"tool": "patch_cartridge", "args": '{"segments":[]}',
                 "result": '{"error":"guard failed"}',
                 "context": {"session": "old", "epoch": 0}, "time": 101}]
            notebook.data.pop("changes")
            notebook.save()
            recovered = GameNotebook("AD" * 20, root)
            self.assertEqual(len(recovered.data["changes"]), 1)
            self.assertEqual(recovered.data["changes"][0]["source"], "older tool history")
            self.assertIn("None prove what is active now",
                          recovered.summary({"session": "new"})["recovery"]["notice"])


    def test_toolbox_returns_exact_saved_change_without_game_write(self):
        from astra_snes.toolbox import Toolbox
        with tempfile.TemporaryDirectory() as temp:
            notebook = GameNotebook("AE" * 20, Path(temp))
            notebook.record("apply_bytes", {"edits": [{"address": "7E0100", "expected": 2, "value": 9}]},
                            {"bytes_written": 1}, {"session": "prior", "epoch": 1})
            class NoBridge:
                def rpc(self, *args, **kwargs):
                    raise AssertionError("Saved change retrieval must not contact the emulator")
            toolbox = Toolbox(NoBridge(), knowledge_directory=Path(temp))
            toolbox.notebook = notebook
            self.assertEqual(toolbox.dispatch("get_saved_change", {"index": 0})["args"]["edits"][0]["value"], 9)
