"""Atomic JSON writer for MT5 EA consumption."""
import json
import os
import tempfile
from pathlib import Path


def write_atomic(payload: dict, dst: str) -> None:
    """Write the JSON payload via temp file + os.replace so the EA never
    reads a half-written file (matches the atomic-write pattern from the
    GGTH ensemble weights file)."""
    p = Path(dst)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".sent_", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=True, indent=2)
        os.replace(tmp, p)             # atomic on Windows + POSIX
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass