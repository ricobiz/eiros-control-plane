from pathlib import Path

PAGE = Path("runtime/mastering_calibration.html")


def test_calibration_page_contract():
    text = PAGE.read_text(encoding="utf-8")
    for token in [
        "E-MASTER CAL",
        'id="start"',
        'id="ok"',
        'id="no"',
        "AudioContext",
        "visibilitychange",
        "pagehide",
        "EMasterCalibration",
        "Math.sqrt",
    ]:
        assert token in text
