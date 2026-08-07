from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

TUNNEL_CLIENT = "/usr/local/bin/tunnel-client"
DEFAULT_AUDIT_PATH = Path("/var/log/eiros/openai-control-plane.jsonl")
DEFAULT_ADMIN_SECRET_PATH = Path("/etc/eiros/openai-admin.key")
DEFAULT_CONTROL_PLANE_BASE_URL = "https://api.openai.com"

_TUNNEL_ID_RE = re.compile(r"^tunnel_[a-z0-9]{32}$")
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_SECRET_ASSIGN_RE = re.compile(
    r"(?i)\b(OPENAI_ADMIN_KEY|CONTROL_PLANE_API_KEY|OPENAI_API_KEY)\s*=\s*([^\s\"']+)"
)
_BEARER_RE = re.compile(r"(?i)(Authorization\s*:\s*Bearer\s+)([^\s]+)")
_SK_RE = re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}\b")


@dataclass(frozen=True)
class CommandResult:
    ok: bool
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: int


class ControlPlaneError(RuntimeError):
    def __init__(self, category: str, message: str) -> None:
        self.category = str(category)
        self.message = str(message)
        super().__init__(f"{self.category}: {self.message}")


def redact_text(value: str, extra_secrets: list[str] | tuple[str, ...] | None = None) -> str:
    text = str(value or "")
    text = _BEARER_RE.sub(r"\1[REDACTED]", text)
    text = _SECRET_ASSIGN_RE.sub(lambda m: f"{m.group(1)}=[REDACTED]", text)
    text = _SK_RE.sub("[REDACTED]", text)
    for secret in extra_secrets or ():
        if secret:
            text = text.replace(str(secret), "[REDACTED]")
    return text


def _sanitize(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text.lower() in {
                "admin_key",
                "api_key",
                "authorization",
                "token",
                "access_token",
                "refresh_token",
                "secret",
            }:
                continue
            out[key_text] = _sanitize(item)
        return out
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize(item) for item in value]
    return value


def _default_runner(argv: list[str], timeout: int = 30) -> dict[str, Any]:
    started = time.time()
    try:
        proc = subprocess.run(
            argv,
            shell=False,
            text=True,
            capture_output=True,
            timeout=max(1, min(int(timeout), 180)),
            env={
                "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                "HOME": "/home/eiros",
                "LANG": "C.UTF-8",
            },
        )
        return {
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "stdout": proc.stdout or "",
            "stderr": proc.stderr or "",
            "duration_ms": int((time.time() - started) * 1000),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "exit_code": None,
            "stdout": exc.stdout or "",
            "stderr": "timeout",
            "duration_ms": int((time.time() - started) * 1000),
        }


Runner = Callable[[list[str], int], dict[str, Any]]


class OpenAIControlPlane:
    def __init__(
        self,
        runner: Runner | None = None,
        audit_path: Path | str = DEFAULT_AUDIT_PATH,
        admin_secret_path: Path | str = DEFAULT_ADMIN_SECRET_PATH,
        protected_tunnel_ids: set[str] | None = None,
        protected_profile_names: set[str] | None = None,
        protected_service_names: set[str] | None = None,
        control_plane_base_url: str = DEFAULT_CONTROL_PLANE_BASE_URL,
    ) -> None:
        self.runner = runner or _default_runner
        self.audit_path = Path(audit_path)
        self.admin_secret_path = Path(admin_secret_path)
        self.protected_tunnel_ids = set(protected_tunnel_ids or set())
        self.protected_profile_names = set(protected_profile_names or {"eiros", "eiros-vps-ops"})
        self.protected_service_names = set(protected_service_names or {"eiros-tunnel.service"})
        self.control_plane_base_url = str(control_plane_base_url or DEFAULT_CONTROL_PLANE_BASE_URL)

    @staticmethod
    def validate_tunnel_id(tunnel_id: str) -> bool:
        if not _TUNNEL_ID_RE.fullmatch(str(tunnel_id or "")):
            raise ControlPlaneError("invalid_identifier", "invalid tunnel id")
        return True

    @staticmethod
    def validate_slug(value: str) -> str:
        slug = str(value or "").strip()
        if not _SLUG_RE.fullmatch(slug):
            raise ControlPlaneError("invalid_identifier", "invalid managed slug")
        return slug

    @staticmethod
    def validate_local_mcp_url(value: str) -> str:
        raw = str(value or "").strip()
        parsed = urlparse(raw)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise ControlPlaneError("invalid_local_mcp_url", "MCP URL must use loopback HTTP")
        if parsed.port is None or parsed.port < 1 or parsed.port > 65535:
            raise ControlPlaneError("invalid_local_mcp_url", "MCP URL must include a valid port")
        if not parsed.path.startswith("/"):
            raise ControlPlaneError("invalid_local_mcp_url", "MCP URL must include a path")
        return raw

    def _run_tunnel_client(self, args: list[str], timeout: int = 30) -> CommandResult:
        argv = [TUNNEL_CLIENT, *[str(a) for a in args]]
        raw = self.runner(argv, timeout)
        stdout = redact_text(str(raw.get("stdout") or ""))[-120000:]
        stderr = redact_text(str(raw.get("stderr") or ""))[-120000:]
        return CommandResult(
            ok=bool(raw.get("ok")),
            exit_code=raw.get("exit_code"),
            stdout=stdout,
            stderr=stderr,
            duration_ms=int(raw.get("duration_ms") or 0),
        )

    @staticmethod
    def _json_or_empty(text: str) -> Any:
        raw = str(text or "").strip()
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    def admin_status(self) -> dict[str, Any]:
        profiles_result = self._run_tunnel_client(["admin-profiles", "list", "--json"], timeout=15)
        version_result = self._run_tunnel_client(["--version"], timeout=10)
        tunnel_help = self._run_tunnel_client(["admin", "tunnels", "--help"], timeout=10)
        runtime_help = self._run_tunnel_client(["runtimes", "--help"], timeout=10)

        profiles_payload = self._json_or_empty(profiles_result.stdout)
        profiles: list[dict[str, Any]] = []
        if isinstance(profiles_payload, dict):
            maybe = profiles_payload.get("profiles")
            if isinstance(maybe, list):
                profiles = [p for p in maybe if isinstance(p, dict)]
        elif isinstance(profiles_payload, list):
            profiles = [p for p in profiles_payload if isinstance(p, dict)]

        active = any(bool(p.get("active")) for p in profiles)
        if not active and isinstance(profiles_payload, dict):
            active_name = str(profiles_payload.get("active") or profiles_payload.get("active_profile") or "")
            active = bool(active_name)

        tunnel_text = f"{tunnel_help.stdout}\n{tunnel_help.stderr}".lower()
        runtime_text = f"{runtime_help.stdout}\n{runtime_help.stderr}".lower()
        tunnel_crud = tunnel_help.ok and all(word in tunnel_text for word in ("create", "update", "delete", "get", "list"))
        runtime_crud = runtime_help.ok and all(word in runtime_text for word in ("create", "update", "delete"))

        return {
            "ok": bool(profiles_result.ok or self.admin_secret_path.exists()),
            "secret_reference_configured": self.admin_secret_path.is_file(),
            "admin_profile_active": active,
            "control_plane_base_url": self.control_plane_base_url,
            "tunnel_client_version": redact_text(version_result.stdout.strip() or version_result.stderr.strip())[:500],
            "tunnel_crud_available": tunnel_crud,
            "runtime_crud_available": runtime_crud,
        }

    def _write_audit(
        self,
        *,
        operation: str,
        target_type: str,
        target: str,
        requested: dict[str, Any] | None,
        ok: bool,
        exit_code: int | None,
        duration_ms: int,
        error_category: str,
    ) -> None:
        event = {
            "timestamp": int(time.time()),
            "operation": str(operation),
            "target_type": str(target_type),
            "target": str(target),
            "requested": _sanitize(requested or {}),
            "ok": bool(ok),
            "exit_code": exit_code,
            "duration_ms": int(duration_ms),
            "error_category": str(error_category or ""),
        }
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        with self.audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")

    def audit(self, limit: int = 100) -> dict[str, Any]:
        bounded = max(1, min(int(limit), 500))
        if not self.audit_path.exists():
            return {"ok": True, "events": []}
        lines = self.audit_path.read_text(encoding="utf-8", errors="replace").splitlines()
        events: list[dict[str, Any]] = []
        for line in lines[-bounded:]:
            try:
                payload = json.loads(redact_text(line))
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                events.append(_sanitize(payload))
        return {"ok": True, "events": events}
