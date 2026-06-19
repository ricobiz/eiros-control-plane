from __future__ import annotations

import compileall
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from runtime.config import CODE_ROOT, DATA_ROOT, RUNTIME_DIR
from runtime.doctor import run_doctor
from runtime.version import __version__

TESTS = [
    "runtime.test_scheduler",
    "runtime.test_queue",
    "runtime.test_foundation",
]


def run_module(module: str) -> dict[str, Any]:
    process = subprocess.run(
        [sys.executable, "-m", module],
        cwd=CODE_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    return {
        "module": module,
        "ok": process.returncode == 0,
        "exit_code": process.returncode,
        "stdout": process.stdout[-20000:],
        "stderr": process.stderr[-20000:],
    }


def run_release_check() -> dict[str, Any]:
    started = int(time.time())
    compiled = compileall.compile_dir(CODE_ROOT / "runtime", quiet=1) and compileall.compile_dir(CODE_ROOT / "root", quiet=1)
    tests = [run_module(module) for module in TESTS]
    doctor = run_doctor(offline=False)
    widget = (CODE_ROOT / "runtime" / "pulse_widget.html").read_text(encoding="utf-8")
    server = (CODE_ROOT / "runtime" / "server_v2.py").read_text(encoding="utf-8")
    contract = {
        "bootstrap_placeholder": "__EIROS_BOOTSTRAP__" in widget,
        "ui_message": "ui/message" in widget,
        "app_only_poll": 'name="pulse_poll"' in server and 'visibility": ["app"]' in server,
        "instance_binding": "instance_id" in server and "channel" in server,
    }
    ok = compiled and all(test["ok"] for test in tests) and doctor["ok"] and all(contract.values())
    report = {
        "ok": ok,
        "version": __version__,
        "started_at": started,
        "finished_at": int(time.time()),
        "code_root": str(CODE_ROOT),
        "data_root": str(DATA_ROOT),
        "compile": compiled,
        "tests": tests,
        "doctor": doctor,
        "contract": contract,
    }
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    (RUNTIME_DIR / "release-check.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    report = run_release_check()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
