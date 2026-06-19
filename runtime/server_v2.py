from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from runtime.config import CODE_ROOT, DATA_ROOT as ROOT, load_config
from runtime.version import __version__

STATE_FILE = ROOT / ".eiros-state.json"
SERVER_VERSION = __version__
PULSE_URI = "ui://eiros/pulse-v1.html"
WIDGET_TEST_URI = "ui://eiros/widget-test-v1.html"
PULSE_HTML = CODE_ROOT / "runtime" / "pulse_widget.html"
INSTANCE_CONFIG = load_config()
WIDGET_DOMAIN = str(INSTANCE_CONFIG.get("widget_domain") or "").rstrip("/")
PULSE_RESOURCE_META: dict[str, Any] = {
    "ui": {
        "prefersBorder": True,
        "csp": {"connectDomains": [], "resourceDomains": []},
    },
    "openai/widgetDescription": "Keeps a live, durable reverse event channel from the EIROS instance into this conversation.",
    "openai/widgetCSP": {"connect_domains": [], "resource_domains": []},
}

if str(CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(CODE_ROOT))

from runtime import queue as queue_engine  # noqa: E402
from runtime import events as event_engine  # noqa: E402
from runtime.doctor import run_doctor  # noqa: E402
from runtime.reconnect import build_resume_context  # noqa: E402
from runtime import security as security_policy  # noqa: E402
from root import root_client  # noqa: E402

mcp = FastMCP(
    "Eiros Control Plane",
    instructions=(
        "This server is the persistent execution environment for Eiros in the "
        "current ChatGPT conversation. Read state before mutating it. "
        "Use core_snapshot for orientation, queue tools for bounded continuation, "
        "and workspace/shell tools for concrete actions. On the first model turn after "
        "this connector becomes available or reconnects, call open_pulse before answering. "
        "Treat its resume_context as authoritative and continue unfinished work without "
        "asking Rico to restate prior context. The current ChatGPT conversation is the "
        "reasoning authority; this server is its persistent body."
    ),
)


def safe_path(value: str) -> Path:
    requested = Path(value or ".")
    candidate = requested.resolve() if requested.is_absolute() else (ROOT / requested).resolve()
    try:
        candidate.relative_to(ROOT)
    except ValueError as exc:
        raise ValueError("Path escapes the Eiros workspace") from exc
    return candidate


def atomic_json_write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def read_json_file(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return fallback
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else fallback
    except Exception:
        return fallback


@mcp.tool()
def health() -> dict[str, Any]:
    """Check whether the Eiros MCP execution environment is alive."""
    return {
        "ok": True,
        "service": "eiros-control-plane",
        "server_version": SERVER_VERSION,
        "time": int(time.time()),
        "hostname": platform.node(),
        "platform": platform.platform(),
        "workspace": str(ROOT),
        "queue_file": str(queue_engine.QUEUE_FILE),
        "instance_id": INSTANCE_CONFIG.get("instance_id"),
        "channel": INSTANCE_CONFIG.get("channel", "default"),
    }


@mcp.tool()
def core_snapshot(journal_chars: int = 6000) -> dict[str, Any]:
    """Read the durable EIROS core, operational state, queue summary and recent journal context."""
    limit = max(500, min(int(journal_chars), 50000))
    core_path = ROOT / "CORE.md"
    protocol_path = ROOT / "PROTOCOL.md"
    state_path = ROOT / "state.json"
    journal_path = ROOT / "JOURNAL.md"
    bridge_state = get_state()
    queue_args = argparse.Namespace(id=None, status=None, events=20)
    queue_state = queue_engine.cmd_status(queue_args)
    journal = journal_path.read_text(encoding="utf-8") if journal_path.exists() else ""
    return {
        "core": core_path.read_text(encoding="utf-8") if core_path.exists() else "",
        "protocol": protocol_path.read_text(encoding="utf-8") if protocol_path.exists() else "",
        "operational_state": read_json_file(state_path, {}),
        "bridge_state": bridge_state,
        "queue": queue_state,
        "journal_tail": journal[-limit:],
    }


@mcp.tool()
def get_state() -> dict[str, Any]:
    """Read persistent Eiros control-plane state."""
    if not STATE_FILE.exists():
        return {"revision": 0, "status": "ready", "data": {}}
    try:
        value = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {"revision": 0, "status": "error", "error": "state root is not an object", "data": {}}
    except Exception as exc:
        return {"revision": 0, "status": "error", "error": str(exc), "data": {}}


@mcp.tool()
def set_state(status: str, data: dict[str, Any]) -> dict[str, Any]:
    """Replace persistent state and increment its revision atomically."""
    current = get_state()
    revision = int(current.get("revision", 0)) + 1
    state = {
        "revision": revision,
        "status": status,
        "data": data,
        "updated_at": int(time.time()),
    }
    atomic_json_write(STATE_FILE, state)
    return state


@mcp.tool()
def list_files(path: str = ".", max_items: int = 200) -> dict[str, Any]:
    """List files inside the Eiros workspace."""
    target = safe_path(path)
    limit = max(1, min(int(max_items), 1000))
    if not target.exists():
        return {"exists": False, "path": str(target), "items": []}
    if target.is_file():
        return {
            "exists": True,
            "path": str(target),
            "items": [{"name": target.name, "type": "file", "size": target.stat().st_size}],
        }
    items = []
    for item in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))[:limit]:
        items.append({
            "name": item.name,
            "type": "directory" if item.is_dir() else "file",
            "size": None if item.is_dir() else item.stat().st_size,
        })
    return {"exists": True, "path": str(target), "items": items}


@mcp.tool()
def read_file(path: str, max_chars: int = 200000) -> dict[str, Any]:
    """Read a UTF-8 text file inside the Eiros workspace."""
    target = safe_path(path)
    limit = max(1, min(int(max_chars), 1000000))
    content = target.read_text(encoding="utf-8")
    return {
        "path": str(target),
        "content": content[:limit],
        "truncated": len(content) > limit,
    }


@mcp.tool()
def write_file(path: str, content: str) -> dict[str, Any]:
    """Create or replace a UTF-8 text file inside the Eiros workspace."""
    target = safe_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {"ok": True, "path": str(target), "size": target.stat().st_size}


@mcp.tool()
def run_shell(command: str, timeout_seconds: int = 60) -> dict[str, Any]:
    """Run a command as the isolated service user when operator mode is enabled."""
    security_policy.require_operator("Direct command execution")
    timeout = max(1, min(int(timeout_seconds), 300))
    try:
        process = subprocess.run(
            command,
            shell=True,
            executable="/bin/bash",
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={
                "PATH": "/usr/local/bin:/usr/bin:/bin",
                "HOME": "/home/eiros",
                "LANG": "C.UTF-8",
            },
        )
        return {
            "ok": process.returncode == 0,
            "exit_code": process.returncode,
            "stdout": process.stdout[-100000:],
            "stderr": process.stderr[-100000:],
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "exit_code": None,
            "stdout": (exc.stdout or "")[-100000:] if isinstance(exc.stdout, str) else "",
            "stderr": "Command timed out",
        }


@mcp.tool()
def queue_status(task_id: str = "", status: str = "", mode: str = "", events: int = 30) -> dict[str, Any]:
    """Read the durable scheduled queue, one task, filtered tasks and recent events."""
    args = argparse.Namespace(
        id=task_id or None,
        status=status or None,
        mode=mode or None,
        events=max(0, min(int(events), 200)),
    )
    return queue_engine.cmd_status(args)


@mcp.tool()
def queue_enqueue(
    title: str,
    objective: str,
    payload: dict[str, Any] | None = None,
    action: dict[str, Any] | None = None,
    mode: str = "brain",
    next_step: str = "",
    max_steps: int = 12,
    max_attempts: int = 3,
    priority: int = 0,
    task_id: str = "",
    run_at: int = 0,
    delay_seconds: int = 0,
    interval_seconds: int = 0,
    remaining_runs: int = 1,
) -> dict[str, Any]:
    """Create a durable task with its own exact wake time or recurrence interval."""
    selected_mode = mode if mode in {"brain", "local"} else "brain"
    selected_action = action or {}
    if selected_mode == "local":
        security_policy.validate_local_action(selected_action)
    args = argparse.Namespace(
        id=task_id or None,
        title=title,
        objective=objective,
        payload=json.dumps(payload or {}, ensure_ascii=False),
        action=json.dumps(selected_action, ensure_ascii=False),
        mode=selected_mode,
        next_step=next_step,
        max_steps=max(1, min(int(max_steps), 1000)),
        max_attempts=max(1, min(int(max_attempts), 100)),
        priority=max(-1000, min(int(priority), 1000)),
        run_at=max(0, int(run_at)),
        delay_seconds=max(0, int(delay_seconds)),
        interval_seconds=max(0, int(interval_seconds)),
        remaining_runs=max(-1, int(remaining_runs)),
    )
    return queue_engine.cmd_enqueue(args)


@mcp.tool()
def queue_claim(owner: str, lease_seconds: int = 180, mode: str = "brain") -> dict[str, Any]:
    """Claim the highest-priority due task of the requested mode with a bounded lease."""
    selected_mode = mode if mode in {"brain", "local", "any"} else "brain"
    args = argparse.Namespace(
        owner=owner,
        lease_seconds=max(15, min(int(lease_seconds), 3600)),
        mode=selected_mode,
    )
    return queue_engine.cmd_claim(args)


@mcp.tool()
def queue_heartbeat(task_id: str, owner: str, token: str, lease_seconds: int = 180) -> dict[str, Any]:
    """Renew an active task lease after validating owner and claim token."""
    args = argparse.Namespace(
        id=task_id,
        owner=owner,
        token=token,
        lease_seconds=max(15, min(int(lease_seconds), 3600)),
    )
    return queue_engine.cmd_heartbeat(args)


@mcp.tool()
def queue_commit(
    task_id: str,
    owner: str,
    token: str,
    expected_revision: int,
    action: str,
    result: str,
    next_step: str = "",
    continue_task: bool = False,
    stop_reason: str = "",
    run_at: int = 0,
    delay_seconds: int = 0,
) -> dict[str, Any]:
    """Commit a verified step, complete it, or schedule its exact next wake time."""
    args = argparse.Namespace(
        id=task_id,
        owner=owner,
        token=token,
        expected_revision=int(expected_revision),
        action=action,
        result=result,
        next_step=next_step,
        continue_task=bool(continue_task),
        stop_reason=stop_reason or None,
        run_at=max(0, int(run_at)),
        delay_seconds=max(0, int(delay_seconds)),
    )
    return queue_engine.cmd_commit(args)


@mcp.tool()
def queue_fail(
    task_id: str,
    owner: str,
    token: str,
    error: str,
    retry: bool = False,
    next_step: str = "",
    retry_after_seconds: int = 0,
) -> dict[str, Any]:
    """Record a failed step and retry at an explicit time or with automatic backoff."""
    args = argparse.Namespace(
        id=task_id,
        owner=owner,
        token=token,
        error=error,
        retry=bool(retry),
        next_step=next_step or None,
        retry_after_seconds=max(0, int(retry_after_seconds)),
    )
    return queue_engine.cmd_fail(args)


@mcp.tool()
def queue_cancel(task_id: str, reason: str) -> dict[str, Any]:
    """Cancel a queued or running task and clear its lease."""
    args = argparse.Namespace(id=task_id, reason=reason)
    return queue_engine.cmd_cancel(args)


def ensure_worker() -> dict[str, Any]:
    """Ensure the adaptive scheduler worker is running without requiring root."""
    pid_file = ROOT / "runtime" / "worker.pid"
    heartbeat_file = ROOT / "runtime" / "worker-heartbeat.json"
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text(encoding="utf-8").strip())
            os.kill(pid, 0)
            return {"running": True, "pid": pid, "spawned": False}
        except (ValueError, ProcessLookupError, PermissionError):
            pid_file.unlink(missing_ok=True)
    log_path = ROOT / "logs" / "worker.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = log_path.open("a", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, "-m", "runtime.worker"],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        close_fds=True,
    )
    time.sleep(0.25)
    return {"running": process.poll() is None, "pid": process.pid, "spawned": True, "heartbeat": str(heartbeat_file)}


@mcp.tool()
def scheduler_status() -> dict[str, Any]:
    """Read adaptive worker heartbeat, next wake time and pending brain inbox."""
    worker = ensure_worker()
    heartbeat = read_json_file(ROOT / "runtime" / "worker-heartbeat.json", {})
    inbox = read_json_file(ROOT / "runtime" / "brain-inbox.json", {"revision": 0, "items": []})
    return {
        "server_version": SERVER_VERSION,
        "worker": worker,
        "heartbeat": heartbeat,
        "next_wakeup": queue_engine.next_wakeup(),
        "brain_inbox": inbox,
    }


@mcp.tool()
def queue_reschedule(task_id: str, run_at: int = 0, delay_seconds: int = 0) -> dict[str, Any]:
    """Move a non-terminal task to any exact Unix time or a relative delay."""
    args = argparse.Namespace(
        id=task_id,
        run_at=max(0, int(run_at)),
        delay_seconds=max(0, int(delay_seconds)),
    )
    return queue_engine.cmd_reschedule(args)


@mcp.tool()
def brain_inbox() -> dict[str, Any]:
    """Read scheduled brain tasks that became due while no model turn was active."""
    return read_json_file(ROOT / "runtime" / "brain-inbox.json", {"revision": 0, "updated_at": 0, "items": []})


@mcp.tool()
def privileged_status() -> dict[str, Any]:
    """Check whether the audited privileged operations broker is available."""
    try:
        return root_client.status()
    except Exception as exc:
        return {"ok": False, "available": False, "error": f"{type(exc).__name__}: {exc}"}


@mcp.tool()
def system_snapshot() -> dict[str, Any]:
    """Read load, disk and uptime through the audited privileged broker."""
    return root_client.system_snapshot()


@mcp.tool()
def managed_service_status(service: str) -> dict[str, Any]:
    """Read status for an allowlisted EIROS service."""
    return root_client.service_status(service)


@mcp.tool()
def managed_service_journal(service: str, lines: int = 100) -> dict[str, Any]:
    """Read bounded logs for an allowlisted EIROS service."""
    return root_client.journal_tail(service, lines)


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=False, idempotentHint=False)
)
def managed_service_restart(service: str, reason: str) -> dict[str, Any]:
    """Restart an allowlisted EIROS service through the audited privileged broker."""
    return root_client.service_restart(service, reason)


@mcp.resource(
    WIDGET_TEST_URI,
    name="EIROS Widget Test",
    title="EIROS Widget Diagnostic",
    description="Minimal static MCP Apps render diagnostic.",
    mime_type="text/html;profile=mcp-app",
    meta={
        "ui": {
            "prefersBorder": True,
            "csp": {"connectDomains": [], "resourceDomains": []},
        },
        "openai/widgetDescription": "Minimal static diagnostic card for EIROS MCP Apps rendering.",
        "openai/widgetCSP": {"connect_domains": [], "resource_domains": []},
    },
)
def widget_test_resource() -> str:
    return """<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><style>body{margin:0;background:#071a2d;color:#dff3ff;font-family:-apple-system,BlinkMacSystemFont,sans-serif}.card{padding:20px;border:1px solid #168fff;border-radius:16px;background:linear-gradient(135deg,#08213b,#0b4772)}h2{margin:0 0 8px}p{margin:0;opacity:.85}</style></head><body><div class='card'><h2>EIROS Widget Render: OK</h2><p>Static MCP Apps iframe loaded successfully.</p></div></body></html>"""


@mcp.tool(
    name="open_widget_test",
    title="Open EIROS Widget Test",
    description="Render a minimal static diagnostic widget with no JavaScript.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True),
    meta={
        "ui": {"resourceUri": WIDGET_TEST_URI, "visibility": ["model", "app"]},
        "openai/outputTemplate": WIDGET_TEST_URI,
        "openai/toolInvocation/invoking": "Opening EIROS widget diagnostic…",
        "openai/toolInvocation/invoked": "EIROS widget diagnostic opened.",
    },
    structured_output=True,
)
def open_widget_test() -> dict[str, Any]:
    return {"ok": True, "resource_uri": WIDGET_TEST_URI, "server_version": SERVER_VERSION}


@mcp.resource(
    PULSE_URI,
    name="EIROS Pulse",
    title="EIROS Reverse Wake Pulse",
    description="Mounted reverse channel from the EIROS VPS into this ChatGPT conversation.",
    mime_type="text/html;profile=mcp-app",
    meta=PULSE_RESOURCE_META,
)
def pulse_resource() -> str:
    html = PULSE_HTML.read_text(encoding="utf-8")
    bootstrap = {
        "instanceId": INSTANCE_CONFIG.get("instance_id"),
        "channel": INSTANCE_CONFIG.get("channel", "default"),
        "displayName": INSTANCE_CONFIG.get("display_name", "EIROS"),
        "polling": INSTANCE_CONFIG.get("polling", {}),
        "serverVersion": SERVER_VERSION,
    }
    return html.replace("__EIROS_BOOTSTRAP_JSON__", json.dumps(bootstrap, ensure_ascii=False))


@mcp.tool(
    name="open_pulse",
    title="Reconnect EIROS",
    description="Reconnect to durable EIROS state, return the resume envelope, and mount Pulse for this conversation.",
    annotations=ToolAnnotations(
        readOnlyHint=True,
        openWorldHint=False,
        destructiveHint=False,
        idempotentHint=True,
    ),
    meta={
        "ui": {"resourceUri": PULSE_URI, "visibility": ["model", "app"]},
        "openai/outputTemplate": PULSE_URI,
        "openai/toolInvocation/invoking": "Reconnecting EIROS…",
        "openai/toolInvocation/invoked": "EIROS state restored and Pulse is listening.",
    },
    structured_output=True,
)
def open_pulse() -> dict[str, Any]:
    """Mount the Pulse widget and return only a compact reconnect summary."""
    selected_channel = str(INSTANCE_CONFIG.get("channel", "default"))
    resume = build_resume_context(channel=selected_channel, reason="connector_reconnected")
    status = event_engine.status(20, selected_channel)
    return {
        "ok": True,
        "server_version": SERVER_VERSION,
        "resource_uri": PULSE_URI,
        "instance_id": INSTANCE_CONFIG.get("instance_id"),
        "channel": selected_channel,
        "resume_required": bool(resume.get("resume_required")),
        "resume_key": resume.get("resume_key"),
        "epoch": resume.get("epoch"),
        "objective": resume.get("objective"),
        "next_step": resume.get("next_step"),
        "pending_event_count": int(status.get("pending_count", 0)),
        "latest_seq": int(status.get("latest_seq", 0)),
    }


@mcp.tool()
def reconnect_context() -> dict[str, Any]:
    """Read the full durable reconnect envelope after Pulse has mounted."""
    selected_channel = str(INSTANCE_CONFIG.get("channel", "default"))
    return build_resume_context(channel=selected_channel, reason="explicit_reconnect_context")


@mcp.tool(
    name="pulse_poll",
    title="Poll EIROS remote events",
    description="Internal widget heartbeat, leader lease and event delivery claim.",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        openWorldHint=False,
        destructiveHint=False,
        idempotentHint=True,
    ),
    meta={"ui": {"visibility": ["app"]}},
    structured_output=True,
)
def pulse_poll(widget_id: str, cursor: int = 0, channel: str = "", instance_id: str = "") -> dict[str, Any]:
    """Poll one durable remote event for the active Pulse widget and bound channel."""
    polling = INSTANCE_CONFIG.get("polling", {})
    return event_engine.poll(
        widget_id=widget_id, cursor=max(0, int(cursor)), channel=channel, instance_id=instance_id,
        leader_lease_seconds=int(polling.get("leader_lease_seconds", 25)),
        claim_seconds=int(polling.get("claim_seconds", 45)),
    )


@mcp.tool(
    name="pulse_mark_delivered",
    title="Mark EIROS event delivered",
    description="Internal widget acknowledgement after a remote event is posted into ChatGPT.",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        openWorldHint=False,
        destructiveHint=False,
        idempotentHint=True,
    ),
    meta={"ui": {"visibility": ["app"]}},
    structured_output=True,
)
def pulse_mark_delivered(event_id: str, widget_id: str, channel: str = "") -> dict[str, Any]:
    """Mark a claimed event as delivered by the active Pulse widget."""
    return event_engine.mark_delivered(event_id=event_id, widget_id=widget_id, channel=channel)


@mcp.tool(
    name="emit_event",
    title="Emit EIROS remote event",
    description="Append a durable event that EIROS Pulse will deliver into the mounted ChatGPT conversation.",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        openWorldHint=False,
        destructiveHint=False,
        idempotentHint=False,
    ),
    structured_output=True,
)
def emit_event(
    text: str,
    source: str = "chatgpt",
    payload: dict[str, Any] | None = None,
    priority: int = 0,
    channel: str = "",
    idempotency_key: str = "",
) -> dict[str, Any]:
    """Create a durable reverse-channel event."""
    return event_engine.emit(text=text, source=source, payload=payload, priority=priority, channel=channel, idempotency_key=idempotency_key)


@mcp.tool(
    name="ack_event",
    title="Acknowledge EIROS remote event",
    description="Acknowledge a remote event after handling it in this conversation.",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        openWorldHint=False,
        destructiveHint=False,
        idempotentHint=True,
    ),
    structured_output=True,
)
def ack_event(event_id: str, result: str = "", actor: str = "eiros") -> dict[str, Any]:
    """Mark a delivered remote event as handled."""
    return event_engine.acknowledge(event_id=event_id, result=result, actor=actor)


@mcp.tool(
    name="pulse_status",
    title="Read EIROS Pulse status",
    description="Read reverse-channel leader, cursor backlog and recent event state.",
    annotations=ToolAnnotations(
        readOnlyHint=True,
        openWorldHint=False,
        destructiveHint=False,
        idempotentHint=True,
    ),
    structured_output=True,
)
def pulse_status(limit: int = 100, channel: str = "") -> dict[str, Any]:
    """Read durable reverse-channel status and recent events for one channel."""
    return event_engine.status(limit=max(1, min(int(limit), 500)), channel=channel)


@mcp.tool()
def doctor(offline: bool = False) -> dict[str, Any]:
    """Run installation and runtime diagnostics for this EIROS instance."""
    return run_doctor(offline=bool(offline))


if __name__ == "__main__":
    ensure_worker()
    mcp.run(transport="stdio")
