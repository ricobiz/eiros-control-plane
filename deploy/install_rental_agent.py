from __future__ import annotations

import argparse
import json
import os
import pwd
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.rental_agent.tunnel import PROFILE_NAME, PROFILE_PATH, redacted_tunnel_status, render_profile, validate_tunnel_id

SERVICE_NAME = "eiros-rental-mcp.service"
SERVICE_SOURCE = ROOT / "deploy" / SERVICE_NAME
SERVICE_DEST = Path("/etc/systemd/system") / SERVICE_NAME
ENV_PATH = Path("/etc/eiros/rental-agent.env")
DATA_DIR = Path("/var/lib/eiros-rental")
BROWSER_DIR = DATA_DIR / "browser"
BROWSER_RUNTIME_DIR = Path("/opt/eiros-playwright-browsers")
LOG_DIR = DATA_DIR / "logs"
DB_PATH = DATA_DIR / "rental.db"
SERVICE_USER = "eiros-rental"
PORT = 8794
TUNNEL_SERVICE_NAME = "eiros-rental-tunnel.service"
TUNNEL_SERVICE_SOURCE = ROOT / "deploy" / TUNNEL_SERVICE_NAME
TUNNEL_SERVICE_DEST = Path("/etc/systemd/system") / TUNNEL_SERVICE_NAME


def action_list(tunnel_id: str = "") -> list[str]:
    actions = [
        f"ensure_system_user:{SERVICE_USER}",
        f"ensure_directory:{DATA_DIR}",
        f"ensure_directory:{BROWSER_DIR}",
        f"ensure_directory:{LOG_DIR}",
        f"ensure_env:{ENV_PATH}",
        f"ensure_browser_runtime:{BROWSER_RUNTIME_DIR}",
        f"install_unit:{SERVICE_NAME}",
        "systemd_daemon_reload",
        f"enable_restart:{SERVICE_NAME}",
        f"initialize_database:{DB_PATH}",
    ]
    if tunnel_id.strip():
        validate_tunnel_id(tunnel_id)
        actions.extend([
            f"install_tunnel_profile:{PROFILE_NAME}",
            f"install_unit:{TUNNEL_SERVICE_NAME}",
            f"enable_restart:{TUNNEL_SERVICE_NAME}",
        ])
    return actions


def report(dry_run: bool, tunnel_id: str = "") -> dict[str, object]:
    status = redacted_tunnel_status(
        tunnel_id=tunnel_id,
        runtime_key=os.environ.get("CONTROL_PLANE_API_KEY", ""),
        profile_exists=PROFILE_PATH.exists(),
    )
    return {
        "ok": True,
        "dry_run": dry_run,
        "service": SERVICE_NAME,
        "data_dir": str(DATA_DIR),
        "port": PORT,
        "actions": action_list(tunnel_id),
        "tunnel": status,
    }


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def ensure_user() -> None:
    try:
        pwd.getpwnam(SERVICE_USER)
    except KeyError:
        run([
            "useradd",
            "--system",
            "--home-dir",
            str(DATA_DIR),
            "--shell",
            "/usr/sbin/nologin",
            SERVICE_USER,
        ])


def ensure_directories() -> None:
    for path in (DATA_DIR, BROWSER_DIR, LOG_DIR):
        path.mkdir(parents=True, exist_ok=True)
    shutil.chown(DATA_DIR, user=SERVICE_USER, group=SERVICE_USER)
    shutil.chown(BROWSER_DIR, user=SERVICE_USER, group=SERVICE_USER)
    shutil.chown(LOG_DIR, user=SERVICE_USER, group=SERVICE_USER)
    DATA_DIR.chmod(0o750)
    BROWSER_DIR.chmod(0o750)
    LOG_DIR.chmod(0o750)


def ensure_env() -> None:
    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not ENV_PATH.exists():
        ENV_PATH.write_text(
            "EIROS_RENTAL_DATA_DIR=/var/lib/eiros-rental\n"
            "EIROS_RENTAL_PORT=8794\n"
            "EIROS_RENTAL_HOST=127.0.0.1\n",
            encoding="utf-8",
        )
        ENV_PATH.chmod(0o640)


def ensure_browser_runtime() -> None:
    BROWSER_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    BROWSER_RUNTIME_DIR.chmod(0o755)
    env = dict(os.environ)
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(BROWSER_RUNTIME_DIR)
    subprocess.run(
        [
            "/opt/eiros-control-plane/venv/bin/python",
            "-m",
            "playwright",
            "install",
            "chromium",
        ],
        env=env,
        check=True,
    )


def install_service() -> None:
    shutil.copy2(SERVICE_SOURCE, SERVICE_DEST)
    run(["systemctl", "daemon-reload"])
    run(["systemctl", "enable", SERVICE_NAME])
    run(["systemctl", "restart", SERVICE_NAME])


def initialize_database() -> None:
    env = dict(os.environ)
    env["EIROS_RENTAL_DATA_DIR"] = str(DATA_DIR)
    env["PYTHONPATH"] = "/opt/eiros-control-plane"
    command = [
        "runuser",
        "-u",
        SERVICE_USER,
        "--",
        "/opt/eiros-control-plane/venv/bin/python",
        "-c",
        (
            "from runtime.rental_agent.db import RentalDatabase; "
            "from runtime.rental_agent.config import DEFAULT_DB_PATH; "
            "db=RentalDatabase(DEFAULT_DB_PATH); db.initialize(); "
            "print(db.health()['schema_version'])"
        ),
    ]
    subprocess.run(command, env=env, check=True, stdout=subprocess.DEVNULL)


def install_tunnel(tunnel_id: str) -> None:
    validate_tunnel_id(tunnel_id)
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(render_profile(tunnel_id), encoding="utf-8")
    PROFILE_PATH.chmod(0o600)
    shutil.chown(PROFILE_PATH.parent, user="eiros", group="eiros")
    shutil.chown(PROFILE_PATH, user="eiros", group="eiros")
    shutil.copy2(TUNNEL_SERVICE_SOURCE, TUNNEL_SERVICE_DEST)
    run(["systemctl", "daemon-reload"])
    run(["systemctl", "enable", TUNNEL_SERVICE_NAME])
    run(["systemctl", "restart", TUNNEL_SERVICE_NAME])


def install(tunnel_id: str = "") -> None:
    if os.geteuid() != 0:
        raise SystemExit("install_rental_agent.py must run as root")
    ensure_user()
    ensure_directories()
    ensure_env()
    ensure_browser_runtime()
    install_service()
    initialize_database()
    if tunnel_id.strip():
        install_tunnel(tunnel_id)


def main() -> None:
    parser = argparse.ArgumentParser(description="Install EIROS Rental Agent MCP foundation")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--tunnel-id", default=os.environ.get("EIROS_RENTAL_TUNNEL_ID", ""))
    args = parser.parse_args()
    tunnel_id = args.tunnel_id.strip()
    if tunnel_id:
        validate_tunnel_id(tunnel_id)
    if not args.dry_run:
        install(tunnel_id=tunnel_id)
    print(json.dumps(report(args.dry_run, tunnel_id=tunnel_id), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
