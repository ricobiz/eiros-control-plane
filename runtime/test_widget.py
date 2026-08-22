from __future__ import annotations

import json
import re
from pathlib import Path

from runtime import server_v2

ROOT = Path(__file__).resolve().parents[1]


def test_pulse_widget_template_contract():
    widget = (ROOT / "runtime" / "pulse_widget.html").read_text(encoding="utf-8")
    assert widget.count("__EIROS_BOOTSTRAP_JSON__") == 1
    assert "window.__EIROS_BOOTSTRAP__=__EIROS_BOOTSTRAP_JSON__;" in widget
    bootstrap = {
        "instanceId": "instance-test",
        "channel": "channel-test",
        "displayName": "EIROS Test",
        "polling": {"active_ms": 750},
        "serverVersion": "test",
    }
    rendered = widget.replace("__EIROS_BOOTSTRAP_JSON__", json.dumps(bootstrap))
    assert "__EIROS_BOOTSTRAP_JSON__" not in rendered
    assert "window.__EIROS_BOOTSTRAP__={" in rendered
    assert "window.{" not in rendered
    assert "instance-test" in rendered and "channel-test" in rendered
    assert "ui/message" in rendered and "tools/call" in rendered
    scripts = re.findall(r"<script>(.*?)</script>", rendered, flags=re.DOTALL)
    assert len(scripts) == 1 and scripts[0].count("(function(){") == 1


def test_widget_test_resources_are_listener_aliases(monkeypatch):
    calls: list[str] = []

    def fake_mark(uri: str):
        calls.append(uri)
        return {"mount_id": "fixed-mount"}

    monkeypatch.setattr(server_v2, "_mark_widget_resource_served", fake_mark)
    canonical = server_v2.widget_test_resource()
    legacy = server_v2.widget_test_resource_legacy()

    assert canonical == legacy
    assert calls == [server_v2.WIDGET_TEST_URI, server_v2.WIDGET_TEST_LEGACY_URI]
    assert server_v2.PULSE_SUM_VERSION in canonical
    assert "pulse_poll" in canonical and "ui/message" in canonical
    assert "EIROS Kill Switch" not in canonical
    assert server_v2.WIDGET_TEST_URI.endswith("widget-test-v2.html")
    resources = server_v2.mcp._resource_manager._resources
    canonical_resource = resources[server_v2.WIDGET_TEST_URI]
    legacy_resource = resources[server_v2.WIDGET_TEST_LEGACY_URI]
    assert canonical_resource.meta == legacy_resource.meta
    assert canonical_resource.mime_type == legacy_resource.mime_type
    assert canonical_resource.title == legacy_resource.title


def test_current_room_contract_and_legacy_aliases():
    room_template = (ROOT / "runtime" / "collab_room.html").read_text(encoding="utf-8")
    room_ids = set(re.findall(r'id="([^"]+)"', room_template))
    room_refs = set(re.findall(r"\$\('([^']+)'\)", room_template))
    assert not (room_refs - room_ids), f"missing room DOM ids: {sorted(room_refs-room_ids)}"

    room_rendered = server_v2.room_resource()
    assert "__EIROS_ROOM_BOOTSTRAP_JSON__" not in room_rendered
    assert "initialSystem" in room_rendered
    assert len(room_rendered.encode("utf-8")) < 50000
    assert server_v2.ROOM_URI == "ui://eiros/collab-room-v9-25-listener-safe.html"
    assert server_v2.ROOM_VERSION == "0.9.25-listener-safe"
    assert "EIROS Control" in room_rendered
    assert "operator_send" in room_rendered and "request_immediate_wake" in room_rendered
    assert "room_cleanup_stale" in room_rendered and "dockFresh" in room_rendered
    assert "EIROS_SCHEDULED_WAKE" in room_rendered
    assert "FROM_ROLE: user" in room_rendered and "FROM_AGENT: rico" in room_rendered
    assert "rico_authorized_durable_scheduler_continuation" in room_rendered
    assert "pending messages preserved" in room_rendered
    assert "noticeUntil" in room_rendered and "Refreshed ·" in room_rendered
    assert "lampShort" in room_rendered and "lastSig=null" in room_rendered
    assert "room_telemetry_update" in room_rendered and "Both agents" in room_rendered
    assert server_v2.ROOM_LEGACY_V924_URI == "ui://eiros/collab-room-v9-24-inline-isolated.html"
    assert server_v2.ROOM_VERSION in server_v2.room_resource_legacy_v924()

    assert server_v2.ROOM_VERSION in server_v2.room_resource_legacy_v914()
    assert server_v2.ROOM_VERSION in server_v2.room_resource_legacy_v916()
    assert server_v2.ROOM_LEGACY_V919_URI == "ui://eiros/collab-room-v9-19-clean-start.html"
    assert server_v2.ROOM_LEGACY_V94_LOCALWAKE_URI == "ui://eiros/collab-room-v9-4-localwake.html"
    assert server_v2.ROOM_VERSION in server_v2.room_resource_legacy_v94_localwake()


def test_room_boot_does_not_broadcast_global_kill_to_listener():
    room_template = (ROOT / "runtime" / "collab_room.html").read_text(encoding="utf-8")
    boot_start = room_template.index("async function bootRoom()")
    boot_end = room_template.index("bootRoom();", boot_start)
    boot = room_template[boot_start:boot_end]

    # A Room refresh may take the Room lease, but it must never broadcast the
    # operator-only global kill key because Pulse listens to that key too.
    assert "localStorage.setItem(killKey" not in boot
    assert "claimLease()" in boot

    # Explicit GLOBAL KILL must still be honored when the operator invokes it.
    assert "if(e.key===killKey){stale();return}" in room_template
    assert "eiros-ui-kill" in room_template
    assert "lease_key:'v925'" in room_template


def test_current_connector_boot_and_launcher_contract():
    source = (ROOT / "runtime" / "server_v2.py").read_text(encoding="utf-8")
    assert "EIROS CONNECTOR BOOT PROTOCOL v1.0" in source
    assert "If no live Wake Listener or live Pulse leader exists, call open_pulse_v57 exactly once." in source
    assert "Never call close_eiros_widgets automatically." in source
    assert "Open Room only after Rico explicitly asks for Room" in source
    assert '"resume_context": resume' in source and 'reason="room_reconnected"' in source
    assert "call open_collab_room as the only UI-opening tool" not in source

    launcher = server_v2.room_launcher_resource()
    assert "__EIROS_CONSOLE_BOOTSTRAP__" in launcher
    assert "EIROS Console" in launcher and "Fullscreen" in launcher
    assert "pulse_status" in launcher and "room_snapshot" in launcher
    assert "queue_status" in launcher and "hub_status" in launcher
    assert server_v2.ROOM_LAUNCHER_URI.endswith("room-launcher-v1d-static-proof.html")


def test_delivery_receipts_distinguish_live_wake_from_offline_mail(monkeypatch):
    monkeypatch.setattr(
        server_v2.collab_engine,
        "hub_status",
        lambda: {
            "agents": [
                {"agent_id": "chatgpt", "presence": "online", "activity": "idle"},
                {"agent_id": "claude", "presence": "offline", "activity": "offline"},
            ]
        },
    )
    receipts = server_v2._delivery_receipts(
        [
            {"message_id": "m1", "to_agent": "chatgpt"},
            {"message_id": "m2", "to_agent": "claude"},
        ],
        [{"message_id": "m1", "event_id": "e1"}],
    )
    assert receipts[0]["mode"] == "wake queued"
    assert receipts[1]["mode"] == "offline mail"
