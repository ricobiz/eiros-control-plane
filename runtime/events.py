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

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
EVENT_FILE = RUNTIME / "events.json"
LOCK_FILE = RUNTIME / "events.lock"
SCHEMA_VERSION = 1
MAX_EVENTS = 5000


def now() -> int:
    return int(time.time())


def empty_store() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "revision": 0,
        "next_seq": 1,
        "updated_at": now(),
        "leader": None,
        "events": [],
    }


def atomic_write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    parent_stat = path.parent.stat()
    target_uid = parent_stat.st_uid
    target_gid = parent_stat.st_gid
    target_mode = 0o660
    if path.exists():
        try:
            current = path.stat()
            target_uid = current.st_uid if current.st_uid != 0 else parent_stat.st_uid
            target_gid = current.st_gid if current.st_gid != 0 else parent_stat.st_gid
            target_mode = current.st_mode & 0o777 or 0o660
        except OSError:
            pass
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        try:
            os.fchmod(fd, target_mode)
            os.fchown(fd, target_uid, target_gid)
        except PermissionError:
            pass
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def load_store() -> dict[str, Any]:
    if not EVENT_FILE.exists():
        return empty_store()
    data = json.loads(EVENT_FILE.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError("Event store is not an object")
    if int(data.get("schema_version", 0)) != SCHEMA_VERSION:
        raise RuntimeError("Unsupported event schema")
    data.setdefault("revision", 0)
    data.setdefault("next_seq", 1)
    data.setdefault("leader", None)
    data.setdefault("events", [])
    return data


@contextmanager
def locked_store() -> Iterator[dict[str, Any]]:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    with LOCK_FILE.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        store = load_store()
        yield store
        store["revision"] = int(store.get("revision", 0)) + 1
        store["updated_at"] = now()
        if len(store["events"]) > MAX_EVENTS:
            store["events"] = store["events"][-MAX_EVENTS:]
        atomic_write(EVENT_FILE, store)
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def read_store() -> dict[str, Any]:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    with LOCK_FILE.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_SH)
        store = load_store()
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        return store


def emit(text: str, source: str = "remote", payload: dict[str, Any] | None = None, priority: int = 0, idempotency_key: str = "") -> dict[str, Any]:
    message = str(text or "").strip()
    if not message:
        raise ValueError("Event text is required")
    key = str(idempotency_key or "").strip()[:240]
    with locked_store() as store:
        if key:
            for existing in store["events"]:
                if existing.get("idempotency_key") == key:
                    return existing
        seq = int(store["next_seq"])
        store["next_seq"] = seq + 1
        event = {
            "id": str(uuid.uuid4()),
            "seq": seq,
            "source": str(source or "remote")[:120],
            "text": message[:20000],
            "payload": payload or {},
            "priority": max(-1000, min(int(priority), 1000)),
            "idempotency_key": key or None,
            "status": "pending",
            "created_at": now(),
            "claim": None,
            "delivered_at": None,
            "acked_at": None,
            "ack_result": None,
        }
        store["events"].append(event)
        return event


def _leader_alive(leader: dict[str, Any] | None, timestamp: int) -> bool:
    return bool(leader and int(leader.get("lease_until", 0)) > timestamp)


def poll(widget_id: str, cursor: int = 0, leader_lease_seconds: int = 25, claim_seconds: int = 45) -> dict[str, Any]:
    identity = str(widget_id or "").strip()[:200]
    if not identity:
        raise ValueError("widget_id is required")
    timestamp = now()
    with locked_store() as store:
        leader = store.get("leader")
        if not _leader_alive(leader, timestamp) or leader.get("widget_id") == identity:
            store["leader"] = {
                "widget_id": identity,
                "lease_until": timestamp + max(10, min(int(leader_lease_seconds), 120)),
                "last_seen": timestamp,
            }
        leader = store["leader"]
        is_leader = leader.get("widget_id") == identity

        selected = None
        if is_leader:
            candidates = []
            for item in store["events"]:
                if int(item.get("seq", 0)) <= int(cursor):
                    continue
                if item.get("status") == "acked":
                    continue
                claim = item.get("claim") or {}
                claim_alive = int(claim.get("until", 0)) > timestamp
                if claim_alive and claim.get("widget_id") != identity:
                    continue
                candidates.append(item)
            candidates.sort(key=lambda item: (-int(item.get("priority", 0)), int(item.get("seq", 0))))
            if candidates:
                selected = candidates[0]
                selected["status"] = "claimed"
                selected["claim"] = {
                    "widget_id": identity,
                    "until": timestamp + max(15, min(int(claim_seconds), 180)),
                    "claimed_at": timestamp,
                }

        latest_seq = max([int(item.get("seq", 0)) for item in store["events"]] or [0])
        pending_count = sum(1 for item in store["events"] if item.get("status") != "acked")
        return {
            "leader": is_leader,
            "leader_widget_id": leader.get("widget_id") if leader else None,
            "leader_lease_until": leader.get("lease_until") if leader else None,
            "event": selected,
            "latest_seq": latest_seq,
            "pending_count": pending_count,
            "server_time": timestamp,
        }


def mark_delivered(event_id: str, widget_id: str) -> dict[str, Any]:
    with locked_store() as store:
        for item in store["events"]:
            if item.get("id") != event_id:
                continue
            claim = item.get("claim") or {}
            if claim.get("widget_id") != widget_id:
                raise RuntimeError("Delivery claim belongs to another widget")
            item["status"] = "delivered"
            item["delivered_at"] = now()
            item["claim"]["until"] = now() + 120
            return item
    raise RuntimeError(f"Event not found: {event_id}")


def acknowledge(event_id: str, result: str = "", actor: str = "eiros") -> dict[str, Any]:
    with locked_store() as store:
        for item in store["events"]:
            if item.get("id") != event_id:
                continue
            item["status"] = "acked"
            item["acked_at"] = now()
            item["ack_result"] = str(result or "")[:20000]
            item["ack_actor"] = str(actor or "eiros")[:120]
            item["claim"] = None
            return item
    raise RuntimeError(f"Event not found: {event_id}")


def status(limit: int = 100) -> dict[str, Any]:
    store = read_store()
    events = list(store["events"])[-max(1, min(int(limit), 500)):]
    return {
        "schema_version": store["schema_version"],
        "revision": store["revision"],
        "updated_at": store["updated_at"],
        "leader": store.get("leader"),
        "latest_seq": max([int(item.get("seq", 0)) for item in store["events"]] or [0]),
        "pending_count": sum(1 for item in store["events"] if item.get("status") != "acked"),
        "events": events,
    }
