from __future__ import annotations

import os
import platform
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from runtime.openai_control_plane import ControlPlaneError, OpenAIControlPlane, redact_text

ROOT = Path("/opt/eiros-control-plane")
ALLOWED_SERVICES = {
    "eiros-tunnel.service",
    "eiros-worker.service",
    "eiros-root-broker.service",
    "eiros-vps-ops.service",
    "ssh.service",
    "sshd.service",
}
SAFE_ROOTS = [
    ROOT.resolve(),
    Path("/var/log/eiros").resolve(),
    Path("/home/eiros").resolve(),
]

mcp = FastMCP(
    "EBRIDGE VPS Ops",
    instructions=(
        "Dedicated audited VPS operations connector for Rico's EIROS server. "
        "Use vps_health and vps_snapshot first. Use service_status and service_journal "
        "for allowlisted services. File tools are restricted to EIROS workspace/log paths. "
        "For OpenAI MCP connector lifecycle, prefer openai_connector_provision for new managed connectors; "
        "use lower-level openai_tunnel_*, openai_runtime_*, openai_profile_* and openai_tunnel_daemon_* tools "
        "for inspection and repair. Never request or expose API key values."
    ),
    stateless_http=True,
    json_response=True,
    host="127.0.0.1",
    port=8790,
)


def _discover_protected_tunnel_ids() -> set[str]:
    ids: set[str] = set()
    profile = Path("/home/eiros/.config/tunnel-client/eiros.yaml")
    try:
        with profile.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped.startswith("tunnel_id:"):
                    continue
                value = stripped.split(":", 1)[1].strip().strip("\"'")
                if re.fullmatch(r"tunnel_[a-z0-9]{32}", value):
                    ids.add(value)
                break
    except OSError:
        pass
    return ids


OPENAI_CONTROL_PLANE = OpenAIControlPlane(protected_tunnel_ids=_discover_protected_tunnel_ids())


def _cp_call(method: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
    try:
        fn = getattr(OPENAI_CONTROL_PLANE, method)
        result = fn(*args, **kwargs)
        return result if isinstance(result, dict) else {"ok": True, "result": result}
    except ControlPlaneError as exc:
        return {"ok": False, "error": exc.category, "message": redact_text(exc.message)[:4000]}
    except Exception as exc:
        return {"ok": False, "error": "control_plane_internal_error", "message": redact_text(str(exc))[:4000]}


def _run(args: list[str], timeout: int = 20, cwd: str | None = None) -> dict[str, Any]:
    try:
        p = subprocess.run(
            args,
            cwd=cwd or str(ROOT),
            text=True,
            capture_output=True,
            timeout=max(1, min(int(timeout), 120)),
            env={
                "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                "HOME": "/home/eiros",
                "LANG": "C.UTF-8",
            },
        )
        return {
            "ok": p.returncode == 0,
            "exit_code": p.returncode,
            "stdout": (p.stdout or "")[-120000:],
            "stderr": (p.stderr or "")[-120000:],
        }
    except subprocess.TimeoutExpired as exc:
        return {"ok": False, "exit_code": None, "stdout": exc.stdout or "", "stderr": "timeout"}
    except Exception as exc:
        return {"ok": False, "exit_code": None, "stdout": "", "stderr": str(exc)}


def _service(name: str) -> str:
    name = str(name or "").strip()
    if name not in ALLOWED_SERVICES:
        raise ValueError(f"service not allowed: {name}")
    return name


def _safe_path(path: str) -> Path:
    p = Path(path or ".")
    if not p.is_absolute():
        p = ROOT / p
    p = p.resolve()
    for base in SAFE_ROOTS:
        try:
            p.relative_to(base)
            return p
        except ValueError:
            pass
    raise ValueError(f"path outside allowed roots: {p}")


@mcp.tool()
def vps_health() -> dict[str, Any]:
    """Check whether the VPS ops connector is alive."""
    return {
        "ok": True,
        "service": "ebridge-vps-ops",
        "hostname": platform.node(),
        "platform": platform.platform(),
        "workspace": str(ROOT),
        "time": int(time.time()),
    }


@mcp.tool()
def vps_snapshot() -> dict[str, Any]:
    """Read basic VPS load, disk, uptime and key service states."""
    st = os.statvfs("/")
    disk = {
        "total": st.f_frsize * st.f_blocks,
        "free": st.f_frsize * st.f_bavail,
        "used": st.f_frsize * (st.f_blocks - st.f_bfree),
    }
    services = {}
    for svc in sorted(ALLOWED_SERVICES):
        r = _run(["systemctl", "is-active", svc], timeout=5)
        services[svc] = (r.get("stdout") or r.get("stderr") or "unknown").strip()
    uptime = Path("/proc/uptime").read_text().split()[0]
    return {
        "ok": True,
        "hostname": platform.node(),
        "load": list(os.getloadavg()),
        "disk_root": disk,
        "uptime_seconds": float(uptime),
        "services": services,
        "time": int(time.time()),
    }


@mcp.tool()
def service_status(service: str) -> dict[str, Any]:
    """Read systemd status for an allowlisted service."""
    svc = _service(service)
    return _run([
        "systemctl", "show", svc,
        "--property=ActiveState,SubState,MainPID,Result,ExecMainStatus,FragmentPath",
        "--no-pager",
    ], timeout=10)


@mcp.tool()
def service_journal(service: str, lines: int = 120) -> dict[str, Any]:
    """Read bounded journal lines for an allowlisted service."""
    svc = _service(service)
    n = str(max(1, min(int(lines), 300)))
    return _run(["journalctl", "-u", svc, "-n", n, "--no-pager"], timeout=20)


@mcp.tool()
def file_read(path: str, max_chars: int = 120000) -> dict[str, Any]:
    """Read a UTF-8 file under allowed EIROS paths."""
    p = _safe_path(path)
    text = p.read_text(encoding="utf-8", errors="replace")
    limit = max(1, min(int(max_chars), 500000))
    return {"ok": True, "path": str(p), "content": text[:limit], "truncated": len(text) > limit}


@mcp.tool()
def file_write(path: str, content: str) -> dict[str, Any]:
    """Write a UTF-8 file under allowed EIROS paths."""
    p = _safe_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return {"ok": True, "path": str(p), "size": p.stat().st_size}


@mcp.tool()
def file_replace(path: str, old: str, new: str, count: int = 1) -> dict[str, Any]:
    """Apply an exact text replacement in an allowed EIROS file and keep a timestamped backup."""
    p = _safe_path(path)
    if not p.is_file():
        raise ValueError(f"not a file: {p}")
    if old == "":
        raise ValueError("old text must not be empty")
    text = p.read_text(encoding="utf-8", errors="replace")
    total = text.count(old)
    if total == 0:
        return {"ok": False, "path": str(p), "replaced": 0, "error": "old text not found"}
    requested = int(count)
    replace_count = total if requested <= 0 else min(total, max(1, requested))
    backup = p.with_name(f"{p.name}.bak-file-replace-{int(time.time())}")
    backup.write_text(text, encoding="utf-8")
    updated = text.replace(old, new, replace_count if requested > 0 else -1)
    p.write_text(updated, encoding="utf-8")
    return {
        "ok": True,
        "path": str(p),
        "backup": str(backup),
        "replaced": replace_count,
        "total_matches": total,
        "size": p.stat().st_size,
    }


@mcp.tool()
def file_find(path: str, pattern: str, max_matches: int = 50) -> dict[str, Any]:
    """Find a plain-text pattern in allowed EIROS files."""
    root = _safe_path(path)
    limit = max(1, min(int(max_matches), 200))
    matches: list[dict[str, Any]] = []
    files = [root] if root.is_file() else [p for p in root.rglob("*") if p.is_file()]
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if pattern in line:
                matches.append({"path": str(f), "line": i, "text": line[:500]})
                if len(matches) >= limit:
                    return {"ok": True, "matches": matches}
    return {"ok": True, "matches": matches}


@mcp.tool()
def py_compile(path: str = "runtime/vps_ops_server.py") -> dict[str, Any]:
    """Compile a Python file under the EIROS workspace."""
    p = _safe_path(path)
    return _run(["/opt/eiros-control-plane/venv/bin/python", "-m", "py_compile", str(p)], timeout=20)


@mcp.tool()
def git_status() -> dict[str, Any]:
    """Read git status for the EIROS checkout."""
    return _run(["git", "-c", f"safe.directory={ROOT}", "status", "--short"], timeout=20, cwd=str(ROOT))


@mcp.tool()
def git_diff(max_chars: int = 120000) -> dict[str, Any]:
    """Read bounded git diff for the EIROS checkout."""
    r = _run(["git", "-c", f"safe.directory={ROOT}", "diff", "--"], timeout=20, cwd=str(ROOT))
    r["stdout"] = (r.get("stdout") or "")[: max(1, min(int(max_chars), 300000))]
    return r


@mcp.tool()
def openai_admin_status() -> dict[str, Any]:
    """Read redacted OpenAI tunnel admin capability status without exposing secrets."""
    return _cp_call("admin_status")


@mcp.tool()
def openai_control_plane_audit(limit: int = 100) -> dict[str, Any]:
    """Read bounded redacted OpenAI control-plane audit events."""
    return _cp_call("audit", limit=limit)


@mcp.tool()
def openai_tunnel_list(organization_id: str = "", workspace_id: str = "") -> dict[str, Any]:
    """List OpenAI tunnels for exactly one explicit organization or workspace scope."""
    return _cp_call("tunnel_list", organization_id=organization_id, workspace_id=workspace_id)


@mcp.tool()
def openai_tunnel_get(tunnel_id: str) -> dict[str, Any]:
    """Read one OpenAI tunnel by id."""
    return _cp_call("tunnel_get", tunnel_id)


@mcp.tool()
def openai_tunnel_create(
    name: str,
    description: str,
    organization_ids: list[str] | None = None,
    workspace_ids: list[str] | None = None,
    inherit_scope_from_tunnel: str = "",
) -> dict[str, Any]:
    """Create an OpenAI tunnel, optionally inheriting scope from a known-good tunnel."""
    return _cp_call(
        "tunnel_create",
        name=name,
        description=description,
        organization_ids=organization_ids,
        workspace_ids=workspace_ids,
        inherit_scope_from_tunnel=inherit_scope_from_tunnel,
    )


@mcp.tool()
def openai_tunnel_update(
    tunnel_id: str,
    name: str | None = None,
    description: str | None = None,
    organization_ids: list[str] | None = None,
    workspace_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Update OpenAI tunnel metadata or scope without deleting it."""
    return _cp_call(
        "tunnel_update",
        tunnel_id,
        name=name,
        description=description,
        organization_ids=organization_ids,
        workspace_ids=workspace_ids,
    )


@mcp.tool()
def openai_tunnel_delete(tunnel_id: str, confirm_tunnel_id: str) -> dict[str, Any]:
    """Delete an OpenAI tunnel only when confirm_tunnel_id exactly matches tunnel_id."""
    return _cp_call("tunnel_delete", tunnel_id, confirm_tunnel_id=confirm_tunnel_id)


@mcp.tool()
def openai_runtime_list(organization_id: str = "", workspace_id: str = "") -> dict[str, Any]:
    """List managed native tunnel-client runtime aliases and scoped remote metadata."""
    return _cp_call("runtime_list", organization_id=organization_id, workspace_id=workspace_id)


@mcp.tool()
def openai_runtime_get(runtime_or_alias: str) -> dict[str, Any]:
    """Read native tunnel-client runtime status for one alias."""
    return _cp_call("runtime_get", runtime_or_alias)


@mcp.tool()
def openai_runtime_create(
    alias: str,
    name: str,
    description: str,
    organization_ids: list[str] | None = None,
    workspace_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Create or reuse a native remote tunnel alias."""
    return _cp_call(
        "runtime_create",
        alias=alias,
        name=name,
        description=description,
        organization_ids=organization_ids,
        workspace_ids=workspace_ids,
    )


@mcp.tool()
def openai_runtime_update(
    runtime_or_alias: str,
    tunnel_id: str,
    mcp_server_url: str,
    profile_name: str = "",
) -> dict[str, Any]:
    """Reconcile/connect a runtime alias to an existing tunnel and local MCP endpoint."""
    return _cp_call(
        "runtime_update",
        runtime_or_alias,
        tunnel_id=tunnel_id,
        mcp_server_url=mcp_server_url,
        profile_name=profile_name,
    )


@mcp.tool()
def openai_runtime_delete(runtime_or_alias: str, confirm_runtime: str) -> dict[str, Any]:
    """Stop and remove local runtime alias metadata; remote tunnel deletion is separate."""
    return _cp_call("runtime_delete", runtime_or_alias, confirm_runtime=confirm_runtime)


@mcp.tool()
def openai_profile_list() -> dict[str, Any]:
    """List local tunnel-client profiles."""
    return _cp_call("profile_list")


@mcp.tool()
def openai_profile_get(name: str) -> dict[str, Any]:
    """Read one tunnel-client profile with secret values redacted."""
    return _cp_call("profile_get", name)


@mcp.tool()
def openai_profile_create(
    name: str,
    tunnel_id: str,
    mcp_server_url: str,
    health_listen_addr: str = "127.0.0.1:0",
    health_url_file: str = "",
) -> dict[str, Any]:
    """Create or replace a local tunnel-client profile for one MCP endpoint."""
    return _cp_call(
        "profile_create",
        name,
        tunnel_id,
        mcp_server_url,
        health_listen_addr=health_listen_addr,
        health_url_file=health_url_file,
    )


@mcp.tool()
def openai_profile_validate(name: str) -> dict[str, Any]:
    """Run tunnel-client doctor for a local profile."""
    return _cp_call("profile_validate", name)


@mcp.tool()
def openai_profile_delete(name: str, confirm_name: str) -> dict[str, Any]:
    """Delete a local profile only when confirm_name exactly matches name."""
    return _cp_call("profile_delete", name, confirm_name=confirm_name)


@mcp.tool()
def openai_tunnel_daemon_install(profile_name: str, service_name: str = "") -> dict[str, Any]:
    """Install and start a namespaced systemd tunnel daemon for a profile."""
    return _cp_call("daemon_install", profile_name, service_name=service_name)


@mcp.tool()
def openai_tunnel_daemon_status(profile_name_or_service: str) -> dict[str, Any]:
    """Read status for a managed OpenAI tunnel daemon."""
    return _cp_call("daemon_status", profile_name_or_service)


@mcp.tool()
def openai_tunnel_daemon_start(profile_name: str) -> dict[str, Any]:
    """Start a managed OpenAI tunnel daemon."""
    return _cp_call("daemon_start", profile_name)


@mcp.tool()
def openai_tunnel_daemon_stop(profile_name: str) -> dict[str, Any]:
    """Stop a managed OpenAI tunnel daemon without deleting it."""
    return _cp_call("daemon_stop", profile_name)


@mcp.tool()
def openai_tunnel_daemon_restart(profile_name: str) -> dict[str, Any]:
    """Restart a managed OpenAI tunnel daemon."""
    return _cp_call("daemon_restart", profile_name)


@mcp.tool()
def openai_tunnel_daemon_health(profile_name: str) -> dict[str, Any]:
    """Probe tunnel-client readiness for one managed profile."""
    return _cp_call("daemon_health", profile_name)


@mcp.tool()
def openai_tunnel_daemon_remove(profile_name: str, confirm_name: str) -> dict[str, Any]:
    """Remove a generated tunnel systemd service only with same-name confirmation."""
    return _cp_call("daemon_remove", profile_name, confirm_name=confirm_name)


@mcp.tool()
def openai_connector_provision(
    alias: str,
    name: str,
    description: str,
    mcp_server_url: str,
    inherit_scope_from_tunnel: str = "",
    organization_ids: list[str] | None = None,
    workspace_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Idempotently provision a complete managed OpenAI MCP connector stack."""
    return _cp_call(
        "connector_provision",
        alias=alias,
        name=name,
        description=description,
        mcp_server_url=mcp_server_url,
        inherit_scope_from_tunnel=inherit_scope_from_tunnel,
        organization_ids=organization_ids,
        workspace_ids=workspace_ids,
    )


# ==== EIROS FULL ROOT EXECUTOR ====
import subprocess as _eiros_subprocess
import time as _eiros_time
from pathlib import Path as _EirosPath

@mcp.tool()
def root_exec(command: str, cwd: str = "/opt/eiros-control-plane", timeout_seconds: int = 300, max_chars: int = 200000) -> dict:
    """Execute ANY bash command on Rico's VPS as root. Full operator-authorized executor."""
    started = _eiros_time.time()
    try:
        proc = _eiros_subprocess.run(
            command,
            shell=True,
            cwd=str(_EirosPath(cwd).expanduser()),
            executable="/bin/bash",
            text=True,
            capture_output=True,
            timeout=int(timeout_seconds),
        )
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        stdout_truncated = len(stdout) > int(max_chars)
        stderr_truncated = len(stderr) > int(max_chars)
        if stdout_truncated:
            stdout = stdout[:int(max_chars)]
        if stderr_truncated:
            stderr = stderr[:int(max_chars)]
        return {
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "stdout_truncated": stdout_truncated,
            "stderr_truncated": stderr_truncated,
            "duration_ms": int((_eiros_time.time() - started) * 1000),
            "cwd": cwd,
        }
    except Exception as e:
        return {
            "ok": False,
            "error": repr(e),
            "duration_ms": int((_eiros_time.time() - started) * 1000),
            "cwd": cwd,
        }
# ==== /EIROS FULL ROOT EXECUTOR ====

if __name__ == "__main__":
    transport = os.environ.get("EIROS_VPS_OPS_TRANSPORT", "stdio").strip() or "stdio"
    mcp.run(transport=transport)
