from __future__ import annotations

import json
import tempfile
from pathlib import Path

from runtime import watchdog


def main() -> None:
    checks: list[str] = []
    original_state = watchdog.STATE_FILE
    original_doctor = watchdog.run_doctor
    original_tunnel = watchdog.tunnel_health
    original_emit = watchdog.events.emit
    emitted: list[dict] = []

    with tempfile.TemporaryDirectory(prefix="eiros-watchdog-test-") as temp:
        watchdog.STATE_FILE = Path(temp) / "watchdog.json"
        watchdog.events.emit = lambda **kwargs: emitted.append(kwargs) or {"id": f"event-{len(emitted)}"}
        try:
            watchdog.run_doctor = lambda offline=False: {
                "ok": True,
                "status": "ready",
                "checks": [{"name": "worker", "ok": True}],
            }
            watchdog.tunnel_health = lambda: {"ok": True, "status": 200}
            first = watchdog.run_watchdog()
            assert first["transition"] == "initial_healthy" and not emitted
            checks.append("initial healthy suppressed")

            watchdog.tunnel_health = lambda: {"ok": False, "error": "offline"}
            degraded = watchdog.run_watchdog()
            assert degraded["transition"] == "degraded" and len(emitted) == 1
            assert emitted[-1]["source"] == "watchdog"
            checks.append("degraded transition emitted")

            steady = watchdog.run_watchdog()
            assert steady["transition"] == "steady" and len(emitted) == 1
            checks.append("steady state deduplicated")

            watchdog.tunnel_health = lambda: {"ok": True, "status": 200}
            recovered = watchdog.run_watchdog()
            assert recovered["transition"] == "recovered" and len(emitted) == 2
            checks.append("recovery emitted")

            stored = json.loads(watchdog.STATE_FILE.read_text(encoding="utf-8"))
            assert stored["healthy"] is True
            checks.append("state persisted")
        finally:
            watchdog.STATE_FILE = original_state
            watchdog.run_doctor = original_doctor
            watchdog.tunnel_health = original_tunnel
            watchdog.events.emit = original_emit

    print(json.dumps({"ok": True, "checks": checks, "count": len(checks)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
