"""Verify that every installed EIROS unit can still import the code it runs.

The failure this exists to catch: a unit keeps running from memory after its
module has left the working directory - a branch switch, a `git stash -u`, a
half-applied deploy - so systemd reports `active (running)` while the service
has become unrestartable. That state is invisible until something restarts and
the service never comes back.

Run it after any deploy, branch switch or stash, and on a timer:

    python deploy/preflight.py            # human-readable table
    python deploy/preflight.py --json     # machine-readable
    python deploy/preflight.py --write    # also persist runtime/preflight.json

Exit code is non-zero when any unit fails, so it works as an alert source.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

UNIT_GLOB = "eiros-*.service"
UNIT_DIR = Path("/etc/systemd/system")
STATE_FILE = Path(__file__).resolve().parents[1] / "runtime" / "preflight.json"

# Transient units systemd generates for one-shot bootstrap work are not part of
# the deployed surface and disappear on their own.
SKIP_PREFIXES = ("eiros-claude-op-bootstrap-clean-", "eiros-claude-bootstrap")


def systemctl_show(unit: str, *properties: str) -> dict[str, str]:
    args = ["systemctl", "show", unit, "--no-pager"]
    for name in properties:
        args += ["-p", name]
    out = subprocess.run(args, capture_output=True, text=True, timeout=30).stdout
    values: dict[str, str] = {}
    for line in out.splitlines():
        key, _, value = line.partition("=")
        if key:
            values[key] = value
    return values


def parse_exec_start(raw: str) -> list[str]:
    """Pull argv out of the `{ path=... ; argv[]=... ; ... }` form systemd prints."""
    match = re.search(r"argv\[\]=(.*?) ; ignore_errors=", raw, re.DOTALL)
    if not match:
        return []
    try:
        return shlex.split(match.group(1))
    except ValueError:
        return match.group(1).split()


def import_target(argv: list[str]) -> tuple[str, str] | None:
    """Map an ExecStart argv to ('module', name) or ('file', path), or None."""
    if not argv:
        return None
    executable = argv[0]
    if "python" not in Path(executable).name and Path(executable).name != "uvicorn":
        return None
    rest = argv[1:]
    for index, token in enumerate(rest):
        if token == "-m" and index + 1 < len(rest):
            return ("module", rest[index + 1])
        if token == "-c":
            # An inline program pins nothing importable by name; the module it
            # uses is covered by the PYTHONPATH check below instead.
            return None
        if token.endswith(".py"):
            return ("file", token)
        if ":" in token and not token.startswith("-"):
            # uvicorn style `package.module:app`
            return ("module", token.split(":", 1)[0])
    return None


def environment(values: dict[str, str]) -> dict[str, str]:
    env = dict(os.environ)
    for item in shlex.split(values.get("Environment", "")):
        key, _, value = item.partition("=")
        if key:
            env[key] = value
    return env


def check_unit(unit: str) -> dict[str, Any]:
    values = systemctl_show(
        unit,
        "FragmentPath", "WorkingDirectory", "ExecStart", "Environment",
        "User", "ActiveState", "SubState", "ExecMainPID",
    )
    result: dict[str, Any] = {
        "unit": unit,
        "active_state": values.get("ActiveState", ""),
        "sub_state": values.get("SubState", ""),
        "working_directory": values.get("WorkingDirectory", ""),
        "user": values.get("User", "") or "root",
        "pid": values.get("ExecMainPID", "0"),
    }
    argv = parse_exec_start(values.get("ExecStart", ""))
    target = import_target(argv)
    if target is None:
        result.update({"status": "skipped", "reason": "not a python entrypoint"})
        return result

    kind, name = target
    result["target"] = f"{kind}:{name}"
    interpreter = argv[0]
    if Path(interpreter).name == "uvicorn":
        interpreter = str(Path(interpreter).with_name("python"))
    cwd = values.get("WorkingDirectory") or "/"
    env = environment(values)

    if kind == "module":
        program = f"import {name}"
    else:
        path = Path(name)
        if not path.is_absolute():
            path = Path(cwd) / path
        program = (
            "import importlib.util,sys;"
            f"spec=importlib.util.spec_from_file_location('_preflight',{str(path)!r});"
            "sys.exit(0 if spec else 1)"
        )
        if not path.exists():
            result.update({"status": "fail", "error": f"missing file: {path}"})
            return result

    command = [interpreter, "-c", program]
    user = result["user"]
    if user and user != "root" and os.geteuid() == 0:
        command = ["sudo", "-n", "-u", user] + command

    proc = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, timeout=120)
    if proc.returncode == 0:
        result["status"] = "ok"
    else:
        result["status"] = "fail"
        result["error"] = (proc.stderr or proc.stdout).strip().splitlines()[-1:] or ["unknown import failure"]
        result["error"] = result["error"][0]
        # A unit that is running yet cannot import its own entrypoint is the
        # exact ghost-process state this check exists for.
        if result["active_state"] == "active":
            result["status"] = "ghost"
    return result


def installed_units() -> list[str]:
    names = sorted(path.name for path in UNIT_DIR.glob(UNIT_GLOB))
    return [n for n in names if not n.startswith(SKIP_PREFIXES)]


def run(units: list[str] | None = None) -> dict[str, Any]:
    checks = [check_unit(unit) for unit in (units or installed_units())]
    counts: dict[str, int] = {}
    for check in checks:
        counts[check["status"]] = counts.get(check["status"], 0) + 1
    return {
        "ok": not counts.get("fail") and not counts.get("ghost"),
        "checked_at": int(time.time()),
        "summary": counts,
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print the raw report")
    parser.add_argument("--write", action="store_true", help="persist runtime/preflight.json")
    parser.add_argument("unit", nargs="*", help="limit the check to these units")
    args = parser.parse_args()

    report = run(args.unit or None)

    if args.write:
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            STATE_FILE.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        except OSError as exc:
            print(f"could not persist {STATE_FILE}: {exc}", file=sys.stderr)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for check in report["checks"]:
            line = f"  {check['status'].upper():<8} {check['unit']:<42} {check.get('target', '-')}"
            if check.get("error"):
                line += f"\n           {check['error']}"
            print(line)
        print(f"\n  summary: {report['summary']}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
