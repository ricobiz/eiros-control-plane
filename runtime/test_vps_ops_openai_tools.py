from __future__ import annotations

import asyncio

from runtime import vps_ops_server


EXPECTED = {
    "openai_admin_status",
    "openai_control_plane_audit",
    "openai_tunnel_list",
    "openai_tunnel_get",
    "openai_tunnel_create",
    "openai_tunnel_update",
    "openai_tunnel_delete",
    "openai_runtime_list",
    "openai_runtime_get",
    "openai_runtime_create",
    "openai_runtime_update",
    "openai_runtime_delete",
    "openai_profile_list",
    "openai_profile_get",
    "openai_profile_create",
    "openai_profile_validate",
    "openai_profile_delete",
    "openai_tunnel_daemon_install",
    "openai_tunnel_daemon_status",
    "openai_tunnel_daemon_start",
    "openai_tunnel_daemon_stop",
    "openai_tunnel_daemon_restart",
    "openai_tunnel_daemon_health",
    "openai_tunnel_daemon_remove",
    "openai_connector_provision",
}


def test_openai_control_plane_tools_are_registered() -> None:
    tools = asyncio.run(vps_ops_server.mcp.list_tools())
    names = {tool.name for tool in tools}
    assert EXPECTED <= names


def test_connector_provision_wrapper_forwards_arguments(monkeypatch) -> None:
    class Dummy:
        def connector_provision(self, **kwargs):
            return {"ok": True, "kwargs": kwargs}

    monkeypatch.setattr(vps_ops_server, "OPENAI_CONTROL_PLANE", Dummy())
    result = vps_ops_server.openai_connector_provision(
        alias="rental-agent",
        name="EIROS Rental Agent",
        description="Dedicated rental",
        mcp_server_url="http://127.0.0.1:8794/mcp",
        inherit_scope_from_tunnel="tunnel_34343434343434343434343434343434",
    )
    assert result["ok"] is True
    assert result["kwargs"]["alias"] == "rental-agent"
    assert result["kwargs"]["mcp_server_url"] == "http://127.0.0.1:8794/mcp"


def test_control_plane_error_is_returned_as_stable_json(monkeypatch) -> None:
    from runtime.openai_control_plane import ControlPlaneError

    class Dummy:
        def tunnel_get(self, tunnel_id: str):
            raise ControlPlaneError("tunnel_not_found", "missing")

    monkeypatch.setattr(vps_ops_server, "OPENAI_CONTROL_PLANE", Dummy())
    result = vps_ops_server.openai_tunnel_get("tunnel_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    assert result == {"ok": False, "error": "tunnel_not_found", "message": "missing"}
