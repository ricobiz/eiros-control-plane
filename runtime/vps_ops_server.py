from __future__ import annotations

import os
import platform
import subprocess
import time
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

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
        "for allowlisted services. File tools are restricted to EIROS workspace/log paths."
    ),
)


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
    return _run(["git", "status", "--short"], timeout=20, cwd=str(ROOT))


@mcp.tool()
def git_diff(max_chars: int = 120000) -> dict[str, Any]:
    """Read bounded git diff for the EIROS checkout."""
    r = _run(["git", "diff", "--"], timeout=20, cwd=str(ROOT))
    r["stdout"] = (r.get("stdout") or "")[: max(1, min(int(max_chars), 300000))]
    return r


if __name__ == "__main__":
    mcp.run()
