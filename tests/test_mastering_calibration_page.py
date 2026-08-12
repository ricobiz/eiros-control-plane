from pathlib import Path

PAGE = Path("runtime/mastering_calibration.html")


def test_calibration_page_contract():
    text = PAGE.read_text(encoding="utf-8")
    for token in [
        "E-MASTER CAL",
        'id="start"',
        'id="level"',
        'id="ref"',
        'id="test"',
        'id="clean-limit"',
        'id="distort-limit"',
        'id="prev"',
        'id="next"',
        'id="profile-name"',
        'id="profile-code"',
        'id="save-profile"',
        'id="load-profile"',
        "Громкость устройства: MAX",
        "profile/save",
        "profile/load",
        'data-step="-1"',
        'data-step="1"',
        'data-step="-0.2"',
        'data-step="0.2"',
        "AudioContext",
        "visibilitychange",
        "pagehide",
        "EMasterCalibration",
        "testFrequencies",
        "frequencyMap",
        "referenceOffsetDb",
        "setTestLevel",
        "saveCleanLimit",
        "saveDistortLimit",
    ]:
        assert token in text
