from __future__ import annotations

import hashlib
import json
import time
import urllib.request
from pathlib import Path
from typing import Any

from runtime import events
from runtime.config import RUNTIME_DIR, load_config
from runtime.doctor import run_doctor

STATE_FILE = RUNTIME_DIR / "watchdog.json"
DEFAULT_HEALTH_URL_FILE = Path("/home/eiros/tunnel-health.url")


def load_previous() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {}
    try:
        value = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def tunnel_health() -> dict[str, Any]:
    settings = load_config()
    configured = settings.get("tunnel", {}).get("health_url_file")
    url_file = Path(str(configured or DEFAULT_HEALTH_URL_FILE)).expanduser()
    try:
        base = url_file.read_text(encoding="utf-8").strip().rstrip("/")
        with urllib.request.urlopen(base + "/readyz", timeout=4) as response:
            body = response.read(1000).decode("utf-8", errors="replace")
            return {"ok": response.status == 200, "status": response.status, "body": body, "url": base}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "url_file": str(url_file)}


def failure_names(doctor: dict[str, Any], tunnel: dict[str, Any]) -> list[str]:
    names = [str(entry.get("name")) for entry in doctor.get("checks", []) if not entry.get("ok")]
    if not tunnel.get("ok"):
        names.append("tunnel")
    return sorted(set(names))


def signature(names: list[str]) -> str:
    raw = "|".join(names) if names else "healthy"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def run_watchdog() -> dict[str, Any]:
    timestamp = int(time.time())
    doctor = run_doctor(offline=False)
    tunnel = tunnel_health()
    failures = failure_names(doctor, tunnel)
    healthy = not failures
    current_signature = signature(failures)
    previous = load_previous()

    previous_healthy = previous.get("healthy")
    previous_signature = previous.get("signature")
    if previous_healthy is None:
        transition = "initial_healthy" if healthy else "initial_degraded"
    elif previous_healthy and not healthy:
        transition = "degraded"
    elif not previous_healthy and healthy:
        transition = "recovered"
    elif previous_signature != current_signature:
        transition = "changed"
    else:
        transition = "steady"

    report = {
        "ok": True,
        "healthy": healthy,
        "transition": transition,
        "signature": current_signature,
        "failures": failures,
        "doctor_status": doctor.get("status"),
        "tunnel": tunnel,
        "time": timestamp,
    }

    settings = load_config()
    channel = str(settings.get("channel") or "default")
    should_notify = transition in {"initial_degraded", "degraded", "recovered", "changed"}
    if should_notify:
        text = "EIROS recovered and is healthy again." if healthy else f"EIROS watchdog detected: {', '.join(failures)}"
        event = events.emit(
            text=text,
            source="watchdog",
            payload=report,
            priority=1000,
            idempotency_key=f"watchdog:{transition}:{current_signature}:{timestamp // 900}",
            channel=channel,
        )
        report["event_id"] = event["id"]

    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    temporary = STATE_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(STATE_FILE)
    return report


def main() -> None:
    print(json.dumps(run_watchdog(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
