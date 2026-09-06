"""Address conversion and a local RAM scanner; full dumps never go to the model."""
from __future__ import annotations


def address(value: int | str) -> int:
    if isinstance(value, bool):
        raise ValueError("Address must be an integer offset or a hexadecimal string.")
    if isinstance(value, str):
        value = int(value.strip().removeprefix("$").removeprefix("0x"), 16)
    if not isinstance(value, int):
        raise ValueError("Invalid memory address.")
    if 0x7E0000 <= value <= 0x7FFFFF:
        value -= 0x7E0000
    if not 0 <= value < 0x20000:
        raise ValueError("WRAM addresses must be offsets 00000–1FFFF or SNES addresses 7E0000–7FFFFF.")
    return value


def number(value: str) -> int:
    text = value.strip()
    return int(text[1:], 16) if text.startswith("$") else int(text, 0) if text.lower().startswith("0x") else int(text)


def bounded_int(value: object, low: int, high: int, label: str) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{label} must be an integer from {low} to {high}.")
    return value


class Scanner:
    def __init__(self):
        self.previous: bytes | None = None
        self.candidates: list[int] = []
        self.context: tuple | None = None
        self.width = 1

    def scan(self, dump: bytes, context: dict, mode: str, width: int = 1,
             value: int | None = None) -> dict:
        bounded_int(width, 1, 4, "Width")
        if len(dump) != 0x20000:
            raise ValueError("Expected a complete 128 KiB WRAM snapshot.")
        identity = (context["session"], context["romhash"], context["epoch"])
        reset = mode in ("new", "unknown")
        if mode not in ("new", "unknown", "equal", "changed", "unchanged", "increased", "decreased"):
            raise ValueError("Unknown scan mode.")
        if mode in ("new", "equal"):
            bounded_int(value, 0, 2 ** (8 * width) - 1, "Value")
        if not reset and (self.previous is None or self.context != identity or self.width != width):
            raise ValueError("Start a new scan after changing ROM, loading a state, undoing, or changing width.")
        candidates = range(len(dump) - width + 1) if reset else self.candidates
        result = []
        for a in candidates:
            now = int.from_bytes(dump[a:a + width], "little")
            before = int.from_bytes(self.previous[a:a + width], "little") if not reset else now
            keep = {
                "unknown": True, "new": now == value, "equal": now == value,
                "changed": now != before, "unchanged": now == before,
                "increased": now > before, "decreased": now < before,
            }[mode]
            if keep:
                result.append(a)
        self.previous, self.candidates, self.context, self.width = dump, result, identity, width
        return {"count": len(result), "width": width,
                "candidates": [{"address": f"{a + 0x7E0000:06X}",
                                "value": int.from_bytes(dump[a:a + width], "little")}
                               for a in result[:64]], "truncated": len(result) > 64}
