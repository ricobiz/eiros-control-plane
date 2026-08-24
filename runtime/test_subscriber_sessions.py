from __future__ import annotations

from runtime import collab


def test_multiple_runtime_sessions_stay_under_same_subscriber_number(monkeypatch, tmp_path):
    """Spec §8 #3 survivor: session churn does not mint another public subscriber number."""
    monkeypatch.setattr(collab, "STORE_FILE", tmp_path / "collab.json")
    monkeypatch.setattr(collab, "LOCK_FILE", tmp_path / "collab.lock")

    first = collab.bootstrap_agent(
        client_kind="chatgpt",
        platform_class="chatgpt",
        instance_id="installation-a",
        display_name="ChatGPT device A",
    )
    first_identity = first["resume_identity"]

    session_one = collab.session_heartbeat(
        first_identity["agent_id"],
        "runtime-session-1",
        host="chatgpt-ios",
    )
    session_two = collab.session_heartbeat(
        first_identity["agent_id"],
        "runtime-session-2",
        host="chatgpt-ios",
    )

    resumed = collab.bootstrap_agent(
        client_kind="chatgpt",
        platform_class="chatgpt",
        instance_id="installation-a",
        display_name="ChatGPT device A",
    )["resume_identity"]

    assert resumed["agent_id"] == first_identity["agent_id"]
    assert resumed["phone_number"] == first_identity["phone_number"]
    assert set(session_two["sessions"]) == {"runtime-session-1", "runtime-session-2"}
    assert session_one["phone_number"] == first_identity["phone_number"]
