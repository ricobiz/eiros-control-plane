from __future__ import annotations

import json
import socket
import uuid
from pathlib import Path
from typing import Any

SOCKET_PATH = Path("/run/eiros-root.sock")
ALLOWED_SERVICES = {"eiros-worker.service", "eiros-tunnel.service"}


def request(payload: dict[str, Any], timeout: int = 100) -> dict[str, Any]:
    value = dict(payload)
    value.setdefault("request_id", str(uuid.uuid4()))
    raw = (json.dumps(value, ensure_ascii=False) + "\n").encode("utf-8")
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
    result = json.loads(response.decode("utf-8"))
    if not isinstance(result, dict):
        raise RuntimeError("Root broker returned an invalid response")
    return result


def validate_service(service: str) -> str:
    selected = str(service or "").strip()
    if selected not in ALLOWED_SERVICES:
        raise ValueError("Service is not allowed")
    return selected


def status() -> dict[str, Any]:
    return request({"op": "status"}, timeout=10)


def system_snapshot() -> dict[str, Any]:
    return request({"op": "system_snapshot"}, timeout=10)


def service_status(service: str) -> dict[str, Any]:
    return request({"op": "service_status", "service": validate_service(service)}, timeout=30)


def service_restart(service: str, reason: str) -> dict[str, Any]:
    if not str(reason or "").strip():
        raise ValueError("A reason is required")
    return request({"op": "service_restart", "service": validate_service(service), "reason": reason}, timeout=110)


def service_enable(service: str, reason: str) -> dict[str, Any]:
    if not str(reason or "").strip():
        raise ValueError("A reason is required")
    return request({"op": "service_enable", "service": validate_service(service), "reason": reason}, timeout=110)


def journal_tail(service: str, lines: int = 100) -> dict[str, Any]:
    return request({"op": "journal_tail", "service": validate_service(service), "lines": max(1, min(int(lines), 500))}, timeout=40)
