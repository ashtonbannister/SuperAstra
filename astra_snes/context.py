"""ROM-specific retained findings and a local cartridge index."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path
import re
import time

from .transport import ROOT, atomic_json


class GameNotebook:
    def __init__(self, romhash: str, directory: Path | None = None):
        key = romhash.upper().removeprefix("SHA1:")
        if not re.fullmatch(r"[0-9A-F]{40}", key):
            raise ValueError("Cannot retain context without an exact ROM SHA-1.")
        self.path = (directory or ROOT / "knowledge") / (key + ".json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {
            "rom_sha1": key, "findings": [], "routines": {}, "user_notes": ""}
        for field, default in (("events", []), ("sources", {}), ("working", {})):
            self.data.setdefault(field, default)
        self.sources_path = self.path.parent / "sources" / key
        self.investigation_path = self.path.with_suffix(".investigation.json")

    def remember(self, finding: str, evidence: str, confidence: str) -> dict:
        if confidence not in ("hypothesis", "observed", "verified"):
            raise ValueError("Use hypothesis, observed, or verified for confidence.")
        if not 1 <= len(finding) <= 2000 or not 1 <= len(evidence) <= 2000:
            raise ValueError("Finding and evidence must each be 1–2000 characters.")
        self.data["findings"].append({"finding": finding, "evidence": evidence, "confidence": confidence})
        self.data["findings"] = self.data["findings"][-1000:]
        self.save()
        return {"message": "Saved this finding for this exact ROM.", "confidence": confidence}

    def routine(self, name: str, source: str, frames: int) -> None:
        self.data["routines"][name] = {"source": source, "frames": frames, "verified": False}
        if len(self.data["routines"]) > 32:
            del self.data["routines"][next(iter(self.data["routines"]))]
        self.save()

    def save(self) -> None:
        atomic_json(self.path, self.data)

    def summary(self) -> dict:
        return {"findings": self.data["findings"][-16:],
                "finding_count": len(self.data["findings"]),
                "saved_routines": list(self.data["routines"]),
                "user_notes": self.data.get("user_notes", "")[:8000],
                "sources": list(self.data["sources"].values()),
                "working": self.data["working"],
                "recent_evidence": [{**e, "args": e["args"][:600], "result": e["result"][:1400]} for e in self.data["events"][-5:]],
                "retrieval": "Use search_knowledge for older evidence and source text; read_source for exact lines."}

    def record(self, tool: str, args: dict, result: dict, context: dict | None) -> None:
        """Save observed evidence automatically; never upgrade it to a verified fact."""
        def excerpt(value, limit):
            text = json.dumps(value, ensure_ascii=False)
            return text if len(text) <= limit else text[:limit] + " [truncated]"
        self.data["events"].append({"time": int(time.time()), "tool": tool,
            "args": excerpt(args, 22000), "result": excerpt(result, 16000),
            "context": {**{k: (context or {}).get(k) for k in ("session", "epoch", "romhash")},
                        "frame_at_last_inspection": (context or {}).get("frame")}})
        self.data["events"] = self.data["events"][-500:]
        self.save()

    def update_working(self, **fields) -> dict:
        allowed = {"goal", "understanding", "hypotheses", "next_steps", "success_criteria"}
        if set(fields) != allowed or any(not isinstance(v, str) or len(v) > 4000 for v in fields.values()):
            raise ValueError("Supply all five working-context fields, each at most 4000 characters.")
        self.data["working"] = fields
        self.save()
        return {"message": "Saved the investigation plan for this exact ROM."}

    def import_source(self, path: Path) -> dict:
        if path.stat().st_size > 8 * 1024 * 1024:
            raise ValueError("A source file can be at most 8 MiB.")
        raw = path.read_bytes()
        text = raw.decode("utf-8-sig")
        if "\x00" in text:
            raise ValueError("Import UTF-8 text/source, not binary data.")
        key = hashlib.sha256(raw).hexdigest()[:24]
        sources = self.data["sources"]
        if key not in sources and (len(sources) >= 32 or sum(s["bytes"] for s in sources.values()) + len(raw) > 32 * 1024 * 1024):
            raise ValueError("This ROM already has the maximum 32 sources or 32 MiB of source text.")
        self.sources_path.mkdir(parents=True, exist_ok=True)
        (self.sources_path / (key + ".txt")).write_text(text, encoding="utf-8")
        sources[key] = {"id": key, "name": path.name, "bytes": len(raw), "lines": len(text.splitlines())}
        self.save()
        return {"message": "Indexed " + path.name + " for this ROM. Astra can search it and read exact lines.", **sources[key]}

    def read_source(self, source_id: str, start_line: int, line_count: int) -> dict:
        if source_id not in self.data["sources"] or not re.fullmatch(r"[0-9a-f]{24}", source_id):
            raise ValueError("Unknown source ID for this ROM.")
        if type(start_line) is not int or type(line_count) is not int or start_line < 1 or not 1 <= line_count <= 200:
            raise ValueError("Use a positive start line and 1–200 lines.")
        lines = (self.sources_path / (source_id + ".txt")).read_text(encoding="utf-8").splitlines()
        if start_line > len(lines):
            raise ValueError("Start line exceeds this source.")
        text = "\n".join(f"{i + 1}: {lines[i]}" for i in range(start_line - 1, min(len(lines), start_line - 1 + line_count)))
        return {"source": self.data["sources"][source_id], "start_line": start_line,
                "text": text[:20000], "truncated": len(text) > 20000}

    def search(self, query: str) -> dict:
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 300:
            raise ValueError("Search query must have 1–300 characters.")
        terms = set(re.findall(r"[a-z0-9_$]+", query.lower())) - {"the", "a", "and", "of", "in", "to", "for"}
        if not terms:
            raise ValueError("Search for a game concept, symbol or address.")
        candidates = []
        def add(kind, text, metadata):
            lower = text.lower()
            score = sum(min(lower.count(term), 4) for term in terms)
            if score:
                candidates.append((score, len(candidates), {"kind": kind, **metadata, "excerpt": text[:2000]}))
        for i, fact in enumerate(self.data["findings"]):
            add("finding", json.dumps(fact, ensure_ascii=False), {"index": i})
        for i, event in enumerate(self.data["events"]):
            raw = json.dumps(event, ensure_ascii=False)
            for start in range(0, len(raw), 1600):
                add("evidence", raw[start:start + 2000], {"index": i, "tool": event["tool"]})
        add("working", json.dumps(self.data["working"]), {})
        notes = self.data.get("user_notes", "")
        for start in range(0, len(notes), 1600):
            add("legacy_notes", notes[start:start + 2000], {"character_offset": start})
        for source_id, meta in self.data["sources"].items():
            lines = (self.sources_path / (source_id + ".txt")).read_text(encoding="utf-8").splitlines()
            for start in range(0, len(lines), 20):
                # A long data line must not hide a match late in that line.
                for i in range(start, min(start + 20, len(lines))):
                    line = lines[i]
                    if any(term in line.lower() for term in terms):
                        pos = min(line.lower().find(t) for t in terms if t in line.lower())
                        excerpt = "\n".join(lines[max(0, i - 2):i + 4]) if len(line) < 1500 else line[max(0, pos - 400):pos + 1400]
                        add("source", excerpt, {"source_id": source_id, "name": meta["name"], "start_line": max(1, i - 1)})
                        break
        matches = sorted(candidates, key=lambda item: (item[0], item[1]), reverse=True)
        return {"query": query, "matches": [item[2] for item in matches[:8]], "total_matches": len(matches)}

    def load_investigation(self) -> dict:
        if not self.investigation_path.exists():
            return {}
        return json.loads(self.investigation_path.read_text(encoding="utf-8"))

    def save_investigation(self, value: dict) -> None:
        atomic_json(self.investigation_path, value)


class Cartridge:
    def __init__(self, data: bytes):
        self.data = data

    def headers(self) -> list[dict]:
        results = []
        for offset, mapper in ((0x7FC0, "LoROM"), (0xFFC0, "HiROM"), (0x40FFC0, "ExHiROM")):
            if offset + 64 > len(self.data):
                continue
            h = self.data[offset:offset + 64]
            checksum = int.from_bytes(h[30:32], "little")
            complement = int.from_bytes(h[28:30], "little")
            title = h[:21].decode("ascii", errors="replace").strip()
            plausible = all(32 <= c <= 126 for c in h[:21])
            results.append({"file_offset": f"{offset:06X}", "candidate_mapper": mapper,
                            "title": title, "map_mode": f"{h[21]:02X}", "cartridge_type": f"{h[22]:02X}",
                            "checksum_pair_valid": checksum ^ complement == 0xFFFF,
                            "printable_title": plausible,
                            "native_nmi": f"{int.from_bytes(h[42:44], 'little'):04X}",
                            "reset_vector": f"{int.from_bytes(h[60:62], 'little'):04X}"})
        return results

    def read(self, offset: int, length: int) -> dict:
        if type(offset) is not int or type(length) is not int or not 1 <= length <= 4096:
            raise ValueError("Read length must be 1–4096 bytes.")
        if not 0 <= offset <= len(self.data) - length:
            raise ValueError("Cartridge read exceeds its size.")
        data = self.data[offset:offset + length]
        return {"file_offset": f"{offset:06X}", "hex": data.hex(" "),
                "ascii": "".join(chr(b) if 32 <= b <= 126 else "." for b in data)}

    def search(self, pattern_hex: str, start: int = 0) -> dict:
        pattern = bytes.fromhex(pattern_hex)
        if not 2 <= len(pattern) <= 256 or not 0 <= start < len(self.data):
            raise ValueError("Search needs 2–256 exact bytes and an in-range start offset.")
        matches = []
        offset = start
        while len(matches) < 65:
            offset = self.data.find(pattern, offset)
            if offset < 0:
                break
            matches.append(f"{offset:06X}")
            offset += 1
        return {"file_offsets": matches[:64], "truncated": len(matches) > 64}
