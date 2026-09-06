"""Optional real Snes9x game checks. Requires a supplied core, ROM and level state.

Example: python tests/live_smw.py --core /path/snes9x_libretro.so
  --rom /path/game.sfc --state /path/level-start.state --output /path/qa
"""
import argparse
import hashlib
import json
from pathlib import Path

from harness import Harness
from libretro_harness import Emulator
from PIL import Image


def main():
    parser = argparse.ArgumentParser()
    for name in ("core", "rom", "state", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    emulator = Emulator(core=args.core.resolve(), rom=args.rom.resolve())
    romhash = hashlib.sha1(args.rom.read_bytes()).hexdigest().upper()
    report = {"core": emulator.core_name, "version": emulator.core_version, "rom_sha1": romhash,
              "adapter": "Actual Lua command engine connected to live Snes9x WRAM/save states through the test API adapter", "checks": []}
    def reset():
        emulator.load(args.state)
        return Harness(romhash, emulator)
    def capture(name):
        Image.fromarray(emulator.latest).resize((768, 672), Image.Resampling.NEAREST).save(args.output / name)
    try:
        h = reset()
        original = bytes(emulator.wram)
        result = h.call("spawn", {"kind": "star", "count": 1})
        assert result["ok"], result
        slot = result["result"]["spawned"][0]["slot"]
        assert emulator.wram[0x14C8 + slot] == 1
        h.tick(12)
        assert emulator.wram[0x14C8 + slot] == 8
        capture("star-spawn.png")
        h.tick(35)
        assert emulator.wram[0x1490] > 0, "This fixture expects Mario below the falling star"
        report["checks"].append({"name": "Star initialized, fell, and was collected", "passed": True,
                                 "star_timer": emulator.wram[0x1490]})
        assert h.call("undo")["ok"]
        assert bytes(emulator.wram) == original
        report["checks"].append({"name": "Undo restored the complete pre-command WRAM", "passed": True})
        h = reset()
        result = h.call("spawn", {"kind": "chuck", "count": 5})
        assert result["ok"], result
        h.tick(36)
        slots = [s["slot"] for s in result["result"]["spawned"]]
        assert len(set(slots)) == 5
        assert all(emulator.wram[0x14C8 + s] == 8 and emulator.wram[0x9E + s] == 0x91 for s in slots)
        capture("five-chucks.png")
        report["checks"].append({"name": "Five Chucks initialized and remained active after 36 frames", "passed": True, "slots": slots})
        h = reset()
        source = """assert(read(0x100)==0x14)
local coins=read(0x0DBF)
if state.last and coins>state.last then write(0x19,2) end
state.last=coins"""
        result = h.call("routine", {"name": "cape_on_coin_counter_increase", "source": source, "frames": 120})
        assert result["ok"], result
        before = emulator.wram[0x0DBF]
        result = h.call("patch", {"writes": [{"address": 0x0DBF, "value": before + 1}],
                                  "expected": [{"address": 0x0DBF, "value": before}]})
        assert result["ok"], result
        h.tick(1)
        assert emulator.wram[0x19] == 2
        h.tick(5)
        capture("new-routine.png")
        report["checks"].append({"name": "New conditional Lua routine changed powerup when the coin counter increased", "passed": True,
                                 "setup": "The coin-counter increase was injected as a test input; no claim of a physical coin pickup in this check."})
        h = reset()
        assert h.call("create_checkpoint", {"name": "same_scene"})["ok"]
        h.tick(5)
        live_ram, live_frame = bytes(emulator.wram), h.frame
        branch_results = []
        for _ in range(2):
            result = h.call("experiment", {"name": "same_scene", "frames": 30, "buttons": [],
                "addresses": [0x19, 0x94, 0x96], "source": "assert(read(0x100)==0x14);write(0x19,2)", "rom_writes": []})
            assert result["ok"], result
            h.tick(30)
            result = h.call("experiment_result")["result"]["result"]
            assert result["observation"]["elapsed"] == 30
            assert result["observation"]["samples"][-1]["values"][0] == 2
            assert bytes(emulator.wram) == live_ram
            assert h.frame == live_frame
            branch_results.append(result["observation"]["samples"])
        assert branch_results[0] == branch_results[1]
        Image.fromarray(h.branch_image).resize((768, 672), Image.Resampling.NEAREST).save(args.output / "experiment-branch.png")
        report["checks"].append({"name": "Two 30-frame checkpoint experiments produced identical observed results and restored the pre-experiment WRAM and frame", "passed": True,
            "setup": "Generic experiment tool with one-shot Lua setting a known powerup field; no live API call used."})
    finally:
        emulator.close()
    (args.output / "live-results.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
