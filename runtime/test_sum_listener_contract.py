from __future__ import annotations

from pathlib import Path


ANCHOR = (Path(__file__).parent / "pulse_anchor.html").read_text(encoding="utf-8")


def test_sum_fullscreen_controls_exist() -> None:
    for marker in (
        "AUTO WAKE CYCLE",
        'id="sumState"',
        'id="sumToggle"',
        'id="sumCycle"',
        'id="sumWakeAttempts"',
        'id="sumConfirmedWakes"',
        'id="sumCurrentDuration"',
        'id="sumLastTransition"',
        'id="sumPause"',
        'id="sumStop"',
        'id="sumReset"',
        'id="sumOpenLog"',
        'id="sumCopyDiagnostic"',
        'id="sumLog"',
    ):
        assert marker in ANCHOR


def test_sum_visual_state_classes_cover_all_primary_colors() -> None:
    assert ".sumState.idle" in ANCHOR
    assert ".sumState.wake" in ANCHOR
    assert ".sumState.awake" in ANCHOR
    assert ".sumState.working" in ANCHOR
    assert "gray" in ANCHOR
    assert "#ef4444" in ANCHOR
    assert "#19c37d" in ANCHOR
    assert "#f5b849" in ANCHOR


def test_sum_listener_uses_controller_tools() -> None:
    for marker in (
        "function renderSumState",
        "async function refreshSumState",
        "async function setSumEnabled",
        "function renderSumLog",
        "sum_controller_status",
        "sum_controller_set",
        "sum_controller_log",
    ):
        assert marker in ANCHOR


def test_sum_state_updates_compact_listener_indicator() -> None:
    assert "SUM_STATE_DOT_CLASS" in ANCHOR
    assert "IDLE · monitoring" in ANCHOR
    assert "WAKE · attempt" in ANCHOR
    assert "AWAKE · cycle" in ANCHOR
    assert "WORKING ·" in ANCHOR


def test_sum_log_is_bounded_and_loaded_on_demand() -> None:
    assert "sum_controller_log',{limit:100}" in ANCHOR
    assert "sumLog.hidden" in ANCHOR
    assert "entries.slice().reverse()" in ANCHOR


def test_sum_host_activity_detector_listens_to_all_required_signals() -> None:
    for marker in (
        "function recordHostSignal",
        "function classifyHostActivity",
        "function scheduleStaticCandidate",
        "sum_host_signal",
        "openai:set_globals",
        "ui/notifications/host-context-changed",
        "visibilitychange",
        "pageshow",
        "pagehide",
        "freeze",
        "resume",
        "bridge-activity-start",
        "bridge-activity-end",
    ):
        assert marker in ANCHOR


def test_sum_host_detector_keeps_bounded_diagnostics() -> None:
    assert "recentHostSignals" in ANCHOR
    assert "slice(-30)" in ANCHOR
    assert "hostConfidence" in ANCHOR
    assert "sumStaticDebounceMs" in ANCHOR
    assert "lastHostSignalAt" in ANCHOR


def test_sum_ack_epoch_is_correlated_with_working_state() -> None:
    assert "lastObservedAwakeEpoch" in ANCHOR
    assert "ack-confirmed-turn" in ANCHOR
    assert "STATIC_DEBOUNCE" in ANCHOR


def test_sum_continuation_uses_exact_natural_user_message() -> None:
    start = ANCHOR.index("async function pollSumController")
    end = ANCHOR.index("async function heartbeat", start)
    block = ANCHOR[start:end]

    assert "naturalWakeText" in block
    assert "Отлично, продолжай." in block
    assert "postWake(naturalText)" in block
    assert "sum_controller_tick" in block
    assert "sum_wake_sent" in block
    assert "role:'user'" in ANCHOR
    for forbidden in (
        "SUM_WAKE_ID",
        "SUM_CYCLE_ID",
        "SUM_AWAKE_EPOCH",
        "[EIROS_SUM_WAKE]",
        "sum_wake_ack_current",
    ):
        assert forbidden not in block


def test_sum_poll_runs_only_after_normal_pulse_events_are_clear() -> None:
    pulse_event = ANCHOR.index("if(data.event){")
    sum_poll = ANCHOR.index("await pollSumController()")
    assert pulse_event < sum_poll


def test_sum_listener_has_cached_catalog_compatibility_transport() -> None:
    assert "async function callSumTool" in ANCHOR
    assert "callTool('get_state',{})" in ANCHOR
    assert "callTool('set_state',{status:name,data:payload})" in ANCHOR
    assert "sum_controller_status" in ANCHOR
    assert "sum_controller_set" in ANCHOR
    assert "sum_controller_tick" in ANCHOR
    assert "sum_host_signal" in ANCHOR
    assert "sum_wake_sent" in ANCHOR


def test_all_sum_widget_calls_use_compatibility_transport() -> None:
    for direct in (
        "callTool('sum_controller_status'",
        "callTool('sum_controller_set'",
        "callTool('sum_controller_log'",
        "callTool('sum_controller_tick'",
        "callTool('sum_host_signal'",
        "callTool('sum_wake_sent'",
    ):
        assert direct not in ANCHOR
    for routed in (
        "callSumTool('sum_controller_status'",
        "callSumTool('sum_controller_set'",
        "callSumTool('sum_controller_log'",
        "callSumTool('sum_controller_tick'",
        "callSumTool('sum_host_signal'",
        "callSumTool('sum_wake_sent'",
    ):
        assert routed in ANCHOR


def test_sum_uses_only_stable_get_state_set_state_transport() -> None:
    start = ANCHOR.index("async function callSumTool")
    end = ANCHOR.index("function text", start)
    block = ANCHOR[start:end]
    assert "callTool('get_state',{})" in block
    assert "callTool('set_state'" in block
    assert "transport_generation:sumTransportGeneration" in block
    assert "callTool(name" not in block
