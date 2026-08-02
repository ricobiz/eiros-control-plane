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
