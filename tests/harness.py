"""Execute the actual Lua engine with a small emulator API test adapter."""
from __future__ import annotations
import json
from pathlib import Path
import uuid
from lupa import LuaRuntime

ROOT = Path(__file__).resolve().parents[1]
SMW = "6B47BB75D16514B6A476AA0C73A683A2A4C18765"


class Harness:
    def __init__(self, romhash=SMW, emulator=None):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.emulator = emulator
        self.ram = emulator.wram if emulator else bytearray(0x20000)
        self.rom = emulator.rombytes if emulator else bytearray(0x80000)
        self.extra_domains = {"VRAM": bytearray(65536), "CGRAM": bytearray(512)}
        self.observation = None
        self.branch_image = None
        self.romhash = romhash
        self.frame = 1
        self.states = {}
        self.save_count = 0
        self.fail_address = None
        self.fail_once = False
        self.fail_rom_address = None
        self.api = self.lua.table_from({
            "read": self.read, "write": self.write, "size": self.size,
            "frame": lambda: self.frame, "game": lambda: self.table({"romhash": self.romhash, "title": "Test game", "system": "SNES"}),
            "save": self.save, "load": self.load, "drop": lambda k: self.states.pop(k, None),
            "domain_allowed": lambda d: d in self.extra_domains,
            "observe": self.observe, "observation": self.get_observation,
            "cancel_observation": self.cancel_observation, "screenshot": self.screenshot,
        })
        if not emulator:
            self.api.write_rom = self.write_rom
        smw = self.lua.execute((ROOT / "emulator/smw.lua").read_text())(self.api)
        sandbox = self.lua.execute((ROOT / "emulator/sandbox.lua").read_text())(self.api)
        cartridge = self.lua.execute((ROOT / "emulator/cartridge_patch.lua").read_text())(self.api)
        self.engine = self.lua.execute((ROOT / "emulator/engine.lua").read_text())(
            self.api, smw, "secret", "session", lambda: 1000, sandbox, cartridge)
        self.json = self.lua.execute((ROOT / "emulator/json.lua").read_text())

    def table(self, obj):
        return self.lua.table_from(obj, recursive=True)

    def read(self, domain, a):
        return (self.ram if domain == "WRAM" else self.rom if domain == "ROM" else self.extra_domains[domain])[int(a)]

    def size(self, domain):
        return len(self.ram if domain == "WRAM" else self.rom if domain == "ROM" else self.extra_domains[domain])

    def write_rom(self, a, v):
        if int(a) == self.fail_rom_address:
            self.fail_rom_address = None
            raise RuntimeError("Injected cartridge write failure")
        self.rom[int(a)] = int(v)

    def observe(self, args):
        self.observation = {"start": self.frame, "args": json.loads(self.json.encode(args)), "samples": [], "done": False}
        return self.table({"message": "Started fixture observation."})

    def get_observation(self):
        if self.observation is None:
            raise RuntimeError("No observation")
        o = self.observation
        return self.table({"done": o["done"], "samples": o["samples"], "elapsed": self.frame - o["start"], "writes": []})

    def cancel_observation(self):
        self.observation = None

    def screenshot(self):
        if self.emulator:
            self.branch_image = self.emulator.latest.copy()
        else:
            raise RuntimeError("This fixture has no video")

    def write(self, a, v):
        a, v = int(a), int(v)
        if a == self.fail_address:
            if self.fail_once:
                self.fail_address = None
            raise RuntimeError("Injected write failure")
        self.ram[a] = v

    def save(self):
        self.save_count += 1
        key = str(self.save_count)
        if self.emulator:
            import ctypes as C
            e = self.emulator
            e.lib.retro_serialize_size.restype = C.c_size_t
            n = e.lib.retro_serialize_size()
            buf = C.create_string_buffer(n)
            e.lib.retro_serialize.argtypes = [C.c_void_p, C.c_size_t]
            assert e.lib.retro_serialize(buf, n)
            data = buf.raw
        else:
            data = bytes(self.ram)
        self.states[key] = (data, self.frame)
        return key

    def load(self, key):
        data, self.frame = self.states[key]
        if self.emulator:
            import ctypes as C
            buf = C.create_string_buffer(data)
            self.emulator.lib.retro_unserialize.argtypes = [C.c_void_p, C.c_size_t]
            assert self.emulator.lib.retro_unserialize(buf, len(data))
        else:
            self.ram[:] = data

    def request(self, op, args=None, **overrides):
        request = {"protocol": 1, "id": uuid.uuid4().hex, "token": "secret", "session": "session",
                   "romhash": self.romhash, "epoch": self.engine.epoch, "expires": 1005,
                   "op": op, "args": args or {}}
        request.update(overrides)
        return request

    def handle(self, request):
        response = self.engine.handle(self.table(request))
        return json.loads(self.json.encode(response))

    def call(self, op, args=None, **overrides):
        return self.handle(self.request(op, args, **overrides))

    def tick(self, frames=1):
        for _ in range(frames):
            if self.emulator:
                buttons = self.observation["args"].get("buttons", []) if self.observation else []
                self.emulator.run(1, [b.upper() for b in buttons])
            self.frame += 1
            self.engine.tick()
            if self.observation:
                o = self.observation
                o["samples"].append({"frame": self.frame, "values": [self.ram[a] for a in o["args"]["addresses"]]})
                o["done"] = self.frame - o["start"] >= o["args"]["frames"]
                self.engine.poll_probe()

    def level(self):
        self.ram[0x100] = 0x14
        self.ram[0x94] = 100
        self.ram[0x96] = 150


def patch(address=10, value=2, expected=0):
    return {"writes": [{"address": address, "value": value}],
            "expected": [{"address": address, "value": expected}]}
