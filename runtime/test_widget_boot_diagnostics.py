from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = (ROOT / "runtime" / "server_v2.py").read_text(encoding="utf-8")
ANCHOR = (ROOT / "runtime" / "pulse_anchor.html").read_text(encoding="utf-8")


def test_widget_boot_diagnostics_contract() -> None:
    assert 'PULSE_FRESH_URI = "ui://eiros/pulse-anchor-v5-7-self-diagnostic-pip.html"' in SERVER
    assert 'PULSE_FRESH_VERSION = "0.5.7-self-diagnostic-pip"' in SERVER
    assert 'WIDGET_MOUNT_ATTEMPTS_FILE' in SERVER
    assert 'name="open_pulse_v57"' in SERVER
    assert '"openai/outputTemplate": PULSE_FRESH_URI' in SERVER
    assert 'def widget_boot_status(' in SERVER
    assert 'call open_pulse_v59 exactly once' in SERVER
    assert 'call widget_boot_status with wait_seconds=5' in SERVER
    for stage in (
        "JS_STARTED",
        "BRIDGE_READY",
        "HEARTBEAT_OK",
        "PULSE_POLL_OK",
        "VIDEO_READY",
        "PIP_ACTIVE",
    ):
        assert stage in ANCHOR
    assert "boot_stages" in ANCHOR
    assert "sessionPrefix" in ANCHOR


if __name__ == "__main__":
    test_widget_boot_diagnostics_contract()
    print("widget boot diagnostics: ok")
