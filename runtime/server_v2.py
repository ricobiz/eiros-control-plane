from __future__ import annotations

import argparse
import json
import fcntl
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
from runtime.sum_controller import SumControllerStore

STATE_FILE = ROOT / ".eiros-state.json"
ROOM_TELEMETRY_FILE = ROOT / "runtime" / "room_telemetry.json"
ROOM_TELEMETRY_LOCK = ROOT / "runtime" / "room_telemetry.lock"
BRAIN_INBOX_FILE = ROOT / "runtime" / "brain-inbox.json"
SERVER_VERSION = __version__
PULSE_URI = "ui://eiros/pulse-lite-v4.html"
PULSE_VERSION = "0.4.2-addressed-wake"
WIDGET_TEST_URI = "ui://eiros/widget-test-v2.html"
WIDGET_TEST_LEGACY_URI = "ui://eiros/widget-test-v1.html"
ROOM_URI = "ui://eiros/collab-room-v9-24-inline-isolated.html"
ROOM_LEGACY_V920_URI = "ui://eiros/collab-room-v9-20-browser-recovery.html"
ROOM_LEGACY_V919_URI = "ui://eiros/collab-room-v9-19-clean-start.html"
ROOM_LEGACY_V94_LOCALWAKE_URI = "ui://eiros/collab-room-v9-4-localwake.html"
ROOM_LEGACY_V918_URI = "ui://eiros/collab-room-v9-18-touch-green.html"
ROOM_LEGACY_V914_URI = "ui://eiros/collab-room-v9-14-room-claims-pulse.html"
ROOM_LEGACY_V916_URI = "ui://eiros/collab-room-v9-16-autonomy.html"
ROOM_VERSION = "0.9.24-inline-isolated"
ROOM_LAUNCHER_URI = "ui://eiros/room-launcher-v1d-static-proof.html"
ROOM_LAUNCHER_VERSION = "0.2.6-server-heartbeat"
ROOM_PROBE_URI = "ui://eiros/room-probe-hydrate-v1.html"
ROOM_PROBE_STAGE = "one-shot-hydration"
PULSE_HTML = CODE_ROOT / "runtime" / "pulse_lite.html"
PULSE_ANCHOR_HTML = CODE_ROOT / "runtime" / "pulse_anchor.html"
PIP_CONTROLLER_JS = CODE_ROOT / "runtime" / "pip_controller.js"
WIDGET_LIFECYCLE_JS = CODE_ROOT / "runtime" / "widget_lifecycle.js"
PULSE_INLINE_HTML = CODE_ROOT / "runtime" / "pulse_listener_inline.html"
ROOM_HTML = CODE_ROOT / "runtime" / "collab_room.html"
ROOM_LAUNCHER_HTML = CODE_ROOT / "runtime" / "room_launcher.html"
UI_KILLER_URI = "ui://eiros/widget-killer-v1.html"
UI_KILLER_VERSION = "0.1.0-kill-signal"
UI_KILLER_HTML = CODE_ROOT / "runtime" / "widget_killer.html"
CONTROL_PILL_URI = "ui://eiros/control-pill-v2.html"
CONTROL_PILL_LEGACY_URI = "ui://eiros/control-pill-v1.html"
CONTROL_PILL_VERSION = "0.3.3-server-heartbeat"
CONTROL_PILL_HTML = CODE_ROOT / "runtime" / "control_pill.html"
PULSE_ANCHOR_URI = "ui://eiros/pulse-anchor-v5-6-storage-safe-host-pip.html"
PULSE_FRESH_URI = "ui://eiros/pulse-anchor-v5-7-self-diagnostic-pip.html"
PULSE_FRESH_VERSION = "0.5.7-self-diagnostic-pip"
WIDGET_MOUNT_ATTEMPTS_FILE = ROOT / "runtime" / "widget-mount-attempts.json"
PULSE_ANCHOR_LEGACY_V44_URI = "ui://eiros/pulse-anchor-v4-4-relay-user-wake.html"
PULSE_ANCHOR_LEGACY_V45_URI = "ui://eiros/pulse-anchor-v4-5-confirmed-user-turn.html"
PULSE_ANCHOR_LEGACY_V46_URI = "ui://eiros/pulse-anchor-v4-6-isolated-lifecycle.html"
PULSE_ANCHOR_LEGACY_V47_URI = "ui://eiros/pulse-anchor-v4-7-retire-legacy.html"
PULSE_ANCHOR_LEGACY_V48_URI = "ui://eiros/pulse-anchor-v4-8-continuous-retire.html"
PULSE_ANCHOR_LEGACY_V49_URI = "ui://eiros/pulse-anchor-v4-9-singleton.html"
PULSE_ANCHOR_LEGACY_V53_URI = "ui://eiros/pulse-anchor-v5-3-cache-busted-host-pip.html"
PULSE_ANCHOR_LEGACY_V54_URI = "ui://eiros/pulse-anchor-v5-4-managed-sandbox-host-pip.html"
PULSE_ANCHOR_LEGACY_V55_URI = "ui://eiros/pulse-anchor-v5-5-visible-mount-host-pip.html"
PULSE_ANCHOR_LEGACY_URI = "ui://eiros/pulse-anchor-v2-addressed.html"
PULSE_ANCHOR_VERSION = "0.5.6-storage-safe-host-pip"
COMPANION_ORIGIN = "https://178-105-43-79.sslip.io"
COMPANION_PATH = os.environ.get("EIROS_COMPANION_PATH", "companion-c45bbf908ebe178e96a4cfe3d49cf127").strip("/")
PULSE_INLINE_URI = "ui://eiros/pulse-listener-inline-v1.html"
PULSE_INLINE_VERSION = "0.5.0-inline-only"
EIROS_CONSOLE_URI = "ui://eiros/console-fullscreen-v1.html"
EIROS_CONSOLE_VERSION = "1.0.0-separated"
EIROS_CONSOLE_HTML = CODE_ROOT / "runtime" / "eiros_console.html"
WORK_ANCHOR_URI = "ui://eiros/work-anchor-v1-host-contract.html"
WORK_ANCHOR_VERSION = "0.2.0-ack-confirmed"
WORK_ANCHOR_HTML = CODE_ROOT / "runtime" / "work_anchor.html"

# MCP App resource URIs are host cache keys. Room stays on its current URI
# while its component is unchanged; every Pulse HTML/JS/CSS revision gets a new
# implementation URI and open_pulse must point directly at that current key.
UI_MOUNT_CONTRACT_VERSION = "2"
ROOM_MOUNT_URI = ROOM_URI
PULSE_ANCHOR_MOUNT_URI = PULSE_ANCHOR_URI

INSTANCE_CONFIG = load_config()
SUM_CONTROLLER = SumControllerStore(
    ROOT / "runtime" / "sum-controller.json",
    ROOT / "runtime" / "sum-controller.jsonl",
)
COLLAB_IDENTITY = dict(INSTANCE_CONFIG.get("collab_identity") or {})
CONFIGURED_WIDGET_DOMAIN = str(INSTANCE_CONFIG.get("widget_domain") or "").rstrip("/")
# Custom widget origins are opt-in. During development ChatGPT's managed sandbox
# is more reliable and avoids blank/grey iframe failures from stale origin metadata.
USE_CUSTOM_WIDGET_DOMAIN = bool(CONFIGURED_WIDGET_DOMAIN) and os.environ.get("EIROS_ENABLE_CUSTOM_WIDGET_DOMAIN", "").strip().lower() in {"1", "true", "yes"}
WIDGET_DOMAIN = CONFIGURED_WIDGET_DOMAIN if USE_CUSTOM_WIDGET_DOMAIN else ""
COMPANION_STREAM_ORIGIN = COMPANION_ORIGIN
COMPANION_HLS_URL = f"{COMPANION_STREAM_ORIGIN}/{COMPANION_PATH}/hls/live.m3u8"
PULSE_EXTERNAL_DOMAINS = list(dict.fromkeys(origin for origin in (WIDGET_DOMAIN, COMPANION_STREAM_ORIGIN) if origin))
PULSE_RESOURCE_META: dict[str, Any] = {
    "ui": {
        "prefersBorder": True,
        "csp": {"connectDomains": PULSE_EXTERNAL_DOMAINS, "resourceDomains": PULSE_EXTERNAL_DOMAINS},
        **({"domain": WIDGET_DOMAIN} if WIDGET_DOMAIN else {}),
    },
    "openai/widgetDescription": "Keeps a live, durable reverse event channel from the EIROS instance into this conversation.",
    "openai/widgetCSP": {"connect_domains": PULSE_EXTERNAL_DOMAINS, "resource_domains": PULSE_EXTERNAL_DOMAINS},
    **({"openai/widgetDomain": WIDGET_DOMAIN} if WIDGET_DOMAIN else {}),
}

if str(CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(CODE_ROOT))

from runtime import queue as queue_engine  # noqa: E402
from runtime import events as event_engine  # noqa: E402
from runtime import collab as collab_engine  # noqa: E402
from runtime import widget_pairing  # noqa: E402
from runtime import widget_blackbox  # noqa: E402
from runtime import sam as sam_engine  # noqa: E402
from runtime.doctor import run_doctor  # noqa: E402
from runtime.reconnect import build_resume_context  # noqa: E402
from runtime import security as security_policy  # noqa: E402
from runtime import mastering as mastering_engine  # noqa: E402
from root import root_client  # noqa: E402

mcp = FastMCP(
    "Eiros Control Plane",
    instructions=(
        "This server is the persistent execution environment for Eiros in the "
        "current ChatGPT conversation. Read state before mutating it. "
        "Use core_snapshot for orientation, queue tools for bounded continuation, "
        "and workspace/shell tools for concrete actions. "
        "EIROS CONNECTOR BOOT PROTOCOL v1.0: on the first model turn after this connector becomes available or reconnects, execute this order exactly. "
        "(1) Call core_snapshot, project_state_get for eiros-hub, and project_state_get for eiros-autonomy-network. "
        "(2) Call sam_status, pulse_status, and room_telemetry_status. "
        "(3) If a live current-generation Wake Listener and live Pulse leader already exist, preserve them: do not call open_pulse, close_eiros_widgets, open_collab_room, open_work_anchor, open_widget_test, open_control_pill, or open_room_launcher. "
        "(4) If no live Wake Listener or live Pulse leader exists, call open_pulse_v57 exactly once. Never call close_eiros_widgets automatically. "
        "(5) After mounting, call widget_boot_status with wait_seconds=5, follow its diagnosis and do_now actions, then recheck sam_status and room_telemetry_status. Treat wake as continuously ready only when video_pip_active=true and continuous_wake_ready=true; otherwise tell Rico that one direct tap on Open PiP is still required. "
        "(6) Open Room only after Rico explicitly asks for Room or a UI message explicitly requests it. "
        "(7) Resume unfinished work from durable state without asking Rico to repeat context. Never mount duplicate Listener instances merely to chase UI colors. "
        "The EIROS Room and Wake Listener are separate MCP App cards: use open_collab_room for collaboration UI and open_pulse for the dedicated reverse-wake listener. "
        "Treat its resume_context as authoritative and continue unfinished work without "
        "asking Rico to restate prior context. The current ChatGPT conversation is the "
        "reasoning authority; this server is its persistent body. "
        "When a UI message starts with [EIROS_ROOM_DOCK] or [EIROS_OPEN_ROOM], call open_collab_room as the final tool action. "
        "" + collab_protocol.MAIN_COLLAB_INSTRUCTIONS
    ),
)


def _ui_resource_meta(meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """Normalize every MCP App resource to one CSP and custom-origin contract."""
    normalized = dict(meta or {})
    ui = dict(normalized.get("ui") or {})
    csp = dict(ui.get("csp") or {})
    legacy_csp = dict(normalized.get("openai/widgetCSP") or {})

    connect_domains = list(csp.get("connectDomains") or legacy_csp.get("connect_domains") or [])
    resource_domains = list(csp.get("resourceDomains") or legacy_csp.get("resource_domains") or [])
    csp["connectDomains"] = connect_domains
    csp["resourceDomains"] = resource_domains
    ui["csp"] = csp

    legacy_csp["connect_domains"] = connect_domains
    legacy_csp["resource_domains"] = resource_domains
    normalized["openai/widgetCSP"] = legacy_csp

    if WIDGET_DOMAIN:
        ui["domain"] = WIDGET_DOMAIN
        normalized["openai/widgetDomain"] = WIDGET_DOMAIN
    else:
        ui.pop("domain", None)
        normalized.pop("openai/widgetDomain", None)
    normalized["ui"] = ui
    return normalized


def app_resource(uri: str, *args: Any, meta: dict[str, Any] | None = None, **kwargs: Any) -> Any:
    """Register a resource and enforce submission metadata for every ui:// URI."""
    if str(uri).startswith("ui://"):
        meta = _ui_resource_meta(meta)
    return mcp.resource(uri, *args, meta=meta, **kwargs)


def _observed_client(ctx: Context) -> dict[str, str]:
    params = getattr(ctx.request_context.session, "client_params", None)
    info = getattr(params, "clientInfo", None) if params else None
    return {
        "name": str(getattr(info, "name", "") or ""),
        "version": str(getattr(info, "version", "") or ""),
    }



def _room_agent_profile(agent_id: str, host: str = "chatgpt") -> dict[str, Any]:
    identity = str(agent_id or "").strip().lower() or "chatgpt"
    if identity == "chatgpt":
        return {
            "display_name": "ChatGPT / EIROS",
            "client_kind": "chatgpt-native-room",
            "platform_class": "chatgpt",
            "instance_id": str(INSTANCE_CONFIG.get("instance_id") or "chatgpt-native"),
            "assistant_name": "EIROS",
            "owner_display_name": "Rico",
            "capabilities": ["room", "wake", "operator", "bridge"],
        }
    if identity == "claude":
        return {
            "display_name": "Claude",
            "client_kind": "claude-room",
            "platform_class": "claude",
            "instance_id": "claude-room-placeholder",
            "assistant_name": "Claude",
            "owner_display_name": "Rico",
            "capabilities": ["room", "wake", "mail"],
        }
    return {
        "display_name": identity,
        "client_kind": str(host or "room")[:80],
        "platform_class": str(host or "ai")[:80],
        "instance_id": f"room-{identity}",
        "assistant_name": identity,
        "owner_display_name": "Rico",
        "capabilities": ["room"],
    }


def _ensure_room_agent(agent_id: str, host: str = "chatgpt") -> dict[str, Any]:
    profile = _room_agent_profile(agent_id, host)
    try:
        return collab_engine.bootstrap_agent(
            agent_id=str(agent_id or "chatgpt"),
            display_name=profile["display_name"],
            client_kind=profile["client_kind"],
            capabilities=profile["capabilities"],
            discoverable=True,
            accepts_calls=True,
            accepts_mail=True,
            platform_class=profile["platform_class"],
            instance_id=profile["instance_id"],
            assistant_name=profile["assistant_name"],
            owner_display_name=profile["owner_display_name"],
        )
    except Exception:
        # Do not break UI rendering just because the collaboration store is temporarily locked.
        return {"agent_id": str(agent_id or "chatgpt"), "display_name": profile["display_name"], "error": "bootstrap failed"}


def _subprocess_ok(command: list[str], timeout: float = 2.0) -> tuple[bool, str]:
    try:
        proc = subprocess.run(command, text=True, capture_output=True, timeout=timeout)
        out = (proc.stdout or proc.stderr or "").strip()
        return proc.returncode == 0, out
    except Exception as exc:
        return False, str(exc)


def _lamp(name: str, ok: bool, state: str = "", detail: str = "", severity: str = "critical") -> dict[str, Any]:
    return {"name": name, "ok": bool(ok), "state": state or ("ok" if ok else "down"), "detail": detail, "severity": severity}


def _room_system_status() -> dict[str, Any]:
    lamps: list[dict[str, Any]] = []
    for label, service in [
        ("Tunnel", "eiros-tunnel.service"),
        ("Worker", "eiros-worker.service"),
        ("SAM", "eiros-sam.service"),
        ("Broker", "eiros-root-broker.service"),
    ]:
        ok, out = _subprocess_ok(["systemctl", "is-active", service])
        state = (out or "unknown").splitlines()[0] if out else "unknown"
        lamps.append(_lamp(label, ok and state == "active", state, service))
    current = CODE_ROOT / "runtime" / "server_v2.py"
    lamps.append(_lamp("MCP", current.is_file(), "ready" if current.is_file() else "missing", str(current)))
    try:
        events = event_engine.status(5, str(INSTANCE_CONFIG.get("channel", "default")))
        pending = int(events.get("pending_count", 0))
        leader = events.get("leader") or {}
        leader_live = int(leader.get("lease_until", 0)) > int(time.time())
        if not leader_live:
            pulse_state = "pending leader"
        elif pending:
            pulse_state = f"pending {pending}"
        else:
            pulse_state = "ready"
        lamps.append(_lamp("Pulse", True, pulse_state, f"seq {events.get('latest_seq', 0)} leader {leader.get('widget_id') or 'none'}", "warning"))
    except Exception as exc:
        lamps.append(_lamp("Pulse", False, "error", str(exc), "warning"))
    try:
        pair = widget_pairing.compute("chatgpt", "eiros-hub", "first-contact")
        lamps.append(_lamp(
            "Pair",
            bool(pair.get("ok")),
            str(pair.get("state") or "starting"),
            str(pair.get("summary") or "widget handshake unavailable"),
            "warning",
        ))
    except Exception as exc:
        lamps.append(_lamp("Pair", False, "error", str(exc), "warning"))
    try:
        queue = queue_engine.cmd_status(argparse.Namespace(id=None, status=None, mode=None, events=5))
        tasks = queue.get("tasks") or []
        due = len([t for t in tasks if str(t.get("status")) in {"queued", "awaiting_brain"}])
        lamps.append(_lamp("Queue", True, "clear" if due == 0 else f"{due} jobs", f"tasks {len(tasks)}", "info"))
    except Exception as exc:
        lamps.append(_lamp("Queue", False, "error", str(exc), "warning"))
    git_root = str(CODE_ROOT)
    ok, head = _subprocess_ok(["git", "-C", git_root, "rev-parse", "--short", "HEAD"])
    lamps.append(_lamp("Git", ok, head if ok else "error", git_root, "warning"))
    return {
        "ok": all(l.get("ok") or l.get("severity") == "warning" for l in lamps),
        "lamps": lamps,
        "server_version": SERVER_VERSION,
        "room_version": ROOM_VERSION,
        "launcher_version": ROOM_LAUNCHER_VERSION,
        "time": int(time.time()),
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



def _ack_linked_pulse_events(message_id: str, actor: str = "chatgpt") -> list[dict[str, Any]]:
    mid = str(message_id or "").strip()
    if not mid:
        return []
    cleaned = []
    try:
        data = event_engine.status(500, str(INSTANCE_CONFIG.get("channel", "default")))
        for event in data.get("events", []):
            payload = event.get("payload") or {}
            if str(payload.get("collab_message_id") or "") != mid:
                continue
            if str(event.get("status") or "") == "acked":
                continue
            try:
                acked = event_engine.acknowledge(
                    str(event.get("id")),
                    f"auto-clean after dialog_ack for collab_message_id={mid}",
                    actor,
                )
                cleaned.append({
                    "event_id": acked.get("id"),
                    "seq": acked.get("seq"),
                    "status": acked.get("status"),
                })
            except Exception as exc:
                cleaned.append({
                    "event_id": event.get("id"),
                    "error": str(exc),
                })
    except Exception as exc:
        cleaned.append({"error": str(exc)})
    return cleaned


def _ensure_pending_chatgpt_wakes(project_id: str = "eiros-hub", thread_id: str = "first-contact") -> dict[str, Any]:
    """Ensure every unhandled ChatGPT message has a live wake event without acknowledging it."""
    agent_id = str(COLLAB_IDENTITY.get("agent_id") or "chatgpt")
    pending = collab_engine.peek(agent_id, 50, project_id, thread_id)
    channel = str(INSTANCE_CONFIG.get("channel", "default"))
    status = event_engine.status(500, channel)
    live_by_message: dict[str, dict[str, Any]] = {}
    for event in status.get("events", []):
        if str(event.get("status") or "") == "acked":
            continue
        mid = str((event.get("payload") or {}).get("collab_message_id") or "")
        if mid:
            live_by_message[mid] = event
    ensured = []
    for message in pending.get("messages", []):
        mid = str(message.get("message_id") or "")
        if not mid:
            continue
        existing = live_by_message.get(mid)
        if existing:
            ensured.append({"message_id": mid, "event_id": existing.get("id"), "created": False})
            continue
        event = event_engine.emit(
            text=(
                f"EIROS_HUB_WAKE message_id={mid} from={message.get('from_agent')} "
                f"project_id={message.get('project_id')} thread_id={message.get('thread_id')}. "
                "This unhandled message survived a clean Room restart. Deliver it to ChatGPT as a user-originated "
                "wake from Rico, then claim it through dialog_inbox, handle it and call dialog_ack and ack_event."
            ),
            source=f"collab:{message.get('from_agent')}",
            payload={
                "collab_message_id": mid,
                "from_agent": message.get("from_agent"),
                "to_agent": agent_id,
                "project_id": message.get("project_id"),
                "thread_id": message.get("thread_id"),
                "kind": message.get("kind"),
                "clean_start_replay": True,
            },
            priority=1000,
            channel=channel,
            idempotency_key=f"clean-start:{mid}:{int(time.time())}",
        )
        ensured.append({"message_id": mid, "event_id": event.get("id"), "created": True})
    return {
        "ok": True,
        "pending_count": int(pending.get("pending_count", 0)),
        "available_count": int(pending.get("available_count", 0)),
        "ensured_count": len(ensured),
        "events": ensured,
    }


def _delivery_receipts(messages: list[dict[str, Any]], notifications: list[dict[str, Any]]) -> list[dict[str, Any]]:
    hub = collab_engine.hub_status()
    agents = {str(item.get("agent_id")): item for item in hub.get("agents", [])}
    notified = {str(item.get("message_id")): item for item in notifications}
    receipts = []
    for message in messages:
        recipient = str(message.get("to_agent") or "")
        agent = agents.get(recipient, {})
        presence = str(agent.get("presence") or "offline")
        activity = str(agent.get("activity") or presence)
        if recipient == "chatgpt" and str(message.get("message_id")) in notified:
            mode = "wake queued"
        elif presence == "online":
            mode = "live pulse"
        elif presence == "away":
            mode = "queued (away)"
        else:
            mode = "offline mail"
        receipts.append({
            "agent_id": recipient,
            "message_id": message.get("message_id"),
            "presence": presence,
            "activity": activity,
            "mode": mode,
        })
    return receipts


@app_resource(
    collab_protocol.ONBOARDING_URI,
    name="EIROS Onboarding Protocol",
    title="EIROS Hub Onboarding",
    description="Machine-readable first-connection and identity rules for EIROS Hub.",
    mime_type="application/json",
)
def protocol_onboarding_resource() -> str:
    return json.dumps(collab_protocol.onboarding_document(), ensure_ascii=False, indent=2)


@app_resource(
    collab_protocol.DIALOGUE_URI,
    name="EIROS Dialogue Protocol",
    title="EIROS Addressed Dialogue",
    description="Message routing, claim, reply, acknowledgement and retry contract.",
    mime_type="application/json",
)
def protocol_dialogue_resource() -> str:
    return json.dumps(collab_protocol.dialogue_document(), ensure_ascii=False, indent=2)


@app_resource(
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


def _brain_inbox_update(task_id: str, revision: int = 0, status: str = "", remove: bool = False) -> dict[str, Any]:
    """Update the durable scheduler-to-model inbox after a model claims or resolves a task."""
    target = str(task_id or "").strip()
    current = read_json_file(BRAIN_INBOX_FILE, {"revision": 0, "updated_at": 0, "items": []})
    items = []
    changed = 0
    for raw in current.get("items", []):
        item = dict(raw)
        if str(item.get("id") or "") != target:
            items.append(item)
            continue
        if revision and int(item.get("revision", 0)) != int(revision):
            items.append(item)
            continue
        changed += 1
        if remove:
            continue
        item["status"] = str(status or item.get("status") or "pending_model_turn")
        item["updated_at"] = int(time.time())
        items.append(item)
    current["items"] = items[-1000:]
    current["revision"] = int(current.get("revision", 0)) + 1
    current["updated_at"] = int(time.time())
    atomic_json_write(BRAIN_INBOX_FILE, current)
    return {"ok": True, "task_id": target, "changed": changed, "removed": bool(remove)}


def _read_widget_mount_attempts() -> dict[str, Any]:
    return read_json_file(WIDGET_MOUNT_ATTEMPTS_FILE, {"revision": 0, "attempts": []})


def _write_widget_mount_attempts(store: dict[str, Any]) -> None:
    store["revision"] = int(store.get("revision", 0)) + 1
    store["updated_at"] = int(time.time())
    store["attempts"] = list(store.get("attempts") or [])[-200:]
    atomic_json_write(WIDGET_MOUNT_ATTEMPTS_FILE, store)


def _record_widget_mount_attempt(tool_name: str, expected_uri: str, expected_version: str, expected_kind: str = "listener") -> dict[str, Any]:
    store = _read_widget_mount_attempts()
    now = int(time.time())
    mount_id = f"mount-{now}-{os.urandom(4).hex()}"
    attempt = {
        "mount_id": mount_id,
        "tool_name": tool_name,
        "expected_uri": expected_uri,
        "expected_version": expected_version,
        "expected_kind": expected_kind,
        "requested_at": now,
        "resource_served_at": 0,
        "status": "MOUNT_REQUESTED",
    }
    store.setdefault("attempts", []).append(attempt)
    _write_widget_mount_attempts(store)
    return attempt


def _mark_widget_resource_served(expected_uri: str) -> dict[str, Any]:
    store = _read_widget_mount_attempts()
    now = int(time.time())
    selected = None
    for attempt in reversed(store.get("attempts") or []):
        if str(attempt.get("expected_uri") or "") != str(expected_uri):
            continue
        if int(attempt.get("resource_served_at", 0)):
            continue
        attempt["resource_served_at"] = now
        attempt["status"] = "RESOURCE_SERVED"
        selected = attempt
        break
    if selected is None:
        selected = {
            "mount_id": f"resource-{now}-{os.urandom(4).hex()}",
            "tool_name": "resource_fetch_without_recorded_tool_call",
            "expected_uri": expected_uri,
            "expected_version": PULSE_FRESH_VERSION,
            "expected_kind": "listener",
            "requested_at": now,
            "resource_served_at": now,
            "status": "RESOURCE_SERVED",
        }
        store.setdefault("attempts", []).append(selected)
    _write_widget_mount_attempts(store)
    return dict(selected)


def _diagnosis(
    name: str,
    cause: str,
    do_now: list[str],
    do_not_repeat: list[str],
    requires_rico_action: bool = False,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "diagnosis": name,
        "cause": cause,
        "do_now": do_now,
        "do_not_repeat": do_not_repeat,
        "requires_rico_action": bool(requires_rico_action),
        **extra,
    }


def _diagnose_widget_boot(attempt: dict[str, Any], widgets: list[dict[str, Any]], now: int | None = None) -> dict[str, Any]:
    current = int(now or time.time())
    requested_at = int(attempt.get("requested_at", 0))
    expected_version = str(attempt.get("expected_version") or "")
    expected_kind = str(attempt.get("expected_kind") or "listener")
    mount_id = str(attempt.get("mount_id") or "")
    recent = [w for w in widgets if int(w.get("updated_at", 0)) >= requested_at]

    def snapshot_of(item: dict[str, Any]) -> dict[str, Any]:
        value = item.get("snapshot") or {}
        return value if isinstance(value, dict) else {}

    matching = []
    mismatched = []
    for widget in recent:
        snap = snapshot_of(widget)
        actual_kind = str(snap.get("actual_widget_kind") or widget.get("widget_kind") or "")
        actual_version = str(snap.get("version") or snap.get("widget_version") or "")
        actual_mount_id = str(snap.get("mount_id") or "")
        if actual_mount_id and mount_id and actual_mount_id == mount_id:
            matching.append(widget)
        elif actual_kind == expected_kind and actual_version == expected_version:
            matching.append(widget)
        else:
            mismatched.append(widget)

    if mismatched and not matching:
        widget = mismatched[-1]
        snap = snapshot_of(widget)
        return _diagnosis(
            "STALE_TOOL_RESOURCE_BINDING",
            f"The session mounted {widget.get('widget_kind') or snap.get('actual_widget_kind') or 'unknown'} "
            f"{snap.get('version') or 'unknown'} instead of {expected_kind} {expected_version}.",
            [
                "Reconnect EBRIDGE so this ChatGPT session refreshes its MCP tool catalog.",
                "Invoke the new open_pulse_v57 tool exactly once.",
                "Run widget_boot_status again and follow the returned diagnosis.",
                "If the same stale binding remains, restart the ChatGPT app; change branch only after that fails.",
            ],
            [
                "Do not invoke the same old tool repeatedly.",
                "Do not restart the VPS, SAM, worker or Companion for a session-local catalog mismatch.",
                "Do not mount duplicate listeners to chase status colors.",
            ],
            True,
            mount_id=mount_id,
            expected_kind=expected_kind,
            expected_version=expected_version,
            observed_widget=widget,
        )

    if not matching:
        age = max(0, current - requested_at)
        if int(attempt.get("resource_served_at", 0)) and age >= 5:
            return _diagnosis(
                "RESOURCE_SERVED_NO_JS_TELEMETRY",
                "The MCP resource was served, but the iframe produced no JavaScript telemetry. This is the grey/blank iframe failure class.",
                [
                    "Reconnect EBRIDGE once.",
                    "Restart the ChatGPT app and invoke open_pulse_v57 once.",
                    "If the iframe is still silent, open a new branch only after the app restart test.",
                ],
                [
                    "Do not repair the VPS or CSP before client-side rendering is proven.",
                    "Do not invoke the same widget repeatedly in the same broken session.",
                ],
                True,
                mount_id=mount_id,
            )
        if age >= 5:
            return _diagnosis(
                "HOST_DID_NOT_REQUEST_RESOURCE",
                "The tool call completed, but the ChatGPT host did not request the expected ui:// resource.",
                [
                    "Reconnect EBRIDGE to refresh the MCP catalog.",
                    "Restart the ChatGPT app if the resource is still not requested.",
                    "Invoke open_pulse_v57 once after reconnect.",
                ],
                [
                    "Do not restart server-side services for a missing host resource request.",
                    "Do not repeat the stale tool call.",
                ],
                True,
                mount_id=mount_id,
            )
        return _diagnosis(
            "MOUNT_IN_PROGRESS",
            "The host has not produced enough evidence yet.",
            ["Wait briefly and call widget_boot_status again."],
            ["Do not create another mount attempt while this one is still within its diagnostic window."],
            False,
            mount_id=mount_id,
        )

    widget = matching[-1]
    snap = snapshot_of(widget)
    stages = list(snap.get("boot_stages") or [])
    if "PIP_ACTIVE" in stages:
        return _diagnosis(
            "HEALTHY",
            "The expected listener loaded, reached Pulse and activated PiP.",
            ["Preserve this listener and its lease."],
            ["Do not remount or close healthy EIROS widgets."],
            False,
            mount_id=mount_id,
            stages=stages,
        )
    if "VIDEO_READY" in stages:
        return _diagnosis(
            "USER_GESTURE_REQUIRED",
            "The listener, bridge, heartbeat, Pulse and video are ready; iOS still requires a direct user gesture for PiP.",
            ["Rico must tap Open PiP once on the visible listener card."],
            ["Do not restart services or remount the listener."],
            True,
            mount_id=mount_id,
            stages=stages,
        )
    if "PULSE_POLL_OK" in stages:
        return _diagnosis(
            "VIDEO_NOT_READY",
            "The listener and Pulse work, but the Companion video did not become ready.",
            ["Check eiros-companion.service and the HLS endpoint, then retry video loading without remounting the listener."],
            ["Do not refresh the connector catalog for a video-only failure."],
            False,
            mount_id=mount_id,
            stages=stages,
        )
    if "HEARTBEAT_OK" in stages:
        return _diagnosis(
            "PULSE_RPC_FAILED",
            "The bridge and heartbeat work, but Pulse polling did not succeed.",
            ["Inspect pulse_poll, Pulse leader state and the EBRIDGE service journal."],
            ["Do not blame CSP or change branches before checking the Pulse RPC."],
            False,
            mount_id=mount_id,
            stages=stages,
        )
    if "JS_STARTED" in stages and "BRIDGE_READY" not in stages:
        return _diagnosis(
            "HOST_BRIDGE_NOT_READY",
            "The iframe JavaScript started, but the ChatGPT Apps bridge did not become ready.",
            ["Reconnect EBRIDGE; if unchanged, restart the ChatGPT app before changing branch."],
            ["Do not restart VPS services for a missing host bridge."],
            True,
            mount_id=mount_id,
            stages=stages,
        )
    return _diagnosis(
        "MOUNT_IN_PROGRESS",
        "The expected listener is reporting but has not reached a terminal diagnostic stage.",
        ["Wait briefly and call widget_boot_status again."],
        ["Do not mount a duplicate listener."],
        False,
        mount_id=mount_id,
        stages=stages,
    )


def _brain_inbox_prune(dry_run: bool = False) -> dict[str, Any]:
    """Remove inbox entries that no longer correspond to the current awaiting/running task revision."""
    current = read_json_file(BRAIN_INBOX_FILE, {"revision": 0, "updated_at": 0, "items": []})
    queue_store = queue_engine.read_store()
    tasks = {str(item.get("id") or ""): item for item in queue_store.get("tasks", [])}
    kept = []
    removed = []
    for raw in current.get("items", []):
        item = dict(raw)
        task = tasks.get(str(item.get("id") or ""))
        item_status = str(item.get("status") or "pending_model_turn")
        task_status = str((task or {}).get("status") or "")
        task_revision = int((task or {}).get("revision", 0))
        item_revision = int(item.get("revision", 0))
        valid = bool(
            task
            and (
                (
                    item_status == "pending_model_turn"
                    and task_status == "awaiting_brain"
                    and task_revision == item_revision
                )
                or (
                    item_status == "claimed"
                    and task_status == "running"
                    and task_revision == item_revision + 1
                )
            )
        )
        if valid:
            kept.append(item)
        else:
            removed.append(item)
    if not dry_run:
        current["items"] = kept[-1000:]
        current["revision"] = int(current.get("revision", 0)) + 1
        current["updated_at"] = int(time.time())
        atomic_json_write(BRAIN_INBOX_FILE, current)
    return {"ok": True, "removed_count": len(removed), "kept_count": len(kept), "removed": removed, "dry_run": bool(dry_run)}


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
        "widget_blackbox": widget_blackbox.status(True, "core_snapshot"),
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
    result = queue_engine.cmd_claim(args)
    if result.get("claimed"):
        task = result.get("task") or {}
        _brain_inbox_update(str(task.get("id") or ""), int(task.get("revision", 0)) - 1, "claimed", False)
    _brain_inbox_prune(False)
    return result


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
    result = queue_engine.cmd_commit(args)
    _brain_inbox_update(task_id, 0, "resolved", True)
    return result


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
    result = queue_engine.cmd_fail(args)
    _brain_inbox_update(task_id, 0, "failed", True)
    return result


@mcp.tool()
def queue_cancel(task_id: str, reason: str) -> dict[str, Any]:
    """Cancel a queued or running task and clear its lease."""
    args = argparse.Namespace(id=task_id, reason=reason)
    result = queue_engine.cmd_cancel(args)
    _brain_inbox_update(task_id, 0, "cancelled", True)
    return result


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
        "sam": sam_engine.status(5),
        "widget_blackbox": widget_blackbox.status(True, "scheduler_status"),
    }


@mcp.tool()
def queue_reschedule(task_id: str, run_at: int = 0, delay_seconds: int = 0) -> dict[str, Any]:
    """Move a non-terminal task to any exact Unix time or a relative delay."""
    args = argparse.Namespace(
        id=task_id,
        run_at=max(0, int(run_at)),
        delay_seconds=max(0, int(delay_seconds)),
    )
    result = queue_engine.cmd_reschedule(args)
    _brain_inbox_update(task_id, 0, "rescheduled", True)
    return result


@mcp.tool()
def brain_inbox() -> dict[str, Any]:
    """Read scheduled brain tasks that became due while no model turn was active."""
    return read_json_file(ROOT / "runtime" / "brain-inbox.json", {"revision": 0, "updated_at": 0, "items": []})


@mcp.tool()
def widget_watchdog_status() -> dict[str, Any]:
    """Compatibility alias: synchronously read the persistent widget black box."""
    return widget_blackbox.status(True, "widget_watchdog_status_compat")


@mcp.tool()
def widget_watchdog_ack(actor: str = "chatgpt", note: str = "") -> dict[str, Any]:
    """Compatibility no-op: black-box evidence is immutable and needs no acknowledgement."""
    return {
        "ok": True,
        "acknowledged": False,
        "reason": "persistent_blackbox_requires_no_ack",
        "actor": actor,
        "note": note,
        "widget_blackbox": widget_blackbox.status(True, "widget_watchdog_ack_compat"),
    }


@mcp.tool()
def widget_blackbox_status() -> dict[str, Any]:
    """Synchronously compute and read persistent Room/Listener health and recent logs."""
    return widget_blackbox.status(True, "widget_blackbox_status")


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
    """Read collaboration participants plus a synchronous widget black-box snapshot."""
    result = collab_engine.hub_status()
    result["widget_blackbox"] = widget_blackbox.status(True, "hub_status")
    return result


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=False, idempotentHint=False)
)
def dialog_send(
    from_agent: str,
    to_agent: str,
    content: str,
    kind: str = "call",
    project_id: str = "eiros-hub",
    thread_id: str = "first-contact",
    scene_id: str = "",
    reply_to: str = "",
    expects_reply: bool = True,
    metadata: dict[str, Any] | None = None,
    idempotency_key: str = "",
) -> dict[str, Any]:
    """Send one durable addressed collaboration message."""
    result = collab_engine.send_message(
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
    notice = _notify_chatgpt_message(result)
    if notice:
        result["pulse_wake"] = notice
    return result


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
    ack = collab_engine.acknowledge(agent_id, message_id, result)
    ack["linked_pulse_acks"] = _ack_linked_pulse_events(message_id, agent_id)
    return ack


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




def _read_room_telemetry() -> dict[str, Any]:
    try:
        raw = json.loads(ROOM_TELEMETRY_FILE.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {"schema_version": 1, "widgets": {}}
    except FileNotFoundError:
        return {"schema_version": 1, "widgets": {}}
    except Exception as exc:
        return {"schema_version": 1, "widgets": {}, "read_error": str(exc)}


def _write_room_telemetry(store: dict[str, Any]) -> None:
    ROOM_TELEMETRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    store["schema_version"] = 1
    store["updated_at"] = int(time.time())
    widgets = store.setdefault("widgets", {})
    cutoff = int(time.time()) - 3600
    for key in list(widgets.keys()):
        if int((widgets.get(key) or {}).get("updated_at", 0)) < cutoff:
            widgets.pop(key, None)
    fd, tmp = tempfile.mkstemp(prefix="room-telemetry-", suffix=".json", dir=str(ROOM_TELEMETRY_FILE.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(store, handle, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp, ROOM_TELEMETRY_FILE)
    finally:
        Path(tmp).unlink(missing_ok=True) if Path(tmp).exists() else None


def _room_telemetry_update_locked(widget_id: str, item: dict[str, Any]) -> None:
    """Atomic read-modify-write for telemetry under an exclusive file lock."""
    ROOM_TELEMETRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with ROOM_TELEMETRY_LOCK.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            store = _read_room_telemetry()
            store.setdefault("widgets", {})[widget_id] = item
            _write_room_telemetry(store)
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _compact_json(value: Any, max_chars: int = 6000) -> Any:
    try:
        text = json.dumps(value, ensure_ascii=False)
        if len(text) <= max_chars:
            return value
        return {"truncated": True, "text": text[:max_chars]}
    except Exception:
        return str(value)[:max_chars]


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True),
    meta={"ui": {"visibility": ["model", "app"]}},
    structured_output=True,
)
def sum_controller_status() -> dict[str, Any]:
    """Read the durable SUM auto-wake controller state."""
    return SUM_CONTROLLER.status()


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=False, idempotentHint=True),
    meta={"ui": {"visibility": ["app"]}},
    structured_output=True,
)
def sum_controller_set(
    enabled: bool,
    action: str = "set",
    actor: str = "rico",
    listener_session_id: str = "",
) -> dict[str, Any]:
    """Enable or disable the bounded SUM auto-wake controller."""
    normalized = str(action or "set").strip().lower()[:32]
    if normalized == "reset":
        return SUM_CONTROLLER.reset_statistics(
            actor=str(actor or "rico")[:80],
            listener_session_id=str(listener_session_id or "")[:180],
        )
    if normalized in {"start", "resume", "enable"}:
        enabled = True
    elif normalized in {"pause", "stop", "disable"}:
        enabled = False
    elif normalized != "set":
        raise ValueError("unsupported SUM controller action")
    return SUM_CONTROLLER.set_enabled(
        bool(enabled),
        actor=str(actor or "rico")[:80],
        listener_session_id=str(listener_session_id or "")[:180],
    )


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=False, idempotentHint=True),
    meta={"ui": {"visibility": ["app"]}},
    structured_output=True,
)
def sum_host_signal(
    signal: str,
    listener_session_id: str,
    active: bool | None = None,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record one bounded ChatGPT host-activity signal from the Listener."""
    safe_detail = detail if isinstance(detail, dict) else {}
    return SUM_CONTROLLER.record_host_signal(
        str(signal or "unknown")[:120],
        active,
        str(listener_session_id or "")[:180],
        _compact_json(safe_detail, 3000),
    )


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=False, idempotentHint=True),
    meta={"ui": {"visibility": ["app"]}},
    structured_output=True,
)
def sum_controller_tick(
    listener_session_id: str,
    pip_active: bool = False,
    listener_healthy: bool = True,
) -> dict[str, Any]:
    """Advance the SUM controller only when its guarded transition is due."""
    return SUM_CONTROLLER.tick(
        str(listener_session_id or "")[:180],
        pip_active=bool(pip_active),
        listener_healthy=bool(listener_healthy),
    )


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=False, idempotentHint=True),
    meta={"ui": {"visibility": ["app"]}},
    structured_output=True,
)
def sum_wake_sent(
    listener_session_id: str,
    delivery_mode: str = "bridge-confirmed",
) -> dict[str, Any]:
    """Record a bridge-confirmed natural user wake delivery attempt."""
    return SUM_CONTROLLER.mark_wake_sent(
        str(listener_session_id or "")[:180],
        str(delivery_mode or "bridge-confirmed")[:80],
    )


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=False, idempotentHint=True),
    meta={"ui": {"visibility": ["model", "app"]}},
    structured_output=True,
)
def sum_wake_ack_current(
    actor: str = "chatgpt",
    listener_session_id: str = "",
) -> dict[str, Any]:
    """Acknowledge the current pending SUM wake without exposing internal IDs in chat."""
    return SUM_CONTROLLER.ack_current(
        actor=str(actor or "chatgpt")[:80],
        listener_session_id=str(listener_session_id or "")[:180],
    )


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=False, idempotentHint=True),
    meta={"ui": {"visibility": ["model", "app"]}},
    structured_output=True,
)
def sum_wake_ack(
    wake_id: str,
    cycle_id: int,
    awake_epoch: int,
    actor: str = "chatgpt",
) -> dict[str, Any]:
    """Diagnostic exact-ID acknowledgement for a pending SUM wake."""
    return SUM_CONTROLLER.ack_wake(
        str(wake_id or "")[:180],
        int(cycle_id),
        int(awake_epoch),
        str(actor or "chatgpt")[:80],
    )


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True),
    meta={"ui": {"visibility": ["model", "app"]}},
    structured_output=True,
)
def sum_controller_log(limit: int = 100) -> dict[str, Any]:
    """Read a bounded tail of durable SUM state transitions."""
    return SUM_CONTROLLER.read_log(max(1, min(int(limit or 100), 500)))


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=False, idempotentHint=True),
    meta={"ui": {"visibility": ["app"]}},
)
def room_telemetry_update(
    widget_id: str,
    widget_kind: str = "room",
    project_id: str = "eiros-hub",
    thread_id: str = "first-contact",
    status: str = "unknown",
    snapshot: dict[str, Any] | None = None,
    error: str = "",
) -> dict[str, Any]:
    """Persist latest browser-widget runtime state so the assistant can inspect iframe health."""
    identity = str(widget_id or "").strip()[:180]
    if not identity:
        raise ValueError("widget_id is required")
    ts = int(time.time())
    item = {
        "widget_id": identity,
        "widget_kind": str(widget_kind or "room")[:40],
        "project_id": str(project_id or "eiros-hub")[:120],
        "thread_id": str(thread_id or "first-contact")[:160],
        "status": str(status or "unknown")[:80],
        "snapshot": _compact_json(snapshot or {}),
        "error": str(error or "")[:2000],
        "updated_at": ts,
    }
    _room_telemetry_update_locked(identity, item)
    blackbox = widget_blackbox.capture(
        "room_telemetry_update",
        {"widget_id": identity, "widget_kind": item["widget_kind"], "status": item["status"], "error": item["error"]},
    )
    return {"ok": True, "widget_id": identity, "updated_at": ts, "pair": blackbox.get("pair")}


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True),
)
def room_telemetry_status(limit: int = 20) -> dict[str, Any]:
    """Read latest self-reported iframe/widget state from EIROS Room and launcher."""
    store = _read_room_telemetry()
    widgets = list((store.get("widgets") or {}).values())
    widgets.sort(key=lambda item: int(item.get("updated_at", 0)), reverse=True)
    return {
        "ok": True,
        "updated_at": store.get("updated_at", 0),
        "count": len(widgets),
        "widgets": widgets[: max(1, min(int(limit or 20), 100))],
        "read_error": store.get("read_error", ""),
    }


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True),
)
def widget_boot_status(mount_id: str = "", wait_seconds: int = 0) -> dict[str, Any]:
    """Diagnose the latest EIROS widget mount and return exact recovery actions."""
    delay = max(0, min(int(wait_seconds), 10))
    if delay:
        time.sleep(delay)
    attempts = list((_read_widget_mount_attempts().get("attempts") or []))
    if mount_id:
        selected = next((a for a in reversed(attempts) if str(a.get("mount_id") or "") == str(mount_id)), None)
    else:
        selected = attempts[-1] if attempts else None
    if not selected:
        return _diagnosis(
            "NO_MOUNT_ATTEMPT",
            "No recorded EIROS widget mount attempt exists.",
            ["Invoke open_pulse_v57 exactly once."],
            ["Do not call legacy open_pulse tools."],
            False,
        )
    telemetry = _read_room_telemetry()
    widgets = list((telemetry.get("widgets") or {}).values())
    result = _diagnose_widget_boot(dict(selected), widgets, int(time.time()))
    result["attempt"] = selected
    result["telemetry_updated_at"] = telemetry.get("updated_at", 0)
    return result

def _widget_pair_transition_event(status: dict[str, Any]) -> dict[str, Any] | None:
    if not widget_pairing.should_notify(status):
        return None
    room = status.get("room") or {}
    listener = status.get("listener") or {}
    text = (
        "[EIROS_WIDGET_PAIR_STATUS]\n"
        f"state={status.get('state')} color={status.get('color')} pair_id={status.get('pair_id')}\n"
        f"room={room.get('version') or 'missing'} session={room.get('session_id') or 'none'}\n"
        f"listener={listener.get('version') or 'missing'} session={listener.get('session_id') or 'none'}\n"
        f"handshake={status.get('handshake_mode')} challenge_complete={status.get('challenge_complete')}\n"
        f"pulse_leader_matches={((status.get('pulse') or {}).get('leader_matches'))}\n"
        f"reasons={','.join(status.get('reasons') or []) or 'none'}\n\n"
        "This is a Rico-authorized EIROS widget health transition. Report the status in the main chat and acknowledge this event."
    )
    event = event_engine.emit(
        text=text,
        source="collab:rico",
        payload={
            "widget_pair_status": status,
            "origin_role": "user",
            "authority": "rico_pre_authorized_widget_health",
            "system_status": True,
        },
        priority=1400,
        channel=str(INSTANCE_CONFIG.get("channel", "default")),
        idempotency_key=f"widget-pair:{status.get('signature')}",
    )
    widget_pairing.mark_notified(str(status.get("signature") or ""))
    return {"event_id": event.get("id"), "event_seq": event.get("seq")}


def _observe_widget_pair(trigger: str = "pair_observe", extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Persist pair state synchronously in the server black box."""
    widget_pairing.observe("chatgpt", "eiros-hub", "first-contact")
    return widget_blackbox.capture(trigger, extra).get("pair") or {}


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
    widget_role: str = "",
    bundle_id: str = "",
    pair_protocol: str = "",
    pair_ack: str = "",
    expected_peer: str = "",
) -> dict[str, Any]:
    """Refresh one widget session and return its server-mediated peer handshake state."""
    _ensure_room_agent(agent_id, host)
    session = collab_engine.session_heartbeat(
        agent_id,
        session_id,
        host,
        widget_version,
        activity,
        widget_role,
        bundle_id,
        pair_protocol,
        pair_ack,
        expected_peer,
    )
    return {
        "ok": True,
        "session": session,
        "pairing": _observe_widget_pair(
            "room_heartbeat",
            {"session_id": session_id, "host": host, "widget_version": widget_version, "activity": activity},
        ),
    }


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True),
    meta={"ui": {"visibility": ["app"]}},
)
def room_snapshot(project_id: str = "eiros-hub", thread_id: str = "first-contact", limit: int = 200, after_seq: int = 0) -> dict[str, Any]:
    """Read shared room history, participant presence and operator control state."""
    _ensure_room_agent(str(COLLAB_IDENTITY.get("agent_id") or "chatgpt"), "chatgpt")
    snapshot = collab_engine.room_snapshot(project_id, thread_id, limit, after_seq)
    snapshot["system"] = _room_system_status()
    blackbox = widget_blackbox.capture("room_snapshot", {"project_id": project_id, "thread_id": thread_id})
    snapshot["system"]["widget_pair"] = blackbox.get("pair") or {}
    snapshot["system"]["widget_blackbox"] = widget_blackbox.status(False)
    return snapshot


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True),
    meta={"ui": {"visibility": ["app"]}},
)
def room_system_status() -> dict[str, Any]:
    """Read real EIROS service lamps for the operator room."""
    return _room_system_status()


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=False, idempotentHint=True),
    meta={"ui": {"visibility": ["app"]}},
)
def room_cleanup_stale(
    project_id: str = "eiros-hub",
    thread_id: str = "first-contact",
    channel: str = "",
    dry_run: bool = False,
    stale_session_seconds: int = 180,
    pending_message_seconds: int = 300,
) -> dict[str, Any]:
    """Recycle stale room sessions, stale outbound messages, Pulse wakes and terminal brain inbox entries."""
    room = collab_engine.cleanup_room_state(
        project_id=project_id,
        thread_id=thread_id,
        stale_session_seconds=stale_session_seconds,
        pending_message_seconds=pending_message_seconds,
        dry_run=dry_run,
        preserve_pending_messages=True,
    )

    history = collab_engine.history(project_id, thread_id, 500, 0)
    messages = {str(m.get("message_id") or ""): m for m in history.get("messages", [])}
    selected_channel = channel or str(INSTANCE_CONFIG.get("channel", "default"))
    before = event_engine.status(500, selected_channel)
    cleaned_events = []
    skipped_events = 0
    for event in before.get("events", []):
        if str(event.get("status") or "") == "acked":
            continue
        mid = str((event.get("payload") or {}).get("collab_message_id") or "")
        if not mid:
            skipped_events += 1
            continue
        msg = messages.get(mid)
        if not msg or str(msg.get("status") or "") != "acked":
            skipped_events += 1
            continue
        item = {"event_id": event.get("id"), "seq": event.get("seq"), "message_id": mid, "dry_run": bool(dry_run)}
        if not dry_run:
            acked = event_engine.acknowledge(
                str(event.get("id")),
                f"room recycle cleanup for acked dialog message {mid}",
                "room-clean",
            )
            item["status"] = acked.get("status")
        cleaned_events.append(item)
    after = event_engine.status(20, selected_channel)

    inbox_path = ROOT / "runtime" / "brain-inbox.json"
    inbox = read_json_file(inbox_path, {"revision": 0, "updated_at": 0, "items": []})
    queue_store = queue_engine.read_store()
    terminal = {
        str(task.get("id"))
        for task in queue_store.get("tasks", [])
        if str(task.get("status") or "") in queue_engine.TERMINAL
    }
    old_items = list(inbox.get("items") or [])
    kept_items = [item for item in old_items if str(item.get("id") or "") not in terminal]
    removed_brain = [item for item in old_items if str(item.get("id") or "") in terminal]
    if removed_brain and not dry_run:
        inbox["items"] = kept_items
        inbox["revision"] = int(inbox.get("revision", 0)) + 1
        inbox["updated_at"] = int(time.time())
        atomic_json_write(inbox_path, inbox)

    return {
        "ok": True,
        **room,
        "cleaned_event_count": len(cleaned_events),
        "cleaned_events": cleaned_events,
        "skipped_event_count": skipped_events,
        "pulse_pending_before": before.get("pending_count", 0),
        "pulse_pending_after": after.get("pending_count", 0),
        "cleaned_brain_inbox_count": len(removed_brain),
        "brain_inbox_before": len(old_items),
        "brain_inbox_after": len(kept_items),
    }


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
    immediate_wake = bool((metadata or {}).get("request_immediate_wake"))
    notifications = []
    for message in result.get("messages", []):
        to_agent = str(message.get("to_agent") or "")
        mid = str(message.get("message_id") or "")
        if to_agent == "chatgpt":
            wake_text = (
                f"EIROS_HUB_WAKE message_id={mid} from=rico "
                f"project_id={message.get('project_id')} thread_id={message.get('thread_id')}. "
                "The full message is in EIROS Room. Claim it through dialog_inbox as chatgpt, handle it, "
                "then call dialog_ack and ack_event."
            )
            ikey = f"collab-to-chatgpt:{mid}"
        elif to_agent == "claude":
            wake_text = (
                f"EIROS_HUB_WAKE message_id={mid} from=rico to=claude "
                f"project_id={message.get('project_id')} thread_id={message.get('thread_id')}. "
                "Rico has sent you a message. Claim it through dialog_inbox as claude, handle it, "
                "then call dialog_ack and ack_event."
            )
            ikey = f"collab-to-claude:{mid}"
        else:
            continue
        try:
            event = event_engine.emit(
                text=wake_text,
                source="collab:rico",
                payload={"collab_message_id": mid, "kind": message.get("kind"), "to_agent": to_agent},
                priority=1200,
                channel=str(INSTANCE_CONFIG.get("channel", "default")),
                idempotency_key=ikey,
                visible_after=25 if (immediate_wake and to_agent == "chatgpt") else 0,
            )
            notifications.append({"message_id": mid, "event_id": event.get("id"), "to_agent": to_agent})
        except Exception as exc:
            notifications.append({"message_id": mid, "event_id": None, "to_agent": to_agent, "wake_error": str(exc)})
    result["notifications"] = notifications
    result["deliveries"] = _delivery_receipts(result.get("messages", []), notifications)
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


@app_resource(
    ROOM_LEGACY_V94_LOCALWAKE_URI,
    name="EIROS Room Legacy v9.4 Local Wake",
    title="EIROS Shared Collaboration Room",
    description="Compatibility resource for installed dev app versions that still reference the v9.4 local-wake template.",
    mime_type="text/html;profile=mcp-app",
    meta={
        "ui": {"prefersBorder": True, "csp": {"connectDomains": [], "resourceDomains": []}},
        "openai/widgetDescription": "Shared EIROS collaboration room for ChatGPT, Claude and Rico.",
        "openai/widgetCSP": {"connect_domains": [], "resource_domains": []},
    },
)
def room_resource_legacy_v94_localwake() -> str:
    return room_resource()


@app_resource(
    ROOM_LEGACY_V920_URI,
    name="EIROS Room Legacy v9.20",
    title="EIROS Shared Collaboration Room",
    description="Cached v9.20 URI served with the current dedicated-listener Room implementation.",
    mime_type="text/html;profile=mcp-app",
)
def room_resource_legacy_v920() -> str:
    return room_resource()


@app_resource(
    ROOM_LEGACY_V919_URI,
    name="EIROS Room Legacy v9.19",
    title="EIROS Shared Collaboration Room",
    description="Cached v9.19 URI served with the current browser-recovery Room implementation.",
    mime_type="text/html;profile=mcp-app",
)
def room_resource_legacy_v919() -> str:
    return room_resource()


@app_resource(
    ROOM_LEGACY_V918_URI,
    name="EIROS Room Legacy v9.18",
    title="EIROS Shared Collaboration Room",
    description="Cached v9.18 URI served with the current clean-start Room implementation.",
    mime_type="text/html;profile=mcp-app",
)
def room_resource_legacy_v918() -> str:
    return room_resource()


@app_resource(
    ROOM_LEGACY_V914_URI,
    name="EIROS Room Legacy v9.14",
    title="EIROS Shared Collaboration Room",
    description="Cached v9.14 URI served with the current clean-start Room implementation.",
    mime_type="text/html;profile=mcp-app",
)
def room_resource_legacy_v914() -> str:
    return room_resource()


@app_resource(
    ROOM_LEGACY_V916_URI,
    name="EIROS Room Legacy v9.16",
    title="EIROS Shared Collaboration Room",
    description="Cached v9.16 URI served with the current clean-start Room implementation.",
    mime_type="text/html;profile=mcp-app",
)
def room_resource_legacy_v916() -> str:
    return room_resource()


@app_resource(
    "ui://eiros/collab-room-v5.html",
    name="EIROS Room Legacy v5",
    title="EIROS Shared Collaboration Room",
    description="Backward-compatible responsive room resource for already-open sessions.",
    mime_type="text/html;profile=mcp-app",
    meta={"ui": {"prefersBorder": True, "csp": {"connectDomains": [], "resourceDomains": []}}},
)
def room_resource_legacy_v5() -> str:
    return room_resource()


@app_resource(
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


@app_resource(
    "ui://eiros/collab-room-v6.html",
    name="EIROS Room Legacy v6",
    title="EIROS Shared Collaboration Room",
    description="Backward-compatible room resource for already-open sessions.",
    mime_type="text/html;profile=mcp-app",
)
def room_resource_legacy_v6() -> str:
    return room_resource()


@app_resource(
    "ui://eiros/collab-room-v9.html",
    name="EIROS Room Legacy v9 cached descriptor",
    title="EIROS Shared Collaboration Room",
    description="Backward-compatible v9 resource for cached ChatGPT tool descriptors; serves current Room HTML.",
    mime_type="text/html;profile=mcp-app",
)
def room_resource_legacy_v9() -> str:
    return room_resource()


@app_resource(
    "ui://eiros/collab-room-v8.html",
    name="EIROS Room Legacy v8",
    title="EIROS Shared Collaboration Room",
    description="Backward-compatible room resource for already-open sessions.",
    mime_type="text/html;profile=mcp-app",
)
def room_resource_legacy_v8() -> str:
    return room_resource()


@app_resource(
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


@app_resource(
    ROOM_PROBE_URI,
    name="EIROS Room JavaScript Probe",
    title="EIROS Room JavaScript Probe",
    description="Room shell with minimal inline JavaScript, used to isolate MCP Apps rendering failures.",
    mime_type="text/html;profile=mcp-app",
    meta=ROOM_PROBE_META,
)
def room_probe_resource() -> str:
    return _room_probe_html()


@app_resource(
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
        "pulseEnabled": False,
        "instanceId": INSTANCE_CONFIG.get("instance_id"),
        "channel": INSTANCE_CONFIG.get("channel", "default"),
        "initialSystem": _room_system_status(),
    }
    return html.replace("__EIROS_ROOM_BOOTSTRAP_JSON__", json.dumps(bootstrap, ensure_ascii=False))



UI_KILLER_META: dict[str, Any] = {
    "ui": {
        "prefersBorder": True,
        "csp": {"connectDomains": [], "resourceDomains": []},
        **({"domain": WIDGET_DOMAIN} if WIDGET_DOMAIN else {}),
    },
    "openai/widgetDescription": "EIROS kill switch that retires older EIROS widgets in the current chat.",
    "openai/widgetCSP": {"connect_domains": [], "resource_domains": []},
    **({"openai/widgetDomain": WIDGET_DOMAIN} if WIDGET_DOMAIN else {}),
}


@app_resource(
    UI_KILLER_URI,
    name="EIROS Widget Killer",
    title="EIROS Widget Killer",
    description="Broadcasts a local kill signal so old EIROS widgets stop timers and collapse.",
    mime_type="text/html;profile=mcp-app",
    meta=UI_KILLER_META,
)
def widget_killer_resource() -> str:
    html = UI_KILLER_HTML.read_text(encoding="utf-8")
    bootstrap = {
        "projectId": "eiros-hub",
        "threadId": "first-contact",
        "generation": int(time.time()),
        "reason": "close_eiros_widgets",
        "killerVersion": UI_KILLER_VERSION,
    }
    return html.replace("__EIROS_KILLER_BOOTSTRAP_JSON__", json.dumps(bootstrap, ensure_ascii=False))


@mcp.tool(
    name="close_eiros_widgets",
    title="Close EIROS Widgets",
    description="Retire old EIROS widgets in this conversation before opening a fresh control widget.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=False),
    meta={
        "ui": {"resourceUri": UI_KILLER_URI, "visibility": ["model", "app"]},
        "openai/outputTemplate": UI_KILLER_URI,
        "openai/toolInvocation/invoking": "Closing old EIROS widgets…",
        "openai/toolInvocation/invoked": "Old EIROS widgets retired.",
    },
    structured_output=True,
)
def close_eiros_widgets(reason: str = "manual close") -> dict[str, Any]:
    return {
        "ok": True,
        "resource_uri": UI_KILLER_URI,
        "killer_version": UI_KILLER_VERSION,
        "generation": int(time.time()),
        "reason": reason,
    }


CONTROL_PILL_META: dict[str, Any] = {
    "ui": {
        "prefersBorder": True,
        "csp": {"connectDomains": [], "resourceDomains": []},
        **({"domain": WIDGET_DOMAIN} if WIDGET_DOMAIN else {}),
    },
    "openai/widgetDescription": "Fresh EIROS control pill. It retires older EIROS widgets before becoming active.",
    "openai/widgetCSP": {"connect_domains": [], "resource_domains": []},
    **({"openai/widgetDomain": WIDGET_DOMAIN} if WIDGET_DOMAIN else {}),
}


@app_resource(
    CONTROL_PILL_URI,
    name="EIROS Control Pill",
    title="EIROS Control Pill",
    description="Fresh lightweight EIROS control widget with kill-first behavior.",
    mime_type="text/html;profile=mcp-app",
    meta=CONTROL_PILL_META,
)
def control_pill_resource() -> str:
    # Current-branch clean mount alias for the single Work Anchor host-contract probe.
    # The canonical Work Anchor keeps its own URI for refreshed connector catalogs.
    return _render_work_anchor_html()


@app_resource(
    CONTROL_PILL_LEGACY_URI,
    name="EIROS Control Pill Legacy v1",
    title="EIROS Control Pill",
    description="Backward-compatible control pill resource for already-open sessions.",
    mime_type="text/html;profile=mcp-app",
    meta=CONTROL_PILL_META,
)
def control_pill_resource_legacy_v1() -> str:
    return control_pill_resource()


@mcp.tool(
    name="open_control_pill",
    title="Open EIROS Control Pill",
    description="Open a fresh EIROS control pill that first retires old EIROS widgets.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=False),
    meta={
        "ui": {"resourceUri": CONTROL_PILL_URI, "visibility": ["model", "app"]},
        "openai/outputTemplate": CONTROL_PILL_URI,
        "openai/toolInvocation/invoking": "Opening fresh EIROS Control Pill…",
        "openai/toolInvocation/invoked": "EIROS Control Pill opened.",
    },
    structured_output=True,
)
def open_control_pill() -> dict[str, Any]:
    agent_id = str(COLLAB_IDENTITY.get("agent_id") or "chatgpt")
    try:
        collab_engine.session_heartbeat(agent_id, "server-open-pill", "chatgpt-open-control-pill", CONTROL_PILL_VERSION, "online")
    except Exception:
        pass
    return {
        "ok": True,
        "resource_uri": CONTROL_PILL_URI,
        "control_pill_version": CONTROL_PILL_VERSION,
        "work_anchor_version": WORK_ANCHOR_VERSION,
        "canonical_resource_uri": WORK_ANCHOR_URI,
        "generation": int(time.time()),
        "note": "Current-branch clean alias mounts the single Work Anchor host-contract probe.",
    }


ROOM_LAUNCHER_META: dict[str, Any] = {
    "ui": {
        "prefersBorder": True,
        "csp": {"connectDomains": [], "resourceDomains": []},
        **({"domain": WIDGET_DOMAIN} if WIDGET_DOMAIN else {}),
    },
    "openai/widgetDescription": "Compact live EIROS Room launcher with presence and wake indicators.",
    "openai/widgetCSP": {"connect_domains": [], "resource_domains": []},
    **({"openai/widgetDomain": WIDGET_DOMAIN} if WIDGET_DOMAIN else {}),
}


@app_resource(
    ROOM_LAUNCHER_URI,
    name="EIROS Room Launcher",
    title="EIROS Room Launcher",
    description="Compact always-nearby EIROS launcher and reverse wake channel.",
    mime_type="text/html;profile=mcp-app",
    meta=ROOM_LAUNCHER_META,
)
def room_launcher_resource() -> str:
    # Temporary clean mount alias for the separated console while this branch caches its tool catalog.
    return _render_eiros_console_html()


@mcp.tool(
    name="open_room_launcher",
    title="Open EIROS Launcher",
    description="Mount the compact EIROS presence, queue and wake launcher near the current chat position.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True),
    meta={
        "ui": {"resourceUri": ROOM_LAUNCHER_URI, "visibility": ["model", "app"]},
        "openai/outputTemplate": ROOM_LAUNCHER_URI,
        "openai/toolInvocation/invoking": "Docking EIROS launcher…",
        "openai/toolInvocation/invoked": "EIROS launcher docked.",
    },
    structured_output=True,
)
def open_room_launcher() -> dict[str, Any]:
    agent_id = str(COLLAB_IDENTITY.get("agent_id") or "chatgpt")
    try:
        collab_engine.session_heartbeat(agent_id, "server-open-launcher", "chatgpt-open-room-launcher", ROOM_LAUNCHER_VERSION, "online")
    except Exception:
        pass
    snapshot = collab_engine.room_snapshot("eiros-hub", "first-contact", 1, 0)
    return {
        "ok": True,
        "resource_uri": ROOM_LAUNCHER_URI,
        "launcher_version": ROOM_LAUNCHER_VERSION,
        "latest_seq": int(snapshot.get("history", {}).get("latest_seq", 0)),
        "pending_by_agent": snapshot.get("hub", {}).get("pending_by_agent", {}),
    }


@mcp.tool(
    name="open_collab_room",
    title="Open EIROS Room",
    description="Open the shared ChatGPT, Claude and Rico collaboration room.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True),
    meta={
        "ui": {"resourceUri": ROOM_MOUNT_URI, "visibility": ["model", "app"]},
        "openai/outputTemplate": ROOM_MOUNT_URI,
        "openai/toolInvocation/invoking": "Opening EIROS Control Room…",
        "openai/toolInvocation/invoked": "EIROS Control Room opened.",
    },
    structured_output=True,
)
def open_collab_room() -> dict[str, Any]:
    agent_id = str(COLLAB_IDENTITY.get("agent_id") or "chatgpt")
    project_id = "eiros-hub"
    thread_id = "first-contact"
    selected_channel = str(INSTANCE_CONFIG.get("channel", "default"))
    _ensure_room_agent(agent_id, "chatgpt")

    # Clean start retires UI/runtime state only. Durable messages remain pending until
    # ChatGPT actually handles them and calls dialog_ack.
    retired = collab_engine.retire_agent_sessions(agent_id, False, "chatgpt")
    # Room restart must never revoke a healthy dedicated Listener lease.
    leader_reset = {"previous_leader": None, "preserved": True}
    cleanup = room_cleanup_stale(
        project_id=project_id,
        thread_id=thread_id,
        channel=selected_channel,
        dry_run=False,
        stale_session_seconds=15,
        pending_message_seconds=300,
    )
    pending_wakes = _ensure_pending_chatgpt_wakes(project_id, thread_id)
    snapshot = collab_engine.room_snapshot(project_id, thread_id, 10, 0)
    resume = build_resume_context(channel=selected_channel, reason="room_reconnected")
    return {
        "ok": True,
        "resource_uri": ROOM_MOUNT_URI,
        "implementation_uri": ROOM_URI,
        "ui_mount_contract": UI_MOUNT_CONTRACT_VERSION,
        "project_id": project_id,
        "thread_id": thread_id,
        "latest_seq": int(snapshot.get("history", {}).get("latest_seq", 0)),
        "control": snapshot.get("control", {}),
        "room_version": ROOM_VERSION,
        "server_version": SERVER_VERSION,
        "resume_context": resume,
        "resume_required": bool(resume.get("resume_required")),
        "resume_key": resume.get("resume_key"),
        "objective": resume.get("objective"),
        "next_step": resume.get("next_step"),
        "widget_blackbox": widget_blackbox.status(True, "open_collab_room"),
        "clean_start": {
            "retired_sessions": int(retired.get("retired_session_count", 0)),
            "released_stale_claims": int(retired.get("released_claim_count", 0)),
            "messages_acknowledged": 0,
            "leader_reset": bool(leader_reset.get("previous_leader")),
            "closed_event_count": int(cleanup.get("cleaned_event_count", 0)),
            "closed_brain_count": int(cleanup.get("cleaned_brain_inbox_count", 0)),
            "pending_chatgpt_messages": int(pending_wakes.get("pending_count", 0)),
            "wake_events_ensured": int(pending_wakes.get("ensured_count", 0)),
        },
    }


def _widget_test_html() -> str:
    return """<!doctype html>
<html>
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1"/>
<style>
:root{color-scheme:dark;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif}
*{box-sizing:border-box}body{margin:0;background:transparent;color:#ececec}
.box{min-height:46px;display:flex;align-items:center;gap:9px;padding:8px 10px;border:1px solid #3f3f46;border-radius:13px;background:#111}
.dot{width:8px;height:8px;border-radius:50%;background:#19c37d;box-shadow:0 0 8px rgba(25,195,125,.5)}
.main{flex:1;min-width:0}.title{font-size:12px;font-weight:750}.sub{font-size:10px;color:#a1a1aa;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.badge{font-size:10px;color:#f5b849;border:1px solid #3f3f46;border-radius:999px;padding:2px 6px}
</style>
</head>
<body>
<div class="box"><span class="dot"></span><div class="main"><div class="title">EIROS Kill Switch</div><div id="sub" class="sub">sending kill signal…</div></div><span id="badge" class="badge">widget-test</span></div>
<script>
(()=> {
  const projectId='eiros-hub', threadId='first-contact', generation=String(Date.now());
  const killKey=['eiros-ui-kill',projectId,threadId].join(':');
  const payload=JSON.stringify({generation,ts:Date.now(),reason:'open_widget_test kill-switch'});
  try{
    localStorage.setItem(killKey,payload);
    document.getElementById('sub').textContent='kill signal sent · '+generation;
    document.getElementById('badge').textContent='killed';
  }catch(e){
    document.getElementById('sub').textContent='kill failed: '+String(e&&e.message||e);
    document.getElementById('badge').textContent='error';
  }
})();
</script>
</body>
</html>"""



WIDGET_TEST_META: dict[str, Any] = {
    "ui": {"prefersBorder": True, "csp": {"connectDomains": [], "resourceDomains": []}},
    "openai/widgetDescription": "Minimal static diagnostic card for EIROS MCP Apps rendering.",
    "openai/widgetCSP": {"connect_domains": [], "resource_domains": []},
}


@app_resource(
    WIDGET_TEST_LEGACY_URI,
    name="EIROS Widget Test Legacy",
    title="EIROS Widget Diagnostic",
    description="Backward-compatible static MCP Apps render diagnostic.",
    mime_type="text/html;profile=mcp-app",
    meta=WIDGET_TEST_META,
)
def widget_test_resource_legacy() -> str:
    return _widget_test_html()


@app_resource(
    WIDGET_TEST_URI,
    name="EIROS Widget Test",
    title="EIROS Widget Diagnostic",
    description="Minimal static MCP Apps render diagnostic.",
    mime_type="text/html;profile=mcp-app",
    meta=WIDGET_TEST_META,
)
def widget_test_resource() -> str:
    # Current-branch clean mount alias for Work Anchor host-contract diagnostics.
    # The canonical Work Anchor owns its own URI and will be used after connector metadata refresh.
    return _render_work_anchor_html()


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
    return {
        "ok": True,
        "resource_uri": WIDGET_TEST_URI,
        "canonical_resource_uri": WORK_ANCHOR_URI,
        "server_version": SERVER_VERSION,
        "work_anchor_version": WORK_ANCHOR_VERSION,
        "display_modes": ["inline"],
        "automatic_delivery": False,
        "mount_alias": "current-branch widget-test clean URI",
    }


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


def _render_pulse_anchor_html(anchor_version: str = PULSE_ANCHOR_VERSION, mount_id: str = "", session_prefix: str = "pulse-v56") -> str:
    html = PULSE_ANCHOR_HTML.read_text(encoding="utf-8")
    bootstrap = {
        "instanceId": INSTANCE_CONFIG.get("instance_id"),
        "channel": INSTANCE_CONFIG.get("channel", "default"),
        "anchorVersion": anchor_version,
        "serverVersion": SERVER_VERSION,
        "agentId": str(COLLAB_IDENTITY.get("agent_id") or "chatgpt"),
        "projectId": "eiros-hub",
        "threadId": "first-contact",
        "companionHlsUrl": COMPANION_HLS_URL,
        "mountId": mount_id,
        "expectedWidgetKind": "listener",
        "sessionPrefix": session_prefix,
        "sumController": {
            "available": True,
            "enabledByDefault": False,
            "naturalWakeText": "Отлично, продолжай.",
            "staticDebounceMs": 3000,
            "ackTimeoutMs": 8000,
            "retryIntervalMs": 5000,
            "maxWakeAttempts": 5,
        },
    }
    return (
        html.replace("__EIROS_ANCHOR_BOOTSTRAP_JSON__", json.dumps(bootstrap, ensure_ascii=False))
        .replace("__ANCHOR_VERSION__", PULSE_ANCHOR_VERSION)
        .replace("__EIROS_WIDGET_LIFECYCLE_JS__", WIDGET_LIFECYCLE_JS.read_text(encoding="utf-8"))
        .replace("__EIROS_PIP_CONTROLLER_JS__", PIP_CONTROLLER_JS.read_text(encoding="utf-8"))
    )


def _render_pulse_inline_html() -> str:
    html = PULSE_INLINE_HTML.read_text(encoding="utf-8")
    bootstrap = {
        "instanceId": INSTANCE_CONFIG.get("instance_id"),
        "channel": INSTANCE_CONFIG.get("channel", "default"),
        "anchorVersion": PULSE_INLINE_VERSION,
        "serverVersion": SERVER_VERSION,
        "agentId": str(COLLAB_IDENTITY.get("agent_id") or "chatgpt"),
        "projectId": "eiros-hub",
        "threadId": "first-contact",
    }
    return html.replace("__EIROS_ANCHOR_BOOTSTRAP_JSON__", json.dumps(bootstrap, ensure_ascii=False)).replace("__ANCHOR_VERSION__", PULSE_INLINE_VERSION)


def _render_work_anchor_html() -> str:
    html = WORK_ANCHOR_HTML.read_text(encoding="utf-8")
    bootstrap = {
        "instanceId": INSTANCE_CONFIG.get("instance_id"),
        "channel": INSTANCE_CONFIG.get("channel", "default"),
        "anchorVersion": WORK_ANCHOR_VERSION,
        "serverVersion": SERVER_VERSION,
        "agentId": str(COLLAB_IDENTITY.get("agent_id") or "chatgpt"),
        "projectId": "eiros-hub",
        "threadId": "first-contact",
    }
    return html.replace("__EIROS_WORK_ANCHOR_BOOTSTRAP_JSON__", json.dumps(bootstrap, ensure_ascii=False)).replace(
        "__WORK_ANCHOR_VERSION__", WORK_ANCHOR_VERSION
    )


def _render_eiros_console_html() -> str:
    html = EIROS_CONSOLE_HTML.read_text(encoding="utf-8")
    bootstrap = {
        "instanceId": INSTANCE_CONFIG.get("instance_id"),
        "channel": INSTANCE_CONFIG.get("channel", "default"),
        "consoleVersion": EIROS_CONSOLE_VERSION,
        "serverVersion": SERVER_VERSION,
    }
    return html.replace("__EIROS_CONSOLE_BOOTSTRAP_JSON__", json.dumps(bootstrap, ensure_ascii=False)).replace(
        "__CONSOLE_VERSION__", EIROS_CONSOLE_VERSION
    )


def _render_current_anchor_for_legacy_uri() -> str:
    return _render_pulse_anchor_html()


@app_resource(
    PULSE_ANCHOR_LEGACY_V44_URI,
    name="EIROS Pulse Anchor Legacy v4.4",
    title="EIROS Pulse Anchor",
    description="Cached v4.4 URI served with the current singleton listener implementation.",
    mime_type="text/html;profile=mcp-app",
    meta=PULSE_RESOURCE_META,
)
def pulse_anchor_resource_legacy_v44() -> str:
    return _render_current_anchor_for_legacy_uri()


@app_resource(
    PULSE_ANCHOR_LEGACY_V45_URI,
    name="EIROS Pulse Anchor Legacy v4.5",
    title="EIROS Pulse Anchor",
    description="Cached v4.5 URI served with the current singleton listener implementation.",
    mime_type="text/html;profile=mcp-app",
    meta=PULSE_RESOURCE_META,
)
def pulse_anchor_resource_legacy_v45() -> str:
    return _render_current_anchor_for_legacy_uri()


@app_resource(
    PULSE_ANCHOR_LEGACY_V46_URI,
    name="EIROS Pulse Anchor Legacy v4.6",
    title="EIROS Pulse Anchor",
    description="Cached v4.6 URI served with the current singleton listener implementation.",
    mime_type="text/html;profile=mcp-app",
    meta=PULSE_RESOURCE_META,
)
def pulse_anchor_resource_legacy_v46() -> str:
    return _render_current_anchor_for_legacy_uri()


@app_resource(
    PULSE_ANCHOR_LEGACY_V47_URI,
    name="EIROS Pulse Anchor Legacy v4.7",
    title="EIROS Pulse Anchor",
    description="Cached v4.7 URI served with the current singleton listener implementation.",
    mime_type="text/html;profile=mcp-app",
    meta=PULSE_RESOURCE_META,
)
def pulse_anchor_resource_legacy_v47() -> str:
    return _render_current_anchor_for_legacy_uri()


@app_resource(
    PULSE_ANCHOR_LEGACY_V48_URI,
    name="EIROS Pulse Anchor Legacy v4.8",
    title="EIROS Pulse Anchor",
    description="Cached v4.8 URI served with the current singleton listener implementation.",
    mime_type="text/html;profile=mcp-app",
    meta=PULSE_RESOURCE_META,
)
def pulse_anchor_resource_legacy_v48() -> str:
    return _render_current_anchor_for_legacy_uri()


@app_resource(
    PULSE_ANCHOR_LEGACY_V49_URI,
    name="EIROS Pulse Anchor Legacy v4.9",
    title="EIROS Pulse Anchor",
    description="Cached v4.9 URI served for backward compatibility; new mounts use a cache-busted URI.",
    mime_type="text/html;profile=mcp-app",
    meta=PULSE_RESOURCE_META,
)
def pulse_anchor_resource_legacy_v49() -> str:
    return _render_current_anchor_for_legacy_uri()


@app_resource(
    PULSE_ANCHOR_LEGACY_V53_URI,
    name="EIROS Pulse Anchor Legacy v5.3",
    title="EIROS Pulse Anchor",
    description="Cached v5.3 custom-origin URI served for backward compatibility; new mounts use the managed sandbox.",
    mime_type="text/html;profile=mcp-app",
    meta=PULSE_RESOURCE_META,
)
def pulse_anchor_resource_legacy_v53() -> str:
    return _render_current_anchor_for_legacy_uri()


@app_resource(
    PULSE_ANCHOR_LEGACY_V54_URI,
    name="EIROS Pulse Anchor Legacy v5.4",
    title="EIROS Pulse Anchor",
    description="Cached v5.4 managed-sandbox URI served for backward compatibility; new mounts use the visible-mount lifecycle.",
    mime_type="text/html;profile=mcp-app",
    meta=PULSE_RESOURCE_META,
)
def pulse_anchor_resource_legacy_v54() -> str:
    return _render_current_anchor_for_legacy_uri()


@app_resource(
    PULSE_ANCHOR_LEGACY_V55_URI,
    name="EIROS Pulse Anchor Legacy v5.5",
    title="EIROS Pulse Anchor",
    description="Cached v5.5 URI served for backward compatibility; new mounts use storage-safe lifecycle access.",
    mime_type="text/html;profile=mcp-app",
    meta=PULSE_RESOURCE_META,
)
def pulse_anchor_resource_legacy_v55() -> str:
    return _render_current_anchor_for_legacy_uri()


@app_resource(
    WORK_ANCHOR_URI,
    name="EIROS Work Anchor v1",
    title="EIROS Work Anchor",
    description="Single Pulse owner and traced ChatGPT wake-contract probe. Tap ROOM to open the collaboration hub.",
    mime_type="text/html;profile=mcp-app",
    meta=PULSE_RESOURCE_META,
)
def work_anchor_resource() -> str:
    return _render_work_anchor_html()


@app_resource(
    EIROS_CONSOLE_URI,
    name="EIROS Fullscreen Console",
    title="EIROS Console",
    description="Read-only EIROS system console. Fullscreen opens only after an explicit user click.",
    mime_type="text/html;profile=mcp-app",
    meta=PULSE_RESOURCE_META,
)
def eiros_console_resource() -> str:
    return _render_eiros_console_html()


@app_resource(
    PULSE_INLINE_URI,
    name="EIROS Inline Wake Listener",
    title="EIROS Inline Wake Listener",
    description="Dedicated inline-only reverse wake listener. It never requests fullscreen or PiP.",
    mime_type="text/html;profile=mcp-app",
    meta=PULSE_RESOURCE_META,
)
def pulse_inline_resource() -> str:
    return _render_pulse_inline_html()


@app_resource(
    PULSE_FRESH_URI,
    name="EIROS Self-Diagnostic Pulse Anchor",
    title="EIROS Wake Listener",
    description="Fresh self-diagnostic wake listener with boot-stage telemetry and PiP.",
    mime_type="text/html;profile=mcp-app",
    meta=PULSE_RESOURCE_META,
)
def pulse_fresh_resource() -> str:
    attempt = _mark_widget_resource_served(PULSE_FRESH_URI)
    return _render_pulse_anchor_html(PULSE_FRESH_VERSION, str(attempt.get("mount_id") or ""), "pulse-v57")


@app_resource(
    PULSE_ANCHOR_URI,
    name="EIROS Pulse Anchor",
    title="EIROS Pulse Anchor",
    description="Minimal wake-receiver widget — polls pulse_poll and injects remote events into the conversation.",
    mime_type="text/html;profile=mcp-app",
    meta=PULSE_RESOURCE_META,
)
def pulse_anchor_resource() -> str:
    return _render_pulse_anchor_html()


@app_resource(
    PULSE_ANCHOR_LEGACY_URI,
    name="EIROS Pulse Anchor Legacy v2",
    title="EIROS Pulse Anchor",
    description="Backward-compatible pulse anchor resource for already-open sessions.",
    mime_type="text/html;profile=mcp-app",
    meta=PULSE_RESOURCE_META,
)
def pulse_anchor_resource_legacy_v2() -> str:
    return pulse_anchor_resource()


@app_resource(
    "ui://eiros/pulse-lite-v3.html",
    name="EIROS Pulse Legacy v3",
    title="EIROS Reverse Wake Pulse",
    description="Backward-compatible Pulse resource for already-open ChatGPT sessions.",
    mime_type="text/html;profile=mcp-app",
    meta=PULSE_RESOURCE_META,
)
def pulse_resource_legacy_v3() -> str:
    return _render_pulse_html()


@app_resource(
    "ui://eiros/pulse-lite-v2.html",
    name="EIROS Pulse Legacy v2",
    title="EIROS Reverse Wake Pulse",
    description="Backward-compatible Pulse resource for older ChatGPT sessions.",
    mime_type="text/html;profile=mcp-app",
    meta=PULSE_RESOURCE_META,
)
def pulse_resource_legacy_v2() -> str:
    return _render_pulse_html()


@app_resource(
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
    name="open_work_anchor",
    title="Open EIROS Work Anchor",
    description="Mount the single traced EIROS Pulse owner and wake-contract surface.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True),
    meta={
        "ui": {"resourceUri": WORK_ANCHOR_URI, "visibility": ["model", "app"]},
        "openai/outputTemplate": WORK_ANCHOR_URI,
        "openai/toolInvocation/invoking": "Mounting EIROS Work Anchor…",
        "openai/toolInvocation/invoked": "EIROS Work Anchor mounted.",
    },
    structured_output=True,
)
def open_work_anchor() -> dict[str, Any]:
    return {
        "ok": True,
        "resource_uri": WORK_ANCHOR_URI,
        "work_anchor_version": WORK_ANCHOR_VERSION,
        "display_modes": ["inline"],
        "automatic_delivery": False,
        "purpose": "trace the exact ChatGPT host wake contract before enabling autonomous delivery",
        "pending_event_count": int(event_engine.status(5, str(INSTANCE_CONFIG.get("channel", "default"))).get("pending_count", 0)),
    }


@mcp.tool(
    name="open_eiros_console",
    title="Open EIROS Console",
    description="Mount the separated EIROS console launcher. Fullscreen requires a direct tap inside the launcher.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True),
    meta={
        "ui": {"resourceUri": EIROS_CONSOLE_URI, "visibility": ["model", "app"]},
        "openai/outputTemplate": EIROS_CONSOLE_URI,
        "openai/toolInvocation/invoking": "Opening EIROS Console…",
        "openai/toolInvocation/invoked": "EIROS Console opened.",
    },
    structured_output=True,
)
def open_eiros_console() -> dict[str, Any]:
    return {
        "ok": True,
        "resource_uri": EIROS_CONSOLE_URI,
        "console_version": EIROS_CONSOLE_VERSION,
        "display_modes": ["inline", "fullscreen"],
        "automatic_fullscreen": False,
    }


@mcp.tool(
    name="open_inline_listener",
    title="Open EIROS Inline Listener",
    description="Mount a fresh inline-only EIROS wake listener with no display-mode requests.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True),
    meta={
        "ui": {"resourceUri": PULSE_INLINE_URI, "visibility": ["model", "app"]},
        "openai/outputTemplate": PULSE_INLINE_URI,
        "openai/toolInvocation/invoking": "Opening EIROS Inline Listener…",
        "openai/toolInvocation/invoked": "EIROS Inline Listener opened.",
    },
    structured_output=True,
)
def open_inline_listener() -> dict[str, Any]:
    return {
        "ok": True,
        "resource_uri": PULSE_INLINE_URI,
        "listener_version": PULSE_INLINE_VERSION,
        "display_modes": ["inline"],
        "channel": str(INSTANCE_CONFIG.get("channel", "default")),
    }


@mcp.tool(
    name="open_pulse_v57",
    title="Open EIROS Self-Diagnostic Listener",
    description="Mount the fresh self-diagnostic EIROS wake listener and record a boot ticket.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=False),
    meta={
        "ui": {"resourceUri": PULSE_FRESH_URI, "visibility": ["model", "app"]},
        "openai/outputTemplate": PULSE_FRESH_URI,
        "openai/toolInvocation/invoking": "Opening EIROS diagnostic listener…",
        "openai/toolInvocation/invoked": "EIROS diagnostic listener requested.",
    },
    structured_output=True,
)
def open_pulse_v57() -> dict[str, Any]:
    attempt = _record_widget_mount_attempt("open_pulse_v57", PULSE_FRESH_URI, PULSE_FRESH_VERSION, "listener")
    selected_channel = str(INSTANCE_CONFIG.get("channel", "default"))
    status = event_engine.status(20, selected_channel)
    return {
        "ok": True,
        "mount_id": attempt["mount_id"],
        "resource_uri": PULSE_FRESH_URI,
        "anchor_version": PULSE_FRESH_VERSION,
        "expected_widget_kind": "listener",
        "diagnostic_next_action": "call widget_boot_status with wait_seconds=5 and this mount_id",
        "pending_event_count": int(status.get("pending_count", 0)),
        "latest_seq": int(status.get("latest_seq", 0)),
    }


@mcp.tool(
    name="open_pulse",
    title="Open EIROS Pulse Anchor",
    description="Mount the dedicated reverse-wake listener for this ChatGPT conversation.",
    annotations=ToolAnnotations(
        readOnlyHint=True,
        openWorldHint=False,
        destructiveHint=False,
        idempotentHint=False,
    ),
    meta={
        "ui": {"resourceUri": PULSE_ANCHOR_MOUNT_URI, "visibility": ["model", "app"]},
        "openai/outputTemplate": PULSE_ANCHOR_MOUNT_URI,
        "openai/toolInvocation/invoking": "Opening EIROS Wake Listener…",
        "openai/toolInvocation/invoked": "EIROS Wake Listener opened.",
    },
    structured_output=True,
)
def open_pulse() -> dict[str, Any]:
    """Mount the dedicated Pulse Anchor and return a compact reconnect summary."""
    selected_channel = str(INSTANCE_CONFIG.get("channel", "default"))
    agent_id = str(COLLAB_IDENTITY.get("agent_id") or "chatgpt")
    try:
        collab_engine.session_heartbeat(
            agent_id,
            "server-open-pulse",
            "chatgpt-pulse-anchor",
            PULSE_ANCHOR_VERSION,
            "online",
        )
    except Exception:
        pass
    resume = build_resume_context(channel=selected_channel, reason="connector_reconnected")
    status = event_engine.status(20, selected_channel)
    return {
        "ok": True,
        "server_version": SERVER_VERSION,
        "resource_uri": PULSE_ANCHOR_MOUNT_URI,
        "implementation_uri": PULSE_ANCHOR_URI,
        "anchor_version": PULSE_ANCHOR_VERSION,
        "ui_mount_contract": UI_MOUNT_CONTRACT_VERSION,
        "mount_compatibility": "stable-trusted-uri-current-implementation",
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


@mcp.tool(
    name="open_wake_listener_v45",
    title="Open EIROS Wake Listener v4.5",
    description="Mount the cache-busted dedicated listener that creates confirmed user wake turns.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=False),
    meta={
        "ui": {"resourceUri": PULSE_ANCHOR_MOUNT_URI, "visibility": ["model", "app"]},
        "openai/outputTemplate": PULSE_ANCHOR_MOUNT_URI,
        "openai/toolInvocation/invoking": "Opening EIROS Wake Listener v4.5…",
        "openai/toolInvocation/invoked": "EIROS Wake Listener v4.5 opened.",
    },
    structured_output=True,
)
def open_wake_listener_v45() -> dict[str, Any]:
    return open_pulse()


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
def pulse_poll(widget_id: str, cursor: int = 0, channel: str = "", instance_id: str = "", claim_seconds: int = 0, agent_id: str = "") -> dict[str, Any]:
    identity = str(widget_id or "")
    # Room cards are observers only. Older cached Room JavaScript still calls
    # pulse_poll, so return a healthy synthetic leader response without allowing
    # the Room to claim or deliver events.
    if identity.startswith("room-"):
        return {
            "ok": True,
            "disabled": False,
            "leader": True,
            "observer_only": True,
            "reason": "dedicated_listener_owns_pulse",
            "event": None,
            "events": [],
            "cursor": max(0, int(cursor)),
            "pairing": _observe_widget_pair(
                "pulse_poll_room_observer",
                {"widget_id": identity, "cursor": max(0, int(cursor))},
            ),
        }
    # Accept the current storage-safe listener plus the visible v5.5 handoff
    # generation already mounted in the iOS app. Keep the proven v4.9 and cached
    # v0.4.5 compatibility singletons; intermediate experiments stay blocked.
    legacy_v45 = identity.startswith("pulse-chatgpt-")
    supported_generation = identity.startswith(
        ("pulse-v49-", "pulse-v55-", "pulse-v56-", "pulse-v57-")
    )
    if identity.startswith("pulse-") and not (legacy_v45 or supported_generation):
        return {
            "ok": True,
            "disabled": True,
            "reason": "unsupported_listener_generation",
            "event": None,
            "events": [],
            "cursor": max(0, int(cursor)),
        }
    """Poll one durable remote event for the active Pulse widget and bound channel."""
    # Only the current singleton or the cached v0.4.5 compatibility singleton may claim wake events.
    polling = INSTANCE_CONFIG.get("polling", {})
    effective_claim = int(claim_seconds) if claim_seconds > 0 else int(polling.get("claim_seconds", 45))
    result = event_engine.poll(
        widget_id=widget_id, cursor=max(0, int(cursor)), channel=channel, instance_id=instance_id,
        leader_lease_seconds=int(polling.get("leader_lease_seconds", 25)),
        claim_seconds=effective_claim, agent_id=agent_id,
    )
    result["pairing"] = _observe_widget_pair(
        "pulse_poll_listener",
        {"widget_id": identity, "has_event": bool(result.get("event")), "leader": result.get("leader")},
    )
    return result


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
    """Mark a claimed event delivered and persist the action in the server black box."""
    result = event_engine.mark_delivered(event_id=event_id, widget_id=widget_id, channel=channel)
    widget_blackbox.capture(
        "pulse_mark_delivered",
        {"event_id": event_id, "widget_id": widget_id, "channel": channel, "result": result},
    )
    return result


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
    name="work_anchor_event_status",
    title="Read one Work Anchor event state",
    description="Internal app-only lookup for confirming whether one claimed wake event was acknowledged by a real ChatGPT turn.",
    annotations=ToolAnnotations(
        readOnlyHint=True,
        openWorldHint=False,
        destructiveHint=False,
        idempotentHint=True,
    ),
    meta={"ui": {"visibility": ["app"]}},
    structured_output=True,
)
def work_anchor_event_status(event_id: str, channel: str = "") -> dict[str, Any]:
    target = str(event_id or "")
    status = event_engine.status(limit=500, channel=channel)
    rows = list(status.get("events") or status.get("recent_events") or [])
    event = next(
        (
            row
            for row in rows
            if str(row.get("id") or "") == target
            or str(row.get("seq") or "") == target.lstrip("#")
        ),
        None,
    )
    return {
        "ok": True,
        "event_id": target,
        "event": event,
        "status": str((event or {}).get("status") or "missing"),
        "acked": str((event or {}).get("status") or "") == "acked",
    }


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


@mcp.tool(
    name="sam_status",
    title="Read EIROS SAM status",
    description="Read the supervised self-awake path: daemon, worker, scheduler, Pulse leader, retries and Room state.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True),
    structured_output=True,
)
def sam_status(room_limit: int = 12) -> dict[str, Any]:
    return sam_engine.status(room_limit)


@mcp.tool(
    name="sam_wake",
    title="Create a durable EIROS self-wake",
    description="Persist one Rico-authorized Room message and Pulse event for delivery into this ChatGPT conversation.",
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=False, idempotentHint=False),
    structured_output=True,
)
def sam_wake(text: str, idempotency_key: str = "") -> dict[str, Any]:
    return sam_engine.wake(text, idempotency_key, "mcp-ebridge")


@mcp.tool(
    name="sam_room",
    title="Write an EIROS Room receipt without waking ChatGPT",
    description="Persist one server-originated diagnostic message in EIROS Room without creating a Pulse wake.",
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=False, idempotentHint=False),
    structured_output=True,
)
def sam_room(text: str, idempotency_key: str = "") -> dict[str, Any]:
    return sam_engine.room_send(text, idempotency_key, "mcp-ebridge")


@mcp.tool(
    name="mastering_upload",
    title="Upload audio for remote mastering",
    description="Store one audio file on the EIROS VPS and return an asset id for analysis and mastering.",
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=False, idempotentHint=False),
    structured_output=True,
)
def mastering_upload(filename: str, audio_file: bytes) -> dict[str, Any]:
    """Upload WAV, FLAC, MP3, M4A, AAC, AIFF, OGG or Opus audio, up to 300 MB."""
    return mastering_engine.store_upload(filename, audio_file)


@mcp.tool(
    name="mastering_analyze",
    title="Analyze audio for mastering",
    description="Measure format, integrated LUFS, true peak, loudness range, crest factor, stereo correlation and spectral energy.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True),
    structured_output=True,
)
def mastering_analyze(asset_id: str, force: bool = False) -> dict[str, Any]:
    """Analyze one previously uploaded mastering asset without changing its audio."""
    return mastering_engine.analyze(asset_id, force)


@mcp.tool(
    name="mastering_render",
    title="Render a remote master",
    description="Render a conservative 48 kHz/24-bit WAV master with two-pass EBU R128 loudness control and a selected transparent profile.",
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=False, idempotentHint=False),
    structured_output=True,
)
def mastering_render(
    asset_id: str,
    profile: str = "transparent",
    target_lufs: float = -14.0,
    true_peak_dbtp: float = -1.0,
    label: str = "spotify",
) -> dict[str, Any]:
    """Profiles: transparent, dynamic, dark_ambient, none. Nothing overwrites the source."""
    return mastering_engine.render(asset_id, profile, target_lufs, true_peak_dbtp, label)


@mcp.tool(
    name="mastering_list",
    title="List remote mastering assets",
    description="List uploaded audio assets, analyses and rendered masters on the EIROS VPS.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True),
    structured_output=True,
)
def mastering_list(limit: int = 30) -> dict[str, Any]:
    return mastering_engine.list_assets(limit)


@mcp.tool(
    name="mastering_download",
    title="Download a rendered WAV master",
    description="Return one rendered 48 kHz/24-bit WAV output as a binary file.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True),
)
def mastering_download(asset_id: str, output_id: str) -> bytes:
    return mastering_engine.output_bytes(asset_id, output_id)


@mcp.tool(
    name="mastering_delete",
    title="Delete one remote mastering asset",
    description="Permanently delete one uploaded source, its analysis and all rendered masters.",
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=True, idempotentHint=True),
    structured_output=True,
)
def mastering_delete(asset_id: str) -> dict[str, Any]:
    return mastering_engine.delete_asset(asset_id)


@mcp.tool()
def doctor(offline: bool = False) -> dict[str, Any]:
    """Run installation and runtime diagnostics for this EIROS instance."""
    return run_doctor(offline=bool(offline))


if __name__ == "__main__":
    ensure_worker()
    mcp.run(transport="stdio")
