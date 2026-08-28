from __future__ import annotations

import json
import os
import time
from pathlib import Path


class AuditLogger:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _append(self, line: str) -> None:
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, line.encode('utf-8'))
        finally:
            os.close(fd)

    def write(
        self,
        event: str,
        *,
        ok: bool,
        file_id: str | None = None,
        share_id: str | None = None,
        size_bytes: int | None = None,
        detail: str = '',
    ) -> None:
        payload: dict[str, object] = {
            'ts': int(time.time()),
            'event': str(event)[:80],
            'ok': bool(ok),
        }
        if file_id:
            payload['file_id'] = str(file_id)
        if share_id:
            payload['share_id'] = str(share_id)
        if size_bytes is not None:
            payload['size_bytes'] = int(size_bytes)
        if detail:
            payload['detail'] = str(detail)[:500]
        line = json.dumps(payload, ensure_ascii=False, separators=(',', ':')) + '\n'
        try:
            self._append(line)
        except OSError:
            return
