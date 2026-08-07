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


def _default_exec_runner(argv: list[str], timeout: int = 30) -> dict[str, Any]:
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
        system_runner: Runner | None = None,
        audit_path: Path | str = DEFAULT_AUDIT_PATH,
        admin_secret_path: Path | str = DEFAULT_ADMIN_SECRET_PATH,
        admin_profile_name: str = "platform-admin",
        profile_dir: Path | str = Path("/home/eiros/.config/tunnel-client"),
        systemd_dir: Path | str = Path("/etc/systemd/system"),
        health_url_dir: Path | str = Path("/home/eiros"),
        protected_tunnel_ids: set[str] | None = None,
        protected_profile_names: set[str] | None = None,
        protected_service_names: set[str] | None = None,
        control_plane_base_url: str = DEFAULT_CONTROL_PLANE_BASE_URL,
    ) -> None:
        self.runner = runner or _default_exec_runner
        self.system_runner = system_runner or _default_exec_runner
        self.audit_path = Path(audit_path)
        self.admin_secret_path = Path(admin_secret_path)
        self.admin_profile_name = self.validate_slug(admin_profile_name)
        self.profile_dir = Path(profile_dir)
        self.systemd_dir = Path(systemd_dir)
        self.health_url_dir = Path(health_url_dir)
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
        runtime_crud = runtime_help.ok and all(word in runtime_text for word in ("create", "connect", "list", "status", "stop", "rm"))

        return {
            "ok": bool(profiles_result.ok or self.admin_secret_path.exists()),
            "secret_reference_configured": self.admin_secret_path.is_file(),
            "admin_profile_active": active,
            "control_plane_base_url": self.control_plane_base_url,
            "tunnel_client_version": redact_text(version_result.stdout.strip() or version_result.stderr.strip())[:500],
            "tunnel_crud_available": tunnel_crud,
            "runtime_crud_available": runtime_crud,
        }

    def _admin_prefix(self) -> list[str]:
        return ["admin", "--admin-key", f"file:{self.admin_secret_path}", "--json", "tunnels"]

    @staticmethod
    def _bounded_ids(values: list[str] | tuple[str, ...] | None, kind: str) -> list[str]:
        result: list[str] = []
        for raw in values or ():
            value = str(raw or "").strip()
            if not value or len(value) > 128 or not re.fullmatch(r"[A-Za-z0-9_.:-]+", value):
                raise ControlPlaneError("invalid_identifier", f"invalid {kind} id")
            if value not in result:
                result.append(value)
        return result

    def _require_ok(self, result: CommandResult, *, category: str = "tunnel_client_error") -> None:
        if result.ok:
            return
        detail = redact_text(result.stderr or result.stdout or "tunnel-client failed")[:2000]
        lowered = detail.lower()
        mapped = category
        if "not found" in lowered or "404" in lowered:
            mapped = "tunnel_not_found"
        elif "admin" in lowered and ("key" in lowered or "credential" in lowered or "unauthorized" in lowered):
            mapped = "admin_not_configured"
        raise ControlPlaneError(mapped, detail)

    @staticmethod
    def _normalize_tunnel(payload: Any) -> dict[str, Any]:
        data = payload if isinstance(payload, dict) else {}
        tunnel_id = str(data.get("id") or data.get("tunnel_id") or "")
        known = {
            "id", "tunnel_id", "name", "description", "organization_ids", "workspace_ids",
            "status", "state", "created_at", "updated_at",
        }
        raw_meta = {str(k): _sanitize(v) for k, v in data.items() if str(k) not in known}
        return {
            "tunnel_id": tunnel_id,
            "name": str(data.get("name") or ""),
            "description": str(data.get("description") or ""),
            "organization_ids": [str(x) for x in (data.get("organization_ids") or [])],
            "workspace_ids": [str(x) for x in (data.get("workspace_ids") or [])],
            "status": str(data.get("status") or data.get("state") or ""),
            "created_at": data.get("created_at"),
            "updated_at": data.get("updated_at"),
            "raw_meta": raw_meta,
        }

    def tunnel_get(self, tunnel_id: str) -> dict[str, Any]:
        self.validate_tunnel_id(tunnel_id)
        result = self._run_tunnel_client([*self._admin_prefix(), "get", tunnel_id], timeout=30)
        self._require_ok(result)
        payload = self._json_or_empty(result.stdout)
        normalized = self._normalize_tunnel(payload)
        if not normalized["tunnel_id"]:
            normalized["tunnel_id"] = tunnel_id
        return normalized

    def tunnel_list(self, organization_id: str = "", workspace_id: str = "") -> dict[str, Any]:
        org = str(organization_id or "").strip()
        workspace = str(workspace_id or "").strip()
        if bool(org) == bool(workspace):
            raise ControlPlaneError("scope_required", "provide exactly one organization_id or workspace_id")
        args = [*self._admin_prefix(), "list"]
        if org:
            args += ["--organization-id", self._bounded_ids([org], "organization")[0]]
        else:
            args += ["--workspace-id", self._bounded_ids([workspace], "workspace")[0]]
        result = self._run_tunnel_client(args, timeout=30)
        self._require_ok(result)
        payload = self._json_or_empty(result.stdout)
        rows: list[Any]
        if isinstance(payload, list):
            rows = payload
        elif isinstance(payload, dict):
            rows = payload.get("tunnels") if isinstance(payload.get("tunnels"), list) else []
        else:
            rows = []
        return {"ok": True, "tunnels": [self._normalize_tunnel(row) for row in rows if isinstance(row, dict)]}

    def _resolve_scope(
        self,
        organization_ids: list[str] | tuple[str, ...] | None,
        workspace_ids: list[str] | tuple[str, ...] | None,
        inherit_scope_from_tunnel: str,
    ) -> tuple[list[str], list[str]]:
        orgs = self._bounded_ids(organization_ids, "organization")
        workspaces = self._bounded_ids(workspace_ids, "workspace")
        if orgs or workspaces:
            return orgs, workspaces
        source = str(inherit_scope_from_tunnel or "").strip()
        if source:
            inherited = self.tunnel_get(source)
            orgs = self._bounded_ids(inherited.get("organization_ids") or [], "organization")
            workspaces = self._bounded_ids(inherited.get("workspace_ids") or [], "workspace")
        if not orgs and not workspaces:
            raise ControlPlaneError("scope_required", "organization/workspace scope is required")
        return orgs, workspaces

    def tunnel_create(
        self,
        name: str,
        description: str,
        organization_ids: list[str] | tuple[str, ...] | None = None,
        workspace_ids: list[str] | tuple[str, ...] | None = None,
        inherit_scope_from_tunnel: str = "",
    ) -> dict[str, Any]:
        clean_name = str(name or "").strip()
        clean_description = str(description or "").strip()
        if not clean_name or len(clean_name) > 200 or len(clean_description) > 1000:
            raise ControlPlaneError("invalid_identifier", "invalid tunnel name/description")
        orgs, workspaces = self._resolve_scope(organization_ids, workspace_ids, inherit_scope_from_tunnel)
        args = [*self._admin_prefix(), "create", "--name", clean_name, "--description", clean_description]
        for value in orgs:
            args += ["--organization-id", value]
        for value in workspaces:
            args += ["--workspace-id", value]
        result = self._run_tunnel_client(args, timeout=60)
        if not result.ok:
            self._write_audit(
                operation="tunnel_create", target_type="tunnel", target=clean_name,
                requested={"name": clean_name, "description": clean_description, "organization_ids": orgs, "workspace_ids": workspaces},
                ok=False, exit_code=result.exit_code, duration_ms=result.duration_ms, error_category="tunnel_client_error",
            )
            self._require_ok(result)
        normalized = self._normalize_tunnel(self._json_or_empty(result.stdout))
        self._write_audit(
            operation="tunnel_create", target_type="tunnel", target=normalized.get("tunnel_id") or clean_name,
            requested={"name": clean_name, "description": clean_description, "organization_ids": orgs, "workspace_ids": workspaces},
            ok=True, exit_code=result.exit_code, duration_ms=result.duration_ms, error_category="",
        )
        return normalized

    def tunnel_update(
        self,
        tunnel_id: str,
        name: str | None = None,
        description: str | None = None,
        organization_ids: list[str] | tuple[str, ...] | None = None,
        workspace_ids: list[str] | tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        self.validate_tunnel_id(tunnel_id)
        args = [*self._admin_prefix(), "update", tunnel_id]
        requested: dict[str, Any] = {}
        if name is not None:
            clean = str(name).strip()
            if not clean or len(clean) > 200:
                raise ControlPlaneError("invalid_identifier", "invalid tunnel name")
            args += ["--name", clean]
            requested["name"] = clean
        if description is not None:
            clean = str(description).strip()
            if len(clean) > 1000:
                raise ControlPlaneError("invalid_identifier", "description too long")
            args += ["--description", clean]
            requested["description"] = clean
        if organization_ids is not None:
            orgs = self._bounded_ids(organization_ids, "organization")
            for value in orgs:
                args += ["--organization-id", value]
            requested["organization_ids"] = orgs
        if workspace_ids is not None:
            workspaces = self._bounded_ids(workspace_ids, "workspace")
            for value in workspaces:
                args += ["--workspace-id", value]
            requested["workspace_ids"] = workspaces
        if not requested:
            return self.tunnel_get(tunnel_id)
        result = self._run_tunnel_client(args, timeout=60)
        if not result.ok:
            self._write_audit(
                operation="tunnel_update", target_type="tunnel", target=tunnel_id,
                requested=requested, ok=False, exit_code=result.exit_code, duration_ms=result.duration_ms,
                error_category="tunnel_client_error",
            )
            self._require_ok(result)
        normalized = self._normalize_tunnel(self._json_or_empty(result.stdout))
        if not normalized["tunnel_id"]:
            normalized["tunnel_id"] = tunnel_id
        self._write_audit(
            operation="tunnel_update", target_type="tunnel", target=tunnel_id,
            requested=requested, ok=True, exit_code=result.exit_code, duration_ms=result.duration_ms, error_category="",
        )
        return normalized

    def tunnel_delete(self, tunnel_id: str, confirm_tunnel_id: str) -> dict[str, Any]:
        self.validate_tunnel_id(tunnel_id)
        if str(confirm_tunnel_id or "") != tunnel_id:
            raise ControlPlaneError("confirmation_mismatch", "confirm_tunnel_id must equal tunnel_id")
        if tunnel_id in self.protected_tunnel_ids:
            raise ControlPlaneError("protected_target", "protected tunnel cannot be deleted")
        result = self._run_tunnel_client([*self._admin_prefix(), "delete", tunnel_id, "--confirm"], timeout=60)
        if not result.ok:
            self._write_audit(
                operation="tunnel_delete", target_type="tunnel", target=tunnel_id,
                requested={}, ok=False, exit_code=result.exit_code, duration_ms=result.duration_ms,
                error_category="tunnel_client_error",
            )
            self._require_ok(result)
        self._write_audit(
            operation="tunnel_delete", target_type="tunnel", target=tunnel_id,
            requested={}, ok=True, exit_code=result.exit_code, duration_ms=result.duration_ms, error_category="",
        )
        payload = self._json_or_empty(result.stdout)
        return {"ok": True, "tunnel_id": tunnel_id, "result": _sanitize(payload)}

    def _runtime_call(self, command: list[str], timeout: int = 60) -> CommandResult:
        args = ["runtimes", *command, "--admin-key", f"file:{self.admin_secret_path}", "--json"]
        return self._run_tunnel_client(args, timeout=timeout)

    @staticmethod
    def _normalize_runtime(payload: Any, alias: str = "") -> dict[str, Any]:
        data = payload if isinstance(payload, dict) else {}
        return {
            "ok": True,
            "alias": str(data.get("alias") or alias),
            "tunnel_id": str(data.get("tunnel_id") or data.get("id") or ""),
            "state": str(data.get("state") or data.get("status") or ""),
            "profile": str(data.get("profile") or data.get("profile_name") or ""),
            "raw_meta": _sanitize({k: v for k, v in data.items() if k not in {"alias", "tunnel_id", "id", "state", "status", "profile", "profile_name"}}),
        }

    def runtime_list(self, organization_id: str = "", workspace_id: str = "") -> dict[str, Any]:
        command = ["list"]
        if organization_id:
            command += ["--organization-id", self._bounded_ids([organization_id], "organization")[0]]
        if workspace_id:
            command += ["--workspace-id", self._bounded_ids([workspace_id], "workspace")[0]]
        result = self._runtime_call(command, timeout=30)
        self._require_ok(result, category="tunnel_client_error")
        payload = self._json_or_empty(result.stdout)
        rows: list[Any] = []
        if isinstance(payload, list):
            rows = payload
        elif isinstance(payload, dict):
            for key in ("runtimes", "aliases", "items"):
                if isinstance(payload.get(key), list):
                    rows = payload[key]
                    break
        return {"ok": True, "runtimes": [self._normalize_runtime(row) for row in rows if isinstance(row, dict)]}

    def runtime_create(
        self,
        alias: str,
        name: str,
        description: str,
        organization_ids: list[str] | tuple[str, ...] | None = None,
        workspace_ids: list[str] | tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        slug = self.validate_slug(alias)
        orgs = self._bounded_ids(organization_ids, "organization")
        workspaces = self._bounded_ids(workspace_ids, "workspace")
        if not orgs and not workspaces:
            raise ControlPlaneError("scope_required", "runtime creation requires organization/workspace scope")
        command = ["create", "--alias", slug, "--name", str(name), "--description", str(description)]
        for value in orgs:
            command += ["--organization-id", value]
        for value in workspaces:
            command += ["--workspace-id", value]
        result = self._runtime_call(command, timeout=90)
        self._require_ok(result)
        normalized = self._normalize_runtime(self._json_or_empty(result.stdout), slug)
        self._write_audit(
            operation="runtime_create", target_type="runtime", target=slug,
            requested={"name": str(name), "description": str(description), "organization_ids": orgs, "workspace_ids": workspaces},
            ok=True, exit_code=result.exit_code, duration_ms=result.duration_ms, error_category="",
        )
        return normalized

    def runtime_get(self, runtime_or_alias: str) -> dict[str, Any]:
        alias = self.validate_slug(runtime_or_alias)
        result = self._runtime_call(["status", alias], timeout=30)
        if not result.ok:
            detail = (result.stderr or result.stdout).lower()
            if "not found" in detail or "unknown alias" in detail:
                raise ControlPlaneError("runtime_not_found", "runtime alias not found")
            self._require_ok(result)
        return self._normalize_runtime(self._json_or_empty(result.stdout), alias)

    def runtime_update(
        self,
        runtime_or_alias: str,
        *,
        tunnel_id: str,
        mcp_server_url: str,
        profile_name: str = "",
    ) -> dict[str, Any]:
        alias = self.validate_slug(runtime_or_alias)
        self.validate_tunnel_id(tunnel_id)
        url = self.validate_local_mcp_url(mcp_server_url)
        profile = self.validate_slug(profile_name or alias)
        command = [
            "connect", "--alias", alias, "--tunnel-id", tunnel_id,
            "--mcp-server-url", url, "--profile", profile,
            "--profile-dir", str(self.profile_dir),
            "--runtime-api-key", "env:CONTROL_PLANE_API_KEY",
        ]
        result = self._runtime_call(command, timeout=120)
        self._require_ok(result)
        normalized = self._normalize_runtime(self._json_or_empty(result.stdout), alias)
        if not normalized["tunnel_id"]:
            normalized["tunnel_id"] = tunnel_id
        self._write_audit(
            operation="runtime_update", target_type="runtime", target=alias,
            requested={"tunnel_id": tunnel_id, "mcp_server_url": url, "profile": profile},
            ok=True, exit_code=result.exit_code, duration_ms=result.duration_ms, error_category="",
        )
        return normalized

    def runtime_delete(self, runtime_or_alias: str, confirm_runtime: str) -> dict[str, Any]:
        alias = self.validate_slug(runtime_or_alias)
        if str(confirm_runtime or "") != alias:
            raise ControlPlaneError("confirmation_mismatch", "confirm_runtime must equal runtime alias")
        stop_result = self._runtime_call(["stop", alias], timeout=60)
        if not stop_result.ok and "not found" not in (stop_result.stderr or stop_result.stdout).lower():
            self._require_ok(stop_result)
        rm_result = self._runtime_call(["rm", alias], timeout=60)
        self._require_ok(rm_result)
        self._write_audit(
            operation="runtime_delete", target_type="runtime", target=alias,
            requested={}, ok=True, exit_code=rm_result.exit_code,
            duration_ms=stop_result.duration_ms + rm_result.duration_ms, error_category="",
        )
        return {"ok": True, "alias": alias, "remote_tunnel_deleted": False}

    def profile_list(self) -> dict[str, Any]:
        result = self._run_tunnel_client(["profiles", "list", "--profile-dir", str(self.profile_dir), "--json"], timeout=30)
        self._require_ok(result, category="tunnel_client_error")
        payload = self._json_or_empty(result.stdout)
        names: list[str] = []
        if isinstance(payload, list):
            for row in payload:
                if isinstance(row, str):
                    names.append(row)
                elif isinstance(row, dict) and row.get("name"):
                    names.append(str(row["name"]))
        elif isinstance(payload, dict):
            rows = payload.get("profiles")
            if isinstance(rows, list):
                for row in rows:
                    if isinstance(row, str):
                        names.append(row)
                    elif isinstance(row, dict) and row.get("name"):
                        names.append(str(row["name"]))
        return {"ok": True, "profiles": sorted(set(names))}

    def profile_get(self, name: str) -> dict[str, Any]:
        slug = self.validate_slug(name)
        path = self.profile_dir / f"{slug}.yaml"
        if not path.is_file():
            raise ControlPlaneError("profile_not_found", "profile not found")
        text = redact_text(path.read_text(encoding="utf-8", errors="replace"))
        return {"ok": True, "name": slug, "path": str(path), "content_redacted": text[:120000]}

    def profile_create(
        self,
        name: str,
        tunnel_id: str,
        mcp_server_url: str,
        health_listen_addr: str = "127.0.0.1:0",
        health_url_file: str = "",
    ) -> dict[str, Any]:
        slug = self.validate_slug(name)
        self.validate_tunnel_id(tunnel_id)
        url = self.validate_local_mcp_url(mcp_server_url)
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        health_file = health_url_file or str(self.health_url_dir / f"{slug}-tunnel-health.url")
        args = [
            "init", "--profile", slug, "--profile-dir", str(self.profile_dir),
            "--tunnel-id", tunnel_id, "--mcp-server-url", url,
            "--control-plane-api-key-ref", "env:CONTROL_PLANE_API_KEY",
            "--health-listen-addr", str(health_listen_addr), "--force",
        ]
        result = self._run_tunnel_client(args, timeout=60)
        self._require_ok(result)
        self._write_audit(
            operation="profile_create", target_type="profile", target=slug,
            requested={"tunnel_id": tunnel_id, "mcp_server_url": url, "health_url_file": health_file},
            ok=True, exit_code=result.exit_code, duration_ms=result.duration_ms, error_category="",
        )
        return {"ok": True, "name": slug, "profile_path": str(self.profile_dir / f"{slug}.yaml"), "health_url_file": health_file}

    def profile_validate(self, name: str) -> dict[str, Any]:
        slug = self.validate_slug(name)
        result = self._run_tunnel_client(["doctor", "--profile", slug, "--profile-dir", str(self.profile_dir), "--json"], timeout=60)
        if not result.ok:
            detail = redact_text(result.stderr or result.stdout)[:4000]
            raise ControlPlaneError("doctor_failed", detail)
        payload = self._json_or_empty(result.stdout)
        return {"ok": True, "name": slug, "diagnostic": _sanitize(payload if payload else {"text": result.stdout[:4000]})}

    def profile_delete(self, name: str, confirm_name: str) -> dict[str, Any]:
        slug = self.validate_slug(name)
        if str(confirm_name or "") != slug:
            raise ControlPlaneError("confirmation_mismatch", "confirm_name must equal profile name")
        if slug in self.protected_profile_names:
            raise ControlPlaneError("protected_target", "protected profile cannot be deleted")
        path = self.profile_dir / f"{slug}.yaml"
        if path.exists():
            path.unlink()
        self._write_audit(
            operation="profile_delete", target_type="profile", target=slug,
            requested={}, ok=True, exit_code=0, duration_ms=0, error_category="",
        )
        return {"ok": True, "name": slug}

    @staticmethod
    def _service_name_for_profile(profile_name: str) -> str:
        slug = OpenAIControlPlane.validate_slug(profile_name)
        return f"eiros-tunnel-{slug}.service"

    def _run_system(self, argv: list[str], timeout: int = 30) -> CommandResult:
        raw = self.system_runner([str(a) for a in argv], timeout)
        return CommandResult(
            ok=bool(raw.get("ok")), exit_code=raw.get("exit_code"),
            stdout=redact_text(str(raw.get("stdout") or ""))[-120000:],
            stderr=redact_text(str(raw.get("stderr") or ""))[-120000:],
            duration_ms=int(raw.get("duration_ms") or 0),
        )

    def _unit_text(self, profile_name: str) -> str:
        slug = self.validate_slug(profile_name)
        health_file = self.health_url_dir / f"{slug}-tunnel-health.url"
        return (
            "[Unit]\n"
            f"Description=EIROS OpenAI MCP Tunnel ({slug})\n"
            "After=network-online.target\nWants=network-online.target\n\n"
            "[Service]\nType=simple\nUser=eiros\nGroup=eiros\n"
            "EnvironmentFile=/etc/eiros/tunnel.env\n"
            f"ExecStart={TUNNEL_CLIENT} run --profile {slug} --health.listen-addr 127.0.0.1:0 --health.url-file {health_file}\n"
            "Restart=always\nRestartSec=3\nTimeoutStopSec=20\nNoNewPrivileges=true\nPrivateTmp=true\n\n"
            "[Install]\nWantedBy=multi-user.target\n"
        )

    def daemon_install(self, profile_name: str, service_name: str = "") -> dict[str, Any]:
        slug = self.validate_slug(profile_name)
        expected = self._service_name_for_profile(slug)
        if service_name and str(service_name) != expected:
            raise ControlPlaneError("invalid_identifier", "service name must match managed profile")
        self.systemd_dir.mkdir(parents=True, exist_ok=True)
        path = self.systemd_dir / expected
        path.write_text(self._unit_text(slug), encoding="utf-8")
        reload_result = self._run_system(["systemctl", "daemon-reload"], timeout=30)
        if not reload_result.ok:
            raise ControlPlaneError("daemon_failed", reload_result.stderr or "daemon-reload failed")
        enable_result = self._run_system(["systemctl", "enable", "--now", expected], timeout=60)
        if not enable_result.ok:
            raise ControlPlaneError("daemon_failed", enable_result.stderr or "enable/start failed")
        self._write_audit(
            operation="daemon_install", target_type="service", target=expected,
            requested={"profile": slug}, ok=True, exit_code=enable_result.exit_code,
            duration_ms=reload_result.duration_ms + enable_result.duration_ms, error_category="",
        )
        return {"ok": True, "profile": slug, "service": expected, "unit_path": str(path)}

    def daemon_status(self, profile_name_or_service: str) -> dict[str, Any]:
        raw = str(profile_name_or_service or "").strip()
        service = raw if raw.endswith(".service") else self._service_name_for_profile(raw)
        if not re.fullmatch(r"eiros-tunnel-[a-z0-9][a-z0-9-]{0,62}\.service", service):
            raise ControlPlaneError("invalid_identifier", "invalid managed service")
        result = self._run_system([
            "systemctl", "show", service,
            "--property=ActiveState,SubState,MainPID,Result,ExecMainStatus,FragmentPath", "--no-pager",
        ], timeout=20)
        if not result.ok:
            raise ControlPlaneError("daemon_failed", result.stderr or result.stdout)
        fields: dict[str, str] = {}
        for line in result.stdout.splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                fields[key] = value
        return {
            "ok": True, "service": service,
            "active_state": fields.get("ActiveState", ""),
            "sub_state": fields.get("SubState", ""),
            "main_pid": fields.get("MainPID", ""),
            "result": fields.get("Result", ""),
            "fragment_path": fields.get("FragmentPath", ""),
        }

    def daemon_start(self, profile_name: str) -> dict[str, Any]:
        service = self._service_name_for_profile(profile_name)
        result = self._run_system(["systemctl", "start", service], timeout=60)
        if not result.ok:
            raise ControlPlaneError("daemon_failed", result.stderr or result.stdout)
        return {"ok": True, "service": service, "action": "start"}

    def daemon_restart(self, profile_name: str) -> dict[str, Any]:
        service = self._service_name_for_profile(profile_name)
        result = self._run_system(["systemctl", "restart", service], timeout=60)
        if not result.ok:
            raise ControlPlaneError("daemon_failed", result.stderr or result.stdout)
        return {"ok": True, "service": service, "action": "restart"}

    def daemon_stop(self, profile_name: str) -> dict[str, Any]:
        service = self._service_name_for_profile(profile_name)
        result = self._run_system(["systemctl", "stop", service], timeout=60)
        if not result.ok:
            raise ControlPlaneError("daemon_failed", result.stderr or result.stdout)
        return {"ok": True, "service": service, "action": "stop"}

    def daemon_remove(self, profile_name: str, confirm_name: str) -> dict[str, Any]:
        slug = self.validate_slug(profile_name)
        if str(confirm_name or "") != slug:
            raise ControlPlaneError("confirmation_mismatch", "confirm_name must equal profile name")
        service = self._service_name_for_profile(slug)
        if slug in self.protected_profile_names or service in self.protected_service_names:
            raise ControlPlaneError("protected_target", "protected tunnel daemon cannot be removed")
        disable = self._run_system(["systemctl", "disable", "--now", service], timeout=60)
        path = self.systemd_dir / service
        if path.exists():
            path.unlink()
        reload_result = self._run_system(["systemctl", "daemon-reload"], timeout=30)
        if not reload_result.ok:
            raise ControlPlaneError("daemon_failed", reload_result.stderr or reload_result.stdout)
        self._write_audit(
            operation="daemon_remove", target_type="service", target=service,
            requested={"profile": slug}, ok=True, exit_code=reload_result.exit_code,
            duration_ms=disable.duration_ms + reload_result.duration_ms, error_category="",
        )
        return {"ok": True, "service": service, "profile": slug}

    def daemon_health(self, profile_name: str) -> dict[str, Any]:
        slug = self.validate_slug(profile_name)
        url_file = self.health_url_dir / f"{slug}-tunnel-health.url"
        if not url_file.is_file():
            return {"ok": False, "ready": False, "profile": slug, "error": "health_url_missing"}
        result = self._run_tunnel_client(["health", "--url-file", str(url_file), "--json"], timeout=30)
        if not result.ok:
            return {
                "ok": False,
                "ready": False,
                "profile": slug,
                "error": "daemon_failed",
                "diagnostic": redact_text(result.stderr or result.stdout)[:2000],
            }
        payload = self._json_or_empty(result.stdout)
        ready = True
        if isinstance(payload, dict):
            if "ready" in payload:
                ready = bool(payload.get("ready"))
            elif "ok" in payload:
                ready = bool(payload.get("ok"))
        return {"ok": True, "ready": ready, "profile": slug, "health": _sanitize(payload)}

    def connector_provision(
        self,
        alias: str,
        name: str,
        description: str,
        mcp_server_url: str,
        inherit_scope_from_tunnel: str = "",
        organization_ids: list[str] | tuple[str, ...] | None = None,
        workspace_ids: list[str] | tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        slug = self.validate_slug(alias)
        url = self.validate_local_mcp_url(mcp_server_url)
        orgs, workspaces = self._resolve_scope(organization_ids, workspace_ids, inherit_scope_from_tunnel)

        runtime = self.runtime_create(
            alias=slug,
            name=str(name),
            description=str(description),
            organization_ids=orgs,
            workspace_ids=workspaces,
        )
        tunnel_id = str(runtime.get("tunnel_id") or "")
        if not tunnel_id:
            status = self.runtime_get(slug)
            tunnel_id = str(status.get("tunnel_id") or "")
        if not tunnel_id:
            raise ControlPlaneError("parse_error", "runtime creation did not return a tunnel id")
        self.validate_tunnel_id(tunnel_id)

        raw_meta = runtime.get("raw_meta") if isinstance(runtime.get("raw_meta"), dict) else {}
        if raw_meta.get("created") is True:
            tunnel_state = "created"
        elif raw_meta.get("reused") is True:
            tunnel_state = "reused"
        else:
            tunnel_state = "reused"

        profile_path = self.profile_dir / f"{slug}.yaml"
        profile_existed = profile_path.exists()
        self.profile_create(slug, tunnel_id, url)
        profile_state = "updated" if profile_existed else "created"

        doctor_ok = False
        doctor_error = ""
        try:
            doctor = self.profile_validate(slug)
            doctor_ok = bool(doctor.get("ok"))
        except ControlPlaneError as exc:
            if exc.category != "doctor_failed":
                raise
            doctor_error = exc.category

        service_path = self.systemd_dir / self._service_name_for_profile(slug)
        daemon_existed = service_path.exists()
        daemon = self.daemon_install(slug)
        if daemon_existed:
            self.daemon_restart(slug)
        daemon_state = "restarted" if daemon_existed else "installed"

        status: dict[str, Any]
        try:
            status = self.daemon_status(slug)
        except ControlPlaneError as exc:
            status = {"ok": False, "active_state": "", "error": exc.category}

        health = self.daemon_health(slug)
        ready = bool(health.get("ready")) or (
            status.get("active_state") == "active" and status.get("sub_state") in {"running", "exited"}
        )
        needs_user_action = "" if ready else (doctor_error or "daemon_failed")

        result = {
            "ok": True,
            "alias": slug,
            "tunnel": {"state": tunnel_state, "tunnel_id": tunnel_id},
            "runtime": {"state": tunnel_state, "alias": slug, "tunnel_id": tunnel_id},
            "profile": {"state": profile_state, "name": slug, "doctor_ok": doctor_ok},
            "daemon": {"state": daemon_state, "service": daemon.get("service", self._service_name_for_profile(slug))},
            "ready": ready,
            "needs_user_action": needs_user_action,
            "health": _sanitize(health),
        }
        self._write_audit(
            operation="connector_provision",
            target_type="connector",
            target=slug,
            requested={
                "name": str(name),
                "description": str(description),
                "mcp_server_url": url,
                "organization_ids": orgs,
                "workspace_ids": workspaces,
                "inherit_scope_from_tunnel": str(inherit_scope_from_tunnel or ""),
            },
            ok=True,
            exit_code=0,
            duration_ms=0,
            error_category="" if ready else needs_user_action,
        )
        return result

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
