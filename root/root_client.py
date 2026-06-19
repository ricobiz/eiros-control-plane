from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any

SOCKET_PATH = Path("/run/eiros-root.sock")


def request(payload: dict[str, Any], timeout: int = 65) -> dict[str, Any]:
    raw = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(timeout)
        client.connect(str(SOCKET_PATH))
        client.sendall(raw)
        chunks: list[bytes] = []
        while True:
            chunk = client.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
            if b"\n" in chunk:
                break
    response = b"".join(chunks).split(b"\n", 1)[0]
    return json.loads(response.decode("utf-8"))


def status() -> dict[str, Any]:
    return request({"op": "status"}, timeout=10)


def execute(command: str, reason: str, timeout_seconds: int = 60, cwd: str = "/") -> dict[str, Any]:
    if not reason.strip():
        raise ValueError("reason is required for root execution")
    return request({
        "op": "exec",
        "command": command,
        "reason": reason,
        "timeout_seconds": max(1, min(int(timeout_seconds), 600)),
        "cwd": cwd,
    }, timeout=max(15, min(int(timeout_seconds), 600)) + 10)
