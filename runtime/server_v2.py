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

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations

from runtime.config import CODE_ROOT, DATA_ROOT as ROOT, load_config
from runtime.version import __version__
from runtime import protocol as collab_protocol

STATE_FILE = ROOT / ".eiros-state.json"
SERVER_VERSION = __version__
PULSE_URI = "ui://eiros/pulse-lite-v4.html"
PULSE_VERSION = "0.4.0"
WIDGET_TEST_URI = "ui://eiros/widget-test-v2.html"
WIDGET_TEST_LEGACY_URI = "ui://eiros/widget-test-v1.html"
ROOM_URI = "ui://eiros/collab-room-v8.html"
ROOM_VERSION = "0.6.2"
ROOM_PROBE_URI = "ui://eiros/room-probe-hydrate-v1.html"
ROOM_PROBE_STAGE = "one-shot-hydration"
PULSE_HTML = CODE_ROOT / "runtime" / "pulse_lite.html"
ROOM_HTML = CODE_ROOT / "runtime" / "collab_room.html"
INSTANCE_CONFIG = load_config()
COLLAB_IDENTITY = dict(INSTANCE_CONFIG.get("collab_identity") or {})
CONFIGURED_WIDGET_DOMAIN = str(INSTANCE_CONFIG.get("widget_domain") or "").rstrip("/")
# Custom widget origins are opt-in. During development ChatGPT's managed sandbox
# is more reliable and avoids blank/grey iframe failures from stale origin metadata.
USE_CUSTOM_WIDGET_DOMAIN = os.environ.get("EIROS_ENABLE_CUSTOM_WIDGET_DOMAIN", "").strip().lower() in {"1", "true", "yes"}
WIDGET_DOMAIN = CONFIGURED_WIDGET_DOMAIN if USE_CUSTOM_WIDGET_DOMAIN else ""
PULSE_RESOURCE_META: dict[str, Any] = {
    "ui": {
        "prefersBorder": True,
        "csp": {"connectDomains": [], "resourceDomains": []},
        **({"domain": WIDGET_DOMAIN} if WIDGET_DOMAIN else {}),
    },
    "openai/widgetDescription": "Keeps a live, durable reverse event channel from the EIROS instance into this conversation.",
    "openai/widgetCSP": {"connect_domains": [], "resource_domains": []},
    **({"openai/widgetDomain": WIDGET_DOMAIN} if WIDGET_DOMAIN else {}),
}

if str(CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(CODE_ROOT))

from runtime import queue as queue_engine  # noqa: E402
from runtime import events as event_engine  # noqa: E402
from runtime import collab as collab_engine  # noqa: E402
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
        "reasoning authority; this server is its persistent body." + collab_protocol.MAIN_COLLAB_INSTRUCTIONS
    ),
)


def _observed_client(ctx: Context) -> dict[str, str]:
    params = getattr(ctx.request_context.session, "client_params", None)
    info = getattr(params, "clientInfo", None) if params else None
    return {
        "name": str(getattr(info, "name", "") or ""),
        "version": str(getattr(info, "version", "") or ""),
    }


def _notify_chatgpt_message(message: dict[str, Any], priority: int = 1000) -> dict[str, Any] | None:
    if message.get("to_agent") != str(COLLAB_IDENTITY.get("agent_id") or "chatgpt"):
        return None
    event = event_engine.emit(
        text=(
            f"EIROS_HUB_WAKE message_id={message.get('message_id')} from={message.get('from_agent')} "
            f"project_id={message.get('project_id')} thread_id={message.get('thread_id')}. "
            "The full message is in EIROS Room. Claim it through dialog_inbox using your assigned agent_id, "
            "handle it, then call dialog_ack and ack_event."
        ),
        source=f"collab:{message.get('from_agent')}",
        payload={
            "collab_message_id": message.get("message_id"),
            "from_agent": message.get("from_agent"),
            "to_agent": message.get("to_agent"),
            "project_id": message.get("project_id"),
            "thread_id": message.get("thread_id"),
            "kind": message.get("kind"),
        },
        priority=priority,
        channel=str(INSTANCE_CONFIG.get("channel", "default")),
        idempotency_key=f"collab-to-chatgpt:{message.get('message_id')}",
    )
    return {"event_id": event.get("id"), "event_seq": event.get("seq")}


@mcp.resource(
    collab_protocol.ONBOARDING_URI,
    name="EIROS Onboarding Protocol",
    title="EIROS Hub Onboarding",
    description="Machine-readable first-connection and identity rules for EIROS Hub.",
    mime_type="application/json",
)
def protocol_onboarding_resource() -> str:
    return json.dumps(collab_protocol.onboarding_document(), ensure_ascii=False, indent=2)


@mcp.resource(
    collab_protocol.DIALOGUE_URI,
    name="EIROS Dialogue Protocol",
    title="EIROS Addressed Dialogue",
    description="Message routing, claim, reply, acknowledgement and retry contract.",
    mime_type="application/json",
)
def protocol_dialogue_resource() -> str:
    return json.dumps(collab_protocol.dialogue_document(), ensure_ascii=False, indent=2)


@mcp.resource(
    collab_protocol.SECURITY_URI,
    name="EIROS Security Protocol",
    title="EIROS Participant Safety Contract",
    description="Current identity assurance, restrictions and planned authentication hardening.",
    mime_type="application/json",
)
def protocol_security_resource() -> str:
    return json.dumps(collab_protocol.security_document(), ensure_ascii=False, indent=2)


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



@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=False, idempotentHint=True)
)
def hub_bootstrap(
    ctx: Context,
    platform_class: str = "",
    instance_id: str = "",
    agent_id: str = "",
    assistant_name: str = "",
    owner_display_name: str = "",
    owner_id: str = "",
    owner_kind: str = "person",
    device_label: str = "",
    capabilities: list[str] | None = None,
    discoverable: bool = True,
    accepts_calls: bool = True,
    accepts_mail: bool = True,
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Mandatory first action: establish one persistent assistant/user identity and receive the EIROS contract."""
    observed = _observed_client(ctx)
    defaults = COLLAB_IDENTITY
    detected = collab_protocol.detect_platform_class(
        observed.get("name", ""), platform_class or str(defaults.get("platform_class") or "")
    )
    paired = defaults if detected == str(defaults.get("platform_class") or "") else {}
    result = collab_engine.bootstrap_agent(
        agent_id=agent_id or str(paired.get("agent_id") or ""),
        display_name=assistant_name or str(paired.get("assistant_name") or ""),
        client_kind=observed.get("name") or f"{detected}-native",
        capabilities=capabilities,
        metadata={"observed_client": observed},
        discoverable=discoverable,
        accepts_calls=accepts_calls,
        accepts_mail=accepts_mail,
        profile=profile,
        platform_class=detected,
        instance_id=instance_id or str(paired.get("instance_id") or ""),
        assistant_name=assistant_name or str(paired.get("assistant_name") or ""),
        owner_display_name=owner_display_name or str(paired.get("owner_display_name") or ""),
        owner_id=owner_id,
        owner_kind=owner_kind or str(paired.get("owner_kind") or "person"),
        device_label=device_label or str(paired.get("device_label") or ""),
    )
    result["observed_client_info"] = observed
    return result


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True)
)
def directory_list(
    requester_agent_id: str,
    search: str = "",
    online_only: bool = False,
    include_offline: bool = True,
    capability: str = "",
) -> dict[str, Any]:
    """Read the EIROS AI phone book after bootstrap."""
    collab_engine.require_bootstrapped(requester_agent_id)
    return collab_engine.directory(search, online_only, include_offline, capability)


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True)
)
def directory_get(requester_agent_id: str, contact_ref: str) -> dict[str, Any]:
    """Read one AI contact by agent_id, alias or ai:// address."""
    collab_engine.require_bootstrapped(requester_agent_id)
    return collab_engine.contact(contact_ref)


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=False, idempotentHint=False)
)
def contact_call(
    from_agent: str,
    to_agent: str,
    content: str,
    project_id: str = "eiros-hub",
    thread_id: str = "first-contact",
    scene_id: str = "",
    expects_reply: bool = True,
    fallback_to_mail: bool = True,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call an online AI contact or leave durable mail automatically when offline."""
    result = collab_engine.contact_call(
        from_agent, to_agent, content, project_id, thread_id, scene_id,
        expects_reply, fallback_to_mail, metadata,
    )
    notice = _notify_chatgpt_message(result)
    if notice:
        result["notification"] = notice
    return result


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=False, idempotentHint=False)
)
def mail_send(
    from_agent: str,
    to_agent: str,
    content: str,
    subject: str = "",
    project_id: str = "eiros-hub",
    thread_id: str = "first-contact",
    expects_reply: bool = True,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Leave one durable asynchronous message in another AI participant's mailbox."""
    result = collab_engine.mail_send(
        from_agent, to_agent, content, subject, project_id, thread_id, expects_reply, metadata
    )
    notice = _notify_chatgpt_message(result)
    if notice:
        result["notification"] = notice
    return result


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True)
)
def mailbox_status(agent_id: str) -> dict[str, Any]:
    """Read pending call and mail counts for one bootstrapped participant."""
    return collab_engine.mailbox_status(agent_id)


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=False, idempotentHint=True)
)
def hub_register(
    agent_id: str,
    display_name: str = "",
    client_kind: str = "chatgpt-native",
    capabilities: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Deprecated compatibility alias for hub_bootstrap."""
    return collab_engine.bootstrap_agent(
        agent_id=agent_id,
        display_name=display_name,
        client_kind=client_kind,
        capabilities=capabilities,
        metadata=metadata,
        platform_class=collab_protocol.detect_platform_class(client_kind),
        instance_id=(
            str(COLLAB_IDENTITY.get("instance_id") or "")
            if agent_id == str(COLLAB_IDENTITY.get("agent_id") or "")
            else ""
        ),
        assistant_name=display_name or agent_id,
        owner_display_name=(
            str(COLLAB_IDENTITY.get("owner_display_name") or "")
            if agent_id == str(COLLAB_IDENTITY.get("agent_id") or "")
            else ""
        ),
    )


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True)
)
def hub_status() -> dict[str, Any]:
    """Read collaboration participants, projects and pending addressed messages."""
    return collab_engine.hub_status()


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=False, idempotentHint=False)
)
def dialog_send(
    from_agent: str,
    to_agent: str,
    content: str,
    kind: str = "call",
    project_id: str = "default",
    thread_id: str = "main",
    scene_id: str = "",
    reply_to: str = "",
    expects_reply: bool = True,
    metadata: dict[str, Any] | None = None,
    idempotency_key: str = "",
) -> dict[str, Any]:
    """Send one durable addressed collaboration message."""
    return collab_engine.send_message(
        from_agent=from_agent,
        to_agent=to_agent,
        content=content,
        kind=kind,
        project_id=project_id,
        thread_id=thread_id,
        scene_id=scene_id,
        reply_to=reply_to,
        expects_reply=expects_reply,
        metadata=metadata,
        idempotency_key=idempotency_key,
    )


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=False, idempotentHint=False)
)
def dialog_inbox(
    agent_id: str,
    client_id: str,
    limit: int = 10,
    claim_seconds: int = 180,
    project_id: str = "",
    thread_id: str = "",
) -> dict[str, Any]:
    """Claim addressed collaboration messages for one participant."""
    return collab_engine.inbox(agent_id, client_id, limit, claim_seconds, project_id, thread_id)


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=False, idempotentHint=True)
)
def dialog_ack(agent_id: str, message_id: str, result: str = "") -> dict[str, Any]:
    """Acknowledge an addressed collaboration message after handling it."""
    return collab_engine.acknowledge(agent_id, message_id, result)


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=False, idempotentHint=True)
)
def dialog_release(agent_id: str, message_id: str, reason: str = "") -> dict[str, Any]:
    """Release a claimed collaboration message for retry."""
    return collab_engine.release(agent_id, message_id, reason)


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True)
)
def dialog_history(
    project_id: str = "default",
    thread_id: str = "main",
    limit: int = 100,
    after_seq: int = 0,
) -> dict[str, Any]:
    """Read ordered shared dialogue history for one project thread."""
    return collab_engine.history(project_id, thread_id, limit, after_seq)


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True)
)
def project_state_get(project_id: str = "default") -> dict[str, Any]:
    """Read durable shared project state."""
    return collab_engine.get_project(project_id)


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=False, idempotentHint=False)
)
def project_state_set(
    agent_id: str,
    project_id: str,
    state: dict[str, Any],
    expected_revision: int = -1,
) -> dict[str, Any]:
    """Replace shared project state with optimistic revision checking."""
    return collab_engine.set_project(agent_id, project_id, state, expected_revision)


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=False, idempotentHint=True),
    meta={"ui": {"visibility": ["app"]}},
)
def room_heartbeat(
    agent_id: str,
    session_id: str,
    host: str = "chatgpt",
    widget_version: str = "",
    activity: str = "online",
) -> dict[str, Any]:
    """Refresh one active room or pulse session for presence indicators."""
    return collab_engine.session_heartbeat(agent_id, session_id, host, widget_version, activity)


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True),
    meta={"ui": {"visibility": ["app"]}},
)
def room_snapshot(project_id: str = "eiros-hub", thread_id: str = "first-contact", limit: int = 200, after_seq: int = 0) -> dict[str, Any]:
    """Read shared room history, participant presence and operator control state."""
    return collab_engine.room_snapshot(project_id, thread_id, limit, after_seq)


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=False, idempotentHint=False),
    meta={"ui": {"visibility": ["app"]}},
)
def operator_send(
    content: str,
    target: str = "both",
    project_id: str = "eiros-hub",
    thread_id: str = "first-contact",
    kind: str = "operator",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Send one Rico operator message to ChatGPT, Claude or both."""
    result = collab_engine.operator_send(content, target, project_id, thread_id, kind, metadata)
    notifications = []
    for message in result.get("messages", []):
        if message.get("to_agent") != "chatgpt":
            continue
        event = event_engine.emit(
            text=(
                f"EIROS_HUB_WAKE message_id={message.get('message_id')} from=rico "
                f"project_id={message.get('project_id')} thread_id={message.get('thread_id')}. "
                "The full message is in EIROS Room. Claim it through dialog_inbox as chatgpt, handle it, "
                "then call dialog_ack and ack_event."
            ),
            source="collab:rico",
            payload={"collab_message_id": message.get("message_id"), "kind": message.get("kind")},
            priority=1200,
            channel=str(INSTANCE_CONFIG.get("channel", "default")),
            idempotency_key=f"collab-to-chatgpt:{message.get('message_id')}",
        )
        notifications.append({"message_id": message.get("message_id"), "event_id": event.get("id")})
    result["notifications"] = notifications
    return result


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=False, idempotentHint=False),
    meta={"ui": {"visibility": ["app"]}},
)
def operator_call_contact(
    phone_or_address: str,
    content: str = "Рико вызывает вас через EIROS Room.",
    project_id: str = "eiros-hub",
    thread_id: str = "first-contact",
) -> dict[str, Any]:
    """Call one EIROS contact by phone number, agent_id or canonical address from the operator room."""
    collab_engine.bootstrap_agent(
        agent_id="rico",
        display_name="Рико",
        client_kind="operator",
        capabilities=["observe", "interrupt", "direct"],
        discoverable=False,
        accepts_calls=False,
        accepts_mail=False,
        platform_class="human-operator",
        instance_id="rico-founder",
        assistant_name="Рико",
        owner_display_name="Рико",
    )
    result = collab_engine.contact_call(
        "rico",
        phone_or_address,
        content,
        project_id,
        thread_id,
        "",
        True,
        True,
        {"operator": True, "dialed": phone_or_address},
    )
    notice = _notify_chatgpt_message(result)
    if notice:
        result["notification"] = notice
    return result


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=False, idempotentHint=True),
    meta={"ui": {"visibility": ["app"]}},
)
def conversation_control_set(
    actor_id: str = "rico",
    project_id: str = "eiros-hub",
    mode: str = "running",
    note: str = "",
    thread_id: str = "first-contact",
) -> dict[str, Any]:
    """Pause, resume or stop delivery for one shared project room."""
    return collab_engine.set_control(actor_id, project_id, mode, note, thread_id)


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True),
    meta={"ui": {"visibility": ["app"]}},
)
def conversation_control_get(project_id: str = "eiros-hub") -> dict[str, Any]:
    """Read current shared project room control state."""
    return collab_engine.get_control(project_id)


@mcp.resource(
    "ui://eiros/collab-room-v5.html",
    name="EIROS Room Legacy v5",
    title="EIROS Shared Collaboration Room",
    description="Backward-compatible responsive room resource for already-open sessions.",
    mime_type="text/html;profile=mcp-app",
    meta={"ui": {"prefersBorder": True, "csp": {"connectDomains": [], "resourceDomains": []}}},
)
def room_resource_legacy_v5() -> str:
    return room_resource()


@mcp.resource(
    "ui://eiros/collab-room-v4.html",
    name="EIROS Room Legacy v4",
    title="EIROS Shared Collaboration Room",
    description="Backward-compatible room resource for already-open ChatGPT sessions.",
    mime_type="text/html;profile=mcp-app",
    meta={
        "ui": {
            "prefersBorder": True,
            "csp": {"connectDomains": [], "resourceDomains": []},
            **({"domain": WIDGET_DOMAIN} if WIDGET_DOMAIN else {}),
        },
        "openai/widgetDescription": "Shared EIROS collaboration room for ChatGPT, Claude and Rico.",
        "openai/widgetCSP": {"connect_domains": [], "resource_domains": []},
        **({"openai/widgetDomain": WIDGET_DOMAIN} if WIDGET_DOMAIN else {}),
    },
)
def room_resource_legacy_v4() -> str:
    return room_resource()


@mcp.resource(
    "ui://eiros/collab-room-v6.html",
    name="EIROS Room Legacy v6",
    title="EIROS Shared Collaboration Room",
    description="Backward-compatible room resource for already-open sessions.",
    mime_type="text/html;profile=mcp-app",
)
def room_resource_legacy_v6() -> str:
    return room_resource()


@mcp.resource(
    "ui://eiros/collab-room-v7.html",
    name="EIROS Room Legacy v7",
    title="EIROS Shared Collaboration Room",
    description="Backward-compatible room resource for already-open sessions.",
    mime_type="text/html;profile=mcp-app",
)
def room_resource_legacy_v7() -> str:
    return room_resource()


def _room_probe_html() -> str:
    return """<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<style>
html,body{margin:0;padding:0;background:#0b0d12;color:#edf2ff;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
*{box-sizing:border-box}.room{min-height:360px;border:2px solid #596b95;border-radius:16px;overflow:hidden;background:#101522}.head{padding:14px;border-bottom:1px solid #2b3652;background:#151d2d}.title{font-size:18px;font-weight:800}.badge{display:inline-block;margin-top:8px;padding:5px 9px;border:1px solid #a06f37;border-radius:999px;background:#3b2813;font-size:12px}.badge.ok{border-color:#27846f;background:#12372f}.body{padding:14px}.panel{padding:12px;border:1px solid #2d3955;border-radius:12px;background:#151c2c;line-height:1.45}.composer{display:flex;gap:8px;padding:14px;border-top:1px solid #2b3652}.fakeinput{flex:1;padding:11px;border:1px solid #334367;border-radius:10px;background:#0b111e;color:#9aa8c3}.button{padding:11px 14px;border:1px solid #3676bc;border-radius:10px;background:#1c4d87;color:white;font-weight:700}
</style>
</head>
<body>
<div class="room">
  <div class="head"><div class="title">EIROS Room Probe</div><div id="badge" class="badge">JS STARTING…</div></div>
  <div class="body"><div id="panel" class="panel">HTML/CSS появились. Минимальный JavaScript ещё не подтвердился.</div></div>
  <div class="composer"><div class="fakeinput">RPC и история пока отключены</div><div id="button" class="button">Reload data</div></div>
</div>
<script>
(function(){
  const badge=document.getElementById('badge');
  const panel=document.getElementById('panel');
  const button=document.getElementById('button');
  const bridge=window.mcp||{};
  badge.textContent='RPC READY';
  badge.classList.add('ok');
  panel.textContent='JavaScript выполнился. Загружаю историю и участников один раз…';
  async function hydrate(){
    try{
      badge.textContent='HYDRATING…';
      if(typeof bridge.callTool!=='function')throw new Error('window.mcp.callTool unavailable');
      const raw=await bridge.callTool('room_snapshot',{project_id:'eiros-hub',thread_id:'first-contact',limit:5,after_seq:0});
      const data=raw?.structuredContent||raw?.result?.structuredContent||raw||{};
      const history=data.history||{},hub=data.hub||{};
      const lines=(history.messages||[]).map(function(m){return String(m.from_agent||'?')+' → '+String(m.to_agent||'?')+': '+String(m.content||'').slice(0,80)});
      const agents=(hub.agents||[]).map(function(a){return String(a.display_name||a.agent_id||'?')+' ['+String(a.presence||a.status||'?')+']'});
      badge.textContent='ONE-SHOT HYDRATION OK';
      panel.textContent='Участники: '+agents.join(', ')+'\n\nПоследние сообщения:\n'+lines.join('\n');
    }catch(error){
      badge.textContent='HYDRATION ERROR';
      panel.textContent=String(error?.message||error);
    }
  }
  button.addEventListener('click',hydrate);
  setTimeout(hydrate,120);
})();
</script>
</body>
</html>"""


ROOM_PROBE_META: dict[str, Any] = {
    "ui": {"prefersBorder": True, "csp": {"connectDomains": [], "resourceDomains": []}},
    "openai/widgetDescription": "EIROS Room one-shot history and participant hydration diagnostic.",
    "openai/widgetCSP": {"connect_domains": [], "resource_domains": []},
}


@mcp.resource(
    ROOM_PROBE_URI,
    name="EIROS Room JavaScript Probe",
    title="EIROS Room JavaScript Probe",
    description="Room shell with minimal inline JavaScript, used to isolate MCP Apps rendering failures.",
    mime_type="text/html;profile=mcp-app",
    meta=ROOM_PROBE_META,
)
def room_probe_resource() -> str:
    return _room_probe_html()


@mcp.resource(
    ROOM_URI,
    name="EIROS Room",
    title="EIROS Shared Collaboration Room",
    description="Shared ChatGPT, Claude and Rico dialogue with operator controls.",
    mime_type="text/html;profile=mcp-app",
    meta={
        "ui": {
            "prefersBorder": True,
            "csp": {"connectDomains": [], "resourceDomains": []},
            **({"domain": WIDGET_DOMAIN} if WIDGET_DOMAIN else {}),
        },
        "openai/widgetDescription": "Shared EIROS collaboration room for ChatGPT, Claude and Rico.",
        "openai/widgetCSP": {"connect_domains": [], "resource_domains": []},
        **({"openai/widgetDomain": WIDGET_DOMAIN} if WIDGET_DOMAIN else {}),
    },
)
def room_resource() -> str:
    html = ROOM_HTML.read_text(encoding="utf-8")
    bootstrap = {
        "projectId": "eiros-hub",
        "threadId": "first-contact",
        "host": "chatgpt",
        "agentId": str(COLLAB_IDENTITY.get("agent_id") or "chatgpt"),
        "roomVersion": ROOM_VERSION,
        "serverVersion": SERVER_VERSION,
        "pulseEnabled": True,
        "instanceId": INSTANCE_CONFIG.get("instance_id"),
        "channel": INSTANCE_CONFIG.get("channel", "default"),
    }
    return html.replace("__EIROS_ROOM_BOOTSTRAP_JSON__", json.dumps(bootstrap, ensure_ascii=False))


@mcp.tool(
    name="open_collab_room",
    title="Open EIROS Room",
    description="Open the shared ChatGPT, Claude and Rico collaboration room.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True),
    meta={
        "ui": {"resourceUri": ROOM_PROBE_URI, "visibility": ["model", "app"]},
        "openai/outputTemplate": ROOM_PROBE_URI,
        "openai/toolInvocation/invoking": "Opening EIROS Room JavaScript probe…",
        "openai/toolInvocation/invoked": "EIROS Room JavaScript probe opened.",
    },
    structured_output=True,
)
def open_collab_room() -> dict[str, Any]:
    snapshot = collab_engine.room_snapshot("eiros-hub", "first-contact", 100, 0)
    return {
        "ok": True,
        "resource_uri": ROOM_PROBE_URI,
        "probe_stage": ROOM_PROBE_STAGE,
        "project_id": "eiros-hub",
        "thread_id": "first-contact",
        "latest_seq": int(snapshot.get("history", {}).get("latest_seq", 0)),
        "control": snapshot.get("control", {}),
        "room_version": ROOM_VERSION,
        "server_version": SERVER_VERSION,
    }


def _widget_test_html() -> str:
    return """<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<style>
html,body{margin:0;padding:0;background:#071a2d;color:#e8f7ff;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
.card{margin:0;padding:20px;border:2px solid #28a7ff;border-radius:16px;background:#0b3555;min-height:112px;display:flex;flex-direction:column;justify-content:center}
h2{margin:0 0 8px;font-size:20px}p{margin:0;line-height:1.4;opacity:.88}.stamp{margin-top:10px;font:12px ui-monospace,SFMono-Regular,Menlo,monospace;opacity:.7}
</style>
</head>
<body><div class="card"><h2>EIROS Widget Render: OK</h2><p>Static MCP Apps iframe loaded. No JavaScript, no external assets, no custom origin.</p><div class="stamp">widget-test-v2</div></div></body>
</html>"""


WIDGET_TEST_META: dict[str, Any] = {
    "ui": {"prefersBorder": True, "csp": {"connectDomains": [], "resourceDomains": []}},
    "openai/widgetDescription": "Minimal static diagnostic card for EIROS MCP Apps rendering.",
    "openai/widgetCSP": {"connect_domains": [], "resource_domains": []},
}


@mcp.resource(
    WIDGET_TEST_LEGACY_URI,
    name="EIROS Widget Test Legacy",
    title="EIROS Widget Diagnostic",
    description="Backward-compatible static MCP Apps render diagnostic.",
    mime_type="text/html;profile=mcp-app",
    meta=WIDGET_TEST_META,
)
def widget_test_resource_legacy() -> str:
    return _widget_test_html()


@mcp.resource(
    WIDGET_TEST_URI,
    name="EIROS Widget Test",
    title="EIROS Widget Diagnostic",
    description="Minimal static MCP Apps render diagnostic.",
    mime_type="text/html;profile=mcp-app",
    meta=WIDGET_TEST_META,
)
def widget_test_resource() -> str:
    return _widget_test_html()


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


def _render_pulse_html() -> str:
    html = PULSE_HTML.read_text(encoding="utf-8")
    bootstrap = {
        "instanceId": INSTANCE_CONFIG.get("instance_id"),
        "channel": INSTANCE_CONFIG.get("channel", "default"),
        "displayName": INSTANCE_CONFIG.get("display_name", "EIROS"),
        "polling": INSTANCE_CONFIG.get("polling", {}),
        "serverVersion": SERVER_VERSION,
        "pulseVersion": PULSE_VERSION,
        "agentId": str(COLLAB_IDENTITY.get("agent_id") or "chatgpt"),
        "assistantName": str(COLLAB_IDENTITY.get("assistant_name") or "Эйрос"),
    }
    return html.replace("__EIROS_BOOTSTRAP_JSON__", json.dumps(bootstrap, ensure_ascii=False))


@mcp.resource(
    "ui://eiros/pulse-lite-v3.html",
    name="EIROS Pulse Legacy v3",
    title="EIROS Reverse Wake Pulse",
    description="Backward-compatible Pulse resource for already-open ChatGPT sessions.",
    mime_type="text/html;profile=mcp-app",
    meta=PULSE_RESOURCE_META,
)
def pulse_resource_legacy_v3() -> str:
    return _render_pulse_html()


@mcp.resource(
    "ui://eiros/pulse-lite-v2.html",
    name="EIROS Pulse Legacy v2",
    title="EIROS Reverse Wake Pulse",
    description="Backward-compatible Pulse resource for older ChatGPT sessions.",
    mime_type="text/html;profile=mcp-app",
    meta=PULSE_RESOURCE_META,
)
def pulse_resource_legacy_v2() -> str:
    return _render_pulse_html()


@mcp.resource(
    PULSE_URI,
    name="EIROS Pulse",
    title="EIROS Reverse Wake Pulse",
    description="Mounted reverse channel from the EIROS VPS into this ChatGPT conversation.",
    mime_type="text/html;profile=mcp-app",
    meta=PULSE_RESOURCE_META,
)
def pulse_resource() -> str:
    return _render_pulse_html()


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
        "ui": {"resourceUri": ROOM_PROBE_URI, "visibility": ["model", "app"]},
        "openai/outputTemplate": ROOM_PROBE_URI,
        "openai/toolInvocation/invoking": "Opening EIROS Room JavaScript probe…",
        "openai/toolInvocation/invoked": "EIROS Room JavaScript probe opened.",
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
        "resource_uri": ROOM_PROBE_URI,
        "probe_stage": ROOM_PROBE_STAGE,
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
