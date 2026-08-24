from __future__ import annotations

from runtime import events


def _isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(events, "EVENT_FILE", tmp_path / "events.json")
    monkeypatch.setattr(events, "LOCK_FILE", tmp_path / "events.lock")
    monkeypatch.setattr(events, "cfg", lambda: {
        "instance_id": "test-instance",
        "channel": "default",
        "limits": {"max_events": 100, "max_event_text": 20000},
    })
    monkeypatch.setattr(events, "now", lambda: 1_800_000_000)


def test_newer_unready_listener_cannot_preempt_live_leader(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    old = events.poll(
        widget_id="pulse-v58-chatgpt-1787588000000-old",
        instance_id="test-instance",
        handover_ready=True,
    )
    assert old["leader"] is True

    newer = events.poll(
        widget_id="pulse-v58-chatgpt-1787589000000-new",
        instance_id="test-instance",
        handover_ready=False,
    )

    assert newer["leader"] is False
    assert newer["leader_widget_id"] == "pulse-v58-chatgpt-1787588000000-old"


def test_newer_pip_ready_listener_can_preempt_live_leader(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    events.poll(
        widget_id="pulse-v58-chatgpt-1787588000000-old",
        instance_id="test-instance",
        handover_ready=True,
    )

    newer = events.poll(
        widget_id="pulse-v58-chatgpt-1787589000000-new",
        instance_id="test-instance",
        handover_ready=True,
    )

    assert newer["leader"] is True
    assert newer["leader_widget_id"] == "pulse-v58-chatgpt-1787589000000-new"


def test_unready_listener_can_recover_after_previous_leader_lease_expires(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    clock = {"now": 1_800_000_000}
    monkeypatch.setattr(events, "now", lambda: clock["now"])
    first = events.poll(widget_id="pulse-v58-chatgpt-1787588000000-old", instance_id="test-instance", leader_lease_seconds=10, handover_ready=True)
    assert first["leader"] is True
    clock["now"] += 11
    recovered = events.poll(widget_id="pulse-v58-chatgpt-1787589000000-new", instance_id="test-instance", handover_ready=False)
    assert recovered["leader"] is True
    assert recovered["leader_widget_id"] == "pulse-v58-chatgpt-1787589000000-new"
