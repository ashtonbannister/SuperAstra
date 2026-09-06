"""Single-flight, expiring JSON requests shared with the emulator's Lua script.

No open network port, shell commands, eval, or emulator-specific Python package.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parent.parent


class BridgeError(RuntimeError):
    pass


def atomic_json(path: Path, value: object) -> None:
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temp.open("x", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        try:
            temp.chmod(0o600)
        except OSError:
            pass
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


class Bridge:
    def __init__(self, directory: Path | str | None = None, timeout: float = 8.0):
        self.directory = Path(directory or ROOT / "ipc").resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.lock = threading.Lock()
        config_path = self.directory / "config.json"
        if not config_path.exists():
            atomic_json(config_path, {"protocol": 1, "token": secrets.token_hex(32)})
        self.config = json.loads(config_path.read_text(encoding="utf-8"))
        if self.config.get("protocol") != 1 or len(self.config.get("token", "")) != 64:
            raise BridgeError("Invalid bridge config. Remove ipc/config.json and restart both app and Lua script.")

    def heartbeat(self, require_live: bool = True) -> dict:
        p = self.directory / "heartbeat.json"
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            age = time.time() - p.stat().st_mtime
        except (OSError, ValueError):
            raise BridgeError("Open a SNES ROM in BizHawk, then load LOAD-IN-BIZHAWK.lua in Tools → Lua Console.") from None
        if require_live and age > 4:
            raise BridgeError("The emulator bridge is not responding. Unpause BizHawk and check its Lua Console.")
        if data.get("protocol") != 1:
            raise BridgeError("Bridge version mismatch. Reload the Lua script from this folder.")
        if data.get("error"):
            raise BridgeError(data["error"])
        return data

    def rpc(self, op: str, args: dict | None = None, context: dict | None = None) -> dict:
        """Never retry a timed-out mutation: it might already have committed."""
        with self.lock:
            lease = self.directory / "client.lock"
            try:
                fd = os.open(lease, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                raise BridgeError("Another command is in progress. If an app crashed, close it and remove ipc/client.lock.") from None
            try:
                with os.fdopen(fd, "w") as f:
                    f.write(str(os.getpid()))
                live = self.heartbeat()
                ctx = context or live
                request_id = uuid.uuid4().hex
                request = {
                    "protocol": 1, "id": request_id, "token": self.config["token"],
                    "session": ctx["session"], "romhash": ctx["romhash"],
                    "epoch": ctx["epoch"], "expires": time.time() + self.timeout,
                    "op": op, "args": args or {},
                }
                request_path = self.directory / "request.json"
                response_path = self.directory / "response.json"
                atomic_json(request_path, request)
                deadline = time.monotonic() + self.timeout
                while time.monotonic() < deadline:
                    try:
                        reply = json.loads(response_path.read_text(encoding="utf-8"))
                    except (OSError, ValueError):
                        reply = {}
                    if reply.get("id") == request_id:
                        if not reply.get("ok"):
                            raise BridgeError(str(reply.get("error", "Emulator rejected the command.")))
                        return reply.get("result", {})
                    time.sleep(0.025)
                # Removing an unconsumed request prevents a later surprise spawn.
                # Session, epoch, deadline and deduplication also apply inside Lua.
                try:
                    pending = json.loads(request_path.read_text(encoding="utf-8"))
                    if pending.get("id") == request_id:
                        request_path.unlink(missing_ok=True)
                except (OSError, ValueError):
                    pass
                raise BridgeError("No acknowledgement before timeout. The change may have happened; check the game before repeating it. Undo is available if it committed.")
            finally:
                lease.unlink(missing_ok=True)
