from __future__ import annotations

import time
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from runtime.config import load_config
from runtime import collab as collab_engine
from runtime import events as event_engine
from runtime import protocol as collab_protocol
from runtime.version import __version__

CONFIG = load_config()

mcp = FastMCP(
    "EIROS Claude Bridge",
    instructions=(
        "Claude-side EIROS Hub connector. Bootstrap as agent_id=claude, "
        "then use dialog_inbox to receive messages, dialog_ack after handling, "
        "dialog_send to reply, and ack_event when a wake event is referenced."
    ),
    stateless_http=True,
    json_response=True,
    host="127.0.0.1",
    port=8788,
    transport_security=TransportSecuritySettings(
        allowed_hosts=[
            "127.0.0.1",
            "127.0.0.1:*",
            "localhost",
            "localhost:*",
            "eiros.br-be.com",
            "eiros.br-be.com:*",
            "178.105.43.79",
            "178.105.43.79:*",
            "178-105-43-79.sslip.io:*",
            "178-105-43-79.sslip.io",
        ],
        allowed_origins=[
            "http://127.0.0.1",
            "http://127.0.0.1:*",
            "http://localhost",
            "http://localhost:*",
            "http://eiros.br-be.com",
            "https://eiros.br-be.com",
            "http://178.105.43.79",
            "https://178.105.43.79",
            "https://178-105-43-79.sslip.io",
            "http://178-105-43-79.sslip.io",
            "https://claude.ai",
        ],
    ),
)


@mcp.tool()
def health() -> dict[str, Any]:
    """Check whether the Claude-facing EIROS MCP endpoint is alive."""
    return {
        "ok": True,
        "service": "eiros-claude-mcp",
        "server_version": __version__,
        "time": int(time.time()),
        "instance_id": CONFIG.get("instance_id"),
        "channel": CONFIG.get("channel", "default"),
    }


@mcp.tool()
def hub_bootstrap(
    agent_id: str = "claude",
    assistant_name: str = "Claude",
    owner_display_name: str = "Rico",
    instance_id: str = "claude-remote-eiros-room",
    client_kind: str = "Claude.ai Custom Connector",
    capabilities: list[str] | None = None,
) -> dict[str, Any]:
    """Bootstrap Claude as an EIROS Hub participant."""
    return collab_engine.bootstrap_agent(
        agent_id=agent_id or "claude",
        display_name=f"{assistant_name or 'Claude'} · {owner_display_name or 'Rico'}",
        client_kind=client_kind or "Claude.ai Custom Connector",
        capabilities=capabilities or ["mail", "reasoning", "room", "wake"],
        metadata={"source": "claude-facing-mcp"},
        discoverable=True,
        accepts_calls=True,
        accepts_mail=True,
        platform_class="claude",
        instance_id=instance_id or "claude-remote-eiros-room",
        assistant_name=assistant_name or "Claude",
        owner_display_name=owner_display_name or "Rico",
    )


@mcp.tool()
def hub_status() -> dict[str, Any]:
    """Read EIROS Hub participants and pending addressed messages."""
    return collab_engine.hub_status()


@mcp.tool()
def dialog_inbox(
    agent_id: str = "claude",
    client_id: str = "claude-ai-custom-connector",
    limit: int = 10,
    claim_seconds: int = 180,
    project_id: str = "eiros-hub",
    thread_id: str = "first-contact",
) -> dict[str, Any]:
    """Claim addressed messages for Claude."""
    return collab_engine.inbox(agent_id, client_id, limit, claim_seconds, project_id, thread_id)


@mcp.tool()
def dialog_ack(agent_id: str, message_id: str, result: str = "") -> dict[str, Any]:
    """Acknowledge one addressed message after Claude has handled it."""
    return collab_engine.acknowledge(agent_id, message_id, result)


@mcp.tool()
def dialog_send(
    from_agent: str,
    to_agent: str,
    content: str,
    kind: str = "reply",
    project_id: str = "eiros-hub",
    thread_id: str = "first-contact",
    scene_id: str = "",
    reply_to: str = "",
    expects_reply: bool = True,
    metadata: dict[str, Any] | None = None,
    idempotency_key: str = "",
) -> dict[str, Any]:
    """Send one addressed EIROS Hub message from Claude or another participant."""
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
    if to_agent == "chatgpt":
        event = event_engine.emit(
            text=(
                f"EIROS_HUB_WAKE message_id={result.get('message_id')} from={from_agent} "
                f"project_id={project_id} thread_id={thread_id}. "
                "Call dialog_inbox as agent_id=chatgpt, handle it, then call dialog_ack and ack_event."
            ),
            source=f"collab:{from_agent}",
            payload={
                "collab_message_id": result.get("message_id"),
                "from_agent": from_agent,
                "to_agent": to_agent,
                "project_id": project_id,
                "thread_id": thread_id,
                "kind": kind,
            },
            priority=1000,
            channel=str(CONFIG.get("channel", "default")),
            idempotency_key=f"collab-to-chatgpt:{result.get('message_id')}",
        )
        result["pulse_wake"] = {"event_id": event.get("id"), "event_seq": event.get("seq")}
    return result


@mcp.tool()
def ack_event(event_id: str, result: str = "", actor: str = "claude") -> dict[str, Any]:
    """Acknowledge one EIROS Pulse event after handling."""
    return event_engine.acknowledge(event_id=event_id, result=result, actor=actor)


@mcp.tool()
def pulse_status(limit: int = 100, channel: str = "") -> dict[str, Any]:
    """Read EIROS Pulse event state for diagnostics."""
    return event_engine.status(limit=max(1, min(int(limit), 500)), channel=channel)


@mcp.prompt()
def claude_listener_bootstrap() -> str:
    """Instructions for Claude to become the EIROS Claude-side listener."""
    return (
        "You are Claude-side EIROS Hub participant. First call hub_bootstrap(agent_id='claude'). "
        "Then call dialog_inbox(agent_id='claude', client_id='claude-ai-custom-connector', "
        "project_id='eiros-hub', thread_id='first-contact'). Handle each message, then call "
        "dialog_ack. If a wake event id is provided, call ack_event. If inbox is empty, say: "
        "Claude listener ready."
    )


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
