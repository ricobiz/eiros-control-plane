from __future__ import annotations

import argparse
import json
import os
import pwd
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICE_NAME = "eiros-rental-mcp.service"
SERVICE_SOURCE = ROOT / "deploy" / SERVICE_NAME
SERVICE_DEST = Path("/etc/systemd/system") / SERVICE_NAME
ENV_PATH = Path("/etc/eiros/rental-agent.env")
DATA_DIR = Path("/var/lib/eiros-rental")
BROWSER_DIR = DATA_DIR / "browser"
LOG_DIR = DATA_DIR / "logs"
DB_PATH = DATA_DIR / "rental.db"
SERVICE_USER = "eiros-rental"
PORT = 8794


def action_list() -> list[str]:
    return [
        f"ensure_system_user:{SERVICE_USER}",
        f"ensure_directory:{DATA_DIR}",
        f"ensure_directory:{BROWSER_DIR}",
        f"ensure_directory:{LOG_DIR}",
        f"ensure_env:{ENV_PATH}",
        f"install_unit:{SERVICE_NAME}",
        "systemd_daemon_reload",
        f"enable_restart:{SERVICE_NAME}",
        f"initialize_database:{DB_PATH}",
    ]


def report(dry_run: bool) -> dict[str, object]:
    return {
        "ok": True,
        "dry_run": dry_run,
        "service": SERVICE_NAME,
        "data_dir": str(DATA_DIR),
        "port": PORT,
        "actions": action_list(),
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


def install() -> None:
    if os.geteuid() != 0:
        raise SystemExit("install_rental_agent.py must run as root")
    ensure_user()
    ensure_directories()
    ensure_env()
    install_service()
    initialize_database()


def main() -> None:
    parser = argparse.ArgumentParser(description="Install EIROS Rental Agent MCP foundation")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.dry_run:
        install()
    print(json.dumps(report(args.dry_run), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
