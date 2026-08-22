"""Shared widget-telemetry store.

Every MCP server that hosts EIROS widgets writes here, and they do not all run
as the same uid: eiros-claude.service runs as `eiros` while the operator
surface runs as `root`. The previous implementation lived inside server_v2 and
published the file with the bare `tempfile.mkstemp` default (0600, owned by
whoever wrote last), so the first cross-uid write silently locked the other
server out of its own telemetry. `room_telemetry.json` is 0600 on disk today
for exactly that reason.

This module is the single writer for that file and it publishes through
`runtime.config.publish_shared_file`, the same ownership contract that already
covers collab.json and widget-blackbox.json.
"""
from __future__ import annotations

import fcntl
import json
import os
import stat
import tempfile
import time
from pathlib import Path
from typing import Any

from runtime.config import RUNTIME_DIR, publish_shared_file, shared_gid

TELEMETRY_FILE = RUNTIME_DIR / "room_telemetry.json"
LOCK_FILE = RUNTIME_DIR / "room_telemetry.lock"
SHARED_MODE = 0o660
# Room/pulse widgets re-report every couple of seconds, so an hour of history
# for them is plenty. Boot-trace rows are the opposite: a mount happens once,
# and the whole point is to read it back afterwards - possibly hours later,
# possibly after the session that produced it is gone. Pruning those on the
# same clock silently destroys the only copy of the evidence, which is exactly
# what happened to this file once already.
RETENTION_SECONDS = 3600
DIAGNOSTIC_RETENTION_SECONDS = 24 * 3600
DIAGNOSTIC_KINDS = ("claude-pulse", "claude-pulse-mount")
SCHEMA_VERSION = 1


def _ensure_shared(path: Path, mode: int = SHARED_MODE) -> None:
    """Force one path to the two-writer contract: exists, group eiros, 0660.

    `publish_shared_file` only ORs group-*read* onto an existing file, which is
    right for state one side merely inspects and wrong for a file both uids
    write. It also never touches the lock, and a lock created root-owned 0644
    blocks the eiros side from taking it at all - the write then fails before
    it has even looked at the data. Both are normalised here rather than in the
    shared helper, which is under separate review.

    Every step is best-effort: an unprivileged process cannot chown a file it
    does not own, and that must not be fatal.
    """
    try:
        if not path.exists():
            fd = os.open(str(path), os.O_CREAT | os.O_WRONLY, mode)
            os.close(fd)
    except OSError:
        return
    gid = shared_gid()
    if gid >= 0:
        try:
            os.chown(str(path), -1, gid)
        except (PermissionError, OSError):
            pass
    try:
        current = stat.S_IMODE(path.stat().st_mode)
        if current != mode:
            os.chmod(str(path), mode)
    except (PermissionError, OSError):
        pass


def _empty() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "widgets": {}}


class TelemetryUnreadable(RuntimeError):
    """The store could not be read, so it must not be overwritten."""


def read() -> dict[str, Any]:
    try:
        raw = json.loads(TELEMETRY_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _empty()
    except Exception as exc:  # unreadable => report, never mask
        store = _empty()
        store["read_error"] = str(exc)
        return store
    if not isinstance(raw, dict):
        store = _empty()
        store["read_error"] = f"store root is {type(raw).__name__}, not an object"
        return store
    return raw


def _quarantine() -> Path | None:
    """Move an unreadable store aside so a write can proceed without erasing it.

    Returns the new path, or None when it could not be moved - in which case the
    caller must not write, because writing would destroy whatever is there.

    The destination must never collide: two corruptions in the same wall-clock
    second both used to resolve to ...corrupt-<int(time.time())>, and the second
    os.replace() silently overwrote the first quarantined file - destroying the
    exact evidence this function exists to preserve.

    First attempt at a fix used os.rename() expecting FileExistsError on a
    present destination. That distinction is Windows-only: on POSIX, rename(2)
    - and therefore os.rename() - overwrites an existing destination exactly
    like os.replace() does, so it did not fix anything. The actual fix is an
    explicit pre-check: this function only ever runs while update_locked()
    holds the exclusive flock on LOCK_FILE, so there is no other writer that
    could create the candidate between the check and the move, and a plain
    .exists() loop is sufficient. A random fallback below is defense in depth
    for a future caller that quarantines outside that lock.
    """
    base = f"{TELEMETRY_FILE.name}.corrupt-{int(time.time())}"
    candidate = TELEMETRY_FILE.with_name(base)
    suffix = 1
    while candidate.exists():
        candidate = TELEMETRY_FILE.with_name(f"{base}-{suffix}")
        suffix += 1
        if suffix > 10_000:
            candidate = TELEMETRY_FILE.with_name(f"{base}-{os.urandom(6).hex()}")
            break
    try:
        os.replace(TELEMETRY_FILE, candidate)
    except OSError:
        return None
    return candidate


def _write(store: dict[str, Any]) -> None:
    TELEMETRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    now = int(time.time())
    store["schema_version"] = SCHEMA_VERSION
    store["updated_at"] = now
    widgets = store.setdefault("widgets", {})
    cutoff = now - RETENTION_SECONDS
    diagnostic_cutoff = now - DIAGNOSTIC_RETENTION_SECONDS
    for key in list(widgets.keys()):
        row = widgets.get(key) or {}
        limit = diagnostic_cutoff if str(row.get("widget_kind") or "") in DIAGNOSTIC_KINDS else cutoff
        if int(row.get("updated_at", 0)) < limit:
            widgets.pop(key, None)
    fd, temp_name = tempfile.mkstemp(prefix="room-telemetry-", suffix=".json", dir=str(TELEMETRY_FILE.parent))
    published = False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(store, handle, ensure_ascii=False, indent=2, sort_keys=True)
        publish_shared_file(temp_name, TELEMETRY_FILE, mode=SHARED_MODE)
        published = True
        _ensure_shared(TELEMETRY_FILE)
    finally:
        if not published:
            Path(temp_name).unlink(missing_ok=True)


def compact(value: Any, max_chars: int = 6000) -> Any:
    try:
        text = json.dumps(value, ensure_ascii=False)
        if len(text) <= max_chars:
            return value
        return {"truncated": True, "text": text[:max_chars]}
    except Exception:
        return str(value)[:max_chars]


def record(
    widget_id: str,
    widget_kind: str = "room",
    project_id: str = "eiros-hub",
    thread_id: str = "first-contact",
    status: str = "unknown",
    snapshot: dict[str, Any] | None = None,
    error: str = "",
) -> dict[str, Any]:
    """Persist one widget's latest runtime state. Returns the stored item."""
    identity = str(widget_id or "").strip()[:180]
    if not identity:
        raise ValueError("widget_id is required")
    item = {
        "widget_id": identity,
        "widget_kind": str(widget_kind or "room")[:40],
        "project_id": str(project_id or "eiros-hub")[:120],
        "thread_id": str(thread_id or "first-contact")[:160],
        "status": str(status or "unknown")[:80],
        "snapshot": compact(snapshot or {}),
        "error": str(error or "")[:2000],
        "updated_at": int(time.time()),
    }
    update_locked(identity, item)
    return item


def update_locked(widget_id: str, item: dict[str, Any]) -> None:
    """Atomic read-modify-write under an exclusive lock shared across uids."""
    TELEMETRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    _ensure_shared(LOCK_FILE)
    with LOCK_FILE.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            store = read()
            error = str(store.pop("read_error", "") or "")
            if error:
                # Never blind-overwrite a store we could not read. The old
                # behaviour silently reset it to a single row and wrote the
                # error back in as state, so one corrupt byte erased the whole
                # ledger - the worst possible failure for a channel whose only
                # job is to preserve evidence of what went wrong.
                quarantined = _quarantine()
                if quarantined is None:
                    raise TelemetryUnreadable(
                        f"telemetry store is unreadable and could not be moved aside: {error}"
                    )
                store = _empty()
                store["recovered_from"] = quarantined.name
                store["recovered_reason"] = error[:500]
            store.setdefault("widgets", {})[widget_id] = item
            _write(store)
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


MOUNT_KIND = "claude-pulse-mount"


def open_mount(tool_name: str, uri: str, version: str, kind: str = MOUNT_KIND) -> str:
    """Record that a mount tool was called, and return the mount id.

    The widget's own stages carry this id, so one row chain covers the whole
    path: the model called the tool, the host fetched the resource, the script
    ran, the first tool call landed. Without the first two links a silent
    failure before any JavaScript runs is indistinguishable from the tool never
    having been called.
    """
    mount_id = f"mount-{int(time.time())}-{os.urandom(4).hex()}"
    record(
        widget_id=mount_id,
        widget_kind=kind,
        status="mount-requested:wait",
        snapshot={"tool_name": tool_name, "uri": uri, "version": version, "served_at": 0},
    )
    return mount_id


def mark_served(uri: str, kind: str = MOUNT_KIND) -> str:
    """Stamp the newest unserved mount row for this uri. Returns its mount id.

    A fetch with no matching row means the host requested the resource without
    a recorded tool call - a cached card re-hydrating, typically - so it is
    recorded under its own id rather than dropped.
    """
    now = int(time.time())
    rows = [
        item for item in (read().get("widgets") or {}).values()
        if item.get("widget_kind") == kind
        and str((item.get("snapshot") or {}).get("uri") or "") == uri
        and not int((item.get("snapshot") or {}).get("served_at") or 0)
    ]
    rows.sort(key=lambda item: int(item.get("updated_at", 0)), reverse=True)
    if rows:
        row = rows[0]
        snapshot = dict(row.get("snapshot") or {})
        snapshot["served_at"] = now
        record(widget_id=row["widget_id"], widget_kind=kind, status="resource-served:ok", snapshot=snapshot)
        return str(row["widget_id"])
    orphan = f"served-{now}-{os.urandom(4).hex()}"
    record(
        widget_id=orphan,
        widget_kind=kind,
        status="resource-served:no-recorded-tool-call",
        snapshot={"tool_name": "resource_fetch_without_recorded_tool_call", "uri": uri, "served_at": now},
    )
    return orphan


def recent(limit: int = 20) -> list[dict[str, Any]]:
    widgets = list((read().get("widgets") or {}).values())
    widgets.sort(key=lambda item: int(item.get("updated_at", 0)), reverse=True)
    return widgets[: max(1, min(int(limit or 20), 100))]
