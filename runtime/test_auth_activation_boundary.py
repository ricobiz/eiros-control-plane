from __future__ import annotations

import ast
from pathlib import Path

import pytest


PROTECTED_WRAPPERS = {
    "runtime/server_v2.py": {
        "dialog_send": {"send_message"},
        "dialog_inbox": {"inbox"},
        "dialog_ack": {"acknowledge"},
        "dialog_release": {"release"},
        "project_state_set": {"set_project"},
        "room_heartbeat": {"session_heartbeat"},
    },
    "runtime/claude_server.py": {
        "dialog_send": {"send_message"},
        "dialog_inbox": {"inbox"},
        "dialog_ack": {"acknowledge"},
        "dialog_release": {"release"},
        "project_state_set": {"set_project"},
        "room_heartbeat": {"session_heartbeat"},
    },
}

CORE_NAMES = {"collab_engine", "collab"}


def _direct_core_calls(path: str, function_name: str) -> set[str]:
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    function = next(
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name
    )
    calls: set[str] = set()
    for node in ast.walk(function):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        owner = node.func.value
        if isinstance(owner, ast.Name) and owner.id in CORE_NAMES:
            calls.add(node.func.attr)
    return calls


@pytest.mark.parametrize(
    ("path", "wrapper", "forbidden"),
    [
        (path, wrapper, forbidden)
        for path, wrappers in PROTECTED_WRAPPERS.items()
        for wrapper, forbidden in wrappers.items()
    ],
)
def test_external_subscriber_mutations_do_not_bypass_authenticated_boundary(path, wrapper, forbidden):
    """Activation gate: externally reachable subscriber mutations may not call collab core directly."""
    direct = _direct_core_calls(path, wrapper)
    bypass = direct & forbidden
    assert not bypass, (
        f"{path}:{wrapper} bypasses AuthenticatedCollab via direct core call(s): {sorted(bypass)}"
    )
