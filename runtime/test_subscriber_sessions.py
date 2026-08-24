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


def test_different_installations_keep_sessions_in_separate_subscriber_records(monkeypatch, tmp_path):
    """Spec §8 #3 negative case: another installation cannot share the same subscriber/session bucket."""
    monkeypatch.setattr(collab, "STORE_FILE", tmp_path / "collab.json")
    monkeypatch.setattr(collab, "LOCK_FILE", tmp_path / "collab.lock")

    install_a = collab.bootstrap_agent(
        client_kind="chatgpt",
        platform_class="chatgpt",
        instance_id="installation-a",
        display_name="ChatGPT device A",
    )["resume_identity"]
    install_b = collab.bootstrap_agent(
        client_kind="chatgpt",
        platform_class="chatgpt",
        instance_id="installation-b",
        display_name="ChatGPT device B",
    )["resume_identity"]

    assert install_a["agent_id"] != install_b["agent_id"]
    assert install_a["phone_number"] != install_b["phone_number"]

    # Even a host-local session label collision must remain scoped to the
    # installation's own subscriber record rather than merging the records.
    session_a = collab.session_heartbeat(
        install_a["agent_id"],
        "same-runtime-session-label",
        host="chatgpt-ios",
    )
    session_b = collab.session_heartbeat(
        install_b["agent_id"],
        "same-runtime-session-label",
        host="chatgpt-ios",
    )

    assert session_a["agent_id"] == install_a["agent_id"]
    assert session_b["agent_id"] == install_b["agent_id"]
    assert session_a["phone_number"] == install_a["phone_number"]
    assert session_b["phone_number"] == install_b["phone_number"]
    assert session_a["phone_number"] != session_b["phone_number"]

    store = collab.read_store()
    assert set(store["agents"][install_a["agent_id"]]["sessions"]) == {"same-runtime-session-label"}
    assert set(store["agents"][install_b["agent_id"]]["sessions"]) == {"same-runtime-session-label"}
