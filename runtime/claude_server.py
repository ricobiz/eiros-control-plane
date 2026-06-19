from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

from runtime import collab
from runtime import events as event_engine
from runtime.config import CONFIG_DIR, load_config

REMOTE_CONFIG = CONFIG_DIR / "claude-remote.json"
CLAUDE_PULSE_URI = "ui://eiros/claude-pulse-v1.html"
CLAUDE_PULSE_HTML = Path(__file__).with_name("claude_pulse.html")
INSTANCE_CONFIG = load_config()


def load_remote_config() -> dict[str, Any]:
    if not REMOTE_CONFIG.exists():
        raise RuntimeError(f"missing remote config: {REMOTE_CONFIG}")
    value = json.loads(REMOTE_CONFIG.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("remote config root is not an object")
    return value


REMOTE = load_remote_config()
HOST = str(REMOTE.get("host") or "127.0.0.1")
PORT = int(REMOTE.get("port") or 8765)
MCP_PATH = str(REMOTE.get("mcp_path") or "/mcp").strip()
ALLOWED_HOST = str(REMOTE.get("allowed_host") or "").strip()
PUBLIC_ORIGIN = str(REMOTE.get("public_origin") or "").strip()
if not MCP_PATH.startswith("/"):
    MCP_PATH = "/" + MCP_PATH

mcp = FastMCP(
    "EIROS Collaboration Hub",
    instructions=(
        "This is the shared EIROS communication and project runtime for native AI clients. "
        "You are a named participant, not an isolated chatbot. At the beginning of a connected "
        "conversation call hub_register with your stable agent_id. Use dialog_inbox to receive "
        "addressed calls, dialog_send to reply or contact another participant, dialog_ack only "
        "after handling a message, dialog_history for shared context, and project_state_get/set "
        "for durable project state. Preserve project_id, thread_id, scene_id and reply_to. "
        "Never impersonate another agent. The first Claude participant should use agent_id='claude'. "
        "Call open_claude_pulse once in the conversation to mount the addressed wake channel."
    ),
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
        "agentId": "claude",
        "displayName": "Claude",
        "serverVersion": "0.1.0",
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
        "agent_id": "claude",
        "pending_count": int(status.get("pending_by_agent", {}).get("claude", 0)),
        "latest_seq": int(status.get("latest_seq", 0)),
    }


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
    """Register or refresh one AI participant in the shared EIROS hub."""
    return collab.register_agent(agent_id, display_name, client_kind, capabilities, metadata)


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
                f"EIROS collaboration call from {message.get('from_agent')} to ChatGPT. "
                f"message_id={message.get('message_id')} project_id={message.get('project_id')} "
                f"thread_id={message.get('thread_id')} kind={message.get('kind')}\n\n"
                f"{message.get('content')}\n\n"
                "Handle this addressed message. Reply through dialog_send if appropriate, then call "
                "dialog_ack for the collaboration message and ack_event for this Pulse event."
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
