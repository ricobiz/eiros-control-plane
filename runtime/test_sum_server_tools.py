from __future__ import annotations

from pathlib import Path

from runtime.sum_controller import SumControllerStore


EXPECTED_TOOLS = {
    "sum_controller_status",
    "sum_controller_set",
    "sum_host_signal",
    "sum_controller_tick",
    "sum_wake_sent",
    "sum_wake_ack_current",
    "sum_wake_ack",
    "sum_controller_log",
}

APP_ONLY_TOOLS = {
    "sum_controller_set",
    "sum_host_signal",
    "sum_controller_tick",
    "sum_wake_sent",
}

MODEL_AND_APP_TOOLS = {
    "sum_controller_status",
    "sum_wake_ack_current",
    "sum_wake_ack",
    "sum_controller_log",
}


def test_sum_tools_are_registered() -> None:
    from runtime import server_v2

    registered = set(server_v2.mcp._tool_manager._tools)
    assert EXPECTED_TOOLS <= registered


def test_sum_tool_visibility_contract() -> None:
    from runtime import server_v2

    tools = server_v2.mcp._tool_manager._tools
    for name in APP_ONLY_TOOLS:
        assert tools[name].meta["ui"]["visibility"] == ["app"]
    for name in MODEL_AND_APP_TOOLS:
        assert tools[name].meta["ui"]["visibility"] == ["model", "app"]


def test_listener_bootstrap_contains_sum_defaults_and_natural_wake_text() -> None:
    from runtime import server_v2

    html = server_v2._render_pulse_anchor_html()
    assert '"sumController"' in html
    assert '"available": true' in html
    assert '"enabledByDefault": false' in html
    assert '"naturalWakeText": "Отлично, продолжай."' in html
    assert '"staticDebounceMs": 3000' in html
    assert '"ackTimeoutMs": 8000' in html
    assert '"retryIntervalMs": 5000' in html
    assert '"maxWakeAttempts": 5' in html


def test_sum_wake_ack_current_confirms_pending_wake_without_ids(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from runtime import server_v2

    store = SumControllerStore(
        tmp_path / "sum-controller.json",
        tmp_path / "sum-controller.jsonl",
    )
    monkeypatch.setattr(server_v2, "SUM_CONTROLLER", store)

    store.set_enabled(True, actor="rico", listener_session_id="listener-1")
    wake = store.tick(
        "listener-1",
        pip_active=True,
        listener_healthy=True,
    )
    assert wake["state"] == "WAKE"

    acked = server_v2.sum_wake_ack_current(
        actor="chatgpt",
        listener_session_id="listener-1",
    )
    assert acked["state"] == "AWAKE"
    assert acked["wake_id"] == wake["wake_id"]
    assert acked["counters"]["wakes_acked"] == 1


def test_sum_controller_reset_action_uses_durable_reset(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from runtime import server_v2

    store = SumControllerStore(
        tmp_path / "sum-controller.json",
        tmp_path / "sum-controller.jsonl",
    )
    monkeypatch.setattr(server_v2, "SUM_CONTROLLER", store)
    store.set_enabled(True, actor="rico", listener_session_id="listener-1")
    store.tick("listener-1", pip_active=True, listener_healthy=True)

    state = server_v2.sum_controller_set(
        False,
        action="reset",
        actor="rico",
        listener_session_id="listener-1",
    )
    assert state["state"] == "IDLE"
    assert state["cycle_id"] == 0
    assert state["counters"]["cycles_started"] == 0


def test_connector_instructions_hide_ack_behind_natural_continuation() -> None:
    source = (Path(__file__).parent / "server_v2.py").read_text(encoding="utf-8")
    assert "SUM AUTO-WAKE RULE" in source
    assert "Отлично, продолжай." in source
    assert "call sum_wake_ack_current as the first tool action" in source
    assert "do not expose SUM identifiers in the visible chat" in source
