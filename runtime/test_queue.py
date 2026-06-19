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
    results: list[str] = []

    with tempfile.TemporaryDirectory(prefix="eiros-queue-test-") as tmp:
        root = Path(tmp)
        q.QUEUE_FILE = root / "queue.json"
        q.LOCK_FILE = root / "queue.lock"
        q.WAKEUP_SOCKET = root / "missing.sock"

        try:
            task = q.cmd_enqueue(ns(
                id="queue-selftest",
                title="Queue self-test",
                objective="Verify lease, revision, continuation and completion semantics",
                payload=json.dumps({"probe": True}),
                action="{}",
                mode="brain",
                next_step="claim first step",
                max_steps=3,
                max_attempts=3,
                priority=100,
                run_at=0,
                delay_seconds=0,
                interval_seconds=0,
                remaining_runs=1,
            ))
            assert task["status"] == "queued" and task["revision"] == 1
            results.append("enqueue")

            claimed = q.cmd_claim(ns(owner="eiros-selftest", lease_seconds=120, mode="brain"))
            assert claimed["claimed"] is True
            first = claimed["task"]
            assert first["id"] == task["id"] and first["revision"] == 2
            token = first["lease"]["token"]
            results.append("claim")

            try:
                q.cmd_commit(ns(
                    id=task["id"], owner="eiros-selftest", token=token,
                    expected_revision=1, action="stale", result="must fail",
                    next_step="", continue_task=False, stop_reason=None,
                    run_at=0, delay_seconds=0,
                ))
                raise AssertionError("stale revision unexpectedly accepted")
            except RuntimeError as exc:
                assert "Stale revision" in str(exc)
            results.append("stale revision rejected")

            heartbeat = q.cmd_heartbeat(ns(
                id=task["id"], owner="eiros-selftest", token=token,
                lease_seconds=180,
            ))
            assert heartbeat["lease"]["expires_at"] > int(time.time())
            results.append("heartbeat")

            continued = q.cmd_commit(ns(
                id=task["id"], owner="eiros-selftest", token=token,
                expected_revision=2, action="step one", result="ok",
                next_step="claim second step", continue_task=True,
                stop_reason=None, run_at=0, delay_seconds=0,
            ))
            assert continued["status"] == "queued"
            assert continued["step"] == 1 and continued["revision"] == 3
            results.append("continue")

            claimed_again = q.cmd_claim(ns(owner="eiros-selftest", lease_seconds=120, mode="brain"))
            assert claimed_again["claimed"] is True
            second = claimed_again["task"]
            assert second["revision"] == 4
            results.append("claim again")

            completed = q.cmd_commit(ns(
                id=task["id"], owner="eiros-selftest", token=second["lease"]["token"],
                expected_revision=4, action="final step", result="complete",
                next_step="", continue_task=False,
                stop_reason="selftest_complete", run_at=0, delay_seconds=0,
            ))
            assert completed["status"] == "completed"
            assert completed["step"] == 2 and completed["revision"] == 5
            assert completed["stop_reason"] == "selftest_complete"
            results.append("complete")

            final = q.cmd_status(ns(id=task["id"], status=None, mode=None, events=30))
            assert final["status"] == "completed"
            results.append("final status")

            print(json.dumps({
                "ok": True,
                "assertions": 19,
                "checks": results,
            }, ensure_ascii=False, indent=2))
        finally:
            q.QUEUE_FILE = original_queue
            q.LOCK_FILE = original_lock
            q.WAKEUP_SOCKET = original_socket


if __name__ == "__main__":
    main()
