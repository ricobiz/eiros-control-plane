import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SERVICE = ROOT / "deploy" / "eiros-rental-mcp.service"
INSTALLER = ROOT / "deploy" / "install_rental_agent.py"


def test_systemd_unit_is_dedicated_and_restarts() -> None:
    text = SERVICE.read_text(encoding="utf-8")
    assert "Description=EIROS Rental Agent MCP" in text
    assert "User=eiros-rental" in text
    assert "WorkingDirectory=/opt/eiros-control-plane" in text
    assert "ExecStart=/usr/bin/xvfb-run" in text
    assert "/opt/eiros-control-plane/venv/bin/python -m runtime.rental_agent.server" in text
    assert "EnvironmentFile=/etc/eiros/rental-agent.env" in text
    assert "Environment=PLAYWRIGHT_BROWSERS_PATH=/opt/eiros-playwright-browsers" in text
    assert "Restart=always" in text


def test_installer_dry_run_is_deterministic_and_non_mutating() -> None:
    process = subprocess.run(
        [sys.executable, str(INSTALLER), "--dry-run"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(process.stdout)
    assert payload["dry_run"] is True
    assert payload["service"] == "eiros-rental-mcp.service"
    assert payload["data_dir"] == "/var/lib/eiros-rental"
    assert payload["port"] == 8794
    assert payload["actions"] == [
        "ensure_system_user:eiros-rental",
        "ensure_directory:/var/lib/eiros-rental",
        "ensure_directory:/var/lib/eiros-rental/browser",
        "ensure_directory:/var/lib/eiros-rental/logs",
        "ensure_env:/etc/eiros/rental-agent.env",
        "ensure_browser_runtime:/opt/eiros-playwright-browsers",
        "install_unit:eiros-rental-mcp.service",
        "systemd_daemon_reload",
        "enable_restart:eiros-rental-mcp.service",
        "initialize_database:/var/lib/eiros-rental/rental.db",
    ]
