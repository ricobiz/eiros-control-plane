from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import tempfile
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PYTHON = Path("/opt/eiros-control-plane/venv/bin/python")
DEFAULT_ROLLBACK_SCRIPT = REPO_ROOT / "deploy/eiros_operator_rollback.py"


class SystemdScheduler:
    def __init__(
        self,
        python: Path = DEFAULT_PYTHON,
        script: Path = DEFAULT_ROLLBACK_SCRIPT,
    ) -> None:
        self.python = Path(python)
        self.script = Path(script)

    def schedule(self, tx_id: str, seconds: int) -> None:
        subprocess.run(
            [
                "systemd-run",
                f"--unit=eiros-operator-rollback-{tx_id}",
                f"--on-active={int(seconds)}s",
                "--timer-property=AccuracySec=1s",
                str(self.python),
                str(self.script),
                str(tx_id),
            ],
            check=True,
            capture_output=True,
        )

    def cancel(self, tx_id: str) -> None:
        subprocess.run(
            ["systemctl", "stop", f"eiros-operator-rollback-{tx_id}.timer"],
            check=False,
            capture_output=True,
        )


class RecoveryManager:
    def __init__(
        self,
        root: Path = Path("/var/lib/eiros-operator/rollback"),
        scheduler=None,
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        self.scheduler = scheduler or SystemdScheduler()

    def _dir(self, tx_id: str) -> Path:
        return self.root / str(tx_id)

    def _manifest_path(self, tx_id: str) -> Path:
        return self._dir(tx_id) / "manifest.json"

    def _load(self, tx_id: str) -> dict:
        return json.loads(self._manifest_path(tx_id).read_text())

    def _save(self, tx_id: str, manifest: dict) -> None:
        path = self._manifest_path(tx_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)

    def stage(self, paths: list[str], seconds: int = 120) -> dict[str, object]:
        if not paths:
            raise ValueError("at least one path is required")
        delay = max(5, min(int(seconds), 3600))
        tx_id = f"rb_{uuid.uuid4().hex}"
        directory = self._dir(tx_id)
        backups = directory / "backups"
        backups.mkdir(parents=True)
        os.chmod(directory, 0o700)
        os.chmod(backups, 0o700)

        entries: list[dict[str, object]] = []
        for index, raw in enumerate(paths):
            path = Path(raw).expanduser()
            existed = path.exists() or path.is_symlink()
            entry: dict[str, object] = {
                "path": str(path),
                "existed": existed,
                "backup": "",
                "mode": None,
                "uid": None,
                "gid": None,
            }
            if existed:
                if not path.is_file():
                    raise ValueError(f"rollback paths must be regular files: {path}")
                info = path.stat()
                entry.update(
                    mode=stat.S_IMODE(info.st_mode),
                    uid=info.st_uid,
                    gid=info.st_gid,
                )
                backup = backups / f"{index}.bin"
                shutil.copy2(path, backup)
                os.chmod(backup, 0o600)
                entry["backup"] = str(backup)
            entries.append(entry)

        manifest = {
            "tx_id": tx_id,
            "state": "staged",
            "seconds": delay,
            "entries": entries,
        }
        self._save(tx_id, manifest)
        self.scheduler.schedule(tx_id, delay)
        return {
            "ok": True,
            "tx_id": tx_id,
            "state": "staged",
            "paths": [entry["path"] for entry in entries],
            "rollback_seconds": delay,
        }

    def atomic_write(
        self,
        tx_id: str,
        path: str,
        content: str,
        mode: int = 0o600,
    ) -> dict[str, object]:
        manifest = self._load(tx_id)
        if manifest["state"] != "staged":
            raise ValueError(f"transaction not staged: {manifest['state']}")
        target = str(Path(path).expanduser())
        if target not in {entry["path"] for entry in manifest["entries"]}:
            raise ValueError("path was not staged")
        target_path = Path(target)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=f".{target_path.name}.", dir=str(target_path.parent))
        try:
            os.fchmod(fd, int(mode))
            data = str(content).encode()
            os.write(fd, data)
            os.fsync(fd)
            os.close(fd)
            fd = -1
            os.replace(tmp, target_path)
        finally:
            if fd >= 0:
                os.close(fd)
            if os.path.exists(tmp):
                os.unlink(tmp)
        return {"ok": True, "tx_id": str(tx_id), "path": target, "bytes": len(data)}

    def verify(self, tx_id: str, argv: list[str]) -> dict[str, object]:
        if not argv:
            raise ValueError("argv is required")
        proc = subprocess.run(argv, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            rollback = self.rollback(tx_id)
            return {
                "ok": False,
                "tx_id": str(tx_id),
                "exit_code": proc.returncode,
                "stdout": proc.stdout[-120000:],
                "stderr": proc.stderr[-120000:],
                "rollback": rollback,
            }
        return {
            "ok": True,
            "tx_id": str(tx_id),
            "exit_code": 0,
            "stdout": proc.stdout[-120000:],
            "stderr": proc.stderr[-120000:],
        }

    def commit(self, tx_id: str) -> dict[str, object]:
        manifest = self._load(tx_id)
        if manifest["state"] == "rolled_back":
            raise ValueError("rolled back transaction cannot be committed")
        manifest["state"] = "committed"
        self._save(tx_id, manifest)
        self.scheduler.cancel(tx_id)
        return {"ok": True, "tx_id": str(tx_id), "state": "committed"}

    def rollback(self, tx_id: str) -> dict[str, object]:
        manifest = self._load(tx_id)
        if manifest["state"] == "rolled_back":
            return {"ok": True, "tx_id": str(tx_id), "state": "rolled_back", "already": True}
        if manifest["state"] == "committed":
            raise ValueError("committed transaction cannot be rolled back automatically")

        for entry in manifest["entries"]:
            path = Path(entry["path"])
            if entry["existed"]:
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(entry["backup"], path)
                os.chmod(path, int(entry["mode"]))
                os.chown(path, int(entry["uid"]), int(entry["gid"]))
            elif path.exists() or path.is_symlink():
                if path.is_dir() and not path.is_symlink():
                    shutil.rmtree(path)
                else:
                    path.unlink()

        manifest["state"] = "rolled_back"
        self._save(tx_id, manifest)
        self.scheduler.cancel(tx_id)
        return {"ok": True, "tx_id": str(tx_id), "state": "rolled_back"}

    def status(self, tx_id: str) -> dict[str, object]:
        manifest = self._load(tx_id)
        return {
            "ok": True,
            "tx_id": str(tx_id),
            "state": manifest["state"],
            "paths": [entry["path"] for entry in manifest["entries"]],
            "rollback_seconds": manifest["seconds"],
        }
