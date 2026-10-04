"""OS-owned controller lease; a crashed process releases ownership automatically."""
from __future__ import annotations

import os
from pathlib import Path


class ControllerLease:
    def __init__(self, directory: Path):
        self.path = directory / "controller.lock"
        self.file = None

    def __enter__(self):
        stream = self.path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            stream.close()
            raise RuntimeError(
                "Another SuperAstra controller is active. Stop the personal plugin "
                "client or finish the desktop command before switching controllers."
            ) from exc
        self.file = stream
        return self

    def __exit__(self, *args):
        # Keep the file: unlinking an advisory lock allows a second inode/owner.
        if self.file is not None:
            self.file.close()
            self.file = None
