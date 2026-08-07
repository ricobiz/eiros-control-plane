from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from runtime.openai_control_plane import ControlPlaneError, OpenAIControlPlane, redact_text


class FakeRunner:
    def __init__(self, responses: list[dict[str, Any]] | None = None) -> None:
        self.responses = list(responses or [])
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], timeout: int = 30) -> dict[str, Any]:
        self.calls.append(list(argv))
        if self.responses:
            return self.responses.pop(0)
        return {"ok": True, "exit_code": 0, "stdout": "", "stderr": "", "duration_ms": 1}


def test_redact_text_removes_bearer_and_openai_key_material() -> None:
    raw = (
        "Authorization: Bearer sk-admin-secret123\n"
        "OPENAI_ADMIN_KEY=sk-admin-secret123\n"
        "CONTROL_PLANE_API_KEY=sk-runtime-secret456"
    )
    clean = redact_text(raw)
    assert "sk-admin-secret123" not in clean
    assert "sk-runtime-secret456" not in clean
    assert "[REDACTED]" in clean


def test_identifier_and_local_url_validation(tmp_path: Path) -> None:
    op = OpenAIControlPlane(audit_path=tmp_path / "audit.jsonl")
    assert op.validate_tunnel_id("tunnel_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa") is True
    assert op.validate_slug("rental-agent") == "rental-agent"
    assert op.validate_local_mcp_url("http://127.0.0.1:8794/mcp") == "http://127.0.0.1:8794/mcp"
    assert op.validate_local_mcp_url("http://localhost:8794/mcp") == "http://localhost:8794/mcp"

    with pytest.raises(ControlPlaneError) as exc:
        op.validate_local_mcp_url("https://evil.example/mcp")
    assert exc.value.category == "invalid_local_mcp_url"

    with pytest.raises(ControlPlaneError) as exc:
        op.validate_slug("Rental Agent")
    assert exc.value.category == "invalid_identifier"


def test_admin_status_is_redacted_and_reports_capabilities(tmp_path: Path) -> None:
    secret_ref = tmp_path / "openai-admin.key"
    secret_ref.write_text("sk-admin-do-not-leak", encoding="utf-8")
    runner = FakeRunner(
        [
            {
                "ok": True,
                "exit_code": 0,
                "stdout": json.dumps(
                    {
                        "profiles": [
                            {
                                "name": "platform-admin",
                                "active": True,
                                "admin_key": "file:/etc/eiros/openai-admin.key",
                            }
                        ]
                    }
                ),
                "stderr": "",
                "duration_ms": 2,
            },
            {"ok": True, "exit_code": 0, "stdout": "tunnel-client version 1.2.3\n", "stderr": "", "duration_ms": 1},
            {"ok": True, "exit_code": 0, "stdout": "create update delete get list\n", "stderr": "", "duration_ms": 1},
            {"ok": True, "exit_code": 0, "stdout": "create update delete get list\n", "stderr": "", "duration_ms": 1},
        ]
    )
    op = OpenAIControlPlane(runner=runner, audit_path=tmp_path / "audit.jsonl", admin_secret_path=secret_ref)
    status = op.admin_status()
    encoded = json.dumps(status)

    assert status["secret_reference_configured"] is True
    assert status["admin_profile_active"] is True
    assert status["tunnel_crud_available"] is True
    assert status["runtime_crud_available"] is True
    assert "sk-admin-do-not-leak" not in encoded
    assert "admin_key" not in encoded


def test_audit_writer_redacts_and_returns_bounded_newest_events(tmp_path: Path) -> None:
    audit_path = tmp_path / "audit.jsonl"
    op = OpenAIControlPlane(audit_path=audit_path)
    op._write_audit(
        operation="tunnel_create",
        target_type="tunnel",
        target="rental-agent",
        requested={"description": "Bearer sk-secret-value"},
        ok=True,
        exit_code=0,
        duration_ms=11,
        error_category="",
    )
    op._write_audit(
        operation="tunnel_update",
        target_type="tunnel",
        target="tunnel_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        requested={"name": "Rental"},
        ok=False,
        exit_code=1,
        duration_ms=12,
        error_category="tunnel_client_error",
    )

    raw = audit_path.read_text(encoding="utf-8")
    assert "sk-secret-value" not in raw
    result = op.audit(limit=1)
    assert len(result["events"]) == 1
    assert result["events"][0]["operation"] == "tunnel_update"


def test_tunnel_get_normalizes_metadata(tmp_path: Path) -> None:
    tid = "tunnel_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    runner = FakeRunner([
        {
            "ok": True,
            "exit_code": 0,
            "stdout": json.dumps({
                "id": tid,
                "name": "EBRIDGE",
                "description": "core",
                "organization_ids": ["org_test123"],
                "workspace_ids": [],
                "request_id": "req_hidden",
            }),
            "stderr": "",
            "duration_ms": 3,
        }
    ])
    op = OpenAIControlPlane(runner=runner, audit_path=tmp_path / "audit.jsonl", admin_secret_path=tmp_path / "admin.key")
    result = op.tunnel_get(tid)
    assert result["tunnel_id"] == tid
    assert result["name"] == "EBRIDGE"
    assert result["organization_ids"] == ["org_test123"]
    assert "request_id" in result["raw_meta"]
    assert runner.calls[0][:5] == [
        "/usr/local/bin/tunnel-client", "admin", "--admin-key", f"file:{tmp_path / 'admin.key'}", "--json"
    ]


def test_tunnel_create_inherits_scope_without_guessing(tmp_path: Path) -> None:
    source_tid = "tunnel_cccccccccccccccccccccccccccccccc"
    new_tid = "tunnel_dddddddddddddddddddddddddddddddd"
    runner = FakeRunner([
        {
            "ok": True,
            "exit_code": 0,
            "stdout": json.dumps({
                "id": source_tid,
                "name": "EBRIDGE",
                "organization_ids": ["org_scope"],
                "workspace_ids": ["ws_scope"],
            }),
            "stderr": "",
            "duration_ms": 2,
        },
        {
            "ok": True,
            "exit_code": 0,
            "stdout": json.dumps({
                "id": new_tid,
                "name": "EIROS Rental Agent",
                "description": "Dedicated rental",
                "organization_ids": ["org_scope"],
                "workspace_ids": ["ws_scope"],
            }),
            "stderr": "",
            "duration_ms": 5,
        },
    ])
    op = OpenAIControlPlane(runner=runner, audit_path=tmp_path / "audit.jsonl", admin_secret_path=tmp_path / "admin.key")
    result = op.tunnel_create(
        name="EIROS Rental Agent",
        description="Dedicated rental",
        inherit_scope_from_tunnel=source_tid,
    )
    assert result["tunnel_id"] == new_tid
    create_argv = runner.calls[1]
    assert "--organization-id" in create_argv and "org_scope" in create_argv
    assert "--workspace-id" in create_argv and "ws_scope" in create_argv
    assert "--name" in create_argv and "EIROS Rental Agent" in create_argv


def test_tunnel_create_requires_scope_when_not_inherited(tmp_path: Path) -> None:
    op = OpenAIControlPlane(runner=FakeRunner(), audit_path=tmp_path / "audit.jsonl")
    with pytest.raises(ControlPlaneError) as exc:
        op.tunnel_create(name="No Scope", description="x")
    assert exc.value.category == "scope_required"


def test_tunnel_delete_requires_same_id_and_protects_ebridge(tmp_path: Path) -> None:
    tid = "tunnel_eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
    op = OpenAIControlPlane(runner=FakeRunner(), audit_path=tmp_path / "audit.jsonl", protected_tunnel_ids={tid})
    with pytest.raises(ControlPlaneError) as exc:
        op.tunnel_delete(tid, confirm_tunnel_id="tunnel_ffffffffffffffffffffffffffffffff")
    assert exc.value.category == "confirmation_mismatch"

    with pytest.raises(ControlPlaneError) as exc:
        op.tunnel_delete(tid, confirm_tunnel_id=tid)
    assert exc.value.category == "protected_target"


def test_tunnel_update_and_delete_build_expected_commands(tmp_path: Path) -> None:
    tid = "tunnel_ffffffffffffffffffffffffffffffff"
    runner = FakeRunner([
        {"ok": True, "exit_code": 0, "stdout": json.dumps({"id": tid, "name": "Renamed"}), "stderr": "", "duration_ms": 2},
        {"ok": True, "exit_code": 0, "stdout": json.dumps({"id": tid, "deleted": True}), "stderr": "", "duration_ms": 2},
    ])
    op = OpenAIControlPlane(runner=runner, audit_path=tmp_path / "audit.jsonl", admin_secret_path=tmp_path / "admin.key")
    updated = op.tunnel_update(tid, name="Renamed")
    assert updated["name"] == "Renamed"
    assert "update" in runner.calls[0]
    deleted = op.tunnel_delete(tid, confirm_tunnel_id=tid)
    assert deleted["ok"] is True
    assert "--confirm" in runner.calls[1]


class FakeSystemRunner(FakeRunner):
    pass


def test_runtime_create_get_update_delete_map_to_native_cli(tmp_path: Path) -> None:
    alias = "rental-agent"
    tid = "tunnel_abababababababababababababababab"
    runner = FakeRunner([
        {"ok": True, "exit_code": 0, "stdout": json.dumps({"alias": alias, "tunnel_id": tid}), "stderr": "", "duration_ms": 2},
        {"ok": True, "exit_code": 0, "stdout": json.dumps({"alias": alias, "state": "running", "tunnel_id": tid}), "stderr": "", "duration_ms": 2},
        {"ok": True, "exit_code": 0, "stdout": json.dumps({"alias": alias, "state": "connected", "tunnel_id": tid}), "stderr": "", "duration_ms": 2},
        {"ok": True, "exit_code": 0, "stdout": json.dumps({"alias": alias, "stopped": True}), "stderr": "", "duration_ms": 2},
        {"ok": True, "exit_code": 0, "stdout": json.dumps({"alias": alias, "removed": True}), "stderr": "", "duration_ms": 2},
    ])
    op = OpenAIControlPlane(runner=runner, audit_path=tmp_path / "audit.jsonl", admin_profile_name="platform-admin")

    created = op.runtime_create(alias=alias, name="Rental", description="desc", organization_ids=["org_scope"])
    assert created["alias"] == alias
    assert "create" in runner.calls[0] and "--admin-key" in runner.calls[0]

    status = op.runtime_get(alias)
    assert status["alias"] == alias
    assert "status" in runner.calls[1]

    updated = op.runtime_update(alias, tunnel_id=tid, mcp_server_url="http://127.0.0.1:8794/mcp", profile_name=alias)
    assert updated["alias"] == alias
    assert "connect" in runner.calls[2]
    assert "--tunnel-id" in runner.calls[2]
    assert "--mcp-server-url" in runner.calls[2]

    deleted = op.runtime_delete(alias, confirm_runtime=alias)
    assert deleted["ok"] is True
    assert "stop" in runner.calls[3]
    assert "rm" in runner.calls[4]


def test_runtime_delete_requires_confirmation(tmp_path: Path) -> None:
    op = OpenAIControlPlane(runner=FakeRunner(), audit_path=tmp_path / "audit.jsonl")
    with pytest.raises(ControlPlaneError) as exc:
        op.runtime_delete("rental-agent", confirm_runtime="other")
    assert exc.value.category == "confirmation_mismatch"


def test_profile_create_validate_get_and_delete_are_secret_safe(tmp_path: Path) -> None:
    profile_dir = tmp_path / "profiles"
    profile_dir.mkdir()
    tid = "tunnel_cdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcd"
    runner = FakeRunner([
        {"ok": True, "exit_code": 0, "stdout": "Created profile rental-agent", "stderr": "", "duration_ms": 2},
        {"ok": True, "exit_code": 0, "stdout": json.dumps({"ok": True, "checks": ["config"]}), "stderr": "", "duration_ms": 2},
    ])
    op = OpenAIControlPlane(runner=runner, audit_path=tmp_path / "audit.jsonl", profile_dir=profile_dir)

    created = op.profile_create("rental-agent", tid, "http://127.0.0.1:8794/mcp")
    assert created["name"] == "rental-agent"
    init_call = runner.calls[0]
    assert "init" in init_call and "--profile" in init_call and "rental-agent" in init_call
    assert "--control-plane-api-key-ref" in init_call
    assert "env:CONTROL_PLANE_API_KEY" in init_call

    (profile_dir / "rental-agent.yaml").write_text(
        'control_plane:\n  api_key: "sk-runtime-secret-value"\n  tunnel_id: "' + tid + '"\n',
        encoding="utf-8",
    )
    got = op.profile_get("rental-agent")
    encoded = json.dumps(got)
    assert "sk-runtime-secret-value" not in encoded
    assert "[REDACTED]" in encoded

    checked = op.profile_validate("rental-agent")
    assert checked["ok"] is True
    assert "doctor" in runner.calls[1]

    deleted = op.profile_delete("rental-agent", confirm_name="rental-agent")
    assert deleted["ok"] is True
    assert not (profile_dir / "rental-agent.yaml").exists()


def test_profile_delete_protects_core_profiles(tmp_path: Path) -> None:
    op = OpenAIControlPlane(audit_path=tmp_path / "audit.jsonl", profile_dir=tmp_path / "profiles")
    with pytest.raises(ControlPlaneError) as exc:
        op.profile_delete("eiros", confirm_name="eiros")
    assert exc.value.category == "protected_target"


def test_daemon_install_builds_namespaced_unit_and_lifecycle(tmp_path: Path) -> None:
    systemd_dir = tmp_path / "systemd"
    system_runner = FakeSystemRunner([
        {"ok": True, "exit_code": 0, "stdout": "", "stderr": "", "duration_ms": 1},
        {"ok": True, "exit_code": 0, "stdout": "", "stderr": "", "duration_ms": 1},
        {"ok": True, "exit_code": 0, "stdout": "ActiveState=active\nSubState=running\n", "stderr": "", "duration_ms": 1},
        {"ok": True, "exit_code": 0, "stdout": "", "stderr": "", "duration_ms": 1},
        {"ok": True, "exit_code": 0, "stdout": "", "stderr": "", "duration_ms": 1},
        {"ok": True, "exit_code": 0, "stdout": "", "stderr": "", "duration_ms": 1},
    ])
    op = OpenAIControlPlane(
        runner=FakeRunner(),
        system_runner=system_runner,
        audit_path=tmp_path / "audit.jsonl",
        systemd_dir=systemd_dir,
        health_url_dir=tmp_path / "health",
    )

    installed = op.daemon_install("rental-agent")
    assert installed["service"] == "eiros-tunnel-rental-agent.service"
    unit = (systemd_dir / "eiros-tunnel-rental-agent.service").read_text(encoding="utf-8")
    assert "User=eiros" in unit
    assert "EnvironmentFile=/etc/eiros/tunnel.env" in unit
    assert "tunnel-client run --profile rental-agent" in unit
    assert "Restart=always" in unit

    status = op.daemon_status("rental-agent")
    assert status["active_state"] == "active"
    op.daemon_restart("rental-agent")
    op.daemon_stop("rental-agent")
    removed = op.daemon_remove("rental-agent", confirm_name="rental-agent")
    assert removed["ok"] is True
    assert not (systemd_dir / "eiros-tunnel-rental-agent.service").exists()


def test_daemon_remove_protects_core_service(tmp_path: Path) -> None:
    op = OpenAIControlPlane(audit_path=tmp_path / "audit.jsonl", systemd_dir=tmp_path / "systemd")
    with pytest.raises(ControlPlaneError) as exc:
        op.daemon_remove("eiros", confirm_name="eiros")
    assert exc.value.category == "protected_target"


def test_runtime_commands_use_file_secret_reference_not_home_scoped_admin_profile(tmp_path: Path) -> None:
    runner = FakeRunner([
        {"ok": True, "exit_code": 0, "stdout": json.dumps({"alias": "rental-agent"}), "stderr": "", "duration_ms": 1}
    ])
    secret = tmp_path / "admin.key"
    op = OpenAIControlPlane(runner=runner, audit_path=tmp_path / "audit.jsonl", admin_secret_path=secret)
    op.runtime_create(
        alias="rental-agent",
        name="Rental",
        description="desc",
        organization_ids=["org_scope"],
    )
    call = runner.calls[0]
    assert "--admin-key" in call
    assert f"file:{secret}" in call
    assert "--admin-profile" not in call
