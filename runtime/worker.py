from __future__ import annotations

import json
import os
import selectors
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from runtime.config import CODE_ROOT, DATA_ROOT as ROOT, RUNTIME_DIR as RUNTIME, LOG_DIR as LOGS
HEARTBEAT = RUNTIME / "worker-heartbeat.json"
INBOX = RUNTIME / "brain-inbox.json"
PID_FILE = RUNTIME / "worker.pid"

sys.path.insert(0, str(CODE_ROOT))
from runtime import queue as queue_engine  # noqa: E402
from runtime import events as event_engine  # noqa: E402
from runtime.boot_report import emit_startup_report  # noqa: E402
from runtime import security as security_policy  # noqa: E402
from runtime.maintenance import run_maintenance  # noqa: E402

RUNNING = True
OWNER = f"worker:{socket.gethostname()}:{os.getpid()}"


def atomic_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def heartbeat(status: str, **extra: Any) -> None:
    atomic_json(HEARTBEAT, {
        "ok": status not in {"error", "stopped"},
        "status": status,
        "owner": OWNER,
        "pid": os.getpid(),
        "time": int(time.time()),
        **extra,
    })


def safe_path(value: str) -> Path:
    candidate = (ROOT / (value or ".")).resolve()
    candidate.relative_to(ROOT)
    return candidate


def execute_local(task: dict[str, Any]) -> tuple[bool, str, str]:
    action = task.get("action") or {}
    kind = str(action.get("type") or "noop")

    if kind == "noop":
        return True, "noop", json.dumps({"ok": True, "message": action.get("message", "noop")}, ensure_ascii=False)

    if kind == "write_file":
        target = safe_path(str(action.get("path") or ""))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(action.get("content") or ""), encoding="utf-8")
        return True, "write_file", json.dumps({"ok": True, "path": str(target), "size": target.stat().st_size}, ensure_ascii=False)

    if kind == "state":
        target = safe_path(str(action.get("path") or "runtime/worker-state.json"))
        payload = action.get("data") or {}
        atomic_json(target, payload)
        return True, "state", json.dumps({"ok": True, "path": str(target)}, ensure_ascii=False)

    if kind == "shell":
        security_policy.validate_local_action(action)
        command = str(action.get("command") or "").strip()
        if not command:
            return False, "shell", "Missing shell command"
        timeout = max(1, min(int(action.get("timeout_seconds", 60)), 300))
        process = subprocess.run(
            command,
            shell=True,
            executable="/bin/bash",
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={
                "PATH": "/usr/local/bin:/usr/bin:/bin",
                "HOME": "/home/eiros",
                "LANG": "C.UTF-8",
            },
        )
        result = {
            "ok": process.returncode == 0,
            "exit_code": process.returncode,
            "stdout": process.stdout[-100000:],
            "stderr": process.stderr[-100000:],
        }
        return process.returncode == 0, "shell", json.dumps(result, ensure_ascii=False)

    return False, kind, f"Unsupported local action type: {kind}"


def publish_brain_due(tasks: list[dict[str, Any]]) -> None:
    if not tasks:
        return
    current: dict[str, Any] = {"revision": 0, "updated_at": 0, "items": []}
    if INBOX.exists():
        try:
            current = json.loads(INBOX.read_text(encoding="utf-8"))
        except Exception:
            pass
    known = {item.get("id") for item in current.get("items", [])}
    for task in tasks:
        event = event_engine.emit(
            text=(
                "Scheduled EIROS brain task is due.\n"
                f"task_id={task['id']}\n"
                f"title={task['title']}\n"
                f"objective={task['objective']}\n"
                f"next_step={task.get('next_step') or ''}"
            ),
            source="scheduler",
            payload={
                "task_id": task["id"],
                "task_revision": task["revision"],
                "title": task["title"],
                "objective": task["objective"],
                "payload": task.get("payload") or {},
                "next_step": task.get("next_step") or "",
            },
            priority=int(task.get("priority", 0)),
            idempotency_key=f"brain:{task['id']}:rev:{task['revision']}",
        )
        if task["id"] in known:
            continue
        current.setdefault("items", []).append({
            "id": task["id"],
            "revision": task["revision"],
            "title": task["title"],
            "objective": task["objective"],
            "payload": task.get("payload") or {},
            "next_step": task.get("next_step") or "",
            "run_at": task.get("run_at"),
            "signalled_at": int(time.time()),
            "status": "pending_model_turn",
            "reverse_event_id": event["id"],
        })
    current["revision"] = int(current.get("revision", 0)) + 1
    current["updated_at"] = int(time.time())
    current["items"] = current["items"][-1000:]
    atomic_json(INBOX, current)


def claim_local() -> dict[str, Any] | None:
    import argparse

    result = queue_engine.cmd_claim(argparse.Namespace(owner=OWNER, lease_seconds=300, mode="local"))
    if not result.get("claimed"):
        return None
    return result["task"]


def finish_local(task: dict[str, Any], ok: bool, action: str, result: str) -> None:
    import argparse

    lease = task["lease"]
    if ok:
        queue_engine.cmd_commit(argparse.Namespace(
            id=task["id"],
            owner=OWNER,
            token=lease["token"],
            expected_revision=task["revision"],
            action=action,
            result=result,
            next_step=task.get("next_step") or "",
            continue_task=False,
            stop_reason=None,
            run_at=0,
            delay_seconds=0,
        ))
    else:
        queue_engine.cmd_fail(argparse.Namespace(
            id=task["id"],
            owner=OWNER,
            token=lease["token"],
            error=result,
            retry=True,
            next_step=task.get("next_step") or "",
            retry_after_seconds=0,
        ))


def drain_due() -> dict[str, Any]:
    brain = queue_engine.mark_brain_due()
    publish_brain_due(brain)
    processed = 0
    failures = 0
    while processed < 32:
        task = claim_local()
        if task is None:
            break
        try:
            ok, action, result = execute_local(task)
        except subprocess.TimeoutExpired:
            ok, action, result = False, "shell", "Command timed out"
        except Exception as exc:
            ok, action, result = False, "worker", f"{type(exc).__name__}: {exc}"
        finish_local(task, ok, action, result)
        processed += 1
        if not ok:
            failures += 1
    return {"brain_due": len(brain), "local_processed": processed, "local_failures": failures}


def next_timeout() -> float:
    wake = queue_engine.next_wakeup()
    if not wake.get("has_task"):
        return 3600.0
    return float(max(0, min(int(wake.get("sleep_seconds") or 0), 3600)))


def stop_handler(_signum: int, _frame: Any) -> None:
    global RUNNING
    RUNNING = False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as client:
            client.sendto(b"stop", str(queue_engine.WAKEUP_SOCKET))
    except OSError:
        pass


def main() -> None:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()) + "\n", encoding="utf-8")
    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)

    try:
        queue_engine.WAKEUP_SOCKET.unlink(missing_ok=True)
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        sock.bind(str(queue_engine.WAKEUP_SOCKET))
        os.chmod(queue_engine.WAKEUP_SOCKET, 0o600)
        sock.setblocking(False)
        selector = selectors.DefaultSelector()
        selector.register(sock, selectors.EVENT_READ)

        maintenance_report = run_maintenance()
        startup_report = emit_startup_report()
        heartbeat("running", startup=True, startup_report=startup_report, maintenance=maintenance_report)
        while RUNNING:
            summary = drain_due()
            timeout = next_timeout()
            heartbeat("waiting", next_timeout_seconds=timeout, **summary)
            events = selector.select(timeout=timeout)
            for key, _ in events:
                try:
                    key.fileobj.recv(4096)
                except BlockingIOError:
                    pass
        heartbeat("stopped")
    except Exception as exc:
        heartbeat("error", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        try:
            queue_engine.WAKEUP_SOCKET.unlink(missing_ok=True)
        except OSError:
            pass
        try:
            PID_FILE.unlink(missing_ok=True)
        except OSError:
            pass


if __name__ == "__main__":
    main()
