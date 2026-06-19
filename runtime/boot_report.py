from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import socket
import time
from pathlib import Path
from typing import Any

from runtime import queue as queue_engine

ROOT = Path(__file__).resolve().parents[1]
STATUS_FILE = ROOT / "runtime" / "server-status.json"
LAST_BOOT_FILE = ROOT / "runtime" / ".last-boot-id"


def atomic_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def emit_startup_report() -> dict[str, Any]:
    disk = shutil.disk_usage("/")
    timestamp = int(time.time())
    try:
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
    except Exception:
        boot_id = "unknown"
    previous_boot = LAST_BOOT_FILE.read_text(encoding="utf-8").strip() if LAST_BOOT_FILE.exists() else ""
    new_boot = bool(boot_id != "unknown" and boot_id != previous_boot)
    status = {
        "ok": True,
        "reason": "server_boot" if new_boot else "bridge_restart",
        "time": timestamp,
        "boot_id": boot_id,
        "new_boot": new_boot,
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "load": list(os.getloadavg()),
        "disk_root": {"total": disk.total, "used": disk.used, "free": disk.free},
        "workspace": str(ROOT),
        "queue": queue_engine.next_wakeup(),
    }
    atomic_json(STATUS_FILE, status)
    if not new_boot:
        status["brain_event"] = {"created": False, "reason": "same_boot"}
        atomic_json(STATUS_FILE, status)
        return status
    LAST_BOOT_FILE.write_text(boot_id + "\n", encoding="utf-8")
    task_id = f"boot-{boot_id[:12]}"
    args = argparse.Namespace(
        id=task_id,
        title="EIROS VPS boot/recovery report",
        objective="Verify EIROS services after VPS boot and resume pending work without waiting for Rico.",
        payload=json.dumps({"status_file": "runtime/server-status.json", "snapshot": status}, ensure_ascii=False),
        action="{}",
        mode="brain",
        next_step="Inspect server status, queue and services; recover failures; resume highest-priority objective.",
        max_steps=12,
        max_attempts=5,
        priority=1000,
        run_at=timestamp,
        delay_seconds=0,
        interval_seconds=0,
        remaining_runs=1,
    )
    try:
        queue_engine.cmd_enqueue(args)
        status["brain_event"] = {"created": True, "task_id": task_id}
    except Exception as exc:
        status["brain_event"] = {"created": False, "error": str(exc)}
    atomic_json(STATUS_FILE, status)
    return status
