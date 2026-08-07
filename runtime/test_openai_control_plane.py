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
