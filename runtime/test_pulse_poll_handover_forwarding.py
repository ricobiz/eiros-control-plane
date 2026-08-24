from __future__ import annotations

from unittest.mock import patch

from runtime import server_v2


def test_pulse_poll_forwards_pip_handover_readiness_to_event_engine() -> None:
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
