from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from runtime import events, queue
from runtime.config import DATA_ROOT, RUNTIME_DIR, load_config

RECONNECT_FILE = RUNTIME_DIR / "reconnect.json"
TERMINAL = {"completed", "failed", "cancelled"}


def _read_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value
    except Exception:
        return fallback


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _compact_task(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": task.get("id"),
        "title": task.get("title"),
        "objective": task.get("objective"),
        "status": task.get("status"),
        "mode": task.get("mode"),
        "priority": task.get("priority", 0),
        "revision": task.get("revision", 0),
        "step": task.get("step", 0),
        "next_step": task.get("next_step") or "",
        "run_at": task.get("run_at"),
        "last_action": task.get("last_action"),
        "last_result": task.get("last_result"),
    }


def _compact_event(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": event.get("id"),
        "seq": event.get("seq"),
        "source": event.get("source"),
        "text": event.get("text"),
        "priority": event.get("priority", 0),
        "status": event.get("status"),
        "created_at": event.get("created_at"),
    }


def build_resume_context(channel: str = "", reason: str = "connector_reconnected") -> dict[str, Any]:
    config = load_config()
    selected_channel = str(channel or config.get("channel") or "default")
    bridge_state = _read_json(DATA_ROOT / ".eiros-state.json", {"revision": 0, "status": "ready", "data": {}})
    operational_state = _read_json(DATA_ROOT / "state.json", {"revision": 0, "status": "ready"})
    brain_inbox = _read_json(RUNTIME_DIR / "brain-inbox.json", {"revision": 0, "items": []})
    queue_state = queue.read_store()
    pulse_state = events.status(100, selected_channel)

    active_tasks = [
        _compact_task(task)
        for task in queue_state.get("tasks", [])
        if task.get("status") not in TERMINAL
    ]
    active_tasks.sort(key=lambda task: (-int(task.get("priority") or 0), int(task.get("run_at") or 0)))

    live_task_ids = {str(task.get("id")) for task in active_tasks}
    inbox_items = []
    for item in brain_inbox.get("items", []):
        task_id = str(item.get("id") or "")
        if item.get("status") != "pending_model_turn":
            continue
        if task_id and task_id not in live_task_ids:
            continue
        inbox_items.append({
            "id": task_id,
            "revision": item.get("revision", 0),
            "title": item.get("title"),
            "objective": item.get("objective"),
            "next_step": item.get("next_step") or "",
            "run_at": item.get("run_at"),
            "reverse_event_id": item.get("reverse_event_id"),
        })

    pending_events = [
        _compact_event(event)
        for event in pulse_state.get("events", [])
        if event.get("status") != "acked"
    ]

    bridge_data = bridge_state.get("data") if isinstance(bridge_state.get("data"), dict) else {}
    objective = str(bridge_data.get("objective") or "").strip()
    next_step = str(bridge_data.get("next_step") or "").strip()

    if not objective and active_tasks:
        objective = str(active_tasks[0].get("objective") or "").strip()
    if not next_step and active_tasks:
        next_step = str(active_tasks[0].get("next_step") or "").strip()

    active_task = operational_state.get("active_task") if isinstance(operational_state.get("active_task"), dict) else {}
    if not objective:
        objective = str(active_task.get("objective") or "").strip()
    if not next_step:
        next_step = str(operational_state.get("next_step") or "").strip()

    has_active_objective = bool(objective) and str(bridge_state.get("status") or "") not in {"idle", "completed", "stopped"}
    resume_required = bool(has_active_objective or inbox_items or pending_events)

    fingerprint_source = {
        "instance_id": config.get("instance_id"),
        "channel": selected_channel,
        "bridge_revision": bridge_state.get("revision", 0),
        "operational_revision": operational_state.get("revision", 0),
        "queue_revision": queue_state.get("revision", 0),
        "brain_revision": brain_inbox.get("revision", 0),
        "latest_event_seq": pulse_state.get("latest_seq", 0),
        "active_task_revisions": [(task.get("id"), task.get("revision")) for task in active_tasks],
    }
    resume_key = hashlib.sha256(
        json.dumps(fingerprint_source, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:24]

    previous = _read_json(RECONNECT_FILE, {})
    epoch = int(previous.get("epoch", 0)) + 1
    timestamp = int(time.time())

    context = {
        "ok": True,
        "resume_required": resume_required,
        "reason": reason,
        "epoch": epoch,
        "resume_key": resume_key,
        "instance_id": config.get("instance_id"),
        "channel": selected_channel,
        "server_time": timestamp,
        "objective": objective or None,
        "next_step": next_step or None,
        "bridge_status": bridge_state.get("status"),
        "bridge_revision": bridge_state.get("revision", 0),
        "operational_status": operational_state.get("status"),
        "active_tasks": active_tasks[:20],
        "brain_inbox": inbox_items[:20],
        "pending_events": pending_events[:20],
        "pending_event_count": len(pending_events),
        "model_directive": (
            "Reconnect to the durable EIROS state. Treat this envelope as authoritative, "
            "inspect core_snapshot only when more detail is required, handle pending events, "
            "and continue the saved objective from next_step without asking Rico to repeat context."
            if resume_required
            else
            "Reconnect is healthy. Mount Pulse and remain ready; there is no unfinished model work."
        ),
    }

    _atomic_json(RECONNECT_FILE, {
        "epoch": epoch,
        "last_resume_key": resume_key,
        "last_requested_at": timestamp,
        "last_reason": reason,
        "last_resume_required": resume_required,
        "instance_id": config.get("instance_id"),
        "channel": selected_channel,
    })
    return context
