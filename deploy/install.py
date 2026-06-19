from __future__ import annotations

import argparse
import json
import os
import pwd
import shutil
import subprocess
import sys
import time
from pathlib import Path

def run(*command: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=check, text=True, capture_output=True)

def ensure_user(name: str) -> None:
    try:
        pwd.getpwnam(name)
    except KeyError:
        run("useradd", "--system", "--create-home", "--shell", "/bin/bash", name)

def copy_source(source: Path, target: Path) -> None:
    excluded = {
        ".git", ".venv", "__pycache__", "logs", "memory", "tasks",
        "state.json", ".eiros-state.json", "JOURNAL.md", "eiros-control-plane.bundle",
    }
    def ignore(_directory: str, names: list[str]) -> set[str]:
        return {name for name in names if name in excluded or name.endswith((".pyc", ".lock", ".pid", ".sock"))}
    shutil.copytree(source, target, ignore=ignore)

def main() -> None:
    parser = argparse.ArgumentParser(description="Install an EIROS control-plane release")
    parser.add_argument("--source", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--prefix", default="/opt/eiros-control-plane")
    parser.add_argument("--data-dir", default="/var/lib/eiros")
    parser.add_argument("--user", default="eiros")
    parser.add_argument("--display-name", default="EIROS")
    parser.add_argument("--widget-domain", default="")
    parser.add_argument("--channel", default="default")
    parser.add_argument("--no-systemd", action="store_true")
    parser.add_argument("--plan", action="store_true")
    args = parser.parse_args()

    if os.geteuid() != 0:
        raise SystemExit("Run this installer as root")

    source = Path(args.source).resolve()
    prefix = Path(args.prefix).resolve()
    data_dir = Path(args.data_dir).resolve()
    manifest = json.loads((source / "deploy" / "manifest.json").read_text(encoding="utf-8"))
    version = str(manifest["version"])
    release = prefix / "releases" / f"{version}-{int(time.time())}"
    current = prefix / "current"
    venv = prefix / "venv"

    ensure_user(args.user)
    release.parent.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    copy_source(source, release)

    if not venv.exists():
        run(sys.executable, "-m", "venv", str(venv))
    run(str(venv / "bin" / "python"), "-m", "pip", "install", "--upgrade", "pip")
    run(str(venv / "bin" / "pip"), "install", "-r", str(release / "requirements.txt"))

    temporary = prefix / ".current.new"
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(release)
    os.replace(temporary, current)

    for path in (prefix, release, data_dir):
        shutil.chown(path, user=args.user, group=args.user)
    for root, directories, files in os.walk(data_dir):
        shutil.chown(root, user=args.user, group=args.user)
        for name in directories + files:
            shutil.chown(Path(root) / name, user=args.user, group=args.user)

    environment_dir = Path("/etc/eiros")
    environment_dir.mkdir(parents=True, exist_ok=True)
    environment = environment_dir / "eiros.env"
    environment.write_text(
        f"EIROS_DATA_DIR={data_dir}\nPYTHONPATH={current}\nEIROS_WIDGET_DOMAIN={args.widget_domain}\n",
        encoding="utf-8",
    )
    environment.chmod(0o640)

    init = run(
        "runuser", "-u", args.user, "--",
        "env", f"EIROS_DATA_DIR={data_dir}", f"PYTHONPATH={current}",
        str(venv / "bin" / "python"), "-m", "runtime.bootstrap",
        "--display-name", args.display_name, "--channel", args.channel,
        "--widget-domain", args.widget_domain, "--json",
    )

    if not args.no_systemd:
        shutil.copy2(release / "deploy" / "eiros-worker.service", "/etc/systemd/system/eiros-worker.service")
        shutil.copy2(release / "deploy" / "eiros-tunnel.service", "/etc/systemd/system/eiros-tunnel.service")
        run("systemctl", "daemon-reload")
        run("systemctl", "enable", "--now", "eiros-worker.service")

    result = {
        "ok": True,
        "version": version,
        "release": str(release),
        "current": str(current),
        "data_dir": str(data_dir),
        "user": args.user,
        "bootstrap": json.loads(init.stdout),
        "tunnel_ready": Path("/etc/eiros/tunnel.env").exists(),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
