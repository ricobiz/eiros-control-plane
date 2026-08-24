from __future__ import annotations

from runtime import collab


def test_multiple_runtime_sessions_stay_below_one_subscriber_number(monkeypatch, tmp_path):
    """Spec §8.3: session churn must not allocate another public subscriber number."""
    monkeypatch.setattr(collab, "STORE_FILE", tmp_path / "collab.json")
    monkeypatch.setattr(collab, "LOCK_FILE", tmp_path / "collab.lock")

    first = collab.bootstrap_agent(
        agent_id="rico-chatgpt-phone",
        display_name="ChatGPT · Rico",
        platform_class="chatgpt",
        instance_id="device-install-a",
    )
    agent_id = first["assigned_agent_id"]
    number = first["assigned_phone_number"]

    collab.session_heartbeat(agent_id, "runtime-session-1", host="chatgpt-ios")
    collab.session_heartbeat(agent_id, "runtime-session-2", host="chatgpt-ios")

    reconnected = collab.bootstrap_agent(
        display_name="ChatGPT · Rico",
        platform_class="chatgpt",
        instance_id="device-install-a",
    )
    store = collab.read_store()
    stored = store["agents"][agent_id]

    assert reconnected["assigned_agent_id"] == agent_id
    assert reconnected["assigned_phone_number"] == number
    assert stored["phone_number"] == number
    assert set(stored["sessions"]) == {"runtime-session-1", "runtime-session-2"}
    assert stored["active_session_count"] == 2
    assert store["next_phone_number"] == int(number) + 1
