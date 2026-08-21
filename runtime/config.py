from __future__ import annotations

import fcntl
import grp
import json
import os
import socket
import stat
import tempfile
import uuid
from pathlib import Path
from typing import Any

CODE_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = Path(os.environ.get("EIROS_DATA_DIR", str(CODE_ROOT))).expanduser().resolve()
RUNTIME_DIR = DATA_ROOT / "runtime"
LOG_DIR = DATA_ROOT / "logs"
TASK_DIR = DATA_ROOT / "tasks"
MEMORY_DIR = DATA_ROOT / "memory"
CONFIG_DIR = DATA_ROOT / "config"
CONFIG_FILE = CONFIG_DIR / "instance.json"
CONFIG_LOCK_FILE = CONFIG_DIR / "instance.lock"

DEFAULTS: dict[str, Any] = {
    "schema_version": 1,
    "instance_id": "",
    "display_name": "EIROS",
    "hostname": socket.gethostname(),
    "channel": "default",
    "widget_domain": "",
    "polling": {
        "active_ms": 750,
        "idle_min_ms": 1200,
        "idle_max_ms": 15000,
        "leader_lease_seconds": 25,
        "claim_seconds": 45,
    },
    "limits": {
        "max_events": 5000,
        "max_event_text": 20000,
        "max_queue_events": 5000,
    },
    "features": {
        "reverse_wake": True,
        "scheduler": True,
        "root_broker": False,
        "browser": False,
    },
    "security": {
        "shell_mode": "disabled",
        "allow_local_shell_tasks": False,
    },
}


# One data directory is shared by services that run as root (the Claude
# operator MCP, VPS Ops) and as `eiros` (SAM, the worker, the Room server).
# tempfile.mkstemp() creates 0600 files owned by whoever is writing, so a
# single root-side write used to leave shared state root:root 0600 and lock
# every eiros service out of it - that is how SAM lost config/instance.json
# and spent twelve hours logging PermissionError while systemd still reported
# the unit as active. Shared state is therefore always published group-owned
# by SHARED_GROUP and group-readable.
SHARED_GROUP = "eiros"
SHARED_FILE_MODE = 0o640


def shared_gid() -> int:
    """Return the gid every shared state file must be readable by, or -1."""
    try:
        return grp.getgrnam(SHARED_GROUP).gr_gid
    except KeyError:
        return -1


def publish_shared_file(temp_name: str, target: Path, mode: int = SHARED_FILE_MODE) -> None:
    """Atomically move a freshly written temp file into place, readable by the group.

    The current owner is preserved when the target already exists so that an
    eiros-written file does not silently become root-owned, and the group is
    forced back to SHARED_GROUP so the other side can always read it. chown
    fails for an unprivileged process that does not own the file; that is not
    fatal, the mode alone still keeps the file readable.
    """
    try:
        existing = target.stat()
        uid = existing.st_uid
        mode = stat.S_IMODE(existing.st_mode) | 0o040
    except FileNotFoundError:
        uid = -1
    gid = shared_gid()
    try:
        os.chown(temp_name, uid, gid)
    except (PermissionError, OSError):
        pass
    os.chmod(temp_name, mode)
    os.replace(temp_name, target)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def ensure_directories() -> None:
    for path in (DATA_ROOT, RUNTIME_DIR, LOG_DIR, TASK_DIR, MEMORY_DIR, CONFIG_DIR):
        path.mkdir(parents=True, exist_ok=True)


def ensure_instance_config() -> dict[str, Any]:
    """Read or create one stable instance config under an inter-process lock."""
    ensure_directories()
    with CONFIG_LOCK_FILE.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            current: dict[str, Any] = {}
            if CONFIG_FILE.exists():
                # instance_id is this host's identity: collab.py derives the hub
                # agent id from it, and the reconnect envelope is keyed on it.
                # Swallowing a read error here and falling through to the "no
                # instance_id yet" branch below silently mints a NEW identity
                # and orphans every existing registration. That is exactly what
                # happened when the config briefly became root-owned 0600 - one
                # eiros-side read failure was enough to replace
                # 107abeda-aabe-4c71-b913-ab1eb1a5a1f2 with a fresh uuid.
                # An absent file is a first run; an unreadable or malformed one
                # is a fault, and must be reported rather than papered over.
                try:
                    raw = CONFIG_FILE.read_text(encoding="utf-8")
                except OSError as exc:
                    raise RuntimeError(
                        f"cannot read {CONFIG_FILE}: {exc}. Refusing to mint a new "
                        "instance_id over an existing config."
                    ) from exc
                try:
                    loaded = json.loads(raw)
                except ValueError as exc:
                    raise RuntimeError(
                        f"{CONFIG_FILE} is not valid JSON: {exc}. Refusing to mint a "
                        "new instance_id over an existing config."
                    ) from exc
                if not isinstance(loaded, dict):
                    raise RuntimeError(
                        f"{CONFIG_FILE} does not contain a JSON object. Refusing to "
                        "mint a new instance_id over an existing config."
                    )
                current = loaded

            config = _deep_merge(DEFAULTS, current)
            if not str(config.get("instance_id") or "").strip():
                config["instance_id"] = str(uuid.uuid4())
            config["hostname"] = socket.gethostname()

            widget_domain = os.environ.get("EIROS_WIDGET_DOMAIN", "").strip()
            if widget_domain:
                config["widget_domain"] = widget_domain.rstrip("/")

            encoded = json.dumps(config, ensure_ascii=False, indent=2) + "\n"
            existing = ""
            try:
                existing = CONFIG_FILE.read_text(encoding="utf-8")
            except FileNotFoundError:
                pass

            if existing != encoded:
                fd, temp_name = tempfile.mkstemp(prefix="instance-", suffix=".tmp", dir=CONFIG_DIR)
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as handle:
                        handle.write(encoded)
                        handle.flush()
                        os.fsync(handle.fileno())
                    publish_shared_file(temp_name, CONFIG_FILE)
                finally:
                    if os.path.exists(temp_name):
                        os.unlink(temp_name)
            return config
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def load_config() -> dict[str, Any]:
    return ensure_instance_config()


def source_path(*parts: str) -> Path:
    return CODE_ROOT.joinpath(*parts)


def data_path(*parts: str) -> Path:
    return DATA_ROOT.joinpath(*parts)
