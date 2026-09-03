from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


class SecretStore:
    def __init__(self, root: Path = Path("/var/lib/eiros-operator/secrets")) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)

    def _path(self, name: str) -> Path:
        if not _NAME.fullmatch(str(name)):
            raise ValueError("invalid secret name")
        return self.root / str(name)

    def set(self, name: str, value: str) -> dict[str, object]:
        path = self._path(name)
        data = str(value).encode()
        fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(self.root))
        try:
            os.fchmod(fd, 0o600)
            os.write(fd, data)
            os.fsync(fd)
            os.close(fd)
            fd = -1
            os.replace(tmp, path)
            os.chmod(path, 0o600)
        finally:
            if fd >= 0:
                os.close(fd)
            if os.path.exists(tmp):
                os.unlink(tmp)
        return {"ok": True, "name": str(name), "bytes": len(data)}

    def exists(self, name: str) -> dict[str, object]:
        return {"ok": True, "name": str(name), "exists": self._path(name).is_file()}

    def list(self) -> list[dict[str, object]]:
        return [
            {"name": p.name, "bytes": p.stat().st_size, "mode": "0600"}
            for p in sorted(self.root.iterdir())
            if p.is_file()
        ]

    def delete(self, name: str) -> dict[str, object]:
        path = self._path(name)
        existed = path.exists()
        path.unlink(missing_ok=True)
        return {"ok": True, "name": str(name), "existed": existed}

    def _read(self, name: str) -> bytes:
        return self._path(name).read_bytes()

    @staticmethod
    def _redact(data: bytes, secrets: list[bytes]) -> str:
        safe = bytes(data)
        for secret in secrets:
            if secret:
                safe = safe.replace(secret, b"***REDACTED***")
        return safe.decode("utf-8", "replace")[-200000:]

    def type_into_desktop(self, name: str, desktop) -> dict[str, object]:
        data = self._read(name)
        desktop.type_bytes(data)
        return {"ok": True, "name": str(name), "bytes": len(data)}

    def run_with_stdin(self, name: str, argv: list[str], cwd: str = "/") -> dict[str, object]:
        if not argv:
            raise ValueError("argv is required")
        data = self._read(name)
        proc = subprocess.run(argv, cwd=cwd, input=data, capture_output=True, check=False)
        return {
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "stdout": self._redact(proc.stdout, [data]),
            "stderr": self._redact(proc.stderr, [data]),
        }

    def run_with_env(self, mapping: dict[str, str], argv: list[str], cwd: str = "/") -> dict[str, object]:
        if not argv:
            raise ValueError("argv is required")
        env = os.environ.copy()
        values: list[bytes] = []
        for env_name, secret_name in mapping.items():
            value = self._read(secret_name)
            values.append(value)
            env[str(env_name)] = value.decode("utf-8")
        proc = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, check=False)
        return {
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "stdout": self._redact(proc.stdout, values),
            "stderr": self._redact(proc.stderr, values),
        }
