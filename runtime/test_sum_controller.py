from pathlib import Path

from runtime.sum_controller import SumControllerStore


def make_store(tmp_path: Path) -> SumControllerStore:
    return SumControllerStore(
        tmp_path / "sum-controller.json",
        tmp_path / "sum-controller.jsonl",
    )


def test_initial_state_is_disabled_gray(tmp_path: Path) -> None:
    store = make_store(tmp_path)

    state = store.status()

    assert state["enabled"] is False
    assert state["state"] == "IDLE"
    assert state["color"] == "gray"
    assert state["cycle_id"] == 0
    assert state["wake_id"] == ""


def test_enable_arms_controller_without_sending_wake(tmp_path: Path) -> None:
    store = make_store(tmp_path)

    state = store.set_enabled(
        True,
        actor="rico",
        listener_session_id="listener-1",
    )

    assert state["enabled"] is True
    assert state["state"] == "ARMED"
    assert state["color"] == "gray"
    assert state["cycle_id"] == 0
    assert state["wake_id"] == ""
    assert state["listener_session_id"] == "listener-1"


class FakeClock:
    def __init__(self, value: int = 100) -> None:
        self.value = value

    def __call__(self) -> int:
        return self.value

    def advance(self, seconds: int) -> None:
        self.value += seconds


def test_full_acknowledged_cycle_starts_next_wake(tmp_path: Path) -> None:
    clock = FakeClock()
    store = SumControllerStore(
        tmp_path / "sum-controller.json",
        tmp_path / "sum-controller.jsonl",
        clock=clock,
        static_debounce_seconds=3,
    )
    store.set_enabled(True, actor="rico", listener_session_id="listener-1")

    wake = store.tick("listener-1", pip_active=True, listener_healthy=True)

    assert wake["state"] == "WAKE"
    assert wake["color"] == "red"
    assert wake["cycle_id"] == 1
    assert wake["awake_epoch"] == 1
    assert wake["wake_id"].startswith("wake-")
    assert wake["send_required"] is True

    sent = store.mark_wake_sent("listener-1", "bridge-confirmed")
    assert sent["wake_attempt"] == 1
    assert sent["send_required"] is False
    assert sent["counters"]["wakes_sent"] == 1

    acked = store.ack_current(actor="chatgpt", listener_session_id="listener-1")
    assert acked["state"] == "AWAKE"
    assert acked["color"] == "green"
    assert acked["counters"]["wakes_acked"] == 1

    working = store.record_host_signal(
        "host-context",
        True,
        "listener-1",
        {"source": "test"},
    )
    assert working["state"] == "WORKING"
    assert working["color"] == "yellow"

    settling = store.record_host_signal(
        "host-context",
        False,
        "listener-1",
    )
    assert settling["state"] == "STATIC_DEBOUNCE"
    assert settling["color"] == "green"

    clock.advance(2)
    still_settling = store.tick("listener-1", pip_active=True, listener_healthy=True)
    assert still_settling["state"] == "STATIC_DEBOUNCE"

    clock.advance(1)
    next_wake = store.tick("listener-1", pip_active=True, listener_healthy=True)
    assert next_wake["state"] == "WAKE"
    assert next_wake["cycle_id"] == 2
    assert next_wake["awake_epoch"] == 2
    assert next_wake["wake_id"] != wake["wake_id"]
    assert next_wake["send_required"] is True


def test_ack_current_is_idempotent_after_success(tmp_path: Path) -> None:
    clock = FakeClock()
    store = SumControllerStore(
        tmp_path / "sum-controller.json",
        tmp_path / "sum-controller.jsonl",
        clock=clock,
    )
    store.set_enabled(True, actor="rico", listener_session_id="listener-1")
    store.tick("listener-1", pip_active=True, listener_healthy=True)
    store.mark_wake_sent("listener-1", "bridge-confirmed")

    first = store.ack_current(actor="chatgpt", listener_session_id="listener-1")
    second = store.ack_current(actor="chatgpt", listener_session_id="listener-1")

    assert second["state"] == "AWAKE"
    assert second["last_acked_wake_id"] == first["last_acked_wake_id"]
    assert second["counters"]["wakes_acked"] == 1
