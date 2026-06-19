from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

from runtime import events, queue
from runtime.config import CONFIG_FILE, DATA_ROOT, ensure_directories, ensure_instance_config
from runtime.doctor import run_doctor
from runtime.version import __version__


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def bootstrap(display_name: str = "", widget_domain: str = "", channel: str = "") -> dict[str, Any]:
    ensure_directories()
    config = ensure_instance_config()
    if display_name.strip():
        config["display_name"] = display_name.strip()[:120]
    if widget_domain.strip():
        config["widget_domain"] = widget_domain.strip().rstrip("/")
    if channel.strip():
        config["channel"] = channel.strip()[:120]
    atomic_json(CONFIG_FILE, config)
    with queue.locked_store():
        pass
    with events.locked_store():
        pass
    report = run_doctor(offline=True)
    installation = {
        "ok": report["ok"],
        "version": __version__,
        "instance_id": config["instance_id"],
        "display_name": config["display_name"],
        "channel": config["channel"],
        "widget_domain": config.get("widget_domain") or None,
        "data_root": str(DATA_ROOT),
        "installed_at": int(time.time()),
        "doctor": report,
    }
    atomic_json(DATA_ROOT / "runtime" / "installation.json", installation)
    return installation


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize an EIROS instance")
    parser.add_argument("--display-name", default="")
    parser.add_argument("--widget-domain", default="")
    parser.add_argument("--channel", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = bootstrap(args.display_name, args.widget_domain, args.channel)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"EIROS instance {result['instance_id']} initialized at {result['data_root']}")
        print(f"Doctor: {result['doctor']['status']}")


if __name__ == "__main__":
    main()
