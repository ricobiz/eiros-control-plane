from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "runtime" / "server_v2.py").read_text(encoding="utf-8")


def test_connector_boot_protocol() -> None:
    assert "EIROS CONNECTOR BOOT PROTOCOL v1.0" in SOURCE
    assert "Call core_snapshot, project_state_get for eiros-hub" in SOURCE
    assert "Call sam_status, pulse_status, and room_telemetry_status" in SOURCE
    assert "If a live current-generation Wake Listener and live Pulse leader already exist, preserve them" in SOURCE
    assert "If no live Wake Listener or live Pulse leader exists, call open_pulse_v59 exactly once" in SOURCE
    assert "call widget_boot_status with wait_seconds=5" in SOURCE
    assert "Never call close_eiros_widgets automatically" in SOURCE
    assert "Treat wake as continuously ready only when video_pip_active=true and continuous_wake_ready=true" in SOURCE
    assert "Open Room only after Rico explicitly asks for Room" in SOURCE
    assert "Never mount duplicate Listener instances merely to chase UI colors" in SOURCE
    assert "call open_collab_room as the only UI-opening tool before answering" not in SOURCE


if __name__ == "__main__":
    test_connector_boot_protocol()
    print("connector boot protocol: ok")
