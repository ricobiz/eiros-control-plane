from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import time
from typing import Any

from runtime import events, queue
from runtime.config import CODE_ROOT, CONFIG_FILE, DATA_ROOT, LOG_DIR, MEMORY_DIR, RUNTIME_DIR, TASK_DIR, load_config
from runtime.version import __version__


def item(name: str, ok: bool, severity: str, details: Any) -> dict[str, Any]:
    return {"name": name, "ok": bool(ok), "severity": severity, "details": details}


def run_doctor(offline: bool = False) -> dict[str, Any]:
    config = load_config()
    checks: list[dict[str, Any]] = []
    checks.append(item("instance_config", bool(config.get("instance_id")), "critical", {
        "path": str(CONFIG_FILE), "instance_id": config.get("instance_id")
    }))
    checks.append(item("widget_domain", bool(config.get("widget_domain")), "warning", {
        "configured": bool(config.get("widget_domain"))
    }))

    paths = (DATA_ROOT, RUNTIME_DIR, LOG_DIR, TASK_DIR, MEMORY_DIR)
    path_status = {str(path): {"exists": path.exists(), "writable": os.access(path, os.W_OK | os.X_OK)} for path in paths}
    checks.append(item("data_directories", all(value["writable"] for value in path_status.values()), "critical", path_status))

    try:
        store = queue.read_store()
        checks.append(item("queue_store", isinstance(store.get("tasks"), list), "critical", {
            "schema_version": store.get("schema_version"), "tasks": len(store.get("tasks", []))
        }))
    except Exception as exc:
        checks.append(item("queue_store", False, "critical", {"error": f"{type(exc).__name__}: {exc}"}))

    try:
        store = events.read_store()
        checks.append(item("event_store", isinstance(store.get("events"), list), "critical", {
            "schema_version": store.get("schema_version"), "events": len(store.get("events", []))
        }))
    except Exception as exc:
        checks.append(item("event_store", False, "critical", {"error": f"{type(exc).__name__}: {exc}"}))

    worker_ok = offline
    worker_details: dict[str, Any] = {"offline_check": offline}
    if not offline:
        try:
            heartbeat = json.loads((RUNTIME_DIR / "worker-heartbeat.json").read_text(encoding="utf-8"))
            pid = int((RUNTIME_DIR / "worker.pid").read_text(encoding="utf-8").strip())
            age = max(0, int(time.time()) - int(heartbeat.get("time", 0)))
            alive = (DATA_ROOT / f"/proc/{pid}").exists() if False else os.path.exists(f"/proc/{pid}")
            worker_ok = alive and age <= 3700 and heartbeat.get("status") not in {"error", "stopped"}
            worker_details = {"pid": pid, "alive": alive, "heartbeat_age_seconds": age, "status": heartbeat.get("status")}
        except Exception as exc:
            worker_ok = False
            worker_details = {"error": f"{type(exc).__name__}: {exc}"}
    checks.append(item("worker", worker_ok, "critical" if not offline else "info", worker_details))

    disk = shutil.disk_usage(DATA_ROOT)
    checks.append(item("disk_free", disk.free >= 512 * 1024 * 1024, "warning", {"free_bytes": disk.free}))

    required = [
        CODE_ROOT / "runtime/server_v2.py",
        CODE_ROOT / "runtime/worker.py",
        CODE_ROOT / "runtime/queue.py",
        CODE_ROOT / "runtime/events.py",
        CODE_ROOT / "runtime/pulse_widget.html",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    checks.append(item("source_integrity", not missing, "critical", {"missing": missing}))

    critical = [entry for entry in checks if entry["severity"] == "critical" and not entry["ok"]]
    warnings = [entry for entry in checks if entry["severity"] == "warning" and not entry["ok"]]
    return {
        "ok": not critical,
        "status": "ready" if not critical and not warnings else ("degraded" if not critical else "failed"),
        "version": __version__,
        "instance_id": config.get("instance_id"),
        "hostname": socket.gethostname(),
        "code_root": str(CODE_ROOT),
        "data_root": str(DATA_ROOT),
        "critical_failures": len(critical),
        "warnings": len(warnings),
        "checks": checks,
        "time": int(time.time()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="EIROS installation and runtime doctor")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = run_doctor(offline=args.offline)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"EIROS {report['version']} — {report['status']}")
        for entry in report["checks"]:
            marker = "OK" if entry["ok"] else ("WARN" if entry["severity"] == "warning" else "FAIL")
            print(f"[{marker}] {entry['name']}: {json.dumps(entry['details'], ensure_ascii=False)}")
    raise SystemExit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
