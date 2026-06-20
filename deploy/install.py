from __future__ import annotations

import argparse
import json
import os
import pwd
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class InstallPlan:
    version: str
    source: str
    prefix: str
    data_dir: str
    release: str
    current: str
    previous: str
    venv: str
    user: str
    systemd: bool
    widget_domain: str
    channel: str


def run(*command: str, check: bool = True, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=check, text=True, capture_output=True, env=env)


def read_manifest(source: Path) -> dict[str, Any]:
    path = source / "deploy" / "manifest.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not value.get("version"):
        raise RuntimeError("Invalid deployment manifest")
    return value


def build_plan(args: argparse.Namespace, timestamp: int | None = None) -> InstallPlan:
    source = Path(args.source).expanduser().resolve()
    prefix = Path(args.prefix).expanduser().resolve()
    data_dir = Path(args.data_dir).expanduser().resolve()
    manifest = read_manifest(source)
    version = str(manifest["version"])
    stamp = int(timestamp if timestamp is not None else time.time())
    release = prefix / "releases" / f"{version}-{stamp}"
    return InstallPlan(
        version=version,
        source=str(source),
        prefix=str(prefix),
        data_dir=str(data_dir),
        release=str(release),
        current=str(prefix / "current"),
        previous=str(prefix / "previous"),
        venv=str(prefix / "venv"),
        user=args.user,
        systemd=not args.no_systemd,
        widget_domain=args.widget_domain,
        channel=args.channel,
    )


def ensure_user(name: str) -> None:
    try:
        pwd.getpwnam(name)
    except KeyError:
        run("useradd", "--system", "--create-home", "--shell", "/bin/bash", name)


def source_ignore(directory: str, names: list[str]) -> set[str]:
    folder = Path(directory).name
    ignored = {
        name for name in names
        if name in {".git", ".venv", "__pycache__", "build", "logs", "memory", "tasks"}
        or name.endswith((".pyc", ".lock", ".pid", ".sock", ".bundle", ".sha256", ".egg-info"))
    }
    if folder == "runtime":
        ignored.update(name for name in names if name.endswith(".json") or name.endswith(".root-bak"))
    if folder == "config":
        ignored.add("instance.json")
    return ignored


def copy_source(source: Path, target: Path) -> None:
    shutil.copytree(source, target, ignore=source_ignore)


def atomic_symlink(link: Path, target: Path) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    temporary = link.parent / f".{link.name}.new"
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(target)
    os.replace(temporary, link)


def current_target(link: Path) -> Path | None:
    if not link.is_symlink():
        return None
    return link.resolve(strict=False)


def switch_release(current: Path, previous: Path, release: Path) -> Path | None:
    old = current_target(current)
    if old is not None:
        atomic_symlink(previous, old)
    atomic_symlink(current, release)
    return old


def rollback_release(current: Path, previous: Path) -> Path:
    old = current_target(previous)
    if old is None:
        raise RuntimeError("No previous release is available")
    atomic_symlink(current, old)
    return old


def chown_tree(path: Path, user: str) -> None:
    shutil.chown(path, user=user, group=user)
    if path.is_dir():
        for root, directories, files in os.walk(path):
            shutil.chown(root, user=user, group=user)
            for name in directories + files:
                shutil.chown(Path(root) / name, user=user, group=user)


def write_environment(data_dir: Path, current: Path, widget_domain: str) -> Path:
    directory = Path("/etc/eiros")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "eiros.env"
    temporary = directory / ".eiros.env.new"
    temporary.write_text(
        f"EIROS_DATA_DIR={data_dir}\nPYTHONPATH={current}\nEIROS_WIDGET_DOMAIN={widget_domain}\n",
        encoding="utf-8",
    )
    temporary.chmod(0o640)
    os.replace(temporary, path)
    return path


def run_as_user(user: str, environment: dict[str, str], *command: str) -> subprocess.CompletedProcess[str]:
    env_args = [f"{key}={value}" for key, value in environment.items()]
    return run("runuser", "-u", user, "--", "env", *env_args, *command)


def install_release(args: argparse.Namespace) -> dict[str, Any]:
    if os.geteuid() != 0:
        raise RuntimeError("Run installation as root")

    plan = build_plan(args)
    source = Path(plan.source)
    prefix = Path(plan.prefix)
    data_dir = Path(plan.data_dir)
    release = Path(plan.release)
    current = Path(plan.current)
    previous = Path(plan.previous)
    venv = Path(plan.venv)

    ensure_user(plan.user)
    prefix.mkdir(parents=True, exist_ok=True)
    release.parent.mkdir(parents=True, exist_ok=True)
    # Installation runs as root, while bootstrap runs as the isolated service
    # user. Keep the release parent traversable without making it public.
    shutil.chown(release.parent, user="root", group=plan.user)
    release.parent.chmod(0o750)
    data_dir.mkdir(parents=True, exist_ok=True)
    if release.exists():
        raise RuntimeError(f"Release already exists: {release}")
    copy_source(source, release)

    if not venv.exists():
        run(sys.executable, "-m", "venv", str(venv))
    run(str(venv / "bin" / "python"), "-m", "pip", "install", "--upgrade", "pip")
    run(str(venv / "bin" / "pip"), "install", "--upgrade", str(release))

    chown_tree(release, plan.user)
    chown_tree(data_dir, plan.user)
    shutil.chown(prefix, user=plan.user, group=plan.user)

    environment = {
        "EIROS_DATA_DIR": str(data_dir),
        "PYTHONPATH": str(release),
        "EIROS_WIDGET_DOMAIN": plan.widget_domain,
    }
    bootstrap = run_as_user(
        plan.user,
        environment,
        str(venv / "bin" / "python"), "-m", "runtime.bootstrap",
        "--display-name", args.display_name,
        "--channel", plan.channel,
        "--widget-domain", plan.widget_domain,
        "--json",
    )
    offline_doctor = run_as_user(
        plan.user,
        environment,
        str(venv / "bin" / "python"), "-m", "runtime.doctor", "--offline", "--json",
    )
    doctor_value = json.loads(offline_doctor.stdout)
    if not doctor_value.get("ok"):
        raise RuntimeError("New release failed offline doctor")

    old = switch_release(current, previous, release)
    write_environment(data_dir, current, plan.widget_domain)

    service_actions: list[str] = []
    try:
        if plan.systemd:
            shutil.copy2(release / "deploy" / "eiros-root-broker.service", "/etc/systemd/system/eiros-root-broker.service")
            shutil.copy2(release / "deploy" / "eiros-worker.service", "/etc/systemd/system/eiros-worker.service")
            shutil.copy2(release / "deploy" / "eiros-tunnel.service", "/etc/systemd/system/eiros-tunnel.service")
            run("systemctl", "daemon-reload")
            run("systemctl", "enable", "--now", "eiros-root-broker.service")
            service_actions.append("root_broker_started")
            run("systemctl", "enable", "--now", "eiros-worker.service")
            service_actions.append("worker_started")
            if Path("/etc/eiros/tunnel.env").exists():
                run("systemctl", "enable", "--now", "eiros-tunnel.service")
                service_actions.append("tunnel_started")
            else:
                service_actions.append("tunnel_waiting_for_credentials")
    except Exception:
        if old is not None:
            atomic_symlink(current, old)
            if plan.systemd:
                run("systemctl", "restart", "eiros-root-broker.service", check=False)
                run("systemctl", "restart", "eiros-worker.service", check=False)
                run("systemctl", "restart", "eiros-tunnel.service", check=False)
        raise

    state = {
        "ok": True,
        "version": plan.version,
        "release": str(release),
        "previous_release": str(old) if old else None,
        "current": str(current),
        "data_dir": str(data_dir),
        "user": plan.user,
        "bootstrap": json.loads(bootstrap.stdout),
        "offline_doctor": doctor_value,
        "service_actions": service_actions,
    }
    state_path = data_dir / "runtime" / "install-state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    shutil.chown(state_path, user=plan.user, group=plan.user)
    return state


def rollback(args: argparse.Namespace) -> dict[str, Any]:
    if os.geteuid() != 0:
        raise RuntimeError("Run rollback as root")
    prefix = Path(args.prefix).expanduser().resolve()
    target = rollback_release(prefix / "current", prefix / "previous")
    actions: list[str] = []
    if not args.no_systemd:
        run("systemctl", "restart", "eiros-worker.service", check=False)
        run("systemctl", "restart", "eiros-tunnel.service", check=False)
        actions.append("services_restarted")
    return {"ok": True, "current_release": str(target), "actions": actions}


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Install or roll back an EIROS control-plane release")
    root.add_argument("--source", default=str(Path(__file__).resolve().parents[1]))
    root.add_argument("--prefix", default="/opt/eiros-control-plane")
    root.add_argument("--data-dir", default="/var/lib/eiros")
    root.add_argument("--user", default="eiros")
    root.add_argument("--display-name", default="EIROS")
    root.add_argument("--widget-domain", default="")
    root.add_argument("--channel", default="default")
    root.add_argument("--no-systemd", action="store_true")
    root.add_argument("--plan", action="store_true")
    root.add_argument("--rollback", action="store_true")
    return root


def main() -> None:
    args = parser().parse_args()
    if args.plan:
        print(json.dumps({"ok": True, "plan": asdict(build_plan(args))}, ensure_ascii=False, indent=2))
        return
    result = rollback(args) if args.rollback else install_release(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
