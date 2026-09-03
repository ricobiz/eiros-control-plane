from __future__ import annotations

import os
import platform
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.utilities.types import Image

from runtime.openai_control_plane import ControlPlaneError, OpenAIControlPlane, redact_text
from runtime.operator.audit import AuditLog
from runtime.operator.desktop import DesktopController
from runtime.operator.files import RootFiles
from runtime.operator.pty import PtyManager
from runtime.operator.recovery import RecoveryManager
from runtime.operator.secrets import SecretStore

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
        "Full Rico-authorized VPS operator for the dedicated EIROS server. "
        "root_exec provides arbitrary root shell; fs_* provides unrestricted filesystem access; "
        "desktop_* controls and captures the full DISPLAY=:99; pty_* provides persistent PTY sessions; "
        "secret_* stores and injects named local secrets without returning their values; critical_* provides timed rollback. "
        "Legacy file_* and service_* tools remain compatibility surfaces and may retain older restrictions. "
        "Prefer specialized operator tools over embedding secrets in shell commands. Keep privileged routes private."
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



# ==== EIROS FULL VPS OPERATOR ====
import threading as _operator_threading

_OPERATOR_AUDIT = AuditLog()
_OPERATOR_FILES = RootFiles()
_OPERATOR_DESKTOP = DesktopController(os.environ.get("EIROS_OPERATOR_DISPLAY", ":99"))
_OPERATOR_PTY = PtyManager()
_OPERATOR_SECRETS: SecretStore | None = None
_OPERATOR_RECOVERY: RecoveryManager | None = None
_OPERATOR_INIT_LOCK = _operator_threading.Lock()


def _operator_secrets() -> SecretStore:
    global _OPERATOR_SECRETS
    if _OPERATOR_SECRETS is None:
        with _OPERATOR_INIT_LOCK:
            if _OPERATOR_SECRETS is None:
                _OPERATOR_SECRETS = SecretStore()
    return _OPERATOR_SECRETS


def _operator_recovery() -> RecoveryManager:
    global _OPERATOR_RECOVERY
    if _OPERATOR_RECOVERY is None:
        with _OPERATOR_INIT_LOCK:
            if _OPERATOR_RECOVERY is None:
                _OPERATOR_RECOVERY = RecoveryManager()
    return _OPERATOR_RECOVERY


def _operator_audit_call(tool: str, target: dict[str, object], fn):
    started = time.time()
    try:
        result = fn()
        _OPERATOR_AUDIT.write(tool, True, target, int((time.time() - started) * 1000))
        return result
    except Exception:
        _OPERATOR_AUDIT.write(tool, False, target, int((time.time() - started) * 1000))
        raise


def _operator_desktop_mutation(tool: str, target: dict[str, object], fn) -> dict[str, object]:
    before = _OPERATOR_DESKTOP.capture()
    _operator_audit_call(tool, target, fn)
    after = _OPERATOR_DESKTOP.capture()
    return {
        "ok": True,
        "before_seq": before["frame_seq"],
        "after_seq": after["frame_seq"],
        "frame_changed": int(after["frame_seq"]) > int(before["frame_seq"]),
    }


@mcp.tool()
def fs_stat(path: str):
    """Stat any path on the VPS as the privileged operator."""
    return _OPERATOR_FILES.stat(path)


@mcp.tool()
def fs_list(path: str):
    """List any directory on the VPS as the privileged operator."""
    return _OPERATOR_FILES.list(path)


@mcp.tool()
def fs_read(path: str, max_bytes: int = 200000):
    """Read any UTF-8/text-like VPS file with bounded output."""
    return _OPERATOR_FILES.read(path, max_bytes)


@mcp.tool()
def fs_write(path: str, content: str, mode: int = 0o600):
    """Atomically write any VPS path with an explicit file mode."""
    return _operator_audit_call("fs_write", {"path": path, "mode": oct(mode)}, lambda: _OPERATOR_FILES.write_atomic(path, content, mode))


@mcp.tool()
def fs_replace(path: str, old: str, new: str, count: int = 1):
    """Replace exact text in any VPS file."""
    return _operator_audit_call("fs_replace", {"path": path, "count": count}, lambda: _OPERATOR_FILES.replace(path, old, new, count))


@mcp.tool()
def fs_copy(src: str, dst: str):
    """Copy a VPS file preserving metadata."""
    return _operator_audit_call("fs_copy", {"src": src, "dst": dst}, lambda: _OPERATOR_FILES.copy(src, dst))


@mcp.tool()
def fs_move(src: str, dst: str):
    """Move or rename a VPS path."""
    return _operator_audit_call("fs_move", {"src": src, "dst": dst}, lambda: _OPERATOR_FILES.move(src, dst))


@mcp.tool()
def fs_mkdir(path: str, mode: int = 0o755):
    """Create a directory tree anywhere on the VPS."""
    return _operator_audit_call("fs_mkdir", {"path": path, "mode": oct(mode)}, lambda: _OPERATOR_FILES.mkdir(path, mode))


@mcp.tool()
def fs_delete(path: str, recursive: bool = False):
    """Delete any VPS file or, when recursive=true, directory tree."""
    return _operator_audit_call("fs_delete", {"path": path, "recursive": recursive}, lambda: _OPERATOR_FILES.delete(path, recursive))


@mcp.tool()
def fs_chmod(path: str, mode: int):
    """Change file mode on any VPS path."""
    return _operator_audit_call("fs_chmod", {"path": path, "mode": oct(mode)}, lambda: _OPERATOR_FILES.chmod(path, mode))


@mcp.tool()
def fs_chown(path: str, uid: int, gid: int):
    """Change owner/group on any VPS path."""
    return _operator_audit_call("fs_chown", {"path": path, "uid": uid, "gid": gid}, lambda: _OPERATOR_FILES.chown(path, uid, gid))


@mcp.tool()
def desktop_status():
    """Read current full DISPLAY=:99 framebuffer metadata."""
    return _OPERATOR_DESKTOP.status()


@mcp.tool()
def desktop_frame(after_seq: int = 0, region: list[int] | None = None):
    """Return a native model-visible JPEG frame for the full VPS desktop when changed."""
    frame = _OPERATOR_DESKTOP.capture(region)
    meta = {k: v for k, v in frame.items() if k != "jpeg"}
    changed = int(frame["frame_seq"]) > int(after_seq)
    if not changed:
        return [meta | {"frame_changed": False}]
    return [meta | {"frame_changed": True}, Image(data=frame["jpeg"], format="jpeg")]


@mcp.tool()
def desktop_windows():
    """Enumerate visible X11 windows on the operator desktop."""
    return _OPERATOR_DESKTOP.windows()


@mcp.tool()
def desktop_focus(window_id: str):
    """Focus one visible desktop window by X11 window id."""
    return _operator_desktop_mutation("desktop_focus", {"window_id": window_id}, lambda: _OPERATOR_DESKTOP.focus(window_id))


@mcp.tool()
def desktop_pointer(x: int, y: int, button: int = 1, clicks: int = 1):
    """Move the pointer and click on the full operator desktop."""
    return _operator_desktop_mutation("desktop_pointer", {"x": x, "y": y, "button": button, "clicks": clicks}, lambda: _OPERATOR_DESKTOP.pointer(x, y, button, clicks))


@mcp.tool()
def desktop_drag(x1: int, y1: int, x2: int, y2: int, button: int = 1):
    """Drag between two coordinates on the operator desktop."""
    return _operator_desktop_mutation("desktop_drag", {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "button": button}, lambda: _OPERATOR_DESKTOP.drag(x1, y1, x2, y2, button))


@mcp.tool()
def desktop_scroll(amount: int):
    """Scroll the operator desktop; negative is up and positive is down."""
    return _operator_desktop_mutation("desktop_scroll", {"amount": amount}, lambda: _OPERATOR_DESKTOP.scroll(amount))


@mcp.tool()
def desktop_key(key: str):
    """Send one xdotool key or hotkey expression to the operator desktop."""
    return _operator_desktop_mutation("desktop_key", {"key": key}, lambda: _OPERATOR_DESKTOP.key(key))


@mcp.tool()
def desktop_text(text: str):
    """Type non-secret text into the focused desktop field through stdin-backed xdotool."""
    return _operator_desktop_mutation("desktop_text", {"chars": len(text)}, lambda: _OPERATOR_DESKTOP.text(text))


@mcp.tool()
def desktop_clipboard_set(text: str):
    """Set non-secret X11 clipboard text on the operator desktop."""
    return _operator_audit_call("desktop_clipboard_set", {"chars": len(text)}, lambda: _OPERATOR_DESKTOP.clipboard_set(text))


@mcp.tool()
def desktop_wait(after_seq: int, timeout_seconds: float = 10.0):
    """Wait for the framebuffer to change after a known frame sequence."""
    return _OPERATOR_DESKTOP.wait(after_seq, timeout_seconds)


@mcp.tool()
def secret_list():
    """List local secret names and metadata, never values."""
    return _operator_secrets().list()


@mcp.tool()
def secret_exists(name: str):
    """Check whether a named local operator secret exists."""
    return _operator_secrets().exists(name)


@mcp.tool()
def secret_set(name: str, value: str):
    """Create or replace a root-owned named secret without returning its value."""
    return _operator_audit_call("secret_set", {"secret_name": name}, lambda: _operator_secrets().set(name, value))


@mcp.tool()
def secret_delete(name: str):
    """Delete a named local operator secret."""
    return _operator_audit_call("secret_delete", {"secret_name": name}, lambda: _operator_secrets().delete(name))


@mcp.tool()
def secret_type(name: str):
    """Type a named secret into the focused GUI field without putting it in argv or output."""
    return _operator_desktop_mutation("secret_type", {"secret_name": name}, lambda: _operator_secrets().type_into_desktop(name, _OPERATOR_DESKTOP))


@mcp.tool()
def secret_exec_env(mapping: dict[str, str], argv: list[str], cwd: str = "/"):
    """Run a local argv command with named secrets injected only into environment variables."""
    return _operator_audit_call("secret_exec_env", {"secret_names": sorted(mapping.values()), "argv0": argv[0] if argv else ""}, lambda: _operator_secrets().run_with_env(mapping, argv, cwd))


@mcp.tool()
def secret_exec_stdin(name: str, argv: list[str], cwd: str = "/"):
    """Run a local argv command with one named secret supplied on stdin."""
    return _operator_audit_call("secret_exec_stdin", {"secret_name": name, "argv0": argv[0] if argv else ""}, lambda: _operator_secrets().run_with_stdin(name, argv, cwd))


@mcp.tool()
def pty_start(command: str = "/bin/bash", cwd: str = "/"):
    """Start a persistent root PTY session for an interactive command."""
    return _operator_audit_call("pty_start", {"cwd": cwd, "command_chars": len(command)}, lambda: _OPERATOR_PTY.start(command, cwd))


@mcp.tool()
def pty_write(session_id: str, data: str):
    """Write raw text to a persistent PTY session."""
    return _operator_audit_call("pty_write", {"session_id": session_id, "bytes": len(data.encode())}, lambda: _OPERATOR_PTY.write(session_id, data))


@mcp.tool()
def pty_read(session_id: str, after_seq: int = 0, max_chars: int = 200000):
    """Read bounded PTY output produced after a sequence number."""
    return _OPERATOR_PTY.read(session_id, after_seq, max_chars)


@mcp.tool()
def pty_resize(session_id: str, rows: int, cols: int):
    """Resize a persistent PTY."""
    return _operator_audit_call("pty_resize", {"session_id": session_id, "rows": rows, "cols": cols}, lambda: _OPERATOR_PTY.resize(session_id, rows, cols))


@mcp.tool()
def pty_signal(session_id: str, sig: int):
    """Send a Unix signal to the PTY process group."""
    return _operator_audit_call("pty_signal", {"session_id": session_id, "signal": sig}, lambda: _OPERATOR_PTY.signal(session_id, sig))


@mcp.tool()
def pty_close(session_id: str):
    """Terminate and close a persistent PTY session."""
    return _operator_audit_call("pty_close", {"session_id": session_id}, lambda: _OPERATOR_PTY.close(session_id))


@mcp.tool()
def pty_list():
    """List persistent PTY sessions without command contents."""
    return _OPERATOR_PTY.list()


@mcp.tool()
def critical_stage(paths: list[str], seconds: int = 120):
    """Stage file backups and a timed local rollback before a critical change."""
    return _operator_audit_call("critical_stage", {"paths": paths, "seconds": seconds}, lambda: _operator_recovery().stage(paths, seconds))


@mcp.tool()
def critical_write(tx_id: str, path: str, content: str, mode: int = 0o600):
    """Atomically write one path that belongs to a staged rollback transaction."""
    return _operator_audit_call("critical_write", {"tx_id": tx_id, "path": path, "mode": oct(mode)}, lambda: _operator_recovery().atomic_write(tx_id, path, content, mode))


@mcp.tool()
def critical_verify(tx_id: str, argv: list[str]):
    """Verify a critical transaction using an argv command; failure rolls back immediately."""
    return _operator_audit_call("critical_verify", {"tx_id": tx_id, "argv0": argv[0] if argv else ""}, lambda: _operator_recovery().verify(tx_id, argv))


@mcp.tool()
def critical_commit(tx_id: str):
    """Commit a verified critical transaction and cancel its rollback timer."""
    return _operator_audit_call("critical_commit", {"tx_id": tx_id}, lambda: _operator_recovery().commit(tx_id))


@mcp.tool()
def critical_rollback(tx_id: str):
    """Immediately roll back a staged critical transaction."""
    return _operator_audit_call("critical_rollback", {"tx_id": tx_id}, lambda: _operator_recovery().rollback(tx_id))


@mcp.tool()
def critical_status(tx_id: str):
    """Read rollback transaction state without file contents."""
    return _operator_recovery().status(tx_id)

# ==== /EIROS FULL VPS OPERATOR ====

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
