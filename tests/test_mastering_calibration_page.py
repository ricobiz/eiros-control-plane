from pathlib import Path

PAGE = Path("runtime/mastering_calibration.html")


def test_calibration_page_contract():
    text = PAGE.read_text(encoding="utf-8")
    for token in [
        "E-MASTER CAL",
        'id="start"',
        'id="limit"',
        "AudioContext",
        "visibilitychange",
        "pagehide",
        "EMasterCalibration",
        "testFrequencies",
        "frequencyMap",
        "rampDbPerSecond",
        "safeCeilingDb",
        "safeCeilingDb: 0",
        "requestAnimationFrame",
        "exponentialRampToValueAtTime",
    ]:
        assert token in text
