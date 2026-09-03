from __future__ import annotations

import json
import os
import time
from pathlib import Path

_DENY = {"password", "secret", "token", "api_key", "private_key", "value", "content"}


class AuditLog:
    def __init__(self, path: Path = Path("/var/log/eiros/operator-audit.jsonl")) -> None:
        self.path = Path(path)

    def write(
        self,
        tool: str,
        ok: bool,
        target: dict[str, object],
        duration_ms: int,
        rollback_id: str = "",
    ) -> None:
        safe = {k: v for k, v in target.items() if k.lower() not in _DENY}
        event = {
            "ts": time.time(),
            "tool": tool,
            "ok": bool(ok),
            "duration_ms": int(duration_ms),
            "target": safe,
            "rollback_id": rollback_id,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, (json.dumps(event, ensure_ascii=False) + "\n").encode())
        finally:
            os.close(fd)
