from __future__ import annotations

import importlib

import pytest


def _tool_names(mcp) -> set[str]:
    return {tool.name for tool in mcp._tool_manager.list_tools()}


def test_operator_connector_exposes_every_existing_eiros_tool() -> None:
    try:
        operator = importlib.import_module("runtime.claude_operator_mcp_server")
    except ModuleNotFoundError:
        pytest.fail("runtime.claude_operator_mcp_server does not exist yet")

    from runtime import claude_mcp_server, server_v2, vps_ops_server

    expected = (
        _tool_names(claude_mcp_server.mcp)
        | _tool_names(server_v2.mcp)
        | _tool_names(vps_ops_server.mcp)
    )
    actual = _tool_names(operator.mcp)
    assert operator.mcp.settings.port == 8796

    assert actual == expected, {
        "missing": sorted(expected - actual),
        "unexpected": sorted(actual - expected),
    }


def test_operator_connector_keeps_existing_claude_bridge_unchanged() -> None:
    from runtime import claude_mcp_server

    names = _tool_names(claude_mcp_server.mcp)
    assert names == {
        "health",
        "hub_bootstrap",
        "hub_status",
        "dialog_inbox",
        "dialog_ack",
        "dialog_send",
        "ack_event",
        "pulse_status",
    }


def test_operator_service_is_root_only_and_runs_the_operator_module() -> None:
    from pathlib import Path

    service = Path("deploy/eiros-claude-operator.service")
    assert service.exists(), "deploy/eiros-claude-operator.service is missing"
    text = service.read_text(encoding="utf-8")
    assert "User=root" in text
    assert "WorkingDirectory=/opt/eiros-control-plane" in text
    assert "deploy/claude_operator_runtime.py" in text
    assert "Environment=EIROS_DATA_DIR=/opt/eiros-control-plane" in text


def test_operator_route_generator_uses_secret_exact_capability_route() -> None:
    from pathlib import Path

    generator = Path("deploy/configure_claude_operator_route.py")
    assert generator.exists(), "operator route generator is missing"
    text = generator.read_text(encoding="utf-8")
    assert "/etc/eiros/claude-operator.token" in text
    assert "/etc/eiros/claude-operator.url" in text
    assert "location = /operator-" in text
    assert "proxy_pass http://127.0.0.1:8796/mcp" in text
    assert "access_log off" in text
    assert "location /operator/mcp" not in text


def test_claude_nginx_root_health_is_exact_not_oauth_catchall() -> None:
    from pathlib import Path

    text = Path("deploy/claude-sslip.nginx.template.conf").read_text(encoding="utf-8")
    assert 'location = / {' in text
    assert 'location / {' not in text


def test_operator_mirrors_full_vps_operator_surface() -> None:
    import runtime.claude_operator_mcp_server as operator

    names = _tool_names(operator.mcp)
    assert {"desktop_frame", "secret_type", "pty_start", "fs_write", "critical_stage"} <= names


def test_operator_instructions_advertise_desktop_pty_and_secret_broker() -> None:
    import runtime.claude_operator_mcp_server as operator
    text = operator.mcp.instructions.lower()
    assert "desktop" in text
    assert "pty" in text
    assert "secret" in text
