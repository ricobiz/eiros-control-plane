from __future__ import annotations

import argparse
import json
import time

from runtime import queue
from runtime.config import RUNTIME_DIR


def main() -> None:
    task_id = f"minute-chat-probe-{int(time.time())}"
    (RUNTIME_DIR / "minute-probe.json").unlink(missing_ok=True)
    args = argparse.Namespace(
        id=task_id,
        title="Six-minute chat continuity probe",
        objective=(
            "Emit one durable reverse-wake event every 60 seconds for six minutes and verify "
            "that ChatGPT replies, acknowledges each event, and continues the active work."
        ),
        payload=json.dumps(
            {"experiment": "minute_chat_continuity", "ticks": 6, "interval_seconds": 60},
            ensure_ascii=False,
        ),
        action=json.dumps(
            {
                "type": "shell",
                "command": "PYTHONPATH=. python3 -m runtime.minute_probe",
                "timeout_seconds": 30,
            },
            ensure_ascii=False,
        ),
        mode="local",
        next_step="Emit the next minute tick until all six are complete.",
        max_steps=6,
        max_attempts=12,
        priority=1800,
        run_at=0,
        delay_seconds=60,
        interval_seconds=60,
        remaining_runs=6,
    )
    task = queue.cmd_enqueue(args)
    print(
        json.dumps(
            {
                "ok": True,
                "task_id": task["id"],
                "status": task["status"],
                "first_run_at": task["run_at"],
                "interval_seconds": task["interval_seconds"],
                "remaining_runs": task["remaining_runs"],
                "max_steps": task["max_steps"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
