from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path

from runtime import queue as q


def ns(**kwargs):
    return argparse.Namespace(**kwargs)


def main() -> None:
    original_queue = q.QUEUE_FILE
    original_lock = q.LOCK_FILE
    original_socket = q.WAKEUP_SOCKET
    results = []

    with tempfile.TemporaryDirectory(prefix="eiros-scheduler-") as tmp:
        root = Path(tmp)
        q.QUEUE_FILE = root / "queue.json"
        q.LOCK_FILE = root / "queue.lock"
        q.WAKEUP_SOCKET = root / "missing.sock"

        try:
            immediate = q.cmd_enqueue(ns(
                id="immediate",
                title="Immediate brain task",
                objective="Claim now",
                payload="{}",
                action="{}",
                mode="brain",
                next_step="",
                max_steps=5,
                max_attempts=3,
                priority=1,
                run_at=0,
                delay_seconds=0,
                interval_seconds=0,
                remaining_runs=1,
            ))
            assert immediate["run_at"] <= int(time.time())
            results.append("immediate enqueue")

            delayed = q.cmd_enqueue(ns(
                id="delayed",
                title="Delayed task",
                objective="Wait before claim",
                payload="{}",
                action="{}",
                mode="brain",
                next_step="",
                max_steps=5,
                max_attempts=3,
                priority=100,
                run_at=0,
                delay_seconds=60,
                interval_seconds=0,
                remaining_runs=1,
            ))
            assert delayed["run_at"] >= int(time.time()) + 59
            results.append("delayed enqueue")

            claim = q.cmd_claim(ns(owner="test", lease_seconds=60, mode="brain"))
            assert claim["claimed"] and claim["task"]["id"] == "immediate"
            results.append("due-only claim")

            task = claim["task"]
            committed = q.cmd_commit(ns(
                id=task["id"],
                owner="test",
                token=task["lease"]["token"],
                expected_revision=task["revision"],
                action="step",
                result="ok",
                next_step="later",
                continue_task=True,
                stop_reason=None,
                run_at=0,
                delay_seconds=15,
            ))
            assert committed["status"] == "queued"
            assert committed["run_at"] >= int(time.time()) + 14
            results.append("commit with dynamic delay")

            wake = q.next_wakeup("brain")
            assert wake["has_task"] and wake["sleep_seconds"] >= 14
            results.append("next wakeup")

            recurring = q.cmd_enqueue(ns(
                id="recurring",
                title="Recurring local task",
                objective="Repeat",
                payload="{}",
                action=json.dumps({"type": "noop"}),
                mode="local",
                next_step="repeat",
                max_steps=10,
                max_attempts=10,
                priority=10,
                run_at=0,
                delay_seconds=0,
                interval_seconds=7,
                remaining_runs=3,
            ))
            local_claim = q.cmd_claim(ns(owner="worker", lease_seconds=60, mode="local"))
            assert local_claim["claimed"] and local_claim["task"]["id"] == recurring["id"]
            local_task = local_claim["task"]
            local_commit = q.cmd_commit(ns(
                id=local_task["id"],
                owner="worker",
                token=local_task["lease"]["token"],
                expected_revision=local_task["revision"],
                action="noop",
                result="ok",
                next_step="repeat",
                continue_task=False,
                stop_reason=None,
                run_at=0,
                delay_seconds=0,
            ))
            assert local_commit["status"] == "queued"
            assert local_commit["remaining_runs"] == 2
            assert local_commit["run_at"] >= int(time.time()) + 6
            results.append("interval recurrence")

            q.cmd_reschedule(ns(id="delayed", run_at=0, delay_seconds=0))
            signalled = q.mark_brain_due()
            ids = {item["id"] for item in signalled}
            assert "delayed" in ids
            results.append("brain due signal")

            store = q.read_store()
            assert store["schema_version"] == 2
            assert len(store["events"]) >= 8
            results.append("schema and audit")

            report = {
                "ok": True,
                "checks": len(results),
                "results": results,
                "queue_revision": store["revision"],
            }
            print(json.dumps(report, indent=2))
        finally:
            q.QUEUE_FILE = original_queue
            q.LOCK_FILE = original_lock
            q.WAKEUP_SOCKET = original_socket


if __name__ == "__main__":
    main()
