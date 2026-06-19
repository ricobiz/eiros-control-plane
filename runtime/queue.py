from __future__ import annotations

import argparse
import fcntl
import json
import os
import socket
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from runtime.config import DATA_ROOT as ROOT, RUNTIME_DIR
QUEUE_FILE = RUNTIME_DIR / "queue.json"
LOCK_FILE = RUNTIME_DIR / "queue.lock"
WAKEUP_SOCKET = RUNTIME_DIR / "wakeup.sock"
SCHEMA_VERSION = 2
TERMINAL = {"completed", "failed", "cancelled"}
ACTIVE = {"queued", "running", "awaiting_brain"}


def now() -> int:
    return int(time.time())


def empty_store() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "revision": 0,
        "updated_at": now(),
        "tasks": [],
        "events": [],
    }


def atomic_write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def signal_worker(reason: str = "queue_changed") -> None:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as client:
            client.settimeout(0.15)
            client.sendto(reason.encode("utf-8")[:256], str(WAKEUP_SOCKET))
    except (FileNotFoundError, ConnectionRefusedError, TimeoutError, OSError):
        pass


def normalize_task(task: dict[str, Any]) -> dict[str, Any]:
    timestamp = int(task.get("created_at", now()))
    task.setdefault("mode", "brain")
    task.setdefault("run_at", timestamp)
    task.setdefault("interval_seconds", 0)
    task.setdefault("remaining_runs", 1)
    task.setdefault("action", {})
    task.setdefault("last_signal_at", 0)
    task.setdefault("last_signal_revision", 0)
    task.setdefault("schedule", {"kind": "once"})
    return task


def migrate_store(data: dict[str, Any]) -> dict[str, Any]:
    version = int(data.get("schema_version", 1))
    if version > SCHEMA_VERSION:
        raise RuntimeError(f"Unsupported queue schema: {version}")
    data.setdefault("tasks", [])
    data.setdefault("events", [])
    for task in data["tasks"]:
        normalize_task(task)
    data["schema_version"] = SCHEMA_VERSION
    data.setdefault("revision", 0)
    data.setdefault("updated_at", now())
    return data


def load_store() -> dict[str, Any]:
    if not QUEUE_FILE.exists():
        return empty_store()
    data = json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError("Queue store is not an object")
    return migrate_store(data)


@contextmanager
def locked_store() -> Iterator[dict[str, Any]]:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    with LOCK_FILE.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        store = load_store()
        yield store
        store["revision"] = int(store.get("revision", 0)) + 1
        store["updated_at"] = now()
        atomic_write(QUEUE_FILE, store)
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def read_store() -> dict[str, Any]:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    with LOCK_FILE.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_SH)
        store = load_store()
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        return store


def event(store: dict[str, Any], task_id: str, kind: str, details: dict[str, Any] | None = None) -> None:
    store["events"].append({
        "id": str(uuid.uuid4()),
        "task_id": task_id,
        "kind": kind,
        "at": now(),
        "details": details or {},
    })
    if len(store["events"]) > 5000:
        store["events"] = store["events"][-5000:]


def find_task(store: dict[str, Any], task_id: str) -> dict[str, Any]:
    for task in store["tasks"]:
        if task["id"] == task_id:
            return normalize_task(task)
    raise RuntimeError(f"Task not found: {task_id}")


def expire_leases(store: dict[str, Any]) -> None:
    current = now()
    for task in store["tasks"]:
        normalize_task(task)
        lease = task.get("lease") or {}
        if task.get("status") == "running" and lease.get("expires_at", 0) <= current:
            previous_owner = lease.get("owner")
            task["status"] = "queued"
            task["lease"] = None
            task["run_at"] = current
            task["updated_at"] = current
            event(store, task["id"], "lease_expired", {"owner": previous_owner})


def due(task: dict[str, Any], current: int | None = None) -> bool:
    current = now() if current is None else current
    return (
        task.get("status") == "queued"
        and int(task.get("run_at", 0)) <= current
        and int(task.get("attempts", 0)) < int(task.get("max_attempts", 1))
        and int(task.get("step", 0)) < int(task.get("max_steps", 1))
    )


def next_wakeup(mode: str = "") -> dict[str, Any]:
    store = read_store()
    current = now()
    tasks = [normalize_task(item) for item in store["tasks"] if item.get("status") == "queued"]
    if mode:
        tasks = [item for item in tasks if item.get("mode") == mode]
    if not tasks:
        return {"has_task": False, "next_run_at": None, "sleep_seconds": None}
    tasks.sort(key=lambda item: (int(item.get("run_at", 0)), -int(item.get("priority", 0)), item.get("created_at", 0)))
    task = tasks[0]
    run_at = int(task.get("run_at", current))
    return {
        "has_task": True,
        "task_id": task["id"],
        "mode": task.get("mode", "brain"),
        "next_run_at": run_at,
        "sleep_seconds": max(0, run_at - current),
    }


def cmd_init(_: argparse.Namespace) -> dict[str, Any]:
    with locked_store() as store:
        return store


def cmd_enqueue(args: argparse.Namespace) -> dict[str, Any]:
    with locked_store() as store:
        task_id = getattr(args, "id", None) or str(uuid.uuid4())
        if any(item["id"] == task_id for item in store["tasks"]):
            raise RuntimeError(f"Task already exists: {task_id}")
        timestamp = now()
        delay_seconds = max(0, int(getattr(args, "delay_seconds", 0) or 0))
        explicit_run_at = int(getattr(args, "run_at", 0) or 0)
        run_at = explicit_run_at if explicit_run_at > 0 else timestamp + delay_seconds
        interval = max(0, int(getattr(args, "interval_seconds", 0) or 0))
        remaining_runs = int(getattr(args, "remaining_runs", 1) or 1)
        if remaining_runs == 0:
            remaining_runs = 1
        task = {
            "id": task_id,
            "title": args.title,
            "objective": args.objective,
            "payload": json.loads(args.payload),
            "action": json.loads(getattr(args, "action", "{}") or "{}"),
            "mode": getattr(args, "mode", "brain") or "brain",
            "status": "queued",
            "revision": 1,
            "step": 0,
            "max_steps": args.max_steps,
            "attempts": 0,
            "max_attempts": args.max_attempts,
            "priority": args.priority,
            "run_at": run_at,
            "interval_seconds": interval,
            "remaining_runs": remaining_runs,
            "schedule": {"kind": "interval" if interval > 0 else "once"},
            "lease": None,
            "last_action": None,
            "last_result": None,
            "next_step": args.next_step,
            "stop_reason": None,
            "last_signal_at": 0,
            "last_signal_revision": 0,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        store["tasks"].append(task)
        event(store, task_id, "enqueued", {
            "title": args.title,
            "mode": task["mode"],
            "run_at": run_at,
            "interval_seconds": interval,
        })
    signal_worker("enqueue")
    return task


def cmd_claim(args: argparse.Namespace) -> dict[str, Any]:
    with locked_store() as store:
        expire_leases(store)
        current = now()
        mode = getattr(args, "mode", "brain") or "brain"
        candidates = [
            normalize_task(item) for item in store["tasks"]
            if due(item, current) and (mode == "any" or item.get("mode", "brain") == mode)
        ]
        candidates.sort(key=lambda item: (-int(item["priority"]), int(item["run_at"]), int(item["created_at"])))
        if not candidates:
            wakeup = next((int(item.get("run_at", 0)) for item in sorted(
                [t for t in store["tasks"] if t.get("status") == "queued" and (mode == "any" or t.get("mode") == mode)],
                key=lambda t: int(t.get("run_at", 0)),
            )), None)
            return {"claimed": False, "reason": "no_due_task", "next_run_at": wakeup}
        task = candidates[0]
        token = str(uuid.uuid4())
        task["status"] = "running"
        task["attempts"] += 1
        task["revision"] += 1
        task["lease"] = {
            "owner": args.owner,
            "token": token,
            "claimed_at": current,
            "expires_at": current + args.lease_seconds,
        }
        task["updated_at"] = current
        event(store, task["id"], "claimed", {"owner": args.owner, "attempt": task["attempts"], "mode": task["mode"]})
        return {"claimed": True, "task": task}


def require_lease(task: dict[str, Any], owner: str, token: str) -> None:
    lease = task.get("lease") or {}
    if task.get("status") != "running":
        raise RuntimeError("Task is not running")
    if lease.get("owner") != owner or lease.get("token") != token:
        raise RuntimeError("Lease owner or token mismatch")
    if int(lease.get("expires_at", 0)) <= now():
        raise RuntimeError("Lease expired")


def cmd_heartbeat(args: argparse.Namespace) -> dict[str, Any]:
    with locked_store() as store:
        task = find_task(store, args.id)
        require_lease(task, args.owner, args.token)
        task["lease"]["expires_at"] = now() + args.lease_seconds
        task["updated_at"] = now()
        event(store, task["id"], "heartbeat", {"owner": args.owner})
        return task


def _schedule_after_success(task: dict[str, Any], requested_delay: int, requested_run_at: int) -> bool:
    interval = int(task.get("interval_seconds", 0) or 0)
    remaining = int(task.get("remaining_runs", 1) or 1)
    if requested_run_at > 0 or requested_delay > 0:
        task["run_at"] = requested_run_at if requested_run_at > 0 else now() + requested_delay
        return True
    if interval > 0 and (remaining < 0 or remaining > 1):
        if remaining > 1:
            task["remaining_runs"] = remaining - 1
        task["run_at"] = now() + interval
        return True
    return False


def cmd_commit(args: argparse.Namespace) -> dict[str, Any]:
    with locked_store() as store:
        task = find_task(store, args.id)
        require_lease(task, args.owner, args.token)
        if args.expected_revision != task["revision"]:
            raise RuntimeError(f"Stale revision: expected {task['revision']}, received {args.expected_revision}")
        task["step"] += 1
        task["revision"] += 1
        task["last_action"] = args.action
        task["last_result"] = args.result
        task["next_step"] = args.next_step
        task["updated_at"] = now()
        delay_seconds = max(0, int(getattr(args, "delay_seconds", 0) or 0))
        explicit_run_at = int(getattr(args, "run_at", 0) or 0)
        requested_continue = bool(args.continue_task)
        scheduled = _schedule_after_success(task, delay_seconds, explicit_run_at)
        should_continue = task["step"] < task["max_steps"] and (requested_continue or scheduled)
        if should_continue:
            task["status"] = "queued"
            task["lease"] = None
            if not scheduled:
                task["run_at"] = now()
            event(store, task["id"], "step_committed", {
                "step": task["step"],
                "next_step": args.next_step,
                "run_at": task["run_at"],
            })
        else:
            task["status"] = "completed"
            task["lease"] = None
            task["stop_reason"] = args.stop_reason or "objective_completed"
            event(store, task["id"], "completed", {"step": task["step"], "reason": task["stop_reason"]})
    signal_worker("commit")
    return task


def cmd_fail(args: argparse.Namespace) -> dict[str, Any]:
    with locked_store() as store:
        task = find_task(store, args.id)
        require_lease(task, args.owner, args.token)
        task["revision"] += 1
        task["last_result"] = args.error
        task["updated_at"] = now()
        retry = args.retry and task["attempts"] < task["max_attempts"]
        if retry:
            task["status"] = "queued"
            task["lease"] = None
            task["next_step"] = args.next_step or task.get("next_step")
            retry_after = max(0, int(getattr(args, "retry_after_seconds", 0) or 0))
            if retry_after <= 0:
                retry_after = min(3600, 2 ** max(0, task["attempts"] - 1))
            task["run_at"] = now() + retry_after
            event(store, task["id"], "retry_queued", {
                "error": args.error,
                "attempts": task["attempts"],
                "run_at": task["run_at"],
            })
        else:
            task["status"] = "failed"
            task["lease"] = None
            task["stop_reason"] = args.error
            event(store, task["id"], "failed", {"error": args.error})
    signal_worker("fail")
    return task


def cmd_cancel(args: argparse.Namespace) -> dict[str, Any]:
    with locked_store() as store:
        task = find_task(store, args.id)
        if task["status"] in TERMINAL:
            return task
        task["status"] = "cancelled"
        task["lease"] = None
        task["stop_reason"] = args.reason
        task["revision"] += 1
        task["updated_at"] = now()
        event(store, task["id"], "cancelled", {"reason": args.reason})
    signal_worker("cancel")
    return task


def cmd_reschedule(args: argparse.Namespace) -> dict[str, Any]:
    with locked_store() as store:
        task = find_task(store, args.id)
        if task["status"] in TERMINAL:
            raise RuntimeError("Cannot reschedule terminal task")
        run_at = int(getattr(args, "run_at", 0) or 0)
        delay = max(0, int(getattr(args, "delay_seconds", 0) or 0))
        task["run_at"] = run_at if run_at > 0 else now() + delay
        task["status"] = "queued"
        task["lease"] = None
        task["revision"] += 1
        task["updated_at"] = now()
        event(store, task["id"], "rescheduled", {"run_at": task["run_at"]})
    signal_worker("reschedule")
    return task


def mark_brain_due() -> list[dict[str, Any]]:
    signalled: list[dict[str, Any]] = []
    with locked_store() as store:
        current = now()
        for task in store["tasks"]:
            normalize_task(task)
            if not due(task, current) or task.get("mode") != "brain":
                continue
            if int(task.get("last_signal_revision", 0)) == int(task.get("revision", 0)):
                continue
            task["last_signal_at"] = current
            task["last_signal_revision"] = task["revision"]
            task["status"] = "awaiting_brain"
            task["updated_at"] = current
            event(store, task["id"], "brain_due", {"run_at": task["run_at"]})
            signalled.append(task.copy())
    return signalled


def release_brain_signal(task_id: str) -> dict[str, Any]:
    with locked_store() as store:
        task = find_task(store, task_id)
        if task.get("status") == "awaiting_brain":
            task["status"] = "queued"
            task["updated_at"] = now()
        return task


def cmd_status(args: argparse.Namespace) -> dict[str, Any]:
    with locked_store() as store:
        expire_leases(store)
        if args.id:
            return find_task(store, args.id)
        tasks = store["tasks"]
        if args.status:
            tasks = [item for item in tasks if item["status"] == args.status]
        mode = getattr(args, "mode", "") or ""
        if mode:
            tasks = [item for item in tasks if item.get("mode") == mode]
        wake = None
        queued = [item for item in store["tasks"] if item.get("status") == "queued"]
        if queued:
            wake = min(int(item.get("run_at", 0)) for item in queued)
        return {
            "schema_version": store["schema_version"],
            "revision": store["revision"],
            "updated_at": store["updated_at"],
            "next_run_at": wake,
            "sleep_seconds": None if wake is None else max(0, wake - now()),
            "tasks": tasks,
            "events": store["events"][-args.events:],
        }


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="EIROS durable scheduled queue and lease engine")
    sub = root.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init")
    init.set_defaults(func=cmd_init)

    enqueue = sub.add_parser("enqueue")
    enqueue.add_argument("--id")
    enqueue.add_argument("--title", required=True)
    enqueue.add_argument("--objective", required=True)
    enqueue.add_argument("--payload", default="{}")
    enqueue.add_argument("--action", default="{}")
    enqueue.add_argument("--mode", choices=["brain", "local"], default="brain")
    enqueue.add_argument("--next-step", default="")
    enqueue.add_argument("--max-steps", type=int, default=12)
    enqueue.add_argument("--max-attempts", type=int, default=3)
    enqueue.add_argument("--priority", type=int, default=0)
    enqueue.add_argument("--run-at", type=int, default=0)
    enqueue.add_argument("--delay-seconds", type=int, default=0)
    enqueue.add_argument("--interval-seconds", type=int, default=0)
    enqueue.add_argument("--remaining-runs", type=int, default=1)
    enqueue.set_defaults(func=cmd_enqueue)

    claim = sub.add_parser("claim")
    claim.add_argument("--owner", required=True)
    claim.add_argument("--lease-seconds", type=int, default=120)
    claim.add_argument("--mode", choices=["brain", "local", "any"], default="brain")
    claim.set_defaults(func=cmd_claim)

    heartbeat = sub.add_parser("heartbeat")
    heartbeat.add_argument("--id", required=True)
    heartbeat.add_argument("--owner", required=True)
    heartbeat.add_argument("--token", required=True)
    heartbeat.add_argument("--lease-seconds", type=int, default=120)
    heartbeat.set_defaults(func=cmd_heartbeat)

    commit = sub.add_parser("commit")
    commit.add_argument("--id", required=True)
    commit.add_argument("--owner", required=True)
    commit.add_argument("--token", required=True)
    commit.add_argument("--expected-revision", type=int, required=True)
    commit.add_argument("--action", required=True)
    commit.add_argument("--result", required=True)
    commit.add_argument("--next-step", default="")
    commit.add_argument("--continue-task", action="store_true")
    commit.add_argument("--stop-reason")
    commit.add_argument("--run-at", type=int, default=0)
    commit.add_argument("--delay-seconds", type=int, default=0)
    commit.set_defaults(func=cmd_commit)

    fail = sub.add_parser("fail")
    fail.add_argument("--id", required=True)
    fail.add_argument("--owner", required=True)
    fail.add_argument("--token", required=True)
    fail.add_argument("--error", required=True)
    fail.add_argument("--retry", action="store_true")
    fail.add_argument("--next-step")
    fail.add_argument("--retry-after-seconds", type=int, default=0)
    fail.set_defaults(func=cmd_fail)

    cancel = sub.add_parser("cancel")
    cancel.add_argument("--id", required=True)
    cancel.add_argument("--reason", required=True)
    cancel.set_defaults(func=cmd_cancel)

    reschedule = sub.add_parser("reschedule")
    reschedule.add_argument("--id", required=True)
    reschedule.add_argument("--run-at", type=int, default=0)
    reschedule.add_argument("--delay-seconds", type=int, default=0)
    reschedule.set_defaults(func=cmd_reschedule)

    status = sub.add_parser("status")
    status.add_argument("--id")
    status.add_argument("--status")
    status.add_argument("--mode")
    status.add_argument("--events", type=int, default=30)
    status.set_defaults(func=cmd_status)

    wakeup = sub.add_parser("next-wakeup")
    wakeup.add_argument("--mode", default="")
    wakeup.set_defaults(func=lambda args: next_wakeup(args.mode))

    return root


def main() -> None:
    args = parser().parse_args()
    result = args.func(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
