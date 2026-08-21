from __future__ import annotations

import fcntl
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from runtime.config import RUNTIME_DIR, publish_shared_file
from runtime import widget_pairing

STATE_FILE = RUNTIME_DIR / "widget-blackbox.json"
LOG_FILE = RUNTIME_DIR / "widget-blackbox.jsonl"
LOCK_FILE = RUNTIME_DIR / "widget-blackbox.lock"
TELEMETRY_FILE = RUNTIME_DIR / "room_telemetry.json"
MAX_LOG_LINES = 1000


def _read_json(path: Path, fallback: Any) -> Any:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value
    except Exception:
        return fallback


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        publish_shared_file(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _append_log(entry: dict[str, Any]) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
    try:
        lines = LOG_FILE.read_text(encoding="utf-8").splitlines()
        if len(lines) > MAX_LOG_LINES:
            LOG_FILE.write_text("\n".join(lines[-MAX_LOG_LINES:]) + "\n", encoding="utf-8")
    except Exception:
        pass


def _telemetry_tail(limit: int = 12) -> list[dict[str, Any]]:
    raw = _read_json(TELEMETRY_FILE, {})
    widgets = list((raw.get("widgets") or {}).values()) if isinstance(raw, dict) else []
    widgets.sort(key=lambda item: int((item or {}).get("updated_at", 0)), reverse=True)
    result: list[dict[str, Any]] = []
    for item in widgets[: max(1, min(int(limit), 50))]:
        snap = item.get("snapshot") or {}
        result.append({
            "widget_id": item.get("widget_id"),
            "widget_kind": item.get("widget_kind"),
            "status": item.get("status"),
            "error": item.get("error"),
            "updated_at": item.get("updated_at"),
            "active": snap.get("active") if isinstance(snap, dict) else None,
            "state": snap.get("state") if isinstance(snap, dict) else None,
            "text": snap.get("text") if isinstance(snap, dict) else None,
            "width": snap.get("width") if isinstance(snap, dict) else None,
            "height": snap.get("height") if isinstance(snap, dict) else None,
        })
    return result


def capture(trigger: str = "manual", extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Compute widget health synchronously and persist a black-box snapshot.

    This has no background-process dependency. Any MCP or VPS Ops caller can run it.
    """
    timestamp = int(time.time())
    pair = widget_pairing.compute("chatgpt", "eiros-hub", "first-contact")
    snapshot = {
        "schema_version": 1,
        "captured_at": timestamp,
        "trigger": str(trigger or "manual")[:120],
        "pair": pair,
        "telemetry_tail": _telemetry_tail(),
        "extra": extra or {},
    }

    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_FILE.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            store = _read_json(STATE_FILE, {})
            previous = store.get("latest") or {}
            previous_pair = previous.get("pair") or {}
            changed = str(previous_pair.get("signature") or "") != str(pair.get("signature") or "")
            state_changed = str(previous_pair.get("state") or "") != str(pair.get("state") or "")
            entry = {**snapshot, "changed": changed, "state_changed": state_changed}

            store["schema_version"] = 1
            store["updated_at"] = timestamp
            store["latest"] = entry
            if pair.get("state") == "ready":
                store["last_healthy"] = entry
            else:
                store["last_unhealthy"] = entry
            if changed or state_changed or trigger in {
                "open_collab_room", "open_pulse", "hub_status", "core_snapshot",
                "scheduler_status", "ops_manual", "manual_status",
            }:
                history = list(store.get("history") or [])
                history.append(entry)
                store["history"] = history[-200:]
                _append_log(entry)
            _atomic_json(STATE_FILE, store)
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    return entry


def status(refresh: bool = True, trigger: str = "manual_status") -> dict[str, Any]:
    if refresh:
        capture(trigger)
    store = _read_json(STATE_FILE, {})
    return {
        "ok": True,
        "updated_at": store.get("updated_at", 0),
        "latest": store.get("latest") or {},
        "last_healthy": store.get("last_healthy"),
        "last_unhealthy": store.get("last_unhealthy"),
        "history_tail": list(store.get("history") or [])[-20:],
        "state_file": str(STATE_FILE),
        "log_file": str(LOG_FILE),
    }


def main() -> None:
    print(json.dumps(status(True, "ops_manual"), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
