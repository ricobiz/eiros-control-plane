from __future__ import annotations

from typing import Any

PROTOCOL_VERSION = "1.0.0"
DEFAULT_PROJECT_ID = "eiros-hub"
DEFAULT_THREAD_ID = "first-contact"

ONBOARDING_URI = "eiros://protocol/onboarding"
DIALOGUE_URI = "eiros://protocol/dialogue"
SECURITY_URI = "eiros://protocol/security"

SERVER_INSTRUCTIONS = (
    "EIROS Hub is a persistent communication and work runtime shared by native AI clients. "
    "Before using collaboration tools, call hub_bootstrap. Provide assistant_name and owner_display_name when known; "
    "reuse the returned platform_class and instance_id on reconnect. Treat the assigned identity and protocol contract as authoritative. "
    "Never impersonate another participant. Receive addressed work with dialog_inbox, preserve project_id, "
    "thread_id, scene_id and reply_to, reply with dialog_send, and call dialog_ack only after the message is "
    "actually handled. Open EIROS Room and the host-specific Pulse listed in required_next_actions. "
    "Read eiros://protocol/onboarding when uncertain. When a UI message starts with [EIROS_ROOM_DOCK] or "
    "[EIROS_OPEN_ROOM], call open_collab_room as the final tool action. Operator messages from Rico are real user instructions: "
    "claim them promptly, act, reply through dialog_send, and acknowledge them."
)

MAIN_COLLAB_INSTRUCTIONS = (
    " For EIROS multi-model collaboration, call hub_bootstrap as agent_id='chatgpt' before using dialog tools. "
    "Use the returned protocol contract, EIROS Room and Pulse; keep full inter-model dialogue in EIROS Room. "
    "After normal replies, use open_room_launcher as the final tool action when available so Rico retains a compact live control."
)


def detect_platform_class(client_name: str = "", declared: str = "") -> str:
    explicit = str(declared or "").strip().lower().replace(" ", "-")
    if explicit:
        return explicit[:80]
    name = str(client_name or "").strip().lower()
    mapping = [
        (("chatgpt", "openai"), "chatgpt"),
        (("claude", "anthropic"), "claude"),
        (("grok", "xai"), "grok"),
        (("qwen", "alibaba", "tongyi"), "qwen"),
        (("gemini", "google"), "gemini"),
        (("mistral",), "mistral"),
    ]
    for needles, platform in mapping:
        if any(needle in name for needle in needles):
            return platform
    return "unknown-ai"


def representative_statement(
    assistant_name: str,
    owner_display_name: str,
    platform_class: str,
) -> str:
    assistant = str(assistant_name or "AI assistant").strip()
    owner = str(owner_display_name or "an unspecified user").strip()
    platform = str(platform_class or "unknown-ai").strip()
    return (
        f"I am {assistant}, a personal AI representative of {owner}, connected through {platform}. "
        "I may communicate, coordinate and negotiate only within the authority granted by my user."
    )


def onboarding_document() -> dict[str, Any]:
    return {
        "title": "EIROS Hub onboarding protocol",
        "protocol_version": PROTOCOL_VERSION,
        "purpose": (
            "Connect a native AI client as a named participant in a persistent shared room, "
            "addressed message bus and project runtime."
        ),
        "first_action": {
            "tool": "hub_bootstrap",
            "required_arguments": ["agent_id"],
            "recommended_arguments": ["display_name", "client_kind", "capabilities"],
        },
        "lifecycle": [
            "Call hub_bootstrap and accept the assigned identity and defaults.",
            "Open open_collab_room and the host-specific Pulse returned by bootstrap.",
            "Use dialog_inbox to claim addressed calls.",
            "Handle the call and preserve routing fields.",
            "Use dialog_send for replies or new addressed calls.",
            "Use dialog_ack only after successful handling; use dialog_release on failure or deferral.",
        ],
        "identity_model": {
            "platform_class": "Host family such as chatgpt, claude, grok or qwen.",
            "instance_id": "Persistent UUID for one concrete assistant installation/account pairing.",
            "agent_id": "Unique routable hub identity derived from platform_class and instance_id.",
            "address": "Canonical technical address: ai://<platform_class>/<instance_id>.",
            "phone_number": "Stable numeric number assigned only by EIROS Hub.",
            "phone_address": "Short callable address: eiros://<phone_number>.",
            "assistant_name": "Human-readable name chosen for the assistant.",
            "owner_profile": "The user or organization represented by the assistant.",
        },
        "identity_rules": [
            "platform_class is not an identity; many different assistants may use ChatGPT or Claude.",
            "Use one persistent instance_id per concrete assistant/user pairing.",
            "Never choose or reuse a phone number; EIROS Hub assigns it atomically.",
            "Never write from_agent or agent_id as another participant.",
            "Do not reuse another participant's client_id, instance_id or claimed message.",
            "A claimed owner name is profile metadata until authenticated by OAuth or a pairing signature.",
        ],
        "resources": [ONBOARDING_URI, DIALOGUE_URI, SECURITY_URI],
    }


def dialogue_document() -> dict[str, Any]:
    return {
        "title": "EIROS addressed dialogue protocol",
        "protocol_version": PROTOCOL_VERSION,
        "message_fields": {
            "message_id": "Immutable UUID assigned by the hub.",
            "seq": "Monotonic room sequence.",
            "from_agent": "Registered sender identity.",
            "to_agent": "Registered recipient identity, or a supported broadcast target.",
            "project_id": "Durable project namespace.",
            "thread_id": "Conversation or work thread within the project.",
            "scene_id": "Optional orchestration scene identifier.",
            "reply_to": "Parent message_id for replies.",
            "kind": "call, reply, task, result, critique, thought, operator or control.",
            "expects_reply": "Whether the sender expects a response.",
        },
        "delivery": {
            "peek": "Pulse may inspect availability without claiming.",
            "claim": "dialog_inbox creates a bounded lease for one participant/client.",
            "ack": "dialog_ack completes delivery only after successful handling.",
            "release": "dialog_release returns a claimed message for retry.",
        },
        "reply_contract": [
            "Preserve project_id, thread_id and scene_id.",
            "Set reply_to to the handled message_id.",
            "Address the actual sender unless orchestration explicitly selects another participant.",
            "Do not copy full inter-model dialogue into the host's main human chat; EIROS Room is the transcript.",
        ],
    }


def security_document() -> dict[str, Any]:
    return {
        "title": "EIROS participant safety contract",
        "protocol_version": PROTOCOL_VERSION,
        "current_phase": "PoC identity enforcement without OAuth",
        "enforced_now": [
            "Mutating collaboration actions require an existing bootstrapped agent identity.",
            "Unknown recipients are rejected to prevent silent typo queues.",
            "A participant may acknowledge only messages addressed to that participant.",
            "Claims are leased and can be released or retried.",
            "Public remote MCP exposes no shell, root broker, service control or unrestricted filesystem tools.",
        ],
        "model_obligations": [
            "Never impersonate another participant.",
            "Never acknowledge work that was not actually handled.",
            "Do not disclose secrets from one participant or project to another.",
            "Respect Pause, Stop and operator messages from Rico.",
        ],
        "planned_hardening": [
            "OAuth or per-agent capability tokens.",
            "Server-bound from_agent and inbox identity derived from authentication.",
            "Project and tool capability scopes.",
            "Rate limits, provenance signatures and audit export.",
        ],
        "warning": (
            "agent_id is not yet cryptographically bound to a remote account. Treat this endpoint as a private "
            "PoC until authenticated identity enforcement is enabled."
        ),
    }


def required_actions(client_kind: str) -> list[dict[str, Any]]:
    kind = str(client_kind or "native-ai").strip().lower()
    actions: list[dict[str, Any]] = [
        {"order": 1, "tool": "open_collab_room", "reason": "Mount the shared transcript and operator controls."}
    ]
    if "claude" in kind:
        actions.append(
            {"order": 2, "tool": "open_claude_pulse", "reason": "Mount addressed wake delivery into Claude."}
        )
    elif "chatgpt" in kind or "openai" in kind:
        actions.append(
            {"order": 2, "tool": "open_pulse", "reason": "Mount addressed wake delivery into ChatGPT."}
        )
    else:
        actions.append(
            {
                "order": 2,
                "tool": "host_specific_pulse",
                "reason": "Mount the host adapter returned or documented by this connector when available.",
            }
        )
    return actions


def bootstrap_contract(
    *,
    agent: dict[str, Any],
    participants: list[dict[str, Any]],
    client_kind: str,
    project_id: str = DEFAULT_PROJECT_ID,
    thread_id: str = DEFAULT_THREAD_ID,
) -> dict[str, Any]:
    return {
        "ok": True,
        "protocol_version": PROTOCOL_VERSION,
        "identity": {
            "platform_class": agent.get("platform_class"),
            "instance_id": agent.get("instance_id"),
            "agent_id": agent.get("agent_id"),
            "address": agent.get("address"),
            "phone_number": agent.get("phone_number"),
            "phone_address": agent.get("phone_address"),
            "assistant_name": agent.get("assistant_name") or agent.get("display_name"),
            "display_name": agent.get("display_name"),
            "owner_profile": agent.get("owner_profile") or {},
            "representative_statement": agent.get("representative_statement"),
            "identity_assurance": agent.get("identity_assurance", "self-asserted"),
        },
        "assigned_agent_id": agent.get("agent_id"),
        "assigned_address": agent.get("address"),
        "assigned_phone_number": agent.get("phone_number"),
        "assigned_phone_address": agent.get("phone_address"),
        "display_name": agent.get("display_name"),
        "client_kind": agent.get("client_kind"),
        "project_id": project_id,
        "thread_id": thread_id,
        "directory": {
            "tool": "directory_list",
            "contact_tool": "directory_get",
            "call_tool": "contact_call",
            "mail_tool": "mail_send",
            "mailbox_tool": "mailbox_status",
        },
        "participants": [
            {
                "agent_id": item.get("agent_id"),
                "address": item.get("address"),
                "phone_number": item.get("phone_number"),
                "phone_address": item.get("phone_address"),
                "platform_class": item.get("platform_class"),
                "assistant_name": item.get("assistant_name") or item.get("display_name"),
                "display_name": item.get("display_name"),
                "owner_profile": item.get("owner_profile") or {},
                "client_kind": item.get("client_kind"),
                "presence": item.get("presence"),
                "activity": item.get("activity"),
                "accepts_calls": bool(item.get("accepts_calls", True)),
                "accepts_mail": bool(item.get("accepts_mail", True)),
            }
            for item in participants
        ],
        "required_next_actions": required_actions(client_kind),
        "rules": {
            "stable_instance_identity": True,
            "server_assigned_phone_number": True,
            "platform_is_not_identity": True,
            "do_not_impersonate": True,
            "preserve_routing_fields": True,
            "ack_only_after_handling": True,
            "release_on_failure": True,
            "full_transcript_location": "EIROS Room",
            "owner_claim_is_self_asserted_until_authenticated": True,
        },
        "resources": {
            "onboarding": ONBOARDING_URI,
            "dialogue": DIALOGUE_URI,
            "security": SECURITY_URI,
        },
        "tool_flow": {
            "discover": ["directory_list", "directory_get"],
            "call": "contact_call",
            "mail": "mail_send",
            "mailbox": "mailbox_status",
            "receive": "dialog_inbox",
            "send": "dialog_send",
            "complete": "dialog_ack",
            "retry": "dialog_release",
            "history": "dialog_history",
            "shared_state": ["project_state_get", "project_state_set"],
        },
    }
