from __future__ import annotations

import json
from pathlib import Path
import re

from .memory import address, bounded_int
from .transport import ROOT


def load_profiles() -> list[dict]:
    result = []
    for p in sorted((ROOT / "profiles").glob("*.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data.get("name"), str) or not isinstance(data.get("rom_sha1"), list):
            raise ValueError(f"Invalid profile: {p.name}")
        if not data["rom_sha1"] or any(not re.fullmatch(r"[0-9a-fA-F]{40}", h) for h in data["rom_sha1"]):
            raise ValueError(f"Profile {p.name} needs exact SHA-1 ROM hashes.")
        fields = data.get("fields", {})
        if not isinstance(fields, dict) or len(fields) > 64:
            raise ValueError(f"Invalid fields in {p.name}")
        for name, spec in fields.items():
            if not re.fullmatch(r"[a-z][a-z0-9_]{0,47}", name):
                raise ValueError("Field names use lowercase letters, digits and underscores.")
            a = address(spec["address"])
            width = bounded_int(spec["width"], 1, 4, "Field width")
            if a + width > 0x20000:
                raise ValueError("Field extends past WRAM.")
            bounded_int(spec.get("min", 0), 0, 2 ** (8 * width) - 1, "Field minimum")
            bounded_int(spec["max"], spec.get("min", 0), 2 ** (8 * width) - 1, "Field maximum")
        result.append(data)
    return result


def match_profile(context: dict) -> dict | None:
    if context.get("cartridge_patch_bytes", 0):
        return None
    h = context["romhash"].upper().removeprefix("SHA1:")
    return next((p for p in load_profiles() if h in [x.upper() for x in p["rom_sha1"]]), None)
