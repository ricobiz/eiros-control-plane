from __future__ import annotations

import fcntl
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from runtime.config import RUNTIME_DIR
from runtime import widget_pairing

WATCHDOG_FILE = RUNTIME_DIR / "widget-watchdog.json"
WATCHDOG_LOCK = RUNTIME_DIR / "widget-watchdog.lock"


def _read() -> dict[str, Any]:
    try:
        value = json.loads(WATCHDOG_FILE.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _write(value: dict[str, Any]) -> None:
    WATCHDOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="widget-watchdog-", suffix=".json", dir=WATCHDOG_FILE.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, WATCHDOG_FILE)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def evaluate() -> dict[str, Any]:
    timestamp = int(time.time())
    status = widget_pairing.compute("chatgpt", "eiros-hub", "first-contact")
    WATCHDOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with WATCHDOG_LOCK.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            store = _read()
            previous = store.get("latest") or {}
            changed = str(previous.get("signature") or "") != str(status.get("signature") or "")
            state_changed = str(previous.get("state") or "") != str(status.get("state") or "")
            entry = {
                **status,
                "observed_at": timestamp,
                "changed": changed,
                "state_changed": state_changed,
                "previous_state": previous.get("state"),
            }
            store["schema_version"] = 1
            store["updated_at"] = timestamp
            store["latest"] = entry
            store["last_healthy"] = entry if status.get("state") == "ready" else store.get("last_healthy")
            incident_condition = bool(
                status.get("state") == "degraded"
                or (status.get("state") == "starting" and previous.get("state") == "ready")
            )
            if incident_condition:
                old_incident = dict(store.get("active_incident") or {})
                store["active_incident"] = {
                    **entry,
                    "incident_id": f"widget-{status.get('signature')}",
                    "acknowledged": bool(
                        old_incident.get("incident_id") == f"widget-{status.get('signature')}"
                        and old_incident.get("acknowledged")
                    ),
                }
            elif status.get("state") == "starting" and previous.get("state") != "ready":
                store["active_incident"] = None
            elif status.get("state") == "ready" and state_changed and previous:
                prior_incident = store.get("active_incident") or {}
                store["last_recovery"] = {
                    **entry,
                    "recovered_from": prior_incident.get("incident_id") or previous.get("signature"),
                }
                store["active_incident"] = None
            if changed:
                history = list(store.get("history") or [])
                history.append(entry)
                store["history"] = history[-200:]
            _write(store)
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    return entry


def status() -> dict[str, Any]:
    store = _read()
    if not store:
        evaluate()
        store = _read()
    return {
        "ok": True,
        "updated_at": store.get("updated_at", 0),
        "latest": store.get("latest") or {},
        "active_incident": store.get("active_incident"),
        "last_healthy": store.get("last_healthy"),
        "last_recovery": store.get("last_recovery"),
        "history_tail": list(store.get("history") or [])[-20:],
    }


def acknowledge(actor: str = "chatgpt", note: str = "") -> dict[str, Any]:
    WATCHDOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with WATCHDOG_LOCK.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            store = _read()
            incident = dict(store.get("active_incident") or {})
            if not incident:
                return {"ok": True, "acknowledged": False, "reason": "no_active_incident"}
            incident["acknowledged"] = True
            incident["acknowledged_at"] = int(time.time())
            incident["acknowledged_by"] = str(actor or "chatgpt")[:120]
            incident["ack_note"] = str(note or "")[:2000]
            store["active_incident"] = incident
            store["updated_at"] = int(time.time())
            _write(store)
            return {"ok": True, "acknowledged": True, "incident": incident}
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
