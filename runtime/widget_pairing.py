from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from runtime.config import DATA_ROOT
from runtime import collab as collab_engine
from runtime import events as event_engine

PAIR_PROTOCOL = "eiros-widget-pair-v1"
PAIR_BUNDLE = "eiros-ui-2026-07-26-r1"
LIVE_SECONDS = 15
PAIR_FILE = DATA_ROOT / "runtime" / "widget-pairing.json"
PAIR_LOCK = DATA_ROOT / "runtime" / "widget-pairing.lock"


def _read() -> dict[str, Any]:
    try:
        value = json.loads(PAIR_FILE.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _write(value: dict[str, Any]) -> None:
    PAIR_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="widget-pair-", suffix=".json", dir=PAIR_FILE.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, PAIR_FILE)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _role(session: dict[str, Any]) -> str:
    sid = str(session.get("session_id") or "")
    host = str(session.get("host") or "")
    declared = str(session.get("widget_role") or "").lower()
    if declared in {"room", "listener"}:
        return declared
    if sid.startswith("room-") or host in {"chatgpt", "chatgpt-room"}:
        return "room"
    if sid.startswith("pulse-") or host == "chatgpt-pulse-anchor":
        return "listener"
    return "other"


def _session_generation(session: dict[str, Any]) -> int:
    digit_runs = "".join(ch if ch.isdigit() else " " for ch in str(session.get("session_id") or "")).split()
    values = [int(value) for value in digit_runs if len(value) == 13]
    return max(values or [0])


def _active_sessions(agent_id: str) -> list[dict[str, Any]]:
    hub = collab_engine.hub_status()
    agent = next((a for a in hub.get("agents", []) if str(a.get("agent_id")) == agent_id), {})
    sessions = []
    for raw in agent.get("sessions", []):
        item = dict(raw)
        if str(item.get("session_id")) == "server-open-pulse":
            continue
        if int(item.get("seconds_since_seen", 9999)) > LIVE_SECONDS:
            continue
        item["role"] = _role(item)
        sessions.append(item)
    sessions.sort(
        key=lambda s: (_session_generation(s), int(s.get("last_seen", 0)), str(s.get("session_id") or "")),
        reverse=True,
    )
    return sessions


def _legacy_compatible(room_version: str, listener_version: str) -> bool:
    rv = str(room_version or "")
    lv = str(listener_version or "")
    return rv.startswith("0.9.") and lv.startswith("0.4.")


def _signature(status: dict[str, Any]) -> str:
    important = {
        "state": status.get("state"),
        "pair_id": status.get("pair_id"),
        "reasons": status.get("reasons"),
        "room_count": status.get("room_count"),
        "listener_count": status.get("listener_count"),
        "room_version": (status.get("room") or {}).get("version"),
        "listener_version": (status.get("listener") or {}).get("version"),
        "leader": (status.get("pulse") or {}).get("leader_widget_id"),
        "leader_matches": (status.get("pulse") or {}).get("leader_matches"),
        "challenge_complete": status.get("challenge_complete"),
    }
    payload = json.dumps(important, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def compute(agent_id: str = "chatgpt", project_id: str = "eiros-hub", thread_id: str = "first-contact") -> dict[str, Any]:
    now = int(time.time())
    sessions = _active_sessions(agent_id)
    observed_rooms = [s for s in sessions if s.get("role") == "room"]
    observed_listeners = [s for s in sessions if s.get("role") == "listener"]
    # iOS can keep old iframes alive indefinitely. Only the newest Date.now generation
    # is authoritative; older live heartbeats are zombies and must not degrade the pair.
    rooms = observed_rooms[:1]
    listeners = observed_listeners[:1]
    room = rooms[0] if rooms else None
    listener = listeners[0] if listeners else None

    room_id = str((room or {}).get("session_id") or "")
    listener_id = str((listener or {}).get("session_id") or "")
    pair_seed = f"{agent_id}|{project_id}|{thread_id}|{room_id}|{listener_id}"
    pair_id = hashlib.sha256(pair_seed.encode("utf-8")).hexdigest()[:16] if room_id and listener_id else ""
    challenge = hashlib.sha256(f"{PAIR_PROTOCOL}|{PAIR_BUNDLE}|{pair_id}".encode("utf-8")).hexdigest()[:20] if pair_id else ""

    room_bundle = str((room or {}).get("bundle_id") or "")
    listener_bundle = str((listener or {}).get("bundle_id") or "")
    room_protocol = str((room or {}).get("pair_protocol") or "")
    listener_protocol = str((listener or {}).get("pair_protocol") or "")
    explicit = bool(room_bundle and listener_bundle and room_protocol and listener_protocol)

    if explicit:
        compatible = (
            room_bundle == listener_bundle == PAIR_BUNDLE
            and room_protocol == listener_protocol == PAIR_PROTOCOL
        )
        room_ack = str((room or {}).get("pair_ack") or "") == challenge
        listener_ack = str((listener or {}).get("pair_ack") or "") == challenge
        challenge_complete = bool(room_ack and listener_ack)
        handshake_mode = "challenge"
    else:
        compatible = bool(room and listener and _legacy_compatible(
            str(room.get("widget_version") or ""), str(listener.get("widget_version") or "")
        ))
        room_ack = bool(room)
        listener_ack = bool(listener)
        challenge_complete = bool(room and listener)
        handshake_mode = "legacy-server-mediated"

    pulse = event_engine.status(5, "")
    leader = pulse.get("leader") or {}
    leader_id = str(leader.get("widget_id") or "")
    leader_live = int(leader.get("lease_until", 0)) > now
    leader_matches = bool(listener_id and leader_live and leader_id == listener_id)

    reasons: list[str] = []
    if not room:
        reasons.append("room_missing")
    if not listener:
        reasons.append("listener_missing")
    if room and listener and not compatible:
        reasons.append("bundle_or_protocol_mismatch")
    if explicit and compatible and not challenge_complete:
        reasons.append("challenge_not_confirmed_by_both")
    if listener and not leader_matches:
        reasons.append("listener_not_pulse_leader")

    if not room or not listener:
        state = "starting"
        color = "amber"
    elif reasons:
        state = "degraded"
        color = "red" if any(r in reasons for r in {"bundle_or_protocol_mismatch", "listener_not_pulse_leader"}) else "amber"
    else:
        state = "ready"
        color = "green"

    status = {
        "ok": state == "ready",
        "state": state,
        "color": color,
        "protocol": PAIR_PROTOCOL,
        "bundle_id": PAIR_BUNDLE,
        "handshake_mode": handshake_mode,
        "pair_id": pair_id,
        "challenge": challenge,
        "challenge_complete": challenge_complete,
        "room_ack": room_ack,
        "listener_ack": listener_ack,
        "room_count": len(rooms),
        "listener_count": len(listeners),
        "observed_room_count": len(observed_rooms),
        "observed_listener_count": len(observed_listeners),
        "suppressed_room_zombies": max(0, len(observed_rooms) - len(rooms)),
        "suppressed_listener_zombies": max(0, len(observed_listeners) - len(listeners)),
        "room": {
            "session_id": room_id,
            "version": str((room or {}).get("widget_version") or ""),
            "last_seen": int((room or {}).get("last_seen", 0)),
        } if room else None,
        "listener": {
            "session_id": listener_id,
            "version": str((listener or {}).get("widget_version") or ""),
            "last_seen": int((listener or {}).get("last_seen", 0)),
        } if listener else None,
        "pulse": {
            "leader_widget_id": leader_id,
            "leader_live": leader_live,
            "leader_matches": leader_matches,
            "pending_count": int(pulse.get("pending_count", 0)),
        },
        "checks": {
            "exactly_one_room": len(rooms) == 1,
            "exactly_one_listener": len(listeners) == 1,
            "versions_compatible": compatible,
            "both_confirmed_challenge": challenge_complete,
            "listener_owns_pulse": leader_matches,
        },
        "reasons": reasons,
        "updated_at": now,
    }
    status["signature"] = _signature(status)
    status["summary"] = (
        f"PAIRED {status['room']['version']} ↔ {status['listener']['version']} · Pulse leader OK"
        if state == "ready"
        else f"{state.upper()} · " + ", ".join(reasons or ["waiting_for_peer"])
    )
    return status


def observe(agent_id: str = "chatgpt", project_id: str = "eiros-hub", thread_id: str = "first-contact") -> dict[str, Any]:
    status = compute(agent_id, project_id, thread_id)
    PAIR_FILE.parent.mkdir(parents=True, exist_ok=True)
    with PAIR_LOCK.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            store = _read()
            previous = store.get("latest") or {}
            transition = str(previous.get("signature") or "") != str(status.get("signature") or "")
            store["revision"] = int(store.get("revision", 0)) + (1 if transition else 0)
            store["updated_at"] = int(time.time())
            store["latest"] = status
            if transition:
                history = list(store.get("history") or [])
                history.append(status)
                store["history"] = history[-100:]
            _write(store)
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    return {**status, "transition": transition, "previous_state": previous.get("state")}


def mark_notified(signature: str) -> None:
    PAIR_FILE.parent.mkdir(parents=True, exist_ok=True)
    with PAIR_LOCK.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            store = _read()
            store["last_notified_signature"] = str(signature or "")
            store["last_notified_at"] = int(time.time())
            _write(store)
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def should_notify(status: dict[str, Any]) -> bool:
    store = _read()
    return bool(
        status.get("transition")
        and (
            status.get("state") == "ready"
            or (status.get("state") == "degraded" and status.get("previous_state") == "ready")
        )
        and str(store.get("last_notified_signature") or "") != str(status.get("signature") or "")
    )


def latest() -> dict[str, Any]:
    return (_read().get("latest") or compute())
