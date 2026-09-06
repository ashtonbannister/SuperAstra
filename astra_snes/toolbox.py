from __future__ import annotations

import base64
import json
import re
import time

from .context import Cartridge, GameNotebook
from .memory import Scanner, address, bounded_int
from .profiles import match_profile
from .transport import Bridge, BridgeError


def obj(properties: dict) -> dict:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def string(description: str) -> dict:
    return {"type": "string", "description": description}


def integer(description: str) -> dict:
    return {"type": "integer", "description": description}


def enum(values: list[str]) -> dict:
    return {"type": "string", "enum": values}


def tool(name: str, description: str, parameters: dict) -> dict:
    return {"type": "function", "name": name, "description": description,
            "parameters": obj(parameters), "strict": True}


BYTE_EDIT = obj({"address": string("WRAM hex address, e.g. 7E0019."),
                 "value": integer("New byte, 0–255."), "expected": integer("Observed current byte, 0–255.")})
CARTRIDGE_SEGMENTS = {"type": "array", "maxItems": 16, "items": obj({
    "offset": string("Hex cartridge FILE OFFSET, not CPU address."),
    "expected_hex": string("Exact current bytes as hexadecimal."),
    "replacement_hex": string("Equal number of new bytes as hexadecimal.")})}
BUTTONS = {"type": "array", "maxItems": 12, "items": enum(["Up", "Down", "Left", "Right", "Start", "Select", "A", "B", "X", "Y", "L", "R"])}
TOOLS = [
    tool("get_context", "Read the running game, CPU registers, available capabilities, cartridge headers and retained findings.", {}),
    tool("see_screen", "Capture the actual current emulator screen; an image follows the tool result.", {}),
    tool("read_memory", "Read a bounded window of live WRAM. Addresses are hexadecimal strings.",
         {"address": string("WRAM address or offset."), "length": integer("1–4096 bytes.")}),
    tool("read_domain", "Read console memory such as VRAM, CGRAM, OAM, APURAM or CARTRAM. Use an exact exposed name from get_context. Addresses are offsets within that domain; host memory and System Bus are excluded.",
         {"domain": string("Exposed hardware domain name."), "offset": string("Hex domain offset."), "length": integer("1–4096 bytes.")}),
    tool("read_cartridge", "Inspect a window of the locally indexed cartridge. Offsets are ROM file offsets, NOT CPU addresses.",
         {"offset": string("Hex ROM file offset."), "length": integer("1–4096 bytes.")}),
    tool("search_cartridge", "Search the whole locally indexed ROM for exact instruction/data bytes without uploading the whole ROM.",
         {"pattern_hex": string("2–256 bytes as hex, spaces allowed."), "start_offset": string("Hex file offset; use 0 for the beginning.")}),
    tool("disassemble", "Ask the emulator to disassemble CPU code. Decoder uses the core's current M/X flags; inspect mode changes.",
         {"cpu_address": string("24-bit CPU program address in hex, not ROM file offset."), "count": integer("1–128 instructions.")}),
    tool("scan_memory", "Locally scan all WRAM for a value or changes. New/unknown starts a scan; play or observe between refinements. Results alone do not prove a field's meaning.",
         {"mode": enum(["new", "unknown", "equal", "changed", "unchanged", "increased", "decreased"]),
          "width": integer("1, 2, 3 or 4 bytes, little endian; unaligned candidates included."),
          "value": {"type": ["integer", "null"], "description": "Value for new/equal, null otherwise."}}),
    tool("observe", "Observe 1–300 live frames, optionally press SNES buttons, and sample addresses. Optional CPU bus write trace records registers on writes; capability depends on the core. Trace the actual bus address used by code, including mirrors.",
         {"frames": integer("1–300 frames."), "addresses": {"type": "array", "items": string("Hex WRAM address."), "maxItems": 128},
          "buttons": {"type": "array", "items": enum(["Up", "Down", "Left", "Right", "Start", "Select", "A", "B", "X", "Y", "L", "R"])},
          "trace_cpu_address": {"type": ["string", "null"], "description": "Exact 24-bit CPU bus address to trace writes to, or null."}}),
    tool("apply_bytes", "Apply one atomic WRAM patch with expected-value guards and a full Undo checkpoint. Verify the result in-game afterward.",
         {"edits": {"type": "array", "items": BYTE_EDIT, "minItems": 1, "maxItems": 1024}}),
    tool("patch_cartridge", "Patch loaded cartridge code/data atomically with expected-byte guards and Undo for both core state and cartridge bytes. Up to 4096 bytes total. Never changes the original ROM file. Establish mapping and machine-code/asset validity first, then verify actual behavior. Core must expose writable cartridge memory.",
         {"segments": CARTRIDGE_SEGMENTS}),
    tool("create_checkpoint", "Save a named full game checkpoint, current effects, cartridge overlay and WRAM baseline for repeatable experiments. Up to four per bridge session; same name replaces it.",
         {"name": string("Letters/digits/underscores/hyphens, max 48 characters.")}),
    tool("compare_checkpoint", "Compare live WRAM to a checkpoint locally. Returns changed-byte counts by 4 KiB region and the first 128 changes; narrow the range for more detail.",
         {"name": string("Checkpoint name."), "offset": string("Hex WRAM offset."), "length": integer("1–131072 bytes.")}),
    tool("restore_checkpoint", "Rewind the live game to a named checkpoint, including its effects and cartridge overlay. This creates an Undo of the current state.",
         {"name": string("Checkpoint name.")}),
    tool("delete_checkpoint", "Release a named experiment checkpoint.", {"name": string("Checkpoint name.")}),
    tool("cancel_experiment", "Restore an in-progress temporary experiment, including retrying a reported restoration failure.", {}),
    tool("experiment", "Run a temporary branch from a named checkpoint for exactly 1–300 frames, then automatically restore the player's pre-experiment core state, cartridge and effects. Returns branch WRAM changes, watched values, optional trace, and branch screenshot. Empty buttons releases all buttons; compare this control with a changed input. Optional Lua runs ONCE before the first frame; it is not installed as an ongoing effect. Optional cartridge segments apply only inside the branch. A positive result still requires a separate LIVE application.",
         {"name": string("Checkpoint name."), "frames": integer("1–300 frames."), "buttons": BUTTONS,
          "addresses": {"type": "array", "items": string("Hex WRAM address."), "maxItems": 128},
          "source": string("One-shot restricted Lua, or empty string."), "cartridge_segments": CARTRIDGE_SEGMENTS,
          "trace_cpu_address": {"type": ["string", "null"], "description": "Hex CPU bus write address to trace, or null."}}),
    tool("freeze_bytes", "Keep observed WRAM bytes at specified values each frame until stopped. Add a game-mode guard when needed using a generated routine instead.",
         {"name": string("Short alphanumeric name or underscores."), "edits": {"type": "array", "items": BYTE_EDIT, "minItems": 1, "maxItems": 128}}),
    tool("run_routine", "Create NEW game logic, including new spawns, in restricted Lua. No profile needed. Source sees read(offset,width=1), write(offset,value,width=1), rom(file_offset), frame, state, math.floor/ceil/min/max/abs/sqrt, assert/error, ipairs/pairs/next/type/tonumber. All addresses in these functions are integer WRAM offsets, never CPU addresses. No io/os/require/debug/load, no host access. Each invocation has 50k instructions, 512 staged bytes and 1024 retained state nodes. Assert mode/slot conditions before writing. Writes commit after successful execution. One full Undo checkpoint covers installation. Verify with screen/read/observe before claiming success.",
         {"name": string("Routine name, letters/digits/underscores/hyphens; max 48 characters."),
          "source": string("Lua source, at most 20000 characters. Example: if read(0x100)==0x14 then write(0x0DBE,98) end"),
          "frames": integer("1 = once; 0 = every frame until stopped; otherwise 2–216000 invocations.")}),
    tool("get_saved_routine", "Retrieve the source of a previously created routine for this exact ROM. Reassess context before rerunning.",
         {"name": string("Saved routine name.")}),
    tool("remember", "Retain a finding and its evidence for this exact ROM across app restarts. Distinguish hypotheses from tested facts.",
         {"finding": string("Memory structure, address, code behavior, or result, max 2000 characters."),
          "evidence": string("Actual reads, observed behavior, code, user-provided context or source URL, max 2000 characters."),
          "confidence": enum(["hypothesis", "observed", "verified"])}),
    tool("update_investigation", "Save a compact working model and plan for this exact game. Preserve what is still uncertain. Use during unfamiliar-game investigation and before pausing.",
         {key: string("At most 4000 characters; use empty text if not yet known.") for key in
          ("goal", "understanding", "hypotheses", "next_steps", "success_criteria")}),
    tool("search_knowledge", "Search this exact ROM's retained findings, automatic tool evidence, imported source files and memory maps. Use keywords, symbols and addresses; lexical search, not a semantic embedding service.",
         {"query": string("1–300 characters.")}),
    tool("read_source", "Read exact numbered lines from an indexed user-provided source file. Use source IDs from the context or search results.",
         {"source_id": string("Source ID."), "start_line": integer("1-based line number."), "line_count": integer("1–200 lines, at most 20000 characters returned.")}),
    tool("stop_cheats", "Stop frame routines and freezes. Empty name stops all. Does not reverse prior writes; Undo rewinds them.",
         {"name": string("Name, or empty string for all.")}),
    tool("undo", "Restore the entire game to before the most recent mutation, including earlier freezes/routines. Also rewinds gameplay since that command.", {}),
    tool("smw_spawn", "Optional shortcut for the verified SMW ROM. Unfamiliar games use the general investigation and routine tools.",
         {"kind": enum(["star", "chuck", "mushroom", "flower", "one_up"]), "count": integer("1–10, limited by free sprite slots.")}),
    tool("smw_powerup", "Optional verified SMW shortcut.", {"value": integer("0 small, 1 big, 2 cape, 3 flower.")}),
]


class Toolbox:
    def __init__(self, bridge: Bridge, progress=lambda message: None, knowledge_directory=None):
        self.bridge, self.progress = bridge, progress
        self.context: dict | None = None
        self.scanner = Scanner()
        self.notebook: GameNotebook | None = None
        self.cartridge: Cartridge | None = None
        self.pending_image: str | None = None
        self.mutations: list[dict] = []
        self.cancelled = lambda: False
        self.knowledge_directory = knowledge_directory

    def begin(self) -> dict:
        live = self.bridge.rpc("inspect")
        previous = self.context or {}
        if (live["session"], live["romhash"], live["epoch"]) != (previous.get("session"), previous.get("romhash"), previous.get("epoch")):
            self.cartridge = None
            self.scanner = Scanner()
        self.context = live
        self.pending_image = None
        self.notebook = GameNotebook(live["romhash"], self.knowledge_directory)
        self.mutations = []
        return self.get_context()

    def rpc(self, op: str, args: dict | None = None) -> dict:
        if self.cancelled():
            raise BridgeError("Stopped before the next emulator operation.")
        if self.context is None:
            self.begin()
        return self.bridge.rpc(op, args, context=self.context)

    def ensure_cartridge(self) -> Cartridge:
        if self.cartridge is None:
            self.rpc("export_rom")
            data = (self.bridge.directory / "cartridge.bin").read_bytes()
            if len(data) > 16777216:
                raise ValueError("Cartridge exceeds 16 MiB.")
            self.cartridge = Cartridge(data)
        return self.cartridge

    def get_context(self) -> dict:
        self.context = self.rpc("inspect")
        data = dict(self.context)
        data["profile"] = match_profile(data)
        data["notebook"] = self.notebook.summary() if self.notebook else {}
        try:
            data["cartridge_headers"] = self.ensure_cartridge().headers()
        except (BridgeError, OSError, ValueError) as e:
            data["cartridge_error"] = str(e)
        return data

    @staticmethod
    def edits(args: dict) -> tuple[list[dict], list[dict]]:
        writes, expected = [], []
        for edit in args["edits"]:
            a = address(edit["address"])
            writes.append({"address": a, "value": bounded_int(edit["value"], 0, 255, "Byte")})
            expected.append({"address": a, "value": bounded_int(edit["expected"], 0, 255, "Expected byte")})
        return writes, expected

    def dispatch(self, name: str, args: dict) -> dict:
        try:
            result = self._dispatch(name, args)
        except (RuntimeError, ValueError, OSError, KeyError, TypeError) as e:
            self.record(name, args, {"error": str(e), "success": False})
            raise
        self.record(name, args, result)
        return result

    def record(self, name, args, result):
        # Avoid recursively journaling the journal and retrieval results.
        if self.notebook and name not in {"get_context", "search_knowledge", "read_source", "remember", "update_investigation"}:
            try:
                self.notebook.record(name, args, result, self.context)
            except OSError as e:
                self.progress("Could not save tool evidence: " + str(e))

    @staticmethod
    def cartridge_edits(segments):
        if not isinstance(segments, list) or len(segments) > 16:
            raise ValueError("Use at most 16 cartridge segments.")
        writes = []
        for segment in segments:
            offset = int(segment["offset"], 16)
            expected = bytes.fromhex(segment["expected_hex"])
            replacement = bytes.fromhex(segment["replacement_hex"])
            if not expected or len(expected) != len(replacement):
                raise ValueError("Cartridge segments need equal nonzero expected and replacement lengths.")
            writes.extend({"address": offset + i, "value": b, "expected": expected[i]} for i, b in enumerate(replacement))
        if len(writes) > 4096:
            raise ValueError("Patch at most 4096 cartridge bytes per operation.")
        return writes

    def take_image(self):
        png = (self.bridge.directory / "screen.png").read_bytes()
        if len(png) > 10 * 1024 * 1024 or not png.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("Invalid emulator screenshot.")
        self.pending_image = "data:image/png;base64," + base64.b64encode(png).decode("ascii")

    def refresh_after_restore(self, result):
        current = result.get("context") or self.bridge.rpc("inspect")
        if (current["session"], current["romhash"]) != (self.context["session"], self.context["romhash"]):
            raise BridgeError("The game changed during restoration. Reconnect.")
        self.context = current
        self.scanner = Scanner()
        self.cartridge = None

    def _dispatch(self, name: str, args: dict) -> dict:
        if name not in {t["name"] for t in TOOLS}:
            raise ValueError("Unknown agent tool.")
        if name == "get_context":
            return self.get_context()
        if name == "see_screen":
            result = self.rpc("screenshot")
            self.take_image()
            return result
        if name == "read_memory":
            return self.rpc("read", {"address": address(args["address"]), "length": args["length"], "domain": "WRAM"})
        if name == "read_domain":
            return self.rpc("read", {"address": int(args["offset"], 16), "length": args["length"], "domain": args["domain"]})
        if name in ("create_checkpoint", "delete_checkpoint", "cancel_experiment"):
            return self.rpc(name, args)
        if name == "compare_checkpoint":
            return self.rpc(name, {"name": args["name"], "address": address(args["offset"]), "length": args["length"]})
        if name == "experiment":
            data = {"name": args["name"], "frames": args["frames"], "buttons": args["buttons"],
                "addresses": [address(a) for a in args["addresses"]], "source": args["source"],
                "rom_writes": self.cartridge_edits(args["cartridge_segments"]),
                "trace_address": int(args["trace_cpu_address"], 16) if args["trace_cpu_address"] else None}
            started = False
            try:
                self.rpc("experiment", data)
                started = True
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    time.sleep(0.10)
                    result = self.rpc("experiment_result")
                    if result["done"]:
                        started = False
                        result = result["result"]
                        result["sample_addresses"] = args["addresses"]
                        if result.get("screenshot"):
                            self.take_image()
                        return result
                raise BridgeError("Experiment timed out; requesting restoration.")
            finally:
                if started:
                    # Cancellation must be allowed to restore a temporary branch.
                    self.bridge.rpc("cancel_experiment", context=self.context)
        if name == "read_cartridge":
            return self.ensure_cartridge().read(int(args["offset"], 16), args["length"])
        if name == "search_cartridge":
            return self.ensure_cartridge().search(args["pattern_hex"], int(args["start_offset"], 16))
        if name == "disassemble":
            return self.rpc("disassemble", {"address": int(args["cpu_address"], 16), "count": args["count"]})
        if name == "scan_memory":
            result = self.rpc("dump")
            return self.scanner.scan(bytes.fromhex(result["hex"]), result["context"], **args)
        if name == "observe":
            self.rpc("observe", {"frames": args["frames"], "addresses": [address(a) for a in args["addresses"]],
                                 "buttons": args["buttons"], "trace_address": int(args["trace_cpu_address"], 16) if args["trace_cpu_address"] else None})
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                time.sleep(0.15)
                result = self.rpc("observation")
                if result["done"]:
                    result["sample_addresses"] = args["addresses"]
                    return result
            raise BridgeError("Observation did not finish. Keep BizHawk running.")
        if name in ("apply_bytes", "freeze_bytes"):
            writes, expected = self.edits(args)
            data = {"writes": writes, "expected": expected}
            if name == "freeze_bytes":
                data.update(name=args["name"], guards=[])
            result = self.rpc("patch" if name == "apply_bytes" else "hold", data)
        elif name == "patch_cartridge":
            result = self.rpc("patch_rom", {"writes": self.cartridge_edits(args["segments"])})
            self.cartridge = None
        elif name == "run_routine":
            result = self.rpc("routine", args)
            try:
                self.notebook.routine(args["name"], args["source"], args["frames"])
            except OSError as e:
                result["notebook_error"] = "The routine ran, but its source could not be retained: " + str(e)
        elif name == "get_saved_routine":
            if args["name"] not in self.notebook.data["routines"]:
                raise ValueError("No saved routine with that name for this ROM.")
            return self.notebook.data["routines"][args["name"]]
        elif name == "remember":
            return self.notebook.remember(**args)
        elif name == "update_investigation":
            return self.notebook.update_working(**args)
        elif name == "search_knowledge":
            return self.notebook.search(**args)
        elif name == "read_source":
            return self.notebook.read_source(**args)
        elif name == "stop_cheats":
            result = self.rpc("stop_holds", args)
            self.cartridge = None
        elif name in ("undo", "restore_checkpoint"):
            result = self.rpc(name, args)
            self.refresh_after_restore(result)
        elif name == "smw_spawn":
            result = self.rpc("spawn", args)
        elif name == "smw_powerup":
            result = self.rpc("powerup", args)
        else:
            raise ValueError("Tool is not implemented.")
        self.mutations.append({"tool": name, "result": result})
        return result

    def local(self, prompt: str) -> dict:
        """Explicit offline convenience mode, never presented as an AI response."""
        self.begin()
        p = prompt.lower().strip().rstrip(".!?")
        if p in ("undo", "undo that"):
            return self.dispatch("undo", {})
        if p in ("stop", "stop cheats", "stop all cheats"):
            return self.dispatch("stop_cheats", {"name": ""})
        if p in ("drop a star", "drop star", "spawn a star"):
            return self.dispatch("smw_spawn", {"kind": "star", "count": 1})
        m = re.fullmatch(r"(?:put|spawn|add) (\d+) chucks?(?: on (?:the )?screen)?", p)
        if m:
            return self.dispatch("smw_spawn", {"kind": "chuck", "count": int(m[1])})
        if p in ("give me a cape", "give mario a cape", "cape"):
            return self.dispatch("smw_powerup", {"value": 2})
        raise ValueError("Local mode only has a few Mario shortcuts. Select Astra for open-ended prompts on any game.")
