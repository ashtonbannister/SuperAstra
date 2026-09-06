import copy
import json
from pathlib import Path
import tempfile
import unittest

from astra_snes.agent import AstraAgent
from astra_snes.context import GameNotebook
from astra_snes.toolbox import Toolbox
from harness import Harness, patch
from test_agent import FakeToolbox


def rom_patch(offset=4, value=7, expected=0):
    return {"writes": [{"address": offset, "value": value, "expected": expected}]}


def probe(name="scene", source="", frames=3, rom_writes=None):
    return {"name": name, "source": source, "frames": frames, "addresses": [23],
            "buttons": [], "rom_writes": rom_writes or []}


class ExperimentsTests(unittest.TestCase):
    def setUp(self):
        self.h = Harness(romhash="BC" * 20)

    def test_repeatable_branch_restores_player_state_and_effects(self):
        h = self.h
        h.ram[23] = 8
        self.assertTrue(h.call("create_checkpoint", {"name": "scene"})["ok"])
        h.ram[23] = 19
        h.call("routine", {"name": "counter", "source": "state.n=(state.n or 0)+1;write(40,state.n)", "frames": 0})
        live_ram, live_frame = bytes(h.ram), h.frame
        for _ in range(2):
            self.assertTrue(h.call("experiment", probe(source="assert(read(23)==8);write(23,47)"))["ok"])
            self.assertFalse(h.call("patch", patch())["ok"])
            h.tick(3)
            result = h.call("experiment_result")["result"]["result"]
            self.assertEqual(result["observation"]["elapsed"], 3)
            self.assertEqual(result["observation"]["samples"][-1]["values"], [47])
            self.assertEqual(result["diff"]["changed_bytes"], 1)
            self.assertEqual(bytes(h.ram), live_ram)
            self.assertEqual(h.frame, live_frame)
        h.tick()
        self.assertEqual(h.ram[40], 2)

    def test_cancel_and_failed_source_restore_without_undo(self):
        h = self.h
        h.call("create_checkpoint", {"name": "scene"})
        h.ram[23] = 99
        count = len(h.engine.history)
        self.assertFalse(h.call("experiment", probe(source="write(23,5);error('bad hypothesis')"))["ok"])
        self.assertEqual(h.ram[23], 99)
        h.call("experiment", probe(source="write(23,7)", frames=20))
        h.tick(1)
        self.assertTrue(h.call("cancel_experiment")["ok"])
        self.assertEqual(h.ram[23], 99)
        self.assertEqual(len(h.engine.history), count)
        self.assertEqual(len(h.states), 1)

    def test_cartridge_patches_have_independent_rollback(self):
        h = self.h
        h.call("patch_rom", rom_patch())
        h.call("patch", patch())
        h.call("patch_rom", rom_patch(value=0, expected=7))
        self.assertEqual(h.rom[4], 0)
        self.assertTrue(h.call("undo")["ok"])
        self.assertEqual(h.rom[4], 7)
        h.call("undo")
        self.assertEqual(h.rom[4], 7)
        self.assertEqual(h.ram[10], 0)
        h.call("undo")
        self.assertEqual(h.rom[4], 0)

    def test_cartridge_partial_failure_and_expected_guards(self):
        h = self.h
        h.fail_rom_address = 5
        writes = rom_patch()["writes"] + rom_patch(5, 9)["writes"]
        self.assertFalse(h.call("patch_rom", {"writes": writes})["ok"])
        self.assertEqual(h.rom[4:6], bytes(2))
        self.assertEqual(len(h.states), 0)
        self.assertFalse(h.call("patch_rom", rom_patch(expected=1))["ok"])
        self.assertEqual(h.rom[4], 0)

    def test_experiment_cartridge_overlay_and_checkpoint_restore(self):
        h = self.h
        h.call("patch_rom", rom_patch())
        h.call("create_checkpoint", {"name": "scene"})
        h.call("patch_rom", rom_patch(value=8, expected=7))
        h.ram[23] = 98
        self.assertTrue(h.call("experiment", probe(source="write(23,rom(4))", rom_writes=rom_patch(value=9, expected=7)["writes"]))["ok"])
        h.tick(3)
        result = h.call("experiment_result")["result"]["result"]
        self.assertEqual(result["observation"]["samples"][-1]["values"], [9])
        self.assertEqual(h.rom[4], 8)
        self.assertEqual(h.ram[23], 98)
        h.call("restore_checkpoint", {"name": "scene"})
        self.assertEqual(h.rom[4], 7)
        h.call("undo")
        self.assertEqual(h.rom[4], 8)
        self.assertEqual(h.ram[23], 98)

    def test_checkpoint_cleanup_and_rom_switch_do_not_write_old_rom(self):
        h = self.h
        h.call("patch_rom", rom_patch())
        for i in range(4):
            self.assertTrue(h.call("create_checkpoint", {"name": f"c{i}"})["ok"])
        self.assertFalse(h.call("create_checkpoint", {"name": "full"})["ok"])
        h.romhash = "FF" * 20
        h.rom[4] = 93  # New cartridge has different original contents.
        h.engine.invalidate()
        self.assertEqual(h.rom[4], 93)
        self.assertEqual(len(h.states), 0)
        self.assertEqual(len(h.engine.checkpoints), 0)

    def test_hardware_read_and_checkpoint_diff(self):
        h = self.h
        h.extra_domains["VRAM"][7] = 48
        self.assertEqual(h.call("read", {"domain": "VRAM", "address": 7, "length": 1})["result"]["bytes"], [48])
        self.assertFalse(h.call("read", {"domain": "Waterbox", "address": 0, "length": 1})["ok"])
        h.call("create_checkpoint", {"name": "scene"})
        h.ram[0x1FFFF] = 42
        result = h.call("compare_checkpoint", {"name": "scene", "address": 0x1FFFF, "length": 1})["result"]
        self.assertEqual(result["diff"]["changes"], [{"address": "1FFFF", "before": 0, "after": 42}])

    def test_failed_experiment_restore_retains_state_for_retry(self):
        h = self.h
        h.call("create_checkpoint", {"name": "scene"})
        h.ram[23] = 79
        h.call("experiment", probe(source="write(23,8)"))
        def fail(key):
            raise RuntimeError("Injected restore failure")
        h.api.load = fail
        with self.assertRaisesRegex(Exception, "EXPERIMENT RESTORE FAILED"):
            h.tick(3)
        self.assertTrue(h.engine.probe.restore_failed)
        self.assertFalse(h.engine.poll_probe())
        h.api.load = h.load
        self.assertTrue(h.call("cancel_experiment")["ok"])
        self.assertEqual(h.ram[23], 79)
        self.assertIsNone(h.engine.probe)

    def test_cartridge_changes_disable_verified_layout_shortcuts(self):
        h = Harness()
        h.level()
        self.assertTrue(h.call("patch_rom", rom_patch())["ok"])
        self.assertFalse(h.call("inspect")["result"]["smw"])
        self.assertFalse(h.call("spawn", {"kind": "star", "count": 1})["ok"])
        self.assertTrue(h.call("routine", {"name": "general", "source": "write(23,9)", "frames": 1})["ok"])


class KnowledgeTests(unittest.TestCase):
    def test_large_source_retrieval_and_evidence_persist_per_rom(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            notebook = GameNotebook("AA" * 20, root)
            source = root / "source.asm"
            source.write_text("; unrelated\n" * 9000 + "HealthUpdate: STA $072A\n", encoding="utf-8")
            meta = notebook.import_source(source)
            notebook.record("read_memory", {"address": "072A"}, {"bytes": [4]}, {"frame": 88})
            notebook.update_working(goal="keep health full", understanding="health candidate", hypotheses="072A", next_steps="test damage", success_criteria="health stays full after a hit")
            loaded = GameNotebook("AA" * 20, root)
            result = loaded.search("HealthUpdate")
            self.assertEqual(result["matches"][0]["source_id"], meta["id"])
            self.assertIn("9001: HealthUpdate", loaded.read_source(meta["id"], 9001, 1)["text"])
            self.assertEqual(loaded.data["working"]["goal"], "keep health full")
            self.assertTrue(any(m["kind"] == "evidence" for m in loaded.search("072A")["matches"]))
            self.assertEqual(GameNotebook("BB" * 20, root).search("HealthUpdate")["matches"], [])
            with self.assertRaises(ValueError):
                loaded.read_source("../source", 1, 1)

    def test_budget_pause_resumes_without_replaying_mutation_after_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            toolbox = FakeToolbox()
            toolbox.notebook = GameNotebook("AB" * 20, Path(temp))
            def first(body):
                return {"output": [{"type": "function_call", "call_id": "did_it", "name": "run_routine",
                                    "arguments": '{"name":"new","source":"write(5,3)","frames":1}'}]}
            a = AstraAgent(toolbox, request=first)
            self.assertIn("saved", a.run("invent a shield", max_rounds=1))
            calls_before = len(toolbox.mutations)
            bodies = []
            def second(body):
                bodies.append(copy.deepcopy(body))
                return {"output": [{"type": "message", "content": [{"type": "output_text", "text": "Continue verification"}]}]}
            restarted = AstraAgent(toolbox, request=second)
            self.assertEqual(restarted.run("Continue"), "Continue verification")
            self.assertEqual(len(toolbox.mutations), calls_before)
            self.assertTrue(any(i.get("call_id") == "did_it" and i.get("type") == "function_call_output" for i in bodies[0]["input"]))
            self.assertIn("invent a shield", json.dumps(bodies[0]["input"]))
            self.assertEqual(toolbox.notebook.load_investigation()["goal"], "invent a shield")

    def test_context_trimming_keeps_goal_and_complete_tool_pairs(self):
        cycles = [[{"role": "user", "content": "User request:\nspawn something novel"}]]
        for i in range(40):
            cycles.append([{"type": "function_call", "call_id": str(i), "name": "read_memory", "arguments": "{}"},
                           {"type": "function_call_output", "call_id": str(i), "output": "x" * 1000}])
        result = AstraAgent.trim_cycles(cycles, budget=5000)
        self.assertIn("spawn something", result[0][0]["content"])
        self.assertLess(len(result), len(cycles))
        for cycle in result[1:]:
            self.assertEqual(cycle[0]["call_id"], cycle[1]["call_id"])


if __name__ == "__main__":
    unittest.main()
