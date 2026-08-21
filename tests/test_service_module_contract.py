"""Every module the deploy manifest promises to run must exist in this checkout.

runtime/sam.py, runtime/companion_server.py and runtime/mastering_mcp_server.py
were all reachable only from a worktree or an untracked file while their units
pointed at the canonical checkout. This test fails the moment that happens
again, without needing a host to inspect.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MANIFEST = json.loads((ROOT / "deploy" / "manifest.json").read_text(encoding="utf-8"))

SERVICE_MODULES = [
    "runtime.sam",
    "runtime.companion_server",
    "runtime.mastering_mcp_server",
    "runtime.server_v2",
    "runtime.claude_server",
    "runtime.claude_mcp_server",
    "runtime.vps_ops_server",
    "runtime.worker",
    "runtime.mastering",
    "root.root_broker",
]


@pytest.mark.parametrize("module", SERVICE_MODULES)
def test_service_module_is_present_in_checkout(module):
    assert importlib.util.find_spec(module) is not None, f"{module} is not importable from {ROOT}"


def test_manifest_commands_name_modules_that_exist():
    for name, command in (MANIFEST.get("entrypoints") or {}).items():
        parts = command.split()
        if "-m" not in parts:
            continue
        module = parts[parts.index("-m") + 1]
        assert importlib.util.find_spec(module) is not None, f"manifest entrypoint {name!r} -> {module}"


def test_every_required_service_has_a_unit_file_in_deploy():
    for service in MANIFEST.get("required_services", []):
        assert (ROOT / "deploy" / service).is_file(), f"{service} has no tracked unit file"
