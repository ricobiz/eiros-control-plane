from __future__ import annotations

import json
import os
import socket
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
}


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
    ensure_directories()
    current: dict[str, Any] = {}
    if CONFIG_FILE.exists():
        try:
            loaded = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                current = loaded
        except Exception:
            current = {}
    config = _deep_merge(DEFAULTS, current)
    if not str(config.get("instance_id") or "").strip():
        config["instance_id"] = str(uuid.uuid4())
    config["hostname"] = socket.gethostname()
    widget_domain = os.environ.get("EIROS_WIDGET_DOMAIN", "").strip()
    if widget_domain:
        config["widget_domain"] = widget_domain.rstrip("/")
    temp = CONFIG_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(temp, 0o600)
    os.replace(temp, CONFIG_FILE)
    return config


def load_config() -> dict[str, Any]:
    return ensure_instance_config()


def source_path(*parts: str) -> Path:
    return CODE_ROOT.joinpath(*parts)


def data_path(*parts: str) -> Path:
    return DATA_ROOT.joinpath(*parts)
