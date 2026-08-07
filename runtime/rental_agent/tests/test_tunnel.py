from runtime.rental_agent.tunnel import render_profile, redacted_tunnel_status

DUMMY_TUNNEL_ID = "tunnel_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def test_render_profile_targets_local_rental_mcp_without_raw_key() -> None:
    text = render_profile(
        tunnel_id=DUMMY_TUNNEL_ID,
        api_key_ref="env:CONTROL_PLANE_API_KEY",
    )
    assert f'tunnel_id: "{DUMMY_TUNNEL_ID}"' in text
    assert 'api_key: "env:CONTROL_PLANE_API_KEY"' in text
    assert 'url: "http://127.0.0.1:8794/mcp"' in text
    assert "sk-" not in text
    assert "OPENAI_ADMIN_KEY" not in text


def test_redacted_tunnel_status_exposes_presence_only() -> None:
    status = redacted_tunnel_status(
        tunnel_id=DUMMY_TUNNEL_ID,
        runtime_key="sk-secret-runtime-value",
        profile_exists=True,
    )
    assert status == {
        "profile": "rental-agent",
        "profile_exists": True,
        "tunnel_id_configured": True,
        "runtime_key_configured": True,
    }
    assert "secret" not in repr(status)

from pathlib import Path
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
TUNNEL_UNIT = ROOT / "deploy" / "eiros-rental-tunnel.service"
TUNNEL_EXAMPLE = ROOT / "deploy" / "rental-tunnel-profile.example.yaml"
INSTALLER = ROOT / "deploy" / "install_rental_agent.py"


def test_tunnel_unit_is_independent_from_ebridge_tunnel() -> None:
    text = TUNNEL_UNIT.read_text(encoding="utf-8")
    assert "Description=EIROS Rental Agent OpenAI Secure MCP Tunnel" in text
    assert "ExecStart=/usr/local/bin/tunnel-client run --profile rental-agent" in text
    assert "Requires=eiros-rental-mcp.service" in text
    assert "EnvironmentFile=/etc/eiros/tunnel.env" in text


def test_example_profile_uses_ephemeral_health_port_and_local_mcp() -> None:
    text = TUNNEL_EXAMPLE.read_text(encoding="utf-8")
    assert 'listen_addr: "127.0.0.1:0"' in text
    assert 'url: "http://127.0.0.1:8794/mcp"' in text
    assert 'api_key: "env:CONTROL_PLANE_API_KEY"' in text


def test_installer_tunnel_dry_run_redacts_identifier() -> None:
    process = subprocess.run(
        [sys.executable, str(INSTALLER), "--dry-run", "--tunnel-id", DUMMY_TUNNEL_ID],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert DUMMY_TUNNEL_ID not in process.stdout
    payload = json.loads(process.stdout)
    assert payload["tunnel"]["tunnel_id_configured"] is True
    assert payload["tunnel"]["profile"] == "rental-agent"
    assert "install_tunnel_profile:rental-agent" in payload["actions"]
    assert "enable_restart:eiros-rental-tunnel.service" in payload["actions"]
