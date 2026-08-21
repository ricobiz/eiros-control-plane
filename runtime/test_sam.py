from __future__ import annotations

import unittest
from unittest.mock import patch

from runtime import events
from runtime import sam


class SamContractTests(unittest.TestCase):
    def test_widget_generation_prefers_newest_timestamp(self) -> None:
        self.assertEqual(events.widget_generation("pulse-v49-chatgpt-1785526000000-new"), 1785526000000)
        self.assertEqual(events.widget_generation("legacy-widget"), 0)

    def test_scheduled_wake_uses_sam_contract(self) -> None:
        captured = {}

        def fake_emit(**kwargs):
            captured.update(kwargs)
            return {"id": "event-1", "seq": 9, "status": "pending"}

        task = {
            "id": "task-1",
            "revision": 3,
            "title": "Wake test",
            "objective": "Prove the scheduler route",
            "next_step": "Verify delivery",
            "payload": {"probe": True},
            "priority": 1000,
        }
        with patch.object(sam.event_engine, "emit", side_effect=fake_emit), patch.object(sam, "_append_log"):
            result = sam.emit_scheduled_wake(task)

        self.assertEqual(result["id"], "event-1")
        self.assertEqual(captured["source"], "sam:scheduler")
        self.assertIs(captured["payload"]["sam"], True)
        self.assertEqual(captured["payload"]["sam_kind"], "scheduled_task")
        self.assertEqual(captured["payload"]["task_id"], "task-1")
        self.assertEqual(captured["payload"]["to_agent"], "chatgpt")
        self.assertEqual(captured["idempotency_key"], "brain:task-1:rev:3")

    @staticmethod
    def pip_hub() -> dict:
        return {
            "agents": [
                {
                    "agent_id": "chatgpt",
                    "sessions": [
                        {
                            "session_id": "pulse-v49-chatgpt-1785526000000-pip",
                            "host": "chatgpt-pulse-anchor",
                            "activity": "online·video-pip:active·mode:inline",
                            "last_seen": 9999999998,
                            "seconds_since_seen": 0,
                        }
                    ],
                }
            ]
        }

    def test_listener_surface_detects_active_video_pip(self) -> None:
        value = sam._listener_surface_snapshot(self.pip_hub(), max_age=20)
        self.assertIs(value["active"], True)
        self.assertIs(value["video_pip_active"], True)
        self.assertEqual(value["mode"], "video_pip")
        self.assertEqual(value["session_id"], "pulse-v49-chatgpt-1785526000000-pip")
        self.assertEqual(value["age_seconds"], 0)

    def test_supervisor_reports_continuous_video_pip_readiness(self) -> None:
        delivery = {"leader_live": True, "pending_count": 0, "leader_widget_id": "pulse-pip"}
        with (
            patch.object(sam, "_ensure_pending_message_wakes", return_value=[]),
            patch.object(sam, "_pulse_snapshot", return_value={}),
            patch.object(sam, "_delivery_snapshot", return_value=delivery),
            patch.object(sam, "_runtime_heartbeat", return_value={"ok": True}),
            patch.object(sam, "_listener_surface_snapshot", return_value={
                "active": True,
                "video_pip_active": True,
                "mode": "video_pip",
            }),
            patch.object(sam.queue_engine, "next_wakeup", return_value={"has_task": False}),
            patch.object(sam, "_read_json", return_value={}),
            patch.object(sam, "_atomic_json"),
            patch.object(sam, "_append_log"),
        ):
            report = sam.supervise_once()

        self.assertIs(report["wake_ready_now"], True)
        self.assertIs(report["continuous_wake_ready"], True)
        self.assertEqual(report["listener_surface"]["mode"], "video_pip")

    def test_sam_state_reports_continuous_video_pip_readiness(self) -> None:
        pulse = {
            "leader": {"widget_id": "pulse-1785526000000", "lease_until": 9999999999},
            "pending_count": 0,
            "latest_seq": 4,
            "summary": {},
        }
        heartbeat = {
            "ok": True,
            "pid": 1,
            "alive": True,
            "heartbeat_age_seconds": 0,
            "status": "waiting",
            "heartbeat": {},
        }
        with (
            patch.object(sam, "_pulse_snapshot", return_value=pulse),
            patch.object(sam, "_runtime_heartbeat", return_value=heartbeat),
            patch.object(sam.widget_blackbox, "status", return_value={"latest": {"pair": {}}}),
            patch.object(sam, "_room_history", return_value={"latest_seq": 0, "count": 0, "messages": []}),
            patch.object(sam, "_room_tail", return_value=[]),
            patch.object(sam.queue_engine, "next_wakeup", return_value={"has_task": False}),
            patch.object(sam.collab_engine, "hub_status", return_value=self.pip_hub()),
        ):
            value = sam.status(1)

        self.assertIs(value["ok"], True)
        self.assertIs(value["wake_ready_now"], True)
        self.assertIs(value["continuous_wake_ready"], True)
        self.assertIs(value["listener_surface"]["video_pip_active"], True)
        self.assertEqual(value["state"], "ready")


if __name__ == "__main__":
    unittest.main()
