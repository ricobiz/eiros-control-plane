from __future__ import annotations

import grp
import json
import os
import pwd
import shutil
import socket
import struct
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

SOCKET_PATH = Path("/run/eiros-root.sock")
AUDIT_PATH = Path("/var/log/eiros/root-broker.jsonl")
ALLOWED_USER = "eiros"
ALLOWED_SERVICES = {"eiros-worker.service", "eiros-tunnel.service", "eiros-claude.service"}
MAX_REQUEST_BYTES = 65536


def command_result(process: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    return {
        "ok": process.returncode == 0,
        "exit_code": process.returncode,
        "stdout": process.stdout[-50000:],
        "stderr": process.stderr[-50000:],
    }


def run_command(command: list[str], timeout: int = 60) -> dict[str, Any]:
    process = subprocess.run(command, text=True, capture_output=True, timeout=timeout)
    return command_result(process)


def validate_service(value: Any) -> str:
    service = str(value or "").strip()
    if service not in ALLOWED_SERVICES:
        raise ValueError("Service is not allowed")
    return service


def handle_request(payload: dict[str, Any], runner: Callable[[list[str], int], dict[str, Any]] = run_command) -> dict[str, Any]:
    operation = str(payload.get("op") or "").strip()
    request_id = str(payload.get("request_id") or "")[:120]

    if operation == "status":
        return {
            "ok": True,
            "operation": operation,
            "request_id": request_id,
            "socket": str(SOCKET_PATH),
            "allowed_services": sorted(ALLOWED_SERVICES),
            "time": int(time.time()),
        }

    if operation == "system_snapshot":
        disk = shutil.disk_usage("/")
        return {
            "ok": True,
            "operation": operation,
            "request_id": request_id,
            "load": list(os.getloadavg()),
            "disk_root": {"total": disk.total, "used": disk.used, "free": disk.free},
            "uptime_seconds": float(Path("/proc/uptime").read_text(encoding="utf-8").split()[0]),
            "time": int(time.time()),
        }

    if operation == "service_status":
        service = validate_service(payload.get("service"))
        result = runner(["systemctl", "show", service, "--no-page", "--property=ActiveState,SubState,MainPID,ExecMainStatus,Result"], 20)
        result.update({"operation": operation, "request_id": request_id, "service": service})
        return result

    if operation == "service_restart":
        service = validate_service(payload.get("service"))
        reason = str(payload.get("reason") or "").strip()
        if not reason:
            raise ValueError("A reason is required for service restart")
        result = runner(["systemctl", "restart", service], 90)
        result.update({"operation": operation, "request_id": request_id, "service": service, "reason": reason[:500]})
        return result

    if operation == "service_enable":
        service = validate_service(payload.get("service"))
        reason = str(payload.get("reason") or "").strip()
        if not reason:
            raise ValueError("A reason is required for service enable")
        result = runner(["systemctl", "enable", "--now", service], 90)
        result.update({"operation": operation, "request_id": request_id, "service": service, "reason": reason[:500]})
        return result

    if operation == "journal_tail":
        service = validate_service(payload.get("service"))
        lines = max(1, min(int(payload.get("lines", 100)), 500))
        result = runner(["journalctl", "-u", service, "-n", str(lines), "--no-pager", "--output=short-iso"], 30)
        result.update({"operation": operation, "request_id": request_id, "service": service, "lines": lines})
        return result

    raise ValueError("Unsupported root operation")


def peer_credentials(connection: socket.socket) -> tuple[int, int, int]:
    raw = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    return struct.unpack("3i", raw)


def audit(entry: dict[str, Any]) -> None:
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def read_request(connection: socket.socket) -> dict[str, Any]:
    chunks: list[bytes] = []
    size = 0
    while True:
        chunk = connection.recv(min(8192, MAX_REQUEST_BYTES - size + 1))
        if not chunk:
            break
        chunks.append(chunk)
        size += len(chunk)
        if size > MAX_REQUEST_BYTES:
            raise ValueError("Request is too large")
        if b"\n" in chunk:
            break
    raw = b"".join(chunks).split(b"\n", 1)[0]
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Request must be a JSON object")
    return value


def serve() -> None:
    allowed_uid = pwd.getpwnam(ALLOWED_USER).pw_uid
    allowed_group = grp.getgrnam(ALLOWED_USER).gr_gid
    SOCKET_PATH.unlink(missing_ok=True)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(SOCKET_PATH))
    os.chown(SOCKET_PATH, 0, allowed_group)
    os.chmod(SOCKET_PATH, 0o660)
    server.listen(16)

    while True:
        connection, _ = server.accept()
        started = time.time()
        pid = uid = gid = -1
        payload: dict[str, Any] = {}
        try:
            pid, uid, gid = peer_credentials(connection)
            if uid != allowed_uid:
                raise PermissionError("Peer UID is not allowed")
            payload = read_request(connection)
            response = handle_request(payload)
        except Exception as exc:
            response = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        response["duration_ms"] = int((time.time() - started) * 1000)
        audit({
            "time": int(time.time()),
            "peer": {"pid": pid, "uid": uid, "gid": gid},
            "request": {"op": payload.get("op"), "request_id": payload.get("request_id"), "service": payload.get("service"), "reason": payload.get("reason")},
            "response": {"ok": response.get("ok"), "error": response.get("error"), "exit_code": response.get("exit_code")},
            "duration_ms": response["duration_ms"],
        })
        connection.sendall((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))
        connection.close()


if __name__ == "__main__":
    serve()
