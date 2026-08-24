from __future__ import annotations

from unittest.mock import patch

import pytest

from runtime import events, server_v2


@pytest.fixture
def isolated_events(monkeypatch, tmp_path):
    clock = {"now": 1_800_000_000}
    monkeypatch.setattr(events, "EVENT_FILE", tmp_path / "events.json")
    monkeypatch.setattr(events, "LOCK_FILE", tmp_path / "events.lock")
    monkeypatch.setattr(events, "now", lambda: clock["now"])
    monkeypatch.setattr(
        events,
        "cfg",
        lambda: {
            "instance_id": "test-instance",
            "channel": "default",
            "limits": {"max_events": 5000},
        },
    )
    return clock


def test_newer_unready_listener_does_not_preempt_live_leader(isolated_events):
    old_id = "pulse-v58-chatgpt-1787588000000-oldpip"
    new_id = "pulse-v58-chatgpt-1787589000000-newinline"

    first = events.poll(
        old_id,
        instance_id="test-instance",
        leader_lease_seconds=25,
        handover_ready=True,
    )
    assert first["leader"] is True

    second = events.poll(
        new_id,
        instance_id="test-instance",
        leader_lease_seconds=25,
        handover_ready=False,
    )
    assert second["leader"] is False
    assert second["leader_widget_id"] == old_id


def test_newer_ready_listener_can_preempt_live_leader(isolated_events):
    old_id = "pulse-v58-chatgpt-1787588000000-oldpip"
    new_id = "pulse-v58-chatgpt-1787589000000-newpip"

    events.poll(
        old_id,
        instance_id="test-instance",
        leader_lease_seconds=25,
        handover_ready=True,
    )
    second = events.poll(
        new_id,
        instance_id="test-instance",
        leader_lease_seconds=25,
        handover_ready=True,
    )

    assert second["leader"] is True
    assert second["leader_widget_id"] == new_id


def test_unready_listener_can_recover_after_leader_lease_expires(isolated_events):
    clock = isolated_events
    old_id = "pulse-v58-chatgpt-1787588000000-oldpip"
    new_id = "pulse-v58-chatgpt-1787589000000-newinline"

    events.poll(
        old_id,
        instance_id="test-instance",
        leader_lease_seconds=10,
        handover_ready=True,
    )
    clock["now"] += 11

    recovered = events.poll(
        new_id,
        instance_id="test-instance",
        leader_lease_seconds=10,
        handover_ready=False,
    )

    assert recovered["leader"] is True
    assert recovered["leader_widget_id"] == new_id


def test_server_pulse_poll_forwards_handover_readiness():
    with (
        patch.object(
            server_v2.event_engine,
            "poll",
            return_value={"leader": False, "event": None},
        ) as poll,
        patch.object(server_v2, "_observe_widget_pair", return_value={}),
    ):
        server_v2.pulse_poll(
            widget_id="pulse-v58-chatgpt-1787589000000-newinline",
            handover_ready=False,
        )

    assert poll.call_args.kwargs["handover_ready"] is False


def test_v58_listener_reports_pip_readiness_to_pulse_poll():
    rendered = server_v2._render_pulse_sum_html("mount-test")

    assert "handover_ready:videoPipState==='active'||displayMode()==='pip'" in rendered
