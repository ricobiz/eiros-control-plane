from __future__ import annotations

import json
import time

from runtime import events
from runtime.config import RUNTIME_DIR, load_config

STATE = RUNTIME_DIR / "minute-probe.json"
TOTAL = 6


def main() -> None:
    try:
        state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    except Exception:
        state = {}
    tick = int(state.get("tick", 0)) + 1
    timestamp = int(time.time())
    config = load_config()
    channel = str(config.get("channel") or "default")
    final = tick >= TOTAL
    event = events.emit(
        text=(
            f"MINUTE_PROBE tick={tick}/{TOTAL} time={timestamp}. "
            "Reply in this chat with a short status confirming the tick, "
            "acknowledge this event, and then continue the current EIROS work."
        ),
        source="minute-probe",
        payload={"tick": tick, "total": TOTAL, "time": timestamp, "final": final},
        priority=1800,
        channel=channel,
        idempotency_key=f"minute-probe:{timestamp // 60}:{tick}",
    )
    STATE.write_text(
        json.dumps(
            {
                "tick": tick,
                "total": TOTAL,
                "last_event_id": event["id"],
                "last_time": timestamp,
                "completed": final,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"ok": True, "tick": tick, "event_id": event["id"], "final": final}))


if __name__ == "__main__":
    main()
