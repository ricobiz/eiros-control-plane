from __future__ import annotations

import json
import time
from typing import Any

from runtime import events, queue
from runtime.config import RUNTIME_DIR

REPORT_FILE = RUNTIME_DIR / "maintenance.json"


def run_maintenance() -> dict[str, Any]:
    timestamp = int(time.time())
    cancelled: list[str] = []
    released_claims: list[str] = []
    expired_leaders: list[str] = []

    with queue.locked_store() as store:
        for task in store.get("tasks", []):
            task_id = str(task.get("id") or "")
            if task_id.startswith("startup-") and task.get("status") == "awaiting_brain":
                task["status"] = "cancelled"
                task["stop_reason"] = "legacy_startup_superseded_by_boot_id_deduplication"
                task["updated_at"] = timestamp
                task["revision"] = int(task.get("revision", 0)) + 1
                task["lease"] = None
                cancelled.append(task_id)
            lease = task.get("lease") or {}
            if task.get("status") == "running" and int(lease.get("expires_at", 0)) <= timestamp:
                task["status"] = "queued"
                task["lease"] = None
                task["updated_at"] = timestamp
                task["revision"] = int(task.get("revision", 0)) + 1
                released_claims.append(task_id)

    with events.locked_store() as store:
        for channel, leader in list(store.get("leaders", {}).items()):
            if int((leader or {}).get("lease_until", 0)) <= timestamp:
                store["leaders"].pop(channel, None)
                expired_leaders.append(channel)
        for event in store.get("events", []):
            claim = event.get("claim") or {}
            if event.get("status") == "claimed" and int(claim.get("until", 0)) <= timestamp:
                event["status"] = "pending"
                event["claim"] = None
                released_claims.append(str(event.get("id")))

    report = {
        "ok": True,
        "time": timestamp,
        "cancelled_legacy_startups": cancelled,
        "released_stale_claims": released_claims,
        "expired_leaders": expired_leaders,
    }
    REPORT_FILE.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    print(json.dumps(run_maintenance(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
