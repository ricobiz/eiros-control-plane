from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from runtime import companion_server as companion


class CompanionStateTests(unittest.TestCase):
    def test_render_contract_names_active_video_pip_bridge(self) -> None:
        source = companion.Path(companion.__file__).read_text(encoding="utf-8")
        self.assertIn("WAKE BRIDGE · VIDEO PIP ACTIVE", source)

    def test_collect_state_reports_video_pip_bridge(self) -> None:
        pulse = {
            "leader": {"lease_until": 9999999999, "last_seen": 9999999998},
            "events": [],
            "latest_seq": 72,
        }
        room = {"history": {"messages": []}}
        hub = {"agents": [{"agent_id": "chatgpt", "status": "online"}]}
        surface = {
            "active": True,
            "video_pip_active": True,
            "mode": "video_pip",
            "session_id": "pulse-pip",
            "age_seconds": 0,
        }
        fake_sam = SimpleNamespace(_listener_surface_snapshot=lambda _hub, max_age=20: surface)
        with (
            patch.object(companion.events, "status", return_value=pulse),
            patch.object(companion.collab, "room_snapshot", return_value=room),
            patch.object(companion.collab, "hub_status", return_value=hub),
            patch.object(companion.queue, "read_store", return_value={"tasks": []}),
            patch.object(companion, "sam", fake_sam, create=True),
        ):
            value = companion.collect_state()

        self.assertIs(value["bridge_live"], True)
        self.assertIs(value["bridge_video_pip_active"], True)
        self.assertEqual(value["bridge_mode"], "video_pip")
        self.assertEqual(value["bridge_session_id"], "pulse-pip")


if __name__ == "__main__":
    unittest.main()
