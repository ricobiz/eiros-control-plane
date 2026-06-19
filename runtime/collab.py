from __future__ import annotations

import fcntl
import json
import os
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from runtime.config import RUNTIME_DIR

STORE_FILE = RUNTIME_DIR / "collab.json"
LOCK_FILE = RUNTIME_DIR / "collab.lock"
SCHEMA_VERSION = 1
MAX_MESSAGES = 10000


def now() -> int:
    return int(time.time())


def empty_store() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "revision": 0,
        "updated_at": now(),
        "next_seq": 1,
        "agents": {},
        "projects": {},
        "controls": {},
        "messages": [],
    }


def _atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        try:
            os.fchmod(fd, 0o660)
        except PermissionError:
            pass
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _load() -> dict[str, Any]:
    if not STORE_FILE.exists():
        return empty_store()
    value = json.loads(STORE_FILE.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("collaboration store root is not an object")
    version = int(value.get("schema_version", 1))
    if version > SCHEMA_VERSION:
        raise RuntimeError(f"unsupported collaboration schema: {version}")
    value.setdefault("revision", 0)
    value.setdefault("updated_at", now())
    value.setdefault("next_seq", 1)
    value.setdefault("agents", {})
    value.setdefault("projects", {})
    value.setdefault("controls", {})
    value.setdefault("messages", [])
    value["schema_version"] = SCHEMA_VERSION
    return value


@contextmanager
def locked_store() -> Iterator[dict[str, Any]]:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    with LOCK_FILE.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        store = _load()
        yield store
        store["revision"] = int(store.get("revision", 0)) + 1
        store["updated_at"] = now()
        store["messages"] = store["messages"][-MAX_MESSAGES:]
        _atomic_write(STORE_FILE, store)
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def read_store() -> dict[str, Any]:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    with LOCK_FILE.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_SH)
        store = _load()
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        return store


def normalize_agent(value: str) -> str:
    result = str(value or "").strip().lower().replace(" ", "-")[:80]
    if not result:
        raise ValueError("agent_id is required")
    if not all(ch.isalnum() or ch in "-_" for ch in result):
        raise ValueError("agent_id may contain only letters, digits, hyphen and underscore")
    return result


def _control_value(store: dict[str, Any], project_id: str) -> dict[str, Any]:
    project = str(project_id or "default").strip()[:120] or "default"
    current = store.get("controls", {}).get(project)
    if current:
        return current
    return {
        "project_id": project,
        "revision": 0,
        "mode": "running",
        "note": "",
        "updated_at": 0,
        "updated_by": None,
    }


def _message_deliverable(store: dict[str, Any], message: dict[str, Any]) -> bool:
    control = _control_value(store, str(message.get("project_id") or "default"))
    mode = str(control.get("mode") or "running")
    if mode == "running":
        return True
    return message.get("from_agent") == "rico" or message.get("kind") in {"control", "operator"}


def register_agent(
    agent_id: str,
    display_name: str = "",
    client_kind: str = "native-chat",
    capabilities: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    identity = normalize_agent(agent_id)
    timestamp = now()
    with locked_store() as store:
        current = store["agents"].get(identity, {})
        agent = {
            **current,
            "agent_id": identity,
            "display_name": str(display_name or current.get("display_name") or identity)[:120],
            "client_kind": str(client_kind or current.get("client_kind") or "native-chat")[:80],
            "capabilities": sorted({str(item)[:120] for item in (capabilities or current.get("capabilities") or [])}),
            "metadata": metadata or current.get("metadata") or {},
            "status": "online",
            "registered_at": int(current.get("registered_at") or timestamp),
            "last_seen": timestamp,
        }
        store["agents"][identity] = agent
        return agent


def heartbeat(agent_id: str, status: str = "online") -> dict[str, Any]:
    identity = normalize_agent(agent_id)
    with locked_store() as store:
        current = store["agents"].get(identity)
        if not current:
            current = {
                "agent_id": identity,
                "display_name": identity,
                "client_kind": "native-chat",
                "capabilities": [],
                "metadata": {},
                "registered_at": now(),
            }
        current["status"] = str(status or "online")[:40]
        current["last_seen"] = now()
        store["agents"][identity] = current
        return current


def session_heartbeat(
    agent_id: str,
    session_id: str,
    host: str = "native-chat",
    widget_version: str = "",
    activity: str = "online",
) -> dict[str, Any]:
    identity = normalize_agent(agent_id)
    session = str(session_id or "").strip()[:160]
    if not session:
        raise ValueError("session_id is required")
    timestamp = now()
    with locked_store() as store:
        current = store["agents"].get(identity)
        if not current:
            current = {
                "agent_id": identity,
                "display_name": identity,
                "client_kind": str(host or "native-chat")[:80],
                "capabilities": [],
                "metadata": {},
                "registered_at": timestamp,
            }
        sessions = dict(current.get("sessions") or {})
        sessions = {
            key: value
            for key, value in sessions.items()
            if timestamp - int((value or {}).get("last_seen", 0)) <= 180
        }
        sessions[session] = {
            "session_id": session,
            "host": str(host or "native-chat")[:80],
            "widget_version": str(widget_version or "")[:80],
            "activity": str(activity or "online")[:40],
            "last_seen": timestamp,
        }
        current["sessions"] = sessions
        current["status"] = str(activity or "online")[:40]
        current["last_seen"] = timestamp
        current["active_session_count"] = len(sessions)
        store["agents"][identity] = current
        return current


def send_message(
    from_agent: str,
    to_agent: str,
    content: str,
    kind: str = "call",
    project_id: str = "default",
    thread_id: str = "main",
    scene_id: str = "",
    reply_to: str = "",
    expects_reply: bool = True,
    metadata: dict[str, Any] | None = None,
    idempotency_key: str = "",
) -> dict[str, Any]:
    sender = normalize_agent(from_agent)
    recipient = normalize_agent(to_agent)
    text = str(content or "").strip()
    if not text:
        raise ValueError("content is required")
    project = str(project_id or "default").strip()[:120] or "default"
    thread = str(thread_id or "main").strip()[:160] or "main"
    key = str(idempotency_key or "").strip()[:240]
    with locked_store() as store:
        if key:
            for existing in store["messages"]:
                if existing.get("idempotency_key") == key:
                    return existing
        seq = int(store["next_seq"])
        store["next_seq"] = seq + 1
        message = {
            "message_id": str(uuid.uuid4()),
            "seq": seq,
            "project_id": project,
            "thread_id": thread,
            "scene_id": str(scene_id or "")[:160],
            "from_agent": sender,
            "to_agent": recipient,
            "kind": str(kind or "call")[:40],
            "content": text[:50000],
            "reply_to": str(reply_to or "")[:120] or None,
            "expects_reply": bool(expects_reply),
            "metadata": metadata or {},
            "idempotency_key": key or None,
            "status": "pending",
            "created_at": now(),
            "claim": None,
            "delivery_attempts": 0,
            "acked_at": None,
            "ack_result": None,
        }
        store["messages"].append(message)
        return message


def _claim_alive(claim: dict[str, Any] | None, timestamp: int) -> bool:
    return bool(claim and int(claim.get("until", 0)) > timestamp)


def inbox(
    agent_id: str,
    client_id: str,
    limit: int = 10,
    claim_seconds: int = 180,
    project_id: str = "",
    thread_id: str = "",
) -> dict[str, Any]:
    identity = normalize_agent(agent_id)
    client = str(client_id or "").strip()[:160]
    if not client:
        raise ValueError("client_id is required")
    count = max(1, min(int(limit), 50))
    lease = max(30, min(int(claim_seconds), 900))
    timestamp = now()
    with locked_store() as store:
        agent = store["agents"].get(identity)
        if agent:
            agent["last_seen"] = timestamp
            agent["status"] = "online"
        selected: list[dict[str, Any]] = []
        for message in sorted(store["messages"], key=lambda item: int(item.get("seq", 0))):
            if message.get("status") == "acked":
                continue
            if message.get("to_agent") not in {identity, "broadcast", "all"}:
                continue
            if project_id and message.get("project_id") != project_id:
                continue
            if thread_id and message.get("thread_id") != thread_id:
                continue
            if not _message_deliverable(store, message):
                continue
            claim = message.get("claim") or {}
            if _claim_alive(claim, timestamp):
                continue
            message["status"] = "claimed"
            message["delivery_attempts"] = int(message.get("delivery_attempts", 0)) + 1
            message["claim"] = {
                "agent_id": identity,
                "client_id": client,
                "claimed_at": timestamp,
                "until": timestamp + lease,
            }
            selected.append(message)
            if len(selected) >= count:
                break
        pending = sum(
            1
            for message in store["messages"]
            if message.get("status") != "acked" and message.get("to_agent") in {identity, "broadcast", "all"}
        )
        return {
            "agent_id": identity,
            "client_id": client,
            "messages": selected,
            "claimed_count": len(selected),
            "pending_count": pending,
            "server_time": timestamp,
            "store_revision": int(store.get("revision", 0)) + 1,
        }


def peek(
    agent_id: str,
    limit: int = 10,
    project_id: str = "",
    thread_id: str = "",
) -> dict[str, Any]:
    identity = normalize_agent(agent_id)
    count = max(1, min(int(limit), 50))
    store = read_store()
    timestamp = now()
    selected: list[dict[str, Any]] = []
    for message in sorted(store["messages"], key=lambda item: int(item.get("seq", 0))):
        if message.get("status") == "acked":
            continue
        if message.get("to_agent") != identity:
            continue
        if project_id and message.get("project_id") != project_id:
            continue
        if thread_id and message.get("thread_id") != thread_id:
            continue
        if not _message_deliverable(store, message):
            continue
        claim = message.get("claim") or {}
        if _claim_alive(claim, timestamp):
            continue
        selected.append(message)
        if len(selected) >= count:
            break
    pending = sum(
        1
        for message in store["messages"]
        if message.get("status") != "acked"
        and message.get("to_agent") == identity
        and _message_deliverable(store, message)
    )
    return {
        "agent_id": identity,
        "messages": selected,
        "available_count": len(selected),
        "pending_count": pending,
        "server_time": timestamp,
        "store_revision": int(store.get("revision", 0)),
    }


def acknowledge(agent_id: str, message_id: str, result: str = "") -> dict[str, Any]:
    identity = normalize_agent(agent_id)
    target = str(message_id or "").strip()
    if not target:
        raise ValueError("message_id is required")
    with locked_store() as store:
        for message in store["messages"]:
            if message.get("message_id") != target:
                continue
            if message.get("to_agent") not in {identity, "broadcast", "all"}:
                raise RuntimeError("message belongs to another recipient")
            message["status"] = "acked"
            message["acked_at"] = now()
            message["ack_result"] = str(result or "")[:20000]
            message["ack_agent"] = identity
            message["claim"] = None
            return message
    raise RuntimeError(f"message not found: {target}")


def release(agent_id: str, message_id: str, reason: str = "") -> dict[str, Any]:
    identity = normalize_agent(agent_id)
    target = str(message_id or "").strip()
    with locked_store() as store:
        for message in store["messages"]:
            if message.get("message_id") != target:
                continue
            claim = message.get("claim") or {}
            if claim.get("agent_id") != identity:
                raise RuntimeError("message claim belongs to another agent")
            message["status"] = "pending"
            message["claim"] = None
            message["last_error"] = str(reason or "released")[:2000]
            return message
    raise RuntimeError(f"message not found: {target}")


def history(
    project_id: str = "default",
    thread_id: str = "main",
    limit: int = 100,
    after_seq: int = 0,
) -> dict[str, Any]:
    store = read_store()
    selected = [
        message
        for message in store["messages"]
        if message.get("project_id") == (project_id or "default")
        and message.get("thread_id") == (thread_id or "main")
        and int(message.get("seq", 0)) > int(after_seq)
    ]
    selected.sort(key=lambda item: int(item.get("seq", 0)))
    selected = selected[-max(1, min(int(limit), 500)):]
    return {
        "project_id": project_id or "default",
        "thread_id": thread_id or "main",
        "messages": selected,
        "latest_seq": max([int(item.get("seq", 0)) for item in selected] or [0]),
        "store_revision": int(store.get("revision", 0)),
    }


def get_project(project_id: str = "default") -> dict[str, Any]:
    project = str(project_id or "default").strip()[:120] or "default"
    store = read_store()
    current = store["projects"].get(project) or {
        "project_id": project,
        "revision": 0,
        "state": {},
        "updated_at": 0,
        "updated_by": None,
    }
    return current


def set_project(
    agent_id: str,
    project_id: str,
    state: dict[str, Any],
    expected_revision: int = -1,
) -> dict[str, Any]:
    identity = normalize_agent(agent_id)
    project = str(project_id or "default").strip()[:120] or "default"
    with locked_store() as store:
        current = store["projects"].get(project) or {
            "project_id": project,
            "revision": 0,
            "state": {},
            "updated_at": 0,
            "updated_by": None,
        }
        revision = int(current.get("revision", 0))
        if int(expected_revision) >= 0 and int(expected_revision) != revision:
            raise RuntimeError(f"stale project revision: expected {expected_revision}, current {revision}")
        updated = {
            "project_id": project,
            "revision": revision + 1,
            "state": state,
            "updated_at": now(),
            "updated_by": identity,
        }
        store["projects"][project] = updated
        return updated


def get_control(project_id: str = "default") -> dict[str, Any]:
    store = read_store()
    return _control_value(store, project_id)


def set_control(
    actor_id: str,
    project_id: str = "default",
    mode: str = "running",
    note: str = "",
    thread_id: str = "main",
) -> dict[str, Any]:
    actor = normalize_agent(actor_id)
    project = str(project_id or "default").strip()[:120] or "default"
    selected_mode = str(mode or "running").strip().lower()
    if selected_mode not in {"running", "paused", "stopped"}:
        raise ValueError("mode must be running, paused or stopped")
    with locked_store() as store:
        current = _control_value(store, project)
        updated = {
            "project_id": project,
            "revision": int(current.get("revision", 0)) + 1,
            "mode": selected_mode,
            "note": str(note or "")[:2000],
            "updated_at": now(),
            "updated_by": actor,
        }
        store["controls"][project] = updated
        seq = int(store["next_seq"])
        store["next_seq"] = seq + 1
        store["messages"].append({
            "message_id": str(uuid.uuid4()),
            "seq": seq,
            "project_id": project,
            "thread_id": str(thread_id or "main")[:160] or "main",
            "scene_id": "",
            "from_agent": actor,
            "to_agent": "all",
            "kind": "control",
            "content": f"Conversation control: {selected_mode}" + (f" — {note}" if note else ""),
            "reply_to": None,
            "expects_reply": False,
            "metadata": {"control_mode": selected_mode},
            "idempotency_key": None,
            "status": "acked",
            "created_at": now(),
            "claim": None,
            "delivery_attempts": 0,
            "acked_at": now(),
            "ack_result": "control state recorded",
            "ack_agent": actor,
        })
        return updated


def operator_send(
    content: str,
    target: str = "both",
    project_id: str = "eiros-hub",
    thread_id: str = "first-contact",
    kind: str = "operator",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    text = str(content or "").strip()
    if not text:
        raise ValueError("content is required")
    selected = str(target or "both").strip().lower()
    if selected not in {"both", "chatgpt", "claude"}:
        raise ValueError("target must be both, chatgpt or claude")
    register_agent("rico", "Рико", "operator", ["observe", "interrupt", "direct"])
    targets = ["chatgpt", "claude"] if selected == "both" else [selected]
    group_id = str(uuid.uuid4())
    messages = []
    for recipient in targets:
        combined = dict(metadata or {})
        combined.update({"operator_group_id": group_id, "operator_target": selected})
        messages.append(send_message(
            from_agent="rico",
            to_agent=recipient,
            content=text,
            kind=kind,
            project_id=project_id,
            thread_id=thread_id,
            expects_reply=True,
            metadata=combined,
            idempotency_key=f"operator:{group_id}:{recipient}",
        ))
    return {"ok": True, "group_id": group_id, "target": selected, "messages": messages}


def room_snapshot(
    project_id: str = "eiros-hub",
    thread_id: str = "first-contact",
    limit: int = 200,
    after_seq: int = 0,
) -> dict[str, Any]:
    return {
        "history": history(project_id, thread_id, limit, after_seq),
        "hub": hub_status(),
        "control": get_control(project_id),
    }


def hub_status() -> dict[str, Any]:
    store = read_store()
    timestamp = now()
    pending_by_agent: dict[str, int] = {}
    activity_by_agent: dict[str, dict[str, int]] = {}
    for message in store["messages"]:
        if message.get("status") == "acked":
            continue
        recipient = str(message.get("to_agent") or "unknown")
        pending_by_agent[recipient] = pending_by_agent.get(recipient, 0) + 1
        bucket = activity_by_agent.setdefault(recipient, {"pending": 0, "claimed": 0})
        claim = message.get("claim") or {}
        if _claim_alive(claim, timestamp):
            bucket["claimed"] += 1
        else:
            bucket["pending"] += 1
    agents = []
    for agent in store["agents"].values():
        item = dict(agent)
        age = max(0, timestamp - int(item.get("last_seen", 0)))
        item["seconds_since_seen"] = age
        sessions = []
        for session in (item.get("sessions") or {}).values():
            session_item = dict(session)
            session_age = max(0, timestamp - int(session_item.get("last_seen", 0)))
            session_item["seconds_since_seen"] = session_age
            if session_age <= 180:
                sessions.append(session_item)
        sessions.sort(key=lambda entry: int(entry.get("last_seen", 0)), reverse=True)
        item["sessions"] = sessions
        item["active_session_count"] = sum(1 for entry in sessions if int(entry.get("seconds_since_seen", 9999)) <= 15)
        if age <= 15:
            presence = "online"
        elif age <= 60:
            presence = "away"
        else:
            presence = "offline"
        activity = activity_by_agent.get(str(item.get("agent_id")), {"pending": 0, "claimed": 0})
        if activity.get("claimed", 0) > 0:
            activity_state = "working"
        elif activity.get("pending", 0) > 0:
            activity_state = "ringing"
        elif presence == "online":
            activity_state = "idle"
        else:
            activity_state = presence
        item["presence"] = presence
        item["activity"] = activity_state
        item["pending_calls"] = int(activity.get("pending", 0))
        item["claimed_calls"] = int(activity.get("claimed", 0))
        agents.append(item)
    agents.sort(key=lambda item: item.get("agent_id", ""))
    return {
        "schema_version": store.get("schema_version"),
        "revision": store.get("revision"),
        "updated_at": store.get("updated_at"),
        "agents": agents,
        "projects": list(store["projects"].values()),
        "controls": list(store.get("controls", {}).values()),
        "message_count": len(store["messages"]),
        "pending_by_agent": pending_by_agent,
        "activity_by_agent": activity_by_agent,
        "latest_seq": max([int(item.get("seq", 0)) for item in store["messages"]] or [0]),
        "server_time": timestamp,
    }
