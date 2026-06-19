from __future__ import annotations

import argparse
import json
import time

from runtime import queue as queue_engine
from runtime.worker import drain_due


def main() -> None:
    task_id = f"scheduler-reverse-proof-{int(time.time())}"
    queue_engine.cmd_enqueue(argparse.Namespace(
        id=task_id,
        title="Scheduler reverse wake proof",
        objective="Prove that a timed scheduler task can independently create a new EIROS turn in the mounted ChatGPT conversation.",
        payload=json.dumps({"proof":"scheduler_to_pulse"}),
        action="{}",
        mode="brain",
        next_step="Acknowledge the event and record that scheduler-to-chat autonomy is proven.",
        max_steps=3,
        max_attempts=3,
        priority=1200,
        run_at=int(time.time()),
        delay_seconds=0,
        interval_seconds=0,
        remaining_runs=1,
    ))
    result = drain_due()
    print(json.dumps({"ok": True, "task_id": task_id, "drain": result}, ensure_ascii=False))


if __name__ == "__main__":
    main()
