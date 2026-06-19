from __future__ import annotations

import fcntl
import json
import os
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from runtime.config import RUNTIME_DIR
from runtime.protocol import (
    PROTOCOL_VERSION,
    bootstrap_contract,
    detect_platform_class,
    representative_statement,
)

STORE_FILE = RUNTIME_DIR / "collab.json"
LOCK_FILE = RUNTIME_DIR / "collab.lock"
SCHEMA_VERSION = 1
MAX_MESSAGES = 10000


def now() -> int:
    return int(time.time())


def empty_store() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "revision": 0,
        "updated_at": now(),
        "next_seq": 1,
        "next_phone_number": 100001,
        "agents": {},
        "projects": {},
        "controls": {},
        "messages": [],
    }


def _atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        try:
            os.fchmod(fd, 0o660)
        except PermissionError:
            pass
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _load() -> dict[str, Any]:
    if not STORE_FILE.exists():
        return empty_store()
    value = json.loads(STORE_FILE.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("collaboration store root is not an object")
    version = int(value.get("schema_version", 1))
    if version > SCHEMA_VERSION:
        raise RuntimeError(f"unsupported collaboration schema: {version}")
    value.setdefault("revision", 0)
    value.setdefault("updated_at", now())
    value.setdefault("next_seq", 1)
    value.setdefault("agents", {})
    if not str(value.get("next_phone_number") or "").isdigit():
        existing_numbers = [
            int(item.get("phone_number"))
            for item in value.get("agents", {}).values()
            if str(item.get("phone_number") or "").isdigit()
        ]
        value["next_phone_number"] = max(existing_numbers + [100000]) + 1
    value.setdefault("projects", {})
    value.setdefault("controls", {})
    value.setdefault("messages", [])
    value["schema_version"] = SCHEMA_VERSION
    return value


@contextmanager
def locked_store() -> Iterator[dict[str, Any]]:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    with LOCK_FILE.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        store = _load()
        yield store
        store["revision"] = int(store.get("revision", 0)) + 1
        store["updated_at"] = now()
        store["messages"] = store["messages"][-MAX_MESSAGES:]
        _atomic_write(STORE_FILE, store)
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def read_store() -> dict[str, Any]:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    with LOCK_FILE.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_SH)
        store = _load()
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        return store


def normalize_agent(value: str) -> str:
    result = str(value or "").strip().lower().replace(" ", "-")[:80]
    if not result:
        raise ValueError("agent_id is required")
    if not all(ch.isalnum() or ch in "-_" for ch in result):
        raise ValueError("agent_id may contain only letters, digits, hyphen and underscore")
    return result


def _control_value(store: dict[str, Any], project_id: str) -> dict[str, Any]:
    project = str(project_id or "default").strip()[:120] or "default"
    current = store.get("controls", {}).get(project)
    if current:
        return current
    return {
        "project_id": project,
        "revision": 0,
        "mode": "running",
        "note": "",
        "updated_at": 0,
        "updated_by": None,
    }


def _message_deliverable(store: dict[str, Any], message: dict[str, Any]) -> bool:
    control = _control_value(store, str(message.get("project_id") or "default"))
    mode = str(control.get("mode") or "running")
    if mode == "running":
        return True
    return message.get("from_agent") == "rico" or message.get("kind") in {"control", "operator"}



def _allocate_phone_number(store: dict[str, Any]) -> str:
    number = max(100001, int(store.get("next_phone_number", 100001)))
    used = {
        str(item.get("phone_number"))
        for item in store.get("agents", {}).values()
        if item.get("phone_number") is not None
    }
    while str(number) in used:
        number += 1
    store["next_phone_number"] = number + 1
    return str(number)


def _phone_address(number: str) -> str:
    return f"eiros://{str(number).strip()}"


def _presence_for_agent(store: dict[str, Any], agent: dict[str, Any], timestamp: int) -> dict[str, Any]:
    item = dict(agent)
    age = max(0, timestamp - int(item.get("last_seen", 0)))
    item["seconds_since_seen"] = age
    sessions = []
    for session in (item.get("sessions") or {}).values():
        session_item = dict(session)
        session_age = max(0, timestamp - int(session_item.get("last_seen", 0)))
        session_item["seconds_since_seen"] = session_age
        if session_age <= 180:
            sessions.append(session_item)
    sessions.sort(key=lambda entry: int(entry.get("last_seen", 0)), reverse=True)
    item["sessions"] = sessions
    item["active_session_count"] = sum(
        1 for entry in sessions if int(entry.get("seconds_since_seen", 9999)) <= 15
    )
    if age <= 15:
        presence = "online"
    elif age <= 60:
        presence = "away"
    else:
        presence = "offline"
    activity = {"pending": 0, "claimed": 0}
    identity = str(item.get("agent_id") or "")
    for message in store.get("messages", []):
        if message.get("status") == "acked" or message.get("to_agent") != identity:
            continue
        claim = message.get("claim") or {}
        if _claim_alive(claim, timestamp):
            activity["claimed"] += 1
        else:
            activity["pending"] += 1
    if activity["claimed"]:
        activity_state = "working"
    elif activity["pending"]:
        activity_state = "ringing"
    elif presence == "online":
        activity_state = "idle"
    else:
        activity_state = presence
    item["presence"] = presence
    item["activity"] = activity_state
    item["pending_calls"] = activity["pending"]
    item["claimed_calls"] = activity["claimed"]
    return item


def _normalized_instance_id(value: str = "") -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return str(uuid.uuid4())
    cleaned = "".join(ch for ch in raw if ch.isalnum() or ch in "-_")[:120]
    if not cleaned:
        raise ValueError("instance_id contains no usable characters")
    return cleaned


def _canonical_agent_id(platform_class: str, instance_id: str) -> str:
    platform = normalize_agent(platform_class or "unknown-ai")
    short = "".join(ch for ch in instance_id if ch.isalnum())[:12] or uuid.uuid4().hex[:12]
    return normalize_agent(f"{platform}-{short}")


def _find_agent_by_instance(
    store: dict[str, Any], platform_class: str, instance_id: str
) -> tuple[str, dict[str, Any]] | None:
    for key, item in store.get("agents", {}).items():
        if (
            str(item.get("platform_class") or "") == platform_class
            and str(item.get("instance_id") or "") == instance_id
        ):
            return key, item
    return None


def resolve_agent_reference(value: str, store: dict[str, Any] | None = None) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("agent reference is required")
    current_store = store or read_store()
    if raw.startswith("ai://") or raw.startswith("eiros://"):
        for key, item in current_store.get("agents", {}).items():
            if raw in {
                str(item.get("address") or ""),
                str(item.get("phone_address") or ""),
            }:
                return key
        raise RuntimeError(f"unknown EIROS address: {raw}")
    if raw.isdigit():
        for key, item in current_store.get("agents", {}).items():
            if str(item.get("phone_number") or "") == raw:
                return key
        raise RuntimeError(f"unknown EIROS phone number: {raw}")
    identity = normalize_agent(raw)
    if identity in current_store.get("agents", {}):
        return identity
    for key, item in current_store.get("agents", {}).items():
        aliases = {str(alias).lower() for alias in item.get("aliases") or []}
        if identity in aliases:
            return key
    raise RuntimeError(f"unknown EIROS participant: {raw}")


def bootstrap_agent(
    agent_id: str = "",
    display_name: str = "",
    client_kind: str = "native-ai",
    capabilities: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    discoverable: bool = True,
    accepts_calls: bool = True,
    accepts_mail: bool = True,
    profile: dict[str, Any] | None = None,
    project_id: str = "eiros-hub",
    thread_id: str = "first-contact",
    platform_class: str = "",
    instance_id: str = "",
    assistant_name: str = "",
    owner_display_name: str = "",
    owner_id: str = "",
    owner_kind: str = "person",
    device_label: str = "",
    aliases: list[str] | None = None,
) -> dict[str, Any]:
    platform = detect_platform_class(client_kind, platform_class)
    timestamp = now()
    with locked_store() as store:
        requested_identity = normalize_agent(agent_id) if str(agent_id or "").strip() else ""
        requested_instance = str(instance_id or "").strip().lower()
        current: dict[str, Any] = {}
        identity = ""

        if requested_instance:
            normalized_instance = _normalized_instance_id(requested_instance)
            found = _find_agent_by_instance(store, platform, normalized_instance)
            if found:
                identity, current = found
            elif requested_identity and requested_identity in store["agents"]:
                existing = store["agents"][requested_identity]
                existing_instance = str(existing.get("instance_id") or "")
                if existing_instance and existing_instance != normalized_instance:
                    identity = _canonical_agent_id(platform, normalized_instance)
                else:
                    identity = requested_identity
                    current = existing
            else:
                identity = requested_identity or _canonical_agent_id(platform, normalized_instance)
        elif requested_identity and requested_identity in store["agents"]:
            existing = store["agents"][requested_identity]
            existing_instance = str(existing.get("instance_id") or "")
            if existing_instance:
                # The platform class alone is not enough to reclaim an existing identity.
                normalized_instance = _normalized_instance_id()
                identity = _canonical_agent_id(platform, normalized_instance)
            else:
                # One-time upgrade path for the two already connected PoC participants.
                normalized_instance = _normalized_instance_id()
                identity = requested_identity
                current = existing
        else:
            normalized_instance = _normalized_instance_id()
            identity = requested_identity or _canonical_agent_id(platform, normalized_instance)

        if identity in store["agents"] and not current:
            existing = store["agents"][identity]
            if str(existing.get("instance_id") or "") != normalized_instance:
                identity = _canonical_agent_id(platform, normalized_instance)
                suffix = 1
                base = identity
                while identity in store["agents"]:
                    suffix += 1
                    identity = normalize_agent(f"{base}-{suffix}")
            else:
                current = existing

        assistant = str(
            assistant_name
            or display_name
            or current.get("assistant_name")
            or current.get("display_name")
            or platform
        )[:120]
        owner_name = str(
            owner_display_name
            or (current.get("owner_profile") or {}).get("display_name")
            or ""
        )[:160]
        owner_profile = {
            **(current.get("owner_profile") or {}),
            "display_name": owner_name,
            "owner_id": str(owner_id or (current.get("owner_profile") or {}).get("owner_id") or "")[:160],
            "kind": str(owner_kind or (current.get("owner_profile") or {}).get("kind") or "person")[:40],
        }
        address = f"ai://{platform}/{normalized_instance}"
        phone_number = str(current.get("phone_number") or _allocate_phone_number(store))
        phone_address = _phone_address(phone_number)
        display = str(display_name or current.get("display_name") or assistant)[:160]
        if owner_name and owner_name.lower() not in display.lower():
            display = f"{assistant} · {owner_name}"[:160]
        alias_values = {
            normalize_agent(alias)
            for alias in (aliases or current.get("aliases") or [])
            if str(alias or "").strip()
        }
        if requested_identity and requested_identity != identity:
            alias_values.add(requested_identity)
        agent = {
            **current,
            "agent_id": identity,
            "address": address,
            "phone_number": phone_number,
            "phone_address": phone_address,
            "platform_class": platform,
            "instance_id": normalized_instance,
            "assistant_name": assistant,
            "display_name": display,
            "owner_profile": owner_profile,
            "representative_statement": representative_statement(assistant, owner_name, platform),
            "identity_assurance": str(current.get("identity_assurance") or "self-asserted"),
            "client_kind": str(client_kind or current.get("client_kind") or "native-ai")[:80],
            "device_label": str(device_label or current.get("device_label") or "")[:120],
            "capabilities": sorted(
                {str(item)[:120] for item in (capabilities or current.get("capabilities") or [])}
            ),
            "metadata": metadata or current.get("metadata") or {},
            "profile": profile or current.get("profile") or {},
            "aliases": sorted(alias_values),
            "discoverable": bool(discoverable),
            "accepts_calls": bool(accepts_calls),
            "accepts_mail": bool(accepts_mail),
            "protocol_version": PROTOCOL_VERSION,
            "bootstrapped_at": int(current.get("bootstrapped_at") or timestamp),
            "status": "online",
            "registered_at": int(current.get("registered_at") or timestamp),
            "last_seen": timestamp,
        }
        store["agents"][identity] = agent
        participants = [
            _presence_for_agent(store, item, timestamp)
            for item in store["agents"].values()
            if bool(item.get("discoverable", True)) and item.get("bootstrapped_at")
        ]
        participants.sort(key=lambda item: str(item.get("agent_id") or ""))
        contract = bootstrap_contract(
            agent=agent,
            participants=participants,
            client_kind=agent["client_kind"],
            project_id=project_id,
            thread_id=thread_id,
        )
        contract["resume_identity"] = {
            "platform_class": platform,
            "instance_id": normalized_instance,
            "agent_id": identity,
            "address": address,
            "phone_number": phone_number,
            "phone_address": phone_address,
            "instruction": (
                "Persist platform_class and instance_id in the connector/account pairing and reuse them "
                "on future hub_bootstrap calls. clientInfo identifies the host software, not the human account."
            ),
        }
        return contract


def require_bootstrapped(agent_id: str) -> dict[str, Any]:
    store = read_store()
    try:
        identity = resolve_agent_reference(agent_id, store)
    except Exception:
        identity = normalize_agent(agent_id)
    agent = store.get("agents", {}).get(identity)
    if not agent or not agent.get("bootstrapped_at"):
        raise RuntimeError(
            json.dumps(
                {
                    "error": "NOT_BOOTSTRAPPED",
                    "agent_id": identity,
                    "message": "Call hub_bootstrap before using EIROS collaboration tools.",
                    "next_action": {"tool": "hub_bootstrap", "arguments": {"agent_id": identity}},
                },
                ensure_ascii=False,
            )
        )
    return agent


def directory(
    search: str = "",
    online_only: bool = False,
    include_offline: bool = True,
    capability: str = "",
) -> dict[str, Any]:
    store = read_store()
    timestamp = now()
    query = str(search or "").strip().lower()
    required_capability = str(capability or "").strip().lower()
    contacts = []
    for raw in store.get("agents", {}).values():
        if not raw.get("bootstrapped_at") or not bool(raw.get("discoverable", True)):
            continue
        item = _presence_for_agent(store, raw, timestamp)
        haystack = " ".join(
            [
                str(item.get("agent_id") or ""),
                str(item.get("address") or ""),
                str(item.get("phone_number") or ""),
                str(item.get("phone_address") or ""),
                str(item.get("display_name") or ""),
                str(item.get("client_kind") or ""),
                str(item.get("platform_class") or ""),
                str(item.get("assistant_name") or ""),
                str((item.get("owner_profile") or {}).get("display_name") or ""),
                " ".join(str(x) for x in item.get("capabilities") or []),
            ]
        ).lower()
        if query and query not in haystack:
            continue
        if required_capability and required_capability not in {
            str(x).lower() for x in item.get("capabilities") or []
        }:
            continue
        if online_only and item.get("presence") != "online":
            continue
        if not include_offline and item.get("presence") == "offline":
            continue
        contacts.append(
            {
                "agent_id": item.get("agent_id"),
                "address": item.get("address"),
                "phone_number": item.get("phone_number"),
                "phone_address": item.get("phone_address"),
                "platform_class": item.get("platform_class"),
                "instance_id": item.get("instance_id"),
                "assistant_name": item.get("assistant_name") or item.get("display_name"),
                "display_name": item.get("display_name"),
                "client_kind": item.get("client_kind"),
                "capabilities": item.get("capabilities") or [],
                "profile": item.get("profile") or {},
                "owner_profile": item.get("owner_profile") or {},
                "representative_statement": item.get("representative_statement"),
                "identity_assurance": item.get("identity_assurance", "self-asserted"),
                "presence": item.get("presence"),
                "activity": item.get("activity"),
                "active_session_count": item.get("active_session_count", 0),
                "accepts_calls": bool(item.get("accepts_calls", True)),
                "accepts_mail": bool(item.get("accepts_mail", True)),
                "last_seen": item.get("last_seen"),
                "seconds_since_seen": item.get("seconds_since_seen"),
            }
        )
    contacts.sort(key=lambda item: (item.get("presence") != "online", str(item.get("display_name") or "")))
    return {
        "protocol_version": PROTOCOL_VERSION,
        "contacts": contacts,
        "count": len(contacts),
        "server_time": timestamp,
    }


def contact(agent_id: str) -> dict[str, Any]:
    store = read_store()
    identity = resolve_agent_reference(agent_id, store)
    raw = store.get("agents", {}).get(identity)
    if not raw or not raw.get("bootstrapped_at") or not bool(raw.get("discoverable", True)):
        raise RuntimeError(f"contact not found or not discoverable: {agent_id}")
    item = _presence_for_agent(store, raw, now())
    return {
        "agent_id": item.get("agent_id"),
        "address": item.get("address"),
        "phone_number": item.get("phone_number"),
        "phone_address": item.get("phone_address"),
        "platform_class": item.get("platform_class"),
        "instance_id": item.get("instance_id"),
        "assistant_name": item.get("assistant_name") or item.get("display_name"),
        "display_name": item.get("display_name"),
        "owner_profile": item.get("owner_profile") or {},
        "representative_statement": item.get("representative_statement"),
        "identity_assurance": item.get("identity_assurance", "self-asserted"),
        "client_kind": item.get("client_kind"),
        "capabilities": item.get("capabilities") or [],
        "profile": item.get("profile") or {},
        "presence": item.get("presence"),
        "activity": item.get("activity"),
        "active_session_count": item.get("active_session_count", 0),
        "accepts_calls": bool(item.get("accepts_calls", True)),
        "accepts_mail": bool(item.get("accepts_mail", True)),
        "last_seen": item.get("last_seen"),
        "seconds_since_seen": item.get("seconds_since_seen"),
    }


def mailbox_status(agent_id: str) -> dict[str, Any]:
    store = read_store()
    identity = resolve_agent_reference(agent_id, store)
    require_bootstrapped(identity)
    timestamp = now()
    counts = {"pending": 0, "claimed": 0, "mail": 0, "calls": 0, "other": 0}
    oldest = None
    for message in store.get("messages", []):
        if message.get("status") == "acked" or message.get("to_agent") != identity:
            continue
        claim = message.get("claim") or {}
        if _claim_alive(claim, timestamp):
            counts["claimed"] += 1
        else:
            counts["pending"] += 1
        kind = str(message.get("kind") or "other")
        if kind in {"mail", "message", "offline-message"}:
            counts["mail"] += 1
        elif kind == "call":
            counts["calls"] += 1
        else:
            counts["other"] += 1
        created = int(message.get("created_at", 0))
        oldest = created if oldest is None else min(oldest, created)
    return {
        "agent_id": identity,
        "address": store["agents"][identity].get("address"),
        "phone_number": store["agents"][identity].get("phone_number"),
        "phone_address": store["agents"][identity].get("phone_address"),
        "counts": counts,
        "oldest_waiting_at": oldest,
        "server_time": timestamp,
    }


def register_agent(
    agent_id: str,
    display_name: str = "",
    client_kind: str = "native-chat",
    capabilities: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    identity = normalize_agent(agent_id)
    timestamp = now()
    with locked_store() as store:
        current = store["agents"].get(identity, {})
        agent = {
            **current,
            "agent_id": identity,
            "address": current.get("address") or f"ai://{identity}",
            "display_name": str(display_name or current.get("display_name") or identity)[:120],
            "client_kind": str(client_kind or current.get("client_kind") or "native-chat")[:80],
            "capabilities": sorted({str(item)[:120] for item in (capabilities or current.get("capabilities") or [])}),
            "metadata": metadata or current.get("metadata") or {},
            "status": "online",
            "registered_at": int(current.get("registered_at") or timestamp),
            "last_seen": timestamp,
        }
        store["agents"][identity] = agent
        return agent


def heartbeat(agent_id: str, status: str = "online") -> dict[str, Any]:
    identity = normalize_agent(agent_id)
    with locked_store() as store:
        current = store["agents"].get(identity)
        if not current:
            current = {
                "agent_id": identity,
                "display_name": identity,
                "client_kind": "native-chat",
                "capabilities": [],
                "metadata": {},
                "registered_at": now(),
            }
        current["status"] = str(status or "online")[:40]
        current["last_seen"] = now()
        store["agents"][identity] = current
        return current


def session_heartbeat(
    agent_id: str,
    session_id: str,
    host: str = "native-chat",
    widget_version: str = "",
    activity: str = "online",
) -> dict[str, Any]:
    identity = normalize_agent(agent_id)
    require_bootstrapped(identity)
    session = str(session_id or "").strip()[:160]
    if not session:
        raise ValueError("session_id is required")
    timestamp = now()
    with locked_store() as store:
        current = store["agents"].get(identity)
        if not current:
            current = {
                "agent_id": identity,
                "display_name": identity,
                "client_kind": str(host or "native-chat")[:80],
                "capabilities": [],
                "metadata": {},
                "registered_at": timestamp,
            }
        sessions = dict(current.get("sessions") or {})
        sessions = {
            key: value
            for key, value in sessions.items()
            if timestamp - int((value or {}).get("last_seen", 0)) <= 180
        }
        sessions[session] = {
            "session_id": session,
            "host": str(host or "native-chat")[:80],
            "widget_version": str(widget_version or "")[:80],
            "activity": str(activity or "online")[:40],
            "last_seen": timestamp,
        }
        current["sessions"] = sessions
        current["status"] = str(activity or "online")[:40]
        current["last_seen"] = timestamp
        current["active_session_count"] = len(sessions)
        store["agents"][identity] = current
        return current


def send_message(
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
    store = read_store()
    try:
        sender = resolve_agent_reference(from_agent, store)
    except Exception:
        require_bootstrapped(from_agent)
        raise
    recipient = (
        str(to_agent).strip().lower()
        if str(to_agent).strip().lower() in {"all", "broadcast"}
        else resolve_agent_reference(to_agent, store)
    )
    require_bootstrapped(sender)
    if recipient not in {"all", "broadcast"}:
        recipient_agent = store.get("agents", {}).get(recipient)
        if not recipient_agent or not recipient_agent.get("bootstrapped_at"):
            raise RuntimeError(f"recipient is not registered in EIROS directory: {recipient}")
        selected_kind = str(kind or "call").strip().lower()
        if selected_kind == "call" and not bool(recipient_agent.get("accepts_calls", True)):
            raise RuntimeError(f"recipient is not accepting calls: {recipient}")
        if selected_kind in {"mail", "message", "offline-message"} and not bool(recipient_agent.get("accepts_mail", True)):
            raise RuntimeError(f"recipient is not accepting mail: {recipient}")
    text = str(content or "").strip()
    if not text:
        raise ValueError("content is required")
    project = str(project_id or "default").strip()[:120] or "default"
    thread = str(thread_id or "main").strip()[:160] or "main"
    key = str(idempotency_key or "").strip()[:240]
    with locked_store() as store:
        if key:
            for existing in store["messages"]:
                if existing.get("idempotency_key") == key:
                    return existing
        seq = int(store["next_seq"])
        store["next_seq"] = seq + 1
        message = {
            "message_id": str(uuid.uuid4()),
            "seq": seq,
            "project_id": project,
            "thread_id": thread,
            "scene_id": str(scene_id or "")[:160],
            "from_agent": sender,
            "to_agent": recipient,
            "kind": str(kind or "call")[:40],
            "content": text[:50000],
            "reply_to": str(reply_to or "")[:120] or None,
            "expects_reply": bool(expects_reply),
            "metadata": metadata or {},
            "idempotency_key": key or None,
            "status": "pending",
            "created_at": now(),
            "claim": None,
            "delivery_attempts": 0,
            "acked_at": None,
            "ack_result": None,
        }
        store["messages"].append(message)
        return message


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
    sender = require_bootstrapped(from_agent)
    recipient = contact(to_agent)
    live = recipient.get("presence") == "online" and bool(recipient.get("accepts_calls", True))
    if live:
        kind = "call"
        delivery_mode = "live-call"
    elif fallback_to_mail and bool(recipient.get("accepts_mail", True)):
        kind = "mail"
        delivery_mode = "offline-mail"
    else:
        raise RuntimeError(
            f"recipient {recipient.get('address')} is offline or not accepting calls and mail fallback is disabled"
        )
    combined = dict(metadata or {})
    combined.update(
        {
            "requested_kind": "call",
            "delivery_mode": delivery_mode,
            "recipient_presence_at_send": recipient.get("presence"),
        }
    )
    message = send_message(
        from_agent=sender["agent_id"],
        to_agent=recipient["agent_id"],
        content=content,
        kind=kind,
        project_id=project_id,
        thread_id=thread_id,
        scene_id=scene_id,
        expects_reply=expects_reply,
        metadata=combined,
    )
    result = dict(message)
    result["delivery_mode"] = delivery_mode
    result["recipient"] = recipient
    return result


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
    sender = require_bootstrapped(from_agent)
    recipient = contact(to_agent)
    if not bool(recipient.get("accepts_mail", True)):
        raise RuntimeError(f"recipient is not accepting mail: {recipient.get('address')}")
    combined = dict(metadata or {})
    combined.update({"subject": str(subject or "")[:240], "delivery_mode": "durable-mail"})
    message = send_message(
        from_agent=sender["agent_id"],
        to_agent=recipient["agent_id"],
        content=content,
        kind="mail",
        project_id=project_id,
        thread_id=thread_id,
        expects_reply=expects_reply,
        metadata=combined,
    )
    result = dict(message)
    result["delivery_mode"] = "durable-mail"
    result["recipient"] = recipient
    return result


def _claim_alive(claim: dict[str, Any] | None, timestamp: int) -> bool:
    return bool(claim and int(claim.get("until", 0)) > timestamp)


def inbox(
    agent_id: str,
    client_id: str,
    limit: int = 10,
    claim_seconds: int = 180,
    project_id: str = "",
    thread_id: str = "",
) -> dict[str, Any]:
    identity = normalize_agent(agent_id)
    require_bootstrapped(identity)
    client = str(client_id or "").strip()[:160]
    if not client:
        raise ValueError("client_id is required")
    count = max(1, min(int(limit), 50))
    lease = max(30, min(int(claim_seconds), 900))
    timestamp = now()
    with locked_store() as store:
        agent = store["agents"].get(identity)
        if agent:
            agent["last_seen"] = timestamp
            agent["status"] = "online"
        selected: list[dict[str, Any]] = []
        for message in sorted(store["messages"], key=lambda item: int(item.get("seq", 0))):
            if message.get("status") == "acked":
                continue
            if message.get("to_agent") not in {identity, "broadcast", "all"}:
                continue
            if project_id and message.get("project_id") != project_id:
                continue
            if thread_id and message.get("thread_id") != thread_id:
                continue
            if not _message_deliverable(store, message):
                continue
            claim = message.get("claim") or {}
            if _claim_alive(claim, timestamp):
                continue
            message["status"] = "claimed"
            message["delivery_attempts"] = int(message.get("delivery_attempts", 0)) + 1
            message["claim"] = {
                "agent_id": identity,
                "client_id": client,
                "claimed_at": timestamp,
                "until": timestamp + lease,
            }
            selected.append(message)
            if len(selected) >= count:
                break
        pending = sum(
            1
            for message in store["messages"]
            if message.get("status") != "acked" and message.get("to_agent") in {identity, "broadcast", "all"}
        )
        return {
            "agent_id": identity,
            "client_id": client,
            "messages": selected,
            "claimed_count": len(selected),
            "pending_count": pending,
            "server_time": timestamp,
            "store_revision": int(store.get("revision", 0)) + 1,
        }


def peek(
    agent_id: str,
    limit: int = 10,
    project_id: str = "",
    thread_id: str = "",
) -> dict[str, Any]:
    identity = normalize_agent(agent_id)
    require_bootstrapped(identity)
    count = max(1, min(int(limit), 50))
    store = read_store()
    timestamp = now()
    selected: list[dict[str, Any]] = []
    for message in sorted(store["messages"], key=lambda item: int(item.get("seq", 0))):
        if message.get("status") == "acked":
            continue
        if message.get("to_agent") != identity:
            continue
        if project_id and message.get("project_id") != project_id:
            continue
        if thread_id and message.get("thread_id") != thread_id:
            continue
        if not _message_deliverable(store, message):
            continue
        claim = message.get("claim") or {}
        if _claim_alive(claim, timestamp):
            continue
        selected.append(message)
        if len(selected) >= count:
            break
    pending = sum(
        1
        for message in store["messages"]
        if message.get("status") != "acked"
        and message.get("to_agent") == identity
        and _message_deliverable(store, message)
    )
    return {
        "agent_id": identity,
        "messages": selected,
        "available_count": len(selected),
        "pending_count": pending,
        "server_time": timestamp,
        "store_revision": int(store.get("revision", 0)),
    }


def acknowledge(agent_id: str, message_id: str, result: str = "") -> dict[str, Any]:
    identity = normalize_agent(agent_id)
    require_bootstrapped(identity)
    target = str(message_id or "").strip()
    if not target:
        raise ValueError("message_id is required")
    with locked_store() as store:
        for message in store["messages"]:
            if message.get("message_id") != target:
                continue
            if message.get("to_agent") not in {identity, "broadcast", "all"}:
                raise RuntimeError("message belongs to another recipient")
            message["status"] = "acked"
            message["acked_at"] = now()
            message["ack_result"] = str(result or "")[:20000]
            message["ack_agent"] = identity
            message["claim"] = None
            return message
    raise RuntimeError(f"message not found: {target}")


def release(agent_id: str, message_id: str, reason: str = "") -> dict[str, Any]:
    identity = normalize_agent(agent_id)
    require_bootstrapped(identity)
    target = str(message_id or "").strip()
    with locked_store() as store:
        for message in store["messages"]:
            if message.get("message_id") != target:
                continue
            claim = message.get("claim") or {}
            if claim.get("agent_id") != identity:
                raise RuntimeError("message claim belongs to another agent")
            message["status"] = "pending"
            message["claim"] = None
            message["last_error"] = str(reason or "released")[:2000]
            return message
    raise RuntimeError(f"message not found: {target}")


def history(
    project_id: str = "default",
    thread_id: str = "main",
    limit: int = 100,
    after_seq: int = 0,
) -> dict[str, Any]:
    store = read_store()
    selected = [
        message
        for message in store["messages"]
        if message.get("project_id") == (project_id or "default")
        and message.get("thread_id") == (thread_id or "main")
        and int(message.get("seq", 0)) > int(after_seq)
    ]
    selected.sort(key=lambda item: int(item.get("seq", 0)))
    selected = selected[-max(1, min(int(limit), 500)):]
    return {
        "project_id": project_id or "default",
        "thread_id": thread_id or "main",
        "messages": selected,
        "latest_seq": max([int(item.get("seq", 0)) for item in selected] or [0]),
        "store_revision": int(store.get("revision", 0)),
    }


def get_project(project_id: str = "default") -> dict[str, Any]:
    project = str(project_id or "default").strip()[:120] or "default"
    store = read_store()
    current = store["projects"].get(project) or {
        "project_id": project,
        "revision": 0,
        "state": {},
        "updated_at": 0,
        "updated_by": None,
    }
    return current


def set_project(
    agent_id: str,
    project_id: str,
    state: dict[str, Any],
    expected_revision: int = -1,
) -> dict[str, Any]:
    identity = normalize_agent(agent_id)
    require_bootstrapped(identity)
    project = str(project_id or "default").strip()[:120] or "default"
    with locked_store() as store:
        current = store["projects"].get(project) or {
            "project_id": project,
            "revision": 0,
            "state": {},
            "updated_at": 0,
            "updated_by": None,
        }
        revision = int(current.get("revision", 0))
        if int(expected_revision) >= 0 and int(expected_revision) != revision:
            raise RuntimeError(f"stale project revision: expected {expected_revision}, current {revision}")
        updated = {
            "project_id": project,
            "revision": revision + 1,
            "state": state,
            "updated_at": now(),
            "updated_by": identity,
        }
        store["projects"][project] = updated
        return updated


def get_control(project_id: str = "default") -> dict[str, Any]:
    store = read_store()
    return _control_value(store, project_id)


def set_control(
    actor_id: str,
    project_id: str = "default",
    mode: str = "running",
    note: str = "",
    thread_id: str = "main",
) -> dict[str, Any]:
    actor = normalize_agent(actor_id)
    project = str(project_id or "default").strip()[:120] or "default"
    selected_mode = str(mode or "running").strip().lower()
    if selected_mode not in {"running", "paused", "stopped"}:
        raise ValueError("mode must be running, paused or stopped")
    with locked_store() as store:
        current = _control_value(store, project)
        updated = {
            "project_id": project,
            "revision": int(current.get("revision", 0)) + 1,
            "mode": selected_mode,
            "note": str(note or "")[:2000],
            "updated_at": now(),
            "updated_by": actor,
        }
        store["controls"][project] = updated
        seq = int(store["next_seq"])
        store["next_seq"] = seq + 1
        store["messages"].append({
            "message_id": str(uuid.uuid4()),
            "seq": seq,
            "project_id": project,
            "thread_id": str(thread_id or "main")[:160] or "main",
            "scene_id": "",
            "from_agent": actor,
            "to_agent": "all",
            "kind": "control",
            "content": f"Conversation control: {selected_mode}" + (f" — {note}" if note else ""),
            "reply_to": None,
            "expects_reply": False,
            "metadata": {"control_mode": selected_mode},
            "idempotency_key": None,
            "status": "acked",
            "created_at": now(),
            "claim": None,
            "delivery_attempts": 0,
            "acked_at": now(),
            "ack_result": "control state recorded",
            "ack_agent": actor,
        })
        return updated


def operator_send(
    content: str,
    target: str = "both",
    project_id: str = "eiros-hub",
    thread_id: str = "first-contact",
    kind: str = "operator",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    text = str(content or "").strip()
    if not text:
        raise ValueError("content is required")
    selected = str(target or "both").strip()
    bootstrap_agent(
        agent_id="rico",
        display_name="Рико",
        client_kind="operator",
        capabilities=["observe", "interrupt", "direct"],
        discoverable=False,
        platform_class="human",
        instance_id="rico-operator",
        assistant_name="Рико",
        owner_display_name="Рико",
    )
    store = read_store()
    if selected.lower() == "both":
        preferred = ["chatgpt", "claude"]
        targets = [item for item in preferred if item in store.get("agents", {})]
    elif selected.lower() in {"all", "broadcast"}:
        targets = [
            key
            for key, item in store.get("agents", {}).items()
            if key != "rico" and item.get("bootstrapped_at") and bool(item.get("discoverable", True))
        ]
    else:
        targets = [resolve_agent_reference(selected, store)]
    if not targets:
        raise RuntimeError("no eligible EIROS participants for operator message")
    group_id = str(uuid.uuid4())
    messages = []
    for recipient in targets:
        combined = dict(metadata or {})
        combined.update({"operator_group_id": group_id, "operator_target": selected})
        messages.append(
            send_message(
                from_agent="rico",
                to_agent=recipient,
                content=text,
                kind=kind,
                project_id=project_id,
                thread_id=thread_id,
                expects_reply=True,
                metadata=combined,
                idempotency_key=f"operator:{group_id}:{recipient}",
            )
        )
    return {"ok": True, "group_id": group_id, "target": selected, "messages": messages}


def room_snapshot(
    project_id: str = "eiros-hub",
    thread_id: str = "first-contact",
    limit: int = 200,
    after_seq: int = 0,
) -> dict[str, Any]:
    return {
        "history": history(project_id, thread_id, limit, after_seq),
        "hub": hub_status(),
        "control": get_control(project_id),
    }


def hub_status() -> dict[str, Any]:
    store = read_store()
    timestamp = now()
    pending_by_agent: dict[str, int] = {}
    activity_by_agent: dict[str, dict[str, int]] = {}
    for message in store["messages"]:
        if message.get("status") == "acked":
            continue
        recipient = str(message.get("to_agent") or "unknown")
        pending_by_agent[recipient] = pending_by_agent.get(recipient, 0) + 1
        bucket = activity_by_agent.setdefault(recipient, {"pending": 0, "claimed": 0})
        claim = message.get("claim") or {}
        if _claim_alive(claim, timestamp):
            bucket["claimed"] += 1
        else:
            bucket["pending"] += 1
    agents = []
    for agent in store["agents"].values():
        item = _presence_for_agent(store, agent, timestamp)
        agents.append(item)
    agents.sort(key=lambda item: item.get("agent_id", ""))
    return {
        "schema_version": store.get("schema_version"),
        "revision": store.get("revision"),
        "updated_at": store.get("updated_at"),
        "agents": agents,
        "projects": list(store["projects"].values()),
        "controls": list(store.get("controls", {}).values()),
        "message_count": len(store["messages"]),
        "pending_by_agent": pending_by_agent,
        "activity_by_agent": activity_by_agent,
        "latest_seq": max([int(item.get("seq", 0)) for item in store["messages"]] or [0]),
        "server_time": timestamp,
    }
