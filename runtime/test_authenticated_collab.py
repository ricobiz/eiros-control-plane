from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest

from runtime import collab


@dataclass(frozen=True)
class FakeAuthContext:
    agent_number: str
    principal_id: str = "principal-test"
    principal_type: str = "interactive_installation"
    revocation_epoch: int = 1
    scopes: tuple[str, ...] = ("collab:mutate",)


def _import_facade():
    from runtime.authenticated_collab import AuthenticatedCollab, AuthIdentityMismatch

    return AuthenticatedCollab, AuthIdentityMismatch


def test_send_uses_authenticated_identity_and_rejects_forged_from_agent(monkeypatch):
    """Production change: send_message must derive sender from AuthContext, never body fields."""
    AuthenticatedCollab, AuthIdentityMismatch = _import_facade()
    recorded: dict[str, object] = {}

    def fake_send_message(**kwargs):
        recorded.update(kwargs)
        return dict(kwargs)

    monkeypatch.setattr(collab, "send_message", fake_send_message)
    facade = AuthenticatedCollab(collab)
    auth = FakeAuthContext(agent_number="chatgpt")

    with pytest.raises(AuthIdentityMismatch):
        facade.send_message(auth, from_agent="claude", to_agent="rico", content="forged")

    result = facade.send_message(auth, from_agent="chatgpt", to_agent="rico", content="ok")
    assert result["from_agent"] == "chatgpt"
    assert recorded["from_agent"] == "chatgpt"


def test_inbox_uses_authenticated_identity_and_rejects_agent_mismatch(monkeypatch):
    """Production change: claims must be limited to the authenticated agent_number."""
    AuthenticatedCollab, AuthIdentityMismatch = _import_facade()
    recorded: dict[str, object] = {}

    def fake_inbox(agent_id, client_id, limit=10, claim_seconds=180, project_id="", thread_id=""):
        recorded.update(agent_id=agent_id, client_id=client_id)
        return {"agent_id": agent_id, "client_id": client_id}

    monkeypatch.setattr(collab, "inbox", fake_inbox)
    facade = AuthenticatedCollab(collab)
    auth = FakeAuthContext(agent_number="claude")

    with pytest.raises(AuthIdentityMismatch):
        facade.inbox(auth, agent_id="chatgpt", client_id="ui")

    result = facade.inbox(auth, agent_id="claude", client_id="ui")
    assert result["agent_id"] == "claude"
    assert recorded == {"agent_id": "claude", "client_id": "ui"}


def test_acknowledge_uses_authenticated_identity_and_rejects_agent_mismatch(monkeypatch):
    """Production change: ack authority must come from AuthContext, not agent_id argument."""
    AuthenticatedCollab, AuthIdentityMismatch = _import_facade()
    recorded: dict[str, object] = {}

    def fake_ack(agent_id, message_id, result=""):
        recorded.update(agent_id=agent_id, message_id=message_id, result=result)
        return dict(recorded)

    monkeypatch.setattr(collab, "acknowledge", fake_ack)
    facade = AuthenticatedCollab(collab)
    auth = FakeAuthContext(agent_number="chatgpt")

    with pytest.raises(AuthIdentityMismatch):
        facade.acknowledge(auth, agent_id="claude", message_id="m-1")

    result = facade.acknowledge(auth, agent_id="chatgpt", message_id="m-1", result="handled")
    assert result["agent_id"] == "chatgpt"


def test_release_uses_authenticated_identity_and_rejects_agent_mismatch(monkeypatch):
    """Production change: release authority must come from AuthContext, not agent_id argument."""
    AuthenticatedCollab, AuthIdentityMismatch = _import_facade()
    recorded: dict[str, object] = {}

    def fake_release(agent_id, message_id, reason=""):
        recorded.update(agent_id=agent_id, message_id=message_id, reason=reason)
        return dict(recorded)

    monkeypatch.setattr(collab, "release", fake_release)
    facade = AuthenticatedCollab(collab)
    auth = FakeAuthContext(agent_number="claude")

    with pytest.raises(AuthIdentityMismatch):
        facade.release(auth, agent_id="chatgpt", message_id="m-2")

    result = facade.release(auth, agent_id="claude", message_id="m-2", reason="retry")
    assert result["agent_id"] == "claude"


def test_project_state_set_uses_authenticated_identity_and_rejects_agent_mismatch(monkeypatch):
    """Production change: project writes must be attributed to the authenticated agent."""
    AuthenticatedCollab, AuthIdentityMismatch = _import_facade()
    recorded: dict[str, object] = {}

    def fake_set_project(agent_id, project_id, state, expected_revision=-1):
        recorded.update(
            agent_id=agent_id,
            project_id=project_id,
            state=state,
            expected_revision=expected_revision,
        )
        return dict(recorded)

    monkeypatch.setattr(collab, "set_project", fake_set_project)
    facade = AuthenticatedCollab(collab)
    auth = FakeAuthContext(agent_number="chatgpt")

    with pytest.raises(AuthIdentityMismatch):
        facade.set_project(auth, agent_id="claude", project_id="p", state={})

    result = facade.set_project(auth, agent_id="chatgpt", project_id="p", state={"x": 1})
    assert result["agent_id"] == "chatgpt"
    assert result["state"] == {"x": 1}


def _mutating_collab_tool_names(path: str) -> set[str]:
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        decorators = []
        for decorator in node.decorator_list:
            try:
                decorators.append(ast.unparse(decorator))
            except Exception:
                continue
        if not any("mcp.tool" in value for value in decorators):
            continue
        joined = " ".join(decorators)
        if "readOnlyHint=True" in joined:
            continue
        names.add(node.name)
    return names


def test_collaboration_mutation_entrypoints_are_enumerated_for_auth_migration():
    """Production change: activation gate must enumerate every reachable collab mutation wrapper."""
    expected = {
        "runtime/server_v2.py": {
            "hub_bootstrap",
            "contact_call",
            "mail_send",
            "hub_register",
            "dialog_send",
            "dialog_inbox",
            "dialog_ack",
            "dialog_release",
            "project_state_set",
            "room_heartbeat",
            "room_cleanup_stale",
            "operator_send",
            "operator_call_contact",
            "conversation_control_set",
        },
        "runtime/claude_server.py": {
            "room_heartbeat",
            "room_telemetry_update",
            "room_cleanup_stale",
            "operator_send",
            "operator_call_contact",
            "conversation_control_set",
            "hub_bootstrap",
            "contact_call",
            "mail_send",
            "hub_register",
            "hub_heartbeat",
            "dialog_send",
            "dialog_inbox",
            "dialog_ack",
            "dialog_release",
            "project_state_set",
        },
    }

    for path, required in expected.items():
        actual = _mutating_collab_tool_names(path)
        missing = required - actual
        assert not missing, f"{path} missing expected mutating entrypoints: {sorted(missing)}"
