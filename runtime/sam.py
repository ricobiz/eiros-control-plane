from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from runtime import collab as collab_engine
from runtime import events as event_engine
from runtime import queue as queue_engine
from runtime import widget_blackbox
from runtime.config import RUNTIME_DIR, load_config

SAM_VERSION = "1.1.0-companion-pip"
SAM_LOG = RUNTIME_DIR / "sam.jsonl"
SAM_HEARTBEAT = RUNTIME_DIR / "sam-heartbeat.json"
SAM_PID_FILE = RUNTIME_DIR / "sam.pid"
SAM_STATE_FILE = RUNTIME_DIR / "sam-state.json"
WORKER_HEARTBEAT = RUNTIME_DIR / "worker-heartbeat.json"
WORKER_PID_FILE = RUNTIME_DIR / "worker.pid"
PROJECT_ID = "eiros-hub"
THREAD_ID = "first-contact"
FROM_AGENT = "rico"
TO_AGENT = "chatgpt"
SUPERVISOR_INTERVAL_SECONDS = 5
LIVE_HEARTBEAT_SECONDS = 20

RUNNING = True


def _append_log(entry: dict[str, Any]) -> None:
    SAM_LOG.parent.mkdir(parents=True, exist_ok=True)
    with SAM_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        try:
            os.fchmod(fd, 0o660)
        except PermissionError:
            pass
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _process_alive(pid: int) -> bool:
    return pid > 0 and os.path.exists(f"/proc/{pid}")


def _runtime_heartbeat(path: Path, pid_path: Path, max_age: int) -> dict[str, Any]:
    heartbeat = _read_json(path, {})
    try:
        pid = int(pid_path.read_text(encoding="utf-8").strip())
    except Exception:
        pid = int(heartbeat.get("pid") or 0)
    timestamp = int(time.time())
    age = max(0, timestamp - int(heartbeat.get("time") or 0)) if heartbeat else 10**9
    state = str(heartbeat.get("status") or "missing")
    alive = _process_alive(pid)
    return {
        "ok": bool(alive and age <= max_age and state not in {"error", "stopped"}),
        "pid": pid or None,
        "alive": alive,
        "heartbeat_age_seconds": age,
        "status": state,
        "heartbeat": heartbeat,
    }


def _pulse_snapshot(limit: int = 100) -> dict[str, Any]:
    config = load_config()
    return event_engine.status(max(1, min(int(limit), 500)), str(config.get("channel") or "default"))


def _room_history(limit: int = 12) -> dict[str, Any]:
    bounded = max(1, min(int(limit), 100))
    return collab_engine.history(
        project_id=PROJECT_ID,
        thread_id=THREAD_ID,
        limit=bounded,
        after_seq=0,
    )


def _room_tail(limit: int = 12) -> list[dict[str, Any]]:
    history = _room_history(limit)
    messages = list(history.get("messages") or [])
    tail: list[dict[str, Any]] = []
    for item in messages[-limit:]:
        metadata = dict(item.get("metadata") or {})
        tail.append(
            {
                "seq": int(item.get("seq", 0)),
                "message_id": item.get("message_id"),
                "created_at": int(item.get("created_at", 0)),
                "from": item.get("from_agent"),
                "to": item.get("to_agent"),
                "kind": item.get("kind"),
                "status": item.get("status"),
                "content": str(item.get("content") or ""),
                "sam": bool(metadata.get("sam")),
                "sam_request_id": metadata.get("sam_request_id"),
                "transport": metadata.get("transport"),
            }
        )
    return tail


def _delivery_snapshot(pulse: dict[str, Any] | None = None) -> dict[str, Any]:
    timestamp = int(time.time())
    current = pulse or _pulse_snapshot()
    leader = dict(current.get("leader") or {})
    leader_live = bool(leader and int(leader.get("lease_until", 0)) > timestamp)
    summary = dict(current.get("summary") or {})
    return {
        "leader_widget_id": leader.get("widget_id"),
        "leader_live": leader_live,
        "leader_lease_until": leader.get("lease_until"),
        "pending_count": int(current.get("pending_count", 0)),
        "oldest_age_seconds": int(summary.get("oldest_age_seconds", 0)),
        "in_flight": int(summary.get("in_flight", 0)),
        "awaiting_ack": int(summary.get("awaiting_ack", 0)),
        "retry_ready": int(summary.get("retry_ready", 0)),
        "latest_event_seq": int(current.get("latest_seq", 0)),
    }


def _listener_surface_snapshot(hub: dict[str, Any] | None = None, max_age: int = LIVE_HEARTBEAT_SECONDS) -> dict[str, Any]:
    """Describe the newest live ChatGPT Listener and whether native Video PiP owns it."""
    timestamp = int(time.time())
    current = hub if isinstance(hub, dict) else collab_engine.hub_status()
    agents = list(current.get("agents") or [])
    chatgpt = next((item for item in agents if str(item.get("agent_id") or "") == TO_AGENT), {})
    raw_sessions = chatgpt.get("sessions") or []
    sessions = list(raw_sessions.values()) if isinstance(raw_sessions, dict) else list(raw_sessions)
    candidates: list[dict[str, Any]] = []
    for raw in sessions:
        session = dict(raw or {})
        if str(session.get("host") or "") != "chatgpt-pulse-anchor":
            continue
        if session.get("seconds_since_seen") is None:
            age = max(0, timestamp - int(session.get("last_seen") or 0))
        else:
            age = max(0, int(session.get("seconds_since_seen") or 0))
        session["seconds_since_seen"] = age
        candidates.append(session)
    candidates.sort(key=lambda item: int(item.get("last_seen") or 0), reverse=True)
    selected = candidates[0] if candidates else {}
    age = int(selected.get("seconds_since_seen")) if selected and selected.get("seconds_since_seen") is not None else 10**9
    active = bool(selected and age <= max(1, int(max_age)))
    activity = str(selected.get("activity") or "")
    video_pip_active = bool(active and "video-pip:active" in activity)
    if video_pip_active:
        mode = "video_pip"
    elif active and "mode:pip" in activity:
        mode = "host_pip"
    elif active:
        mode = "inline"
    else:
        mode = "offline"
    return {
        "active": active,
        "video_pip_active": video_pip_active,
        "mode": mode,
        "session_id": selected.get("session_id"),
        "host": selected.get("host"),
        "activity": activity,
        "last_seen": selected.get("last_seen"),
        "age_seconds": age if selected else None,
        "max_age_seconds": max(1, int(max_age)),
    }


def status(room_limit: int = 12) -> dict[str, Any]:
    timestamp = int(time.time())
    pulse = _pulse_snapshot()
    delivery = _delivery_snapshot(pulse)
    listener_surface = _listener_surface_snapshot()
    worker = _runtime_heartbeat(WORKER_HEARTBEAT, WORKER_PID_FILE, LIVE_HEARTBEAT_SECONDS)
    supervisor = _runtime_heartbeat(SAM_HEARTBEAT, SAM_PID_FILE, LIVE_HEARTBEAT_SECONDS)
    blackbox = widget_blackbox.status(False, "sam_status")
    pair = ((blackbox.get("latest") or {}).get("pair") or {})
    room_history = _room_history(room_limit)
    next_wakeup = queue_engine.next_wakeup()

    server_ready = bool(worker.get("ok") and supervisor.get("ok"))
    wake_ready_now = bool(server_ready and delivery.get("leader_live"))
    continuous_wake_ready = bool(wake_ready_now and listener_surface.get("video_pip_active"))
    if wake_ready_now:
        state = "ready"
    elif server_ready:
        state = "armed_waiting_for_chatgpt_surface"
    else:
        state = "degraded"

    return {
        "ok": server_ready,
        "state": state,
        "wake_ready_now": wake_ready_now,
        "continuous_wake_ready": continuous_wake_ready,
        "listener_surface": listener_surface,
        "sam_version": SAM_VERSION,
        "server_time": timestamp,
        "hostname": socket.gethostname(),
        "supervisor": supervisor,
        "worker": worker,
        "delivery": delivery,
        "scheduler": next_wakeup,
        "pair_state": pair.get("state"),
        "pair_color": pair.get("color"),
        "pair_summary": pair.get("summary"),
        "room": pair.get("room"),
        "listener": pair.get("listener"),
        "room_latest_seq": int(room_history.get("latest_seq", 0)),
        "room_message_count": int(room_history.get("count", len(room_history.get("messages") or []))),
        "room_tail": _room_tail(room_limit),
        "host_contract": {
            "server_side": "durable queue, scheduler, Room message, Pulse event and retry state",
            "chatgpt_side": "one mounted EIROS MCP App iframe relays ui/message; native Video PiP is the persistent keepalive surface",
            "background_limit": "Video PiP requires a direct user gesture; no VPS process can bypass the ChatGPT host and create a turn by itself",
        },
        "files": {
            "heartbeat": str(SAM_HEARTBEAT),
            "state": str(SAM_STATE_FILE),
            "log": str(SAM_LOG),
            "collab_store": str(RUNTIME_DIR / "collab.json"),
        },
    }


def _message_event(message: dict[str, Any], *, sam_request_id: str = "", transport: str = "sam-supervisor") -> dict[str, Any]:
    config = load_config()
    channel = str(config.get("channel") or "default")
    message_id = str(message.get("message_id") or "")
    metadata = dict(message.get("metadata") or {})
    is_sam = bool(metadata.get("sam"))
    request_id = sam_request_id or str(metadata.get("sam_request_id") or "")
    event = event_engine.emit(
        text=(
            f"SAM_REMOTE_WAKE message_id={message_id} request_id={request_id} "
            f"from={message.get('from_agent')} project_id={message.get('project_id')} "
            f"thread_id={message.get('thread_id')}. "
            "This is a durable Rico-authorized collaboration wake. Claim the addressed message through "
            "dialog_inbox, handle it in the main ChatGPT conversation, then call dialog_ack and ack_event."
        ),
        source=f"collab:{message.get('from_agent') or FROM_AGENT}",
        payload={
            "collab_message_id": message_id,
            "collab_message_seq": message.get("seq"),
            "from_agent": message.get("from_agent") or FROM_AGENT,
            "to_agent": message.get("to_agent") or TO_AGENT,
            "project_id": message.get("project_id") or PROJECT_ID,
            "thread_id": message.get("thread_id") or THREAD_ID,
            "kind": message.get("kind") or "operator",
            "sam": is_sam,
            "sam_version": SAM_VERSION,
            "sam_request_id": request_id,
            "origin_role": metadata.get("origin_role") or "user",
            "authority": metadata.get("authority") or "rico_authorized_durable_continuation",
            "transport": metadata.get("transport") or transport,
            "room_visual_receipt": bool(metadata.get("room_visual_receipt")),
        },
        priority=1000,
        channel=channel,
        idempotency_key=f"collab-to-chatgpt:{message_id}",
    )
    return event


def emit_scheduled_wake(task: dict[str, Any]) -> dict[str, Any]:
    event = event_engine.emit(
        text=(
            "Scheduled EIROS brain task is due.\n"
            f"task_id={task['id']}\n"
            f"task_revision={task['revision']}\n"
            f"title={task['title']}\n"
            f"objective={task['objective']}\n"
            f"next_step={task.get('next_step') or ''}\n\n"
            "Required continuation protocol:\n"
            "1. Call queue_claim with mode='brain' and a unique ChatGPT owner.\n"
            "2. Execute and verify one concrete next step.\n"
            "3. Call queue_commit to finish or schedule the next wake.\n"
            "4. Acknowledge this reverse event after the task state is committed."
        ),
        source="sam:scheduler",
        payload={
            "sam": True,
            "sam_kind": "scheduled_task",
            "sam_version": SAM_VERSION,
            "authority": "rico_authorized_durable_scheduler_continuation",
            "to_agent": TO_AGENT,
            "task_id": task["id"],
            "task_revision": task["revision"],
            "title": task["title"],
            "objective": task["objective"],
            "payload": task.get("payload") or {},
            "next_step": task.get("next_step") or "",
        },
        priority=int(task.get("priority", 0)),
        idempotency_key=f"brain:{task['id']}:rev:{task['revision']}",
    )
    _append_log(
        {
            "time": int(time.time()),
            "action": "scheduled_wake",
            "task_id": task.get("id"),
            "task_revision": task.get("revision"),
            "event_id": event.get("id"),
            "event_seq": event.get("seq"),
        }
    )
    return event


def _ensure_pending_message_wakes() -> list[dict[str, Any]]:
    pending = collab_engine.peek(TO_AGENT, 100, PROJECT_ID, THREAD_ID)
    pulse = _pulse_snapshot(500)
    live_message_ids = {
        str((event.get("payload") or {}).get("collab_message_id") or "")
        for event in pulse.get("events", [])
        if str(event.get("status") or "") != "acked"
    }
    ensured: list[dict[str, Any]] = []
    for message in pending.get("messages", []):
        message_id = str(message.get("message_id") or "")
        metadata = dict(message.get("metadata") or {})
        if not message_id or metadata.get("no_wake") or metadata.get("visual_only"):
            continue
        if message_id in live_message_ids:
            ensured.append({"message_id": message_id, "created": False})
            continue
        event = _message_event(message)
        live_message_ids.add(message_id)
        ensured.append(
            {
                "message_id": message_id,
                "event_id": event.get("id"),
                "event_seq": event.get("seq"),
                "created": True,
            }
        )
    return ensured


def supervise_once() -> dict[str, Any]:
    timestamp = int(time.time())
    ensured = _ensure_pending_message_wakes()
    pulse = _pulse_snapshot(500)
    delivery = _delivery_snapshot(pulse)
    listener_surface = _listener_surface_snapshot()
    worker = _runtime_heartbeat(WORKER_HEARTBEAT, WORKER_PID_FILE, LIVE_HEARTBEAT_SECONDS)
    wake_ready_now = bool(worker.get("ok") and delivery.get("leader_live"))
    continuous_wake_ready = bool(wake_ready_now and listener_surface.get("video_pip_active"))
    state = "ready" if worker.get("ok") and delivery.get("leader_live") else (
        "waiting_for_chatgpt_surface" if worker.get("ok") else "degraded"
    )
    report = {
        "ok": bool(worker.get("ok")),
        "status": state,
        "sam_version": SAM_VERSION,
        "pid": os.getpid(),
        "owner": f"sam:{socket.gethostname()}:{os.getpid()}",
        "time": timestamp,
        "worker_ok": bool(worker.get("ok")),
        "wake_ready_now": wake_ready_now,
        "continuous_wake_ready": continuous_wake_ready,
        "listener_surface": listener_surface,
        "delivery": delivery,
        "ensured_messages": ensured,
        "next_wakeup": queue_engine.next_wakeup(),
    }
    previous = _read_json(SAM_STATE_FILE, {})
    _atomic_json(SAM_HEARTBEAT, report)
    _atomic_json(SAM_STATE_FILE, report)
    if str(previous.get("status") or "") != state or any(item.get("created") for item in ensured):
        _append_log(
            {
                "time": timestamp,
                "action": "supervisor_transition",
                "previous_status": previous.get("status"),
                "status": state,
                "wake_ready_now": report["wake_ready_now"],
                "continuous_wake_ready": report["continuous_wake_ready"],
                "listener_surface": listener_surface,
                "ensured_messages": ensured,
                "pending_count": delivery.get("pending_count"),
                "leader_widget_id": delivery.get("leader_widget_id"),
            }
        )
    return report


def room_send(text: str, idempotency_key: str = "", transport: str = "ssh-termius") -> dict[str, Any]:
    user_text = str(text or "").strip()
    if not user_text:
        raise ValueError("room text is required")

    request_id = str(uuid.uuid4())
    timestamp = int(time.time())
    hostname = socket.gethostname()
    shell_user = os.environ.get("SUDO_USER") or os.environ.get("USER") or "unknown"
    key = str(idempotency_key or f"sam-room:{request_id}")[:240]
    visible_content = (
        f"{user_text}\n\n"
        f"[SERVER → ROOM RECEIPT]\n"
        f"transport={transport}\n"
        f"host={hostname}\n"
        f"shell_user={shell_user}\n"
        f"request_id={request_id}\n"
        f"accepted_at={timestamp}"
    )
    metadata = {
        "sam_room_test": True,
        "sam_version": SAM_VERSION,
        "request_id": request_id,
        "transport": transport,
        "hostname": hostname,
        "shell_user": shell_user,
        "requested_at": timestamp,
        "room_visual_receipt": True,
        "visual_only": True,
        "no_wake": True,
        "original_text": user_text,
    }
    message = collab_engine.send_message(
        from_agent=FROM_AGENT,
        to_agent=FROM_AGENT,
        content=visible_content,
        kind="control",
        project_id=PROJECT_ID,
        thread_id=THREAD_ID,
        expects_reply=False,
        metadata=metadata,
        idempotency_key=key,
    )
    history = _room_history(8)
    room_persisted = any(
        item.get("message_id") == message.get("message_id")
        for item in history.get("messages") or []
    )
    result = {
        "ok": True,
        "sam_version": SAM_VERSION,
        "mode": "room-only",
        "request_id": request_id,
        "message_id": message.get("message_id"),
        "message_seq": message.get("seq"),
        "room_persisted": room_persisted,
        "room_latest_seq": int(history.get("latest_seq", 0)),
        "room_visual_marker": "[SERVER → ROOM RECEIPT]",
        "pulse_event_created": False,
    }
    _append_log({"time": timestamp, "action": "room_send", **result, "text": user_text[:2000]})
    return result


def wake(text: str, idempotency_key: str = "", transport: str = "ssh-termius") -> dict[str, Any]:
    user_text = str(text or "").strip()
    if not user_text:
        raise ValueError("wake text is required")

    request_id = str(uuid.uuid4())
    key = str(idempotency_key or f"sam:{request_id}")[:240]
    timestamp = int(time.time())
    hostname = socket.gethostname()
    shell_user = os.environ.get("SUDO_USER") or os.environ.get("USER") or "unknown"
    visible_content = (
        f"{user_text}\n\n"
        f"[SAM SERVER RECEIPT]\n"
        f"transport={transport}\n"
        f"host={hostname}\n"
        f"shell_user={shell_user}\n"
        f"request_id={request_id}\n"
        f"accepted_at={timestamp}"
    )
    metadata = {
        "sam": True,
        "sam_version": SAM_VERSION,
        "sam_request_id": request_id,
        "origin_role": "user",
        "origin_agent": FROM_AGENT,
        "authority": "direct_user_operator_request",
        "transport": transport,
        "hostname": hostname,
        "shell_user": shell_user,
        "requested_at": timestamp,
        "room_visual_receipt": True,
        "original_text": user_text,
    }
    message = collab_engine.send_message(
        from_agent=FROM_AGENT,
        to_agent=TO_AGENT,
        content=visible_content,
        kind="operator",
        project_id=PROJECT_ID,
        thread_id=THREAD_ID,
        expects_reply=True,
        metadata=metadata,
        idempotency_key=key,
    )
    event = _message_event(message, sam_request_id=request_id, transport=transport)
    room_history = _room_history(8)
    room_visible = any(
        item.get("message_id") == message.get("message_id")
        for item in room_history.get("messages") or []
    )
    delivery = _delivery_snapshot()
    result = {
        "ok": True,
        "sam_version": SAM_VERSION,
        "request_id": request_id,
        "message_id": message.get("message_id"),
        "message_seq": message.get("seq"),
        "room_persisted": room_visible,
        "room_latest_seq": int(room_history.get("latest_seq", 0)),
        "room_visual_marker": "[SAM SERVER RECEIPT]",
        "event_id": event.get("id"),
        "event_seq": event.get("seq"),
        "event_status": event.get("status"),
        "wake_ready_now": delivery.get("leader_live"),
        "delivery": delivery,
        "instruction": "A live mounted EIROS Room or Wake Listener will relay this durable event into ChatGPT.",
    }
    _append_log({"time": timestamp, "action": "wake", **result, "text": user_text[:2000]})
    return result


def _stop_handler(_signum: int, _frame: Any) -> None:
    global RUNNING
    RUNNING = False


def daemon() -> None:
    global RUNNING
    RUNNING = True
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    SAM_PID_FILE.write_text(str(os.getpid()) + "\n", encoding="utf-8")
    signal.signal(signal.SIGTERM, _stop_handler)
    signal.signal(signal.SIGINT, _stop_handler)
    try:
        while RUNNING:
            try:
                supervise_once()
            except Exception as exc:
                report = {
                    "ok": False,
                    "status": "error",
                    "sam_version": SAM_VERSION,
                    "pid": os.getpid(),
                    "time": int(time.time()),
                    "error": f"{type(exc).__name__}: {exc}",
                }
                _atomic_json(SAM_HEARTBEAT, report)
                _append_log({"time": report["time"], "action": "supervisor_error", **report})
            deadline = time.monotonic() + SUPERVISOR_INTERVAL_SECONDS
            while RUNNING and time.monotonic() < deadline:
                time.sleep(min(0.25, max(0.0, deadline - time.monotonic())))
    finally:
        stopped = {
            "ok": False,
            "status": "stopped",
            "sam_version": SAM_VERSION,
            "pid": os.getpid(),
            "time": int(time.time()),
        }
        _atomic_json(SAM_HEARTBEAT, stopped)
        SAM_PID_FILE.unlink(missing_ok=True)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="EIROS SAM — Self-Awake Mechanism")
    sub = root.add_subparsers(dest="command", required=True)

    wake_cmd = sub.add_parser("wake", help="Send a Rico-authorized external wake to ChatGPT/EIROS")
    wake_cmd.add_argument("text", nargs="+", help="Message for EIROS")
    wake_cmd.add_argument("--idempotency-key", default="")
    wake_cmd.add_argument("--transport", default="ssh-termius")

    room_cmd = sub.add_parser("room", help="Send a server-originated message to Room without a wake event")
    room_cmd.add_argument("text", nargs="+", help="Message to show in EIROS Room")
    room_cmd.add_argument("--idempotency-key", default="")
    room_cmd.add_argument("--transport", default="ssh-termius")

    status_cmd = sub.add_parser("status", help="Read SAM, scheduler, Pulse and Room status")
    status_cmd.add_argument("--room-limit", type=int, default=12)
    sub.add_parser("supervise", help="Run one server-side supervision cycle")
    sub.add_parser("daemon", help="Run the persistent SAM supervisor")
    return root


def main() -> None:
    args = parser().parse_args()
    try:
        if args.command == "wake":
            result = wake(" ".join(args.text), args.idempotency_key, args.transport)
        elif args.command == "room":
            result = room_send(" ".join(args.text), args.idempotency_key, args.transport)
        elif args.command == "status":
            result = status(args.room_limit)
        elif args.command == "supervise":
            result = supervise_once()
        else:
            daemon()
            return
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "sam_version": SAM_VERSION,
                    "error": f"{type(exc).__name__}: {exc}",
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
