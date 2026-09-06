import unittest
from harness import Harness, patch


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.h = Harness()

    def test_patch_and_full_undo(self):
        self.h.ram[20] = 9
        self.assertTrue(self.h.call("patch", patch())["ok"])
        self.h.ram[20] = 33
        self.assertTrue(self.h.call("undo")["ok"])
        self.assertEqual(self.h.ram[10], 0)
        self.assertEqual(self.h.ram[20], 9)

    def test_guard_rejects_before_checkpoint(self):
        self.h.ram[10] = 8
        result = self.h.call("patch", patch())
        self.assertFalse(result["ok"])
        self.assertEqual(self.h.save_count, 0)
        self.assertEqual(self.h.ram[10], 8)

    def test_bounds_and_types(self):
        for a, v in [(-1, 2), (131072, 2), (1, 256), (1, -1), (True, 3), (2.1, 0)]:
            with self.subTest(address=a, value=v):
                self.assertFalse(self.h.call("patch", patch(a, v))["ok"])

    def test_missing_and_duplicate_expected(self):
        p = patch()
        p["expected"][0]["address"] = 11
        self.assertFalse(self.h.call("patch", p)["ok"])
        p = patch()
        p["writes"] *= 2
        self.assertFalse(self.h.call("patch", p)["ok"])

    def test_write_failure_rolls_back_whole_transaction(self):
        self.h.fail_address = 11
        self.h.fail_once = True
        p = {"writes": [{"address": 10, "value": 2}, {"address": 11, "value": 3}],
             "expected": [{"address": 10, "value": 0}, {"address": 11, "value": 0}]}
        self.assertFalse(self.h.call("patch", p)["ok"])
        self.assertEqual(self.h.ram[10:12], bytes(2))
        self.assertEqual(len(self.h.states), 0)

    def test_expired_wrong_session_token_rom_and_epoch(self):
        for override in ({"expires": 999}, {"session": "old"}, {"token": "bad"},
                         {"romhash": "another"}, {"epoch": 9}):
            self.assertFalse(self.h.call("patch", patch(), **override)["ok"])
        self.assertEqual(self.h.save_count, 0)

    def test_duplicate_does_not_repeat(self):
        request = self.h.request("patch", patch())
        self.assertTrue(self.h.handle(request)["ok"])
        self.assertFalse(self.h.handle(request)["ok"])
        self.assertEqual(self.h.save_count, 1)

    def test_retains_eight_checkpoints(self):
        for i in range(12):
            self.assertTrue(self.h.call("patch", patch(value=i + 1, expected=i))["ok"])
        self.assertEqual(len(self.h.states), 8)

    def test_hold_reapplies_and_undo_removes(self):
        args = patch(); args.update(name="test", guards=[])
        self.assertTrue(self.h.call("hold", args)["ok"])
        self.h.ram[10] = 9; self.h.tick()
        self.assertEqual(self.h.ram[10], 2)
        self.h.call("undo"); self.h.ram[10] = 7; self.h.tick()
        self.assertEqual(self.h.ram[10], 7)

    def test_conflicting_holds_rejected(self):
        args = patch(); args.update(name="one", guards=[])
        self.h.call("hold", args)
        args = patch(value=3, expected=2); args.update(name="two", guards=[])
        self.assertFalse(self.h.call("hold", args)["ok"])

    def test_unknown_rom_still_supports_generated_routine(self):
        self.h.romhash = "A" * 40
        self.assertFalse(self.h.call("spawn", {"kind": "star", "count": 1})["ok"])
        result = self.h.call("routine", {"name": "novel_action", "source": "assert(read(23)==0); write(23, 107)", "frames": 1})
        self.assertTrue(result["ok"], result)
        self.assertEqual(self.h.ram[23], 107)

    def test_routine_reads_staged_bytes(self):
        r = self.h.call("routine", {"name": "zero", "source": "write(10,0); write(11,read(10))", "frames": 1})
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.h.ram[11], 0)

    def test_routine_duration_and_state(self):
        r = self.h.call("routine", {"name": "count", "source": "state.n=(state.n or 0)+1; write(99,state.n)", "frames": 3})
        self.assertTrue(r["ok"], r)
        self.h.tick(10)
        self.assertEqual(self.h.ram[99], 3)
        self.assertEqual(len(self.h.engine.rules), 0)

    def test_routine_failed_assert_does_not_commit_partial_writes(self):
        r = self.h.call("routine", {"name": "bad", "source": "write(1,8); assert(false, 'no slot')", "frames": 1})
        self.assertFalse(r["ok"])
        self.assertEqual(self.h.ram[1], 0)

    def test_sandbox_has_no_host_escape_capabilities(self):
        for source in ("os.execute('echo bad')", "io.open('bad','w')", "require('socket')",
                       "load('write(1,9)')()", "debug.sethook()", "getmetatable(state)"):
            r = self.h.call("routine", {"name": "bad", "source": source, "frames": 1})
            self.assertFalse(r["ok"], source)

    def test_instruction_budget_stops_infinite_loop(self):
        r = self.h.call("routine", {"name": "loop", "source": "write(1,8); while true do end", "frames": 1})
        self.assertFalse(r["ok"])
        self.assertIn("instruction budget", r["error"])
        self.assertEqual(self.h.ram[1], 0)

    def test_state_size_cycle_and_function_rejected(self):
        for source in ("state.self=state", "state.f=function()end", "for i=1,1100 do state[i]=i end"):
            r = self.h.call("routine", {"name": "bad_state", "source": source, "frames": 1})
            self.assertFalse(r["ok"])

    def test_running_routine_error_disables_it(self):
        r = self.h.call("routine", {"name": "later", "source": "state.n=(state.n or 0)+1; write(44,9); assert(state.n<2)", "frames": 0})
        self.assertTrue(r["ok"], r)
        self.h.ram[44] = 7
        self.h.tick()
        self.assertEqual(self.h.ram[44], 7)
        self.assertEqual(len(self.h.engine.rules), 0)
        self.assertIn("later", self.h.engine.last_routine_error)

    def test_invalidate_clears_effects_and_undo(self):
        self.h.call("routine", {"name": "persist", "source": "write(1,2)", "frames": 0})
        self.h.engine.invalidate()
        self.assertEqual(len(self.h.engine.rules), 0)
        self.assertEqual(len(self.h.states), 0)
        self.assertFalse(self.h.call("undo")["ok"])

    def test_smw_scene_and_slot_guards(self):
        self.assertFalse(self.h.call("spawn", {"kind": "star", "count": 1})["ok"])
        self.h.level()
        for i in range(6): self.h.ram[0x14C8 + i] = 8
        before = bytes(self.h.ram)
        self.assertFalse(self.h.call("spawn", {"kind": "chuck", "count": 5})["ok"])
        self.assertEqual(bytes(self.h.ram), before)

    def test_smw_five_independent_initialized_chucks(self):
        self.h.level()
        self.h.ram[0x1540 + 9] = 255
        r = self.h.call("spawn", {"kind": "chuck", "count": 5})
        self.assertTrue(r["ok"], r)
        spawned = r["result"]["spawned"]
        self.assertEqual(len(spawned), 5)
        self.assertEqual(len({s["x"] for s in spawned}), 5)
        for s in spawned:
            slot = s["slot"]
            self.assertEqual(self.h.ram[0x14C8 + slot], 1)
            self.assertEqual(self.h.ram[0x9E + slot], 0x91)
            self.assertEqual(self.h.ram[0x161A + slot], 255)
            self.assertEqual(self.h.ram[0x1662 + slot], 13)
            self.assertEqual(self.h.ram[0x1540 + slot], 0)


if __name__ == "__main__":
    unittest.main()
