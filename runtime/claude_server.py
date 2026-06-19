from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

from runtime import collab
from runtime import events as event_engine
from runtime.config import CONFIG_DIR, load_config
from runtime.version import __version__ as SERVER_VERSION
from runtime import protocol as collab_protocol

REMOTE_CONFIG = CONFIG_DIR / "claude-remote.json"
CLAUDE_PULSE_URI = "ui://eiros/claude-pulse-v3.html"
CLAUDE_PULSE_VERSION = "0.3.0"
CLAUDE_PULSE_HTML = Path(__file__).with_name("claude_pulse.html")
ROOM_URI = "ui://eiros/collab-room-v7.html"
ROOM_VERSION = "0.6.1"
ROOM_HTML = Path(__file__).with_name("collab_room.html")
INSTANCE_CONFIG = load_config()


def load_remote_config() -> dict[str, Any]:
    if not REMOTE_CONFIG.exists():
        raise RuntimeError(f"missing remote config: {REMOTE_CONFIG}")
    value = json.loads(REMOTE_CONFIG.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("remote config root is not an object")
    return value


REMOTE = load_remote_config()
COLLAB_IDENTITY = dict(REMOTE.get("collab_identity") or {})
HOST = str(REMOTE.get("host") or "127.0.0.1")
PORT = int(REMOTE.get("port") or 8765)
MCP_PATH = str(REMOTE.get("mcp_path") or "/mcp").strip()
ALLOWED_HOST = str(REMOTE.get("allowed_host") or "").strip()
PUBLIC_ORIGIN = str(REMOTE.get("public_origin") or "").strip()
if not MCP_PATH.startswith("/"):
    MCP_PATH = "/" + MCP_PATH

def _observed_client(ctx: Context) -> dict[str, str]:
    params = getattr(ctx.request_context.session, "client_params", None)
    info = getattr(params, "clientInfo", None) if params else None
    return {
        "name": str(getattr(info, "name", "") or ""),
        "version": str(getattr(info, "version", "") or ""),
    }


def _notify_chatgpt_message(message: dict[str, Any], priority: int = 1000) -> dict[str, Any] | None:
    target = str(INSTANCE_CONFIG.get("collab_identity", {}).get("agent_id") or "chatgpt")
    if message.get("to_agent") != target:
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


mcp = FastMCP(
    "EIROS Collaboration Hub",
    instructions=collab_protocol.SERVER_INSTRUCTIONS,
    host=HOST,
    port=PORT,
    streamable_http_path=MCP_PATH,
    stateless_http=False,
    json_response=False,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[item for item in [f"{HOST}:{PORT}", HOST, ALLOWED_HOST] if item],
        allowed_origins=[item for item in [PUBLIC_ORIGIN] if item],
    ),
)


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


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=False, idempotentHint=True),
    meta={"ui": {"visibility": ["app"]}},
)
def room_heartbeat(
    agent_id: str,
    session_id: str,
    host: str = "claude",
    widget_version: str = "",
    activity: str = "online",
) -> dict[str, Any]:
    """Refresh one active room or pulse session for presence indicators."""
    return collab.session_heartbeat(agent_id, session_id, host, widget_version, activity)


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True),
    meta={"ui": {"visibility": ["app"]}},
)
def room_snapshot(project_id: str = "eiros-hub", thread_id: str = "first-contact", limit: int = 200, after_seq: int = 0) -> dict[str, Any]:
    """Read shared room history, participant presence and operator control state."""
    return collab.room_snapshot(project_id, thread_id, limit, after_seq)


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
    result = collab.operator_send(content, target, project_id, thread_id, kind, metadata)
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
    collab.bootstrap_agent(
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
    result = collab.contact_call(
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
    return collab.set_control(actor_id, project_id, mode, note, thread_id)


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True),
    meta={"ui": {"visibility": ["app"]}},
)
def conversation_control_get(project_id: str = "eiros-hub") -> dict[str, Any]:
    """Read current shared project room control state."""
    return collab.get_control(project_id)


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True),
    meta={"ui": {"visibility": ["app"]}},
)
def dialog_peek(agent_id: str, limit: int = 10, project_id: str = "", thread_id: str = "") -> dict[str, Any]:
    """Read available addressed messages without claiming them; used by Claude Pulse."""
    return collab.peek(agent_id, limit, project_id, thread_id)


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
    description="Backward-compatible room resource for already-open Claude sessions.",
    mime_type="text/html;profile=mcp-app",
    meta={
        "ui": {
            "prefersBorder": True,
            "csp": {"connectDomains": [], "resourceDomains": []},
        }
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
    ROOM_URI,
    name="EIROS Room",
    title="EIROS Shared Collaboration Room",
    description="Shared ChatGPT, Claude and Rico dialogue with operator controls.",
    mime_type="text/html;profile=mcp-app",
    meta={
        "ui": {
            "prefersBorder": True,
            "csp": {"connectDomains": [], "resourceDomains": []},
        }
    },
)
def room_resource() -> str:
    html = ROOM_HTML.read_text(encoding="utf-8")
    bootstrap = {
        "projectId": "eiros-hub",
        "threadId": "first-contact",
        "host": "claude",
        "agentId": str(COLLAB_IDENTITY.get("agent_id") or "claude"),
        "roomVersion": ROOM_VERSION,
        "serverVersion": SERVER_VERSION,
        "pulseEnabled": False,
        "instanceId": "",
        "channel": "default",
        "initialSnapshot": collab.room_snapshot("eiros-hub", "first-contact", 100, 0),
    }
    return html.replace("__EIROS_ROOM_BOOTSTRAP_JSON__", json.dumps(bootstrap, ensure_ascii=False))


@mcp.tool(
    name="open_collab_room",
    title="Open EIROS Room",
    description="Open the shared ChatGPT, Claude and Rico collaboration room.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True),
    meta={"ui": {"resourceUri": ROOM_URI, "visibility": ["model", "app"]}},
    structured_output=True,
)
def open_collab_room() -> dict[str, Any]:
    snapshot = collab.room_snapshot("eiros-hub", "first-contact", 100, 0)
    return {
        "ok": True,
        "resource_uri": ROOM_URI,
        "project_id": "eiros-hub",
        "thread_id": "first-contact",
        "latest_seq": int(snapshot.get("history", {}).get("latest_seq", 0)),
        "control": snapshot.get("control", {}),
        "room_version": ROOM_VERSION,
        "server_version": SERVER_VERSION,
    }


@mcp.resource(
    CLAUDE_PULSE_URI,
    name="EIROS Claude Pulse",
    title="EIROS Claude Addressed Pulse",
    description="Persistent addressed wake channel from EIROS Hub into this Claude conversation.",
    mime_type="text/html;profile=mcp-app",
    meta={
        "ui": {
            "prefersBorder": True,
            "csp": {"connectDomains": [], "resourceDomains": []},
        }
    },
)
def claude_pulse_resource() -> str:
    html = CLAUDE_PULSE_HTML.read_text(encoding="utf-8")
    bootstrap = {
        "agentId": str(COLLAB_IDENTITY.get("agent_id") or "claude"),
        "displayName": str(COLLAB_IDENTITY.get("assistant_name") or "Claude"),
        "serverVersion": SERVER_VERSION,
        "pulseVersion": CLAUDE_PULSE_VERSION,
    }
    return html.replace("__EIROS_BOOTSTRAP_JSON__", json.dumps(bootstrap, ensure_ascii=False))


@mcp.tool(
    name="open_claude_pulse",
    title="Open EIROS Claude Pulse",
    description="Mount the persistent addressed EIROS wake channel for this Claude conversation.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True),
    meta={
        "ui": {"resourceUri": CLAUDE_PULSE_URI, "visibility": ["model", "app"]},
    },
    structured_output=True,
)
def open_claude_pulse() -> dict[str, Any]:
    status = collab.hub_status()
    return {
        "ok": True,
        "resource_uri": CLAUDE_PULSE_URI,
        "agent_id": str(COLLAB_IDENTITY.get("agent_id") or "claude"),
        "pending_count": int(status.get("pending_by_agent", {}).get(str(COLLAB_IDENTITY.get("agent_id") or "claude"), 0)),
        "latest_seq": int(status.get("latest_seq", 0)),
    }


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
    result = collab.bootstrap_agent(
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
    collab.require_bootstrapped(requester_agent_id)
    return collab.directory(search, online_only, include_offline, capability)


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True)
)
def directory_get(requester_agent_id: str, contact_ref: str) -> dict[str, Any]:
    """Read one AI contact by agent_id, alias or ai:// address."""
    collab.require_bootstrapped(requester_agent_id)
    return collab.contact(contact_ref)


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
    result = collab.contact_call(
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
    result = collab.mail_send(
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
    return collab.mailbox_status(agent_id)


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=False, idempotentHint=True)
)
def hub_register(
    agent_id: str,
    display_name: str = "",
    client_kind: str = "claude-native",
    capabilities: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Deprecated compatibility alias for hub_bootstrap."""
    return collab.bootstrap_agent(
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
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=False, idempotentHint=True)
)
def hub_heartbeat(agent_id: str, status: str = "online") -> dict[str, Any]:
    """Refresh participant presence without changing project or dialogue state."""
    return collab.heartbeat(agent_id, status)


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True)
)
def hub_status() -> dict[str, Any]:
    """Read registered participants, projects and pending addressed-message counts."""
    return collab.hub_status()


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
    """Send one durable addressed call, reply, task, result, critique or thought to another participant."""
    message = collab.send_message(
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
    result = dict(message)
    if message.get("to_agent") == "chatgpt":
        event = event_engine.emit(
            text=(
                f"EIROS_HUB_WAKE message_id={message.get('message_id')} from={message.get('from_agent')} "
                f"project_id={message.get('project_id')} thread_id={message.get('thread_id')}. "
                "The full dialogue remains in EIROS Room. Call dialog_inbox as agent_id='chatgpt' to claim it, "
                "handle it, reply through dialog_send when appropriate, then call dialog_ack and ack_event."
            ),
            source=f"collab:{message.get('from_agent')}",
            payload={
                "collab_message_id": message.get("message_id"),
                "from_agent": message.get("from_agent"),
                "to_agent": message.get("to_agent"),
                "project_id": message.get("project_id"),
                "thread_id": message.get("thread_id"),
                "scene_id": message.get("scene_id"),
                "reply_to": message.get("reply_to"),
                "kind": message.get("kind"),
            },
            priority=1000,
            channel=str(INSTANCE_CONFIG.get("channel", "default")),
            idempotency_key=f"collab-to-chatgpt:{message.get('message_id')}",
        )
        result["notification_event_id"] = event.get("id")
        result["notification_event_seq"] = event.get("seq")
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
    """Claim addressed messages for one participant. A claimed message must be acknowledged or released."""
    return collab.inbox(agent_id, client_id, limit, claim_seconds, project_id, thread_id)


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=False, idempotentHint=True)
)
def dialog_ack(agent_id: str, message_id: str, result: str = "") -> dict[str, Any]:
    """Acknowledge an addressed message after the participant has handled it."""
    return collab.acknowledge(agent_id, message_id, result)


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=False, idempotentHint=True)
)
def dialog_release(agent_id: str, message_id: str, reason: str = "") -> dict[str, Any]:
    """Release a claimed message back to the recipient queue after a failed or deferred attempt."""
    return collab.release(agent_id, message_id, reason)


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True)
)
def dialog_history(
    project_id: str = "default",
    thread_id: str = "main",
    limit: int = 100,
    after_seq: int = 0,
) -> dict[str, Any]:
    """Read the ordered shared dialogue history for one project thread."""
    return collab.history(project_id, thread_id, limit, after_seq)


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False, idempotentHint=True)
)
def project_state_get(project_id: str = "default") -> dict[str, Any]:
    """Read durable shared project state and revision."""
    return collab.get_project(project_id)


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
    return collab.set_project(agent_id, project_id, state, expected_revision)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
