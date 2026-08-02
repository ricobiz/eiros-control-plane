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


def test_v58_sum_resource_is_separate_from_v57_rollback() -> None:
    from runtime import server_v2

    assert server_v2.PULSE_SUM_URI == "ui://eiros/pulse-anchor-v5-8-sum-auto-wake.html"
    assert server_v2.PULSE_SUM_VERSION == "0.5.8-sum-auto-wake"
    assert server_v2.PULSE_FRESH_VERSION == "0.5.7-self-diagnostic-pip"

    tools = server_v2.mcp._tool_manager._tools
    tool = tools["open_pulse_v58"]
    assert tool.meta["ui"]["resourceUri"] == server_v2.PULSE_SUM_URI
    assert tool.meta["openai/outputTemplate"] == server_v2.PULSE_SUM_URI

    registered = {str(uri) for uri in server_v2.mcp._resource_manager._resources}
    assert server_v2.PULSE_SUM_URI in registered
    assert server_v2.PULSE_FRESH_URI in registered

    v58 = server_v2._render_pulse_sum_html()
    v57 = server_v2._render_pulse_v57_html()
    assert "AUTO WAKE CYCLE" in v58
    assert "0.5.8-sum-auto-wake" in v58
    assert "AUTO WAKE CYCLE" not in v57
    assert "0.5.7-self-diagnostic-pip" in v57


def test_pulse_poll_accepts_v58_listener_generation() -> None:
    source = (Path(__file__).parent / "server_v2.py").read_text(encoding="utf-8")
    assert '"pulse-v58-"' in source


def test_cached_inline_tool_alias_mounts_v58_sum_listener() -> None:
    from runtime import server_v2

    html = server_v2.pulse_inline_resource()
    assert "AUTO WAKE CYCLE" in html
    assert server_v2.PULSE_SUM_VERSION in html

    result = server_v2.open_inline_listener()
    assert result["resource_uri"] == server_v2.PULSE_INLINE_URI
    assert result["listener_version"] == server_v2.PULSE_SUM_VERSION
    assert result["expected_widget_kind"] == "listener"
    assert result["mount_id"].startswith("mount-")
    assert result["diagnostic_next_action"].startswith("call widget_boot_status")
