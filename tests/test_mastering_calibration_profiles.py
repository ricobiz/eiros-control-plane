import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
from runtime import mastering


def test_save_and_load_calibration_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(mastering, "CALIBRATION_ROOT", tmp_path)
    payload = {
        "schema_version": 1,
        "hardware_volume": "max",
        "reference_offset_db": 6,
        "frequency_map": {"63": {"hz": 63, "cleanLimitDb": -8.2, "distortLimitDb": -2.0}},
    }

    saved = mastering.save_calibration_profile("AirPods test", payload)

    assert saved["ok"] is True
    assert saved["code"].startswith("CAL-")
    path = tmp_path / f'{saved["code"]}.json'
    assert path.exists()
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["name"] == "AirPods test"
    assert stored["profile"]["hardware_volume"] == "max"

    loaded = mastering.load_calibration_profile(saved["code"].lower())
    assert loaded["ok"] is True
    assert loaded["code"] == saved["code"]
    assert loaded["profile"]["frequency_map"]["63"]["cleanLimitDb"] == -8.2


def test_calibration_profile_rejects_invalid_code(tmp_path, monkeypatch):
    monkeypatch.setattr(mastering, "CALIBRATION_ROOT", tmp_path)
    try:
        mastering.load_calibration_profile("../bad")
    except ValueError as exc:
        assert "Invalid calibration profile code" in str(exc)
    else:
        raise AssertionError("invalid calibration profile code must be rejected")
