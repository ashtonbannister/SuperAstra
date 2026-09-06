import copy
import unittest
from astra_snes.agent import AstraAgent


class FakeToolbox:
    def __init__(self):
        self.mutations = []
        self.pending_image = None
        self.calls = []
        self.cancelled = lambda: False

    def begin(self):
        return {"session": "s", "romhash": "AB" * 20, "title": "Unknown Game"}

    def dispatch(self, name, args):
        self.calls.append((name, args))
        if name == "see_screen":
            raise RuntimeError("Screenshot not supported in this fixture")
        if name == "run_routine":
            self.mutations.append({"name": args["name"]})
            return {"message": "Executed novel routine", "bytes_written": 1}
        return {"bytes": [3]}


class AgentTests(unittest.TestCase):
    def test_api_loop_carries_reasoning_and_tool_result(self):
        bodies = []
        def request(body):
            bodies.append(copy.deepcopy(body))
            if len(bodies) == 1:
                return {"output": [
                    {"type": "reasoning", "id": "r1", "summary": [], "encrypted_content": "test"},
                    {"type": "function_call", "call_id": "c1", "name": "run_routine",
                     "arguments": '{"name":"new","source":"write(5,3)","frames":1}'}]}
            return {"output": [{"type": "message", "content": [{"type": "output_text", "text": "Done"}]}]}
        toolbox = FakeToolbox()
        a = AstraAgent(toolbox, api_key="test-key", request=request)
        self.assertEqual(a.run("invent a new action"), "Done")
        self.assertTrue(any(item.get("encrypted_content") == "test" for item in bodies[1]["input"]))
        self.assertTrue(any(item.get("type") == "function_call_output" and item.get("call_id") == "c1" for item in bodies[1]["input"]))
        self.assertFalse(bodies[0]["store"])
        self.assertNotIn("test-key", str(bodies))

    def test_cancelled_response_cannot_apply_tools(self):
        toolbox = FakeToolbox()
        def request(body):
            a.cancel.set()
            return {"output": [{"type": "function_call", "call_id": "c1", "name": "run_routine", "arguments": "{}"}]}
        a = AstraAgent(toolbox, api_key="test", request=request)
        self.assertIn("Stopped", a.run("do it"))
        self.assertEqual(toolbox.mutations, [])

    def test_failure_after_mutation_reports_partial_execution(self):
        toolbox = FakeToolbox()
        n = 0
        def request(body):
            nonlocal n
            n += 1
            if n == 1:
                return {"output": [{"type": "function_call", "call_id": "c1", "name": "run_routine",
                                    "arguments": '{"name":"test","source":"write(5,3)","frames":1}'}]}
            raise RuntimeError("Network failure")
        a = AstraAgent(toolbox, api_key="test", request=request)
        with self.assertRaisesRegex(RuntimeError, "Earlier changes were applied"):
            a.run("do it")


if __name__ == "__main__":
    unittest.main()
