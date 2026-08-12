from pathlib import Path


def test_calibration_route_is_standalone_and_headless():
    text = Path("runtime/mastering_mcp_server.py").read_text(encoding="utf-8")
    assert '@mcp.custom_route("/api/calibration", methods=["GET"])' in text
    assert 'Path(__file__).with_name("mastering_calibration.html")' in text
    route_block = text[text.index('def api_calibration'):text.index('def api_health')]
    assert "HTMLResponse" in route_block
    assert "resourceUri" not in route_block
    assert "outputTemplate" not in route_block


def test_calibration_profile_routes_are_http_only():
    text = Path("runtime/mastering_mcp_server.py").read_text(encoding="utf-8")
    assert '@mcp.custom_route("/api/calibration/profile/save", methods=["POST", "OPTIONS"])' in text
    assert '@mcp.custom_route("/api/calibration/profile/load", methods=["POST", "OPTIONS"])' in text
    block = text[text.index('def api_calibration_profile_save'):text.index('def api_health')]
    assert "save_calibration_profile" in block
    assert "load_calibration_profile" in block
    assert "resourceUri" not in block
    assert "outputTemplate" not in block


def test_mic_loop_routes_are_standalone_http_only():
    text = Path("runtime/mastering_mcp_server.py").read_text(encoding="utf-8")
    assert '@mcp.custom_route("/api/calibration/mic-loop", methods=["GET"])' in text
    assert '@mcp.custom_route("/api/calibration/mic-loop/analyze", methods=["POST", "OPTIONS"])' in text
    block = text[text.index('def api_calibration_mic_loop'):text.index('def api_health')]
    assert 'mastering_mic_loop.html' in block
    assert 'analyze_mic_loop_recordings' in block
    assert 'resourceUri' not in block
    assert 'outputTemplate' not in block


def test_mic_loop_page_contract():
    page = Path("runtime/mastering_mic_loop.html")
    assert page.exists()
    text = page.read_text(encoding="utf-8")
    for token in [
        "E-MASTER MIC LOOP",
        "getUserMedia",
        "enumerateDevices",
        "MediaRecorder",
        "echoCancellation:false",
        "noiseSuppression:false",
        "autoGainControl:false",
        "createGain",
        "BACKGROUND 5s",
        "BASELINE A",
        "BASELINE B",
        "STRESS",
        "SEAL",
        "BASS CONFIDENCE",
        "bass_confidence",
        "background",
        "baseline_a",
        "baseline_b",
        "stress",
        "API+'/list?limit=30'",
        "API+'/download?asset_id='",
        "API+'/calibration/mic-loop/analyze'",
        "clipStart:92.5",
        "clipDuration:20",
        "visibilitychange",
        "pagehide",
    ]:
        assert token in text


def test_mic_loop_baseline_level_is_user_adjustable():
    text = Path("runtime/mastering_mic_loop.html").read_text(encoding="utf-8")
    assert 'id="baseline-level"' in text
    assert 'id="baseline-db"' in text
    assert 'value="-9"' in text
    assert "Number(baselineLevel.value)" in text
    assert "cfg.baselineDb" not in text


def test_mic_loop_capture_reuses_one_open_microphone_stream():
    text = Path("runtime/mastering_mic_loop.html").read_text(encoding="utf-8")
    capture_start = text.index("async function capture")
    capture_end = text.index("function addBlob", capture_start)
    capture_block = text[capture_start:capture_end]
    assert "ensureMic(" not in capture_block
    assert "if(!micStream)" in capture_block
    assert "Сначала нажми MIC" in capture_block


def test_mic_loop_sends_captured_levels_and_renders_level_validation():
    text = Path("runtime/mastering_mic_loop.html").read_text(encoding="utf-8")
    for token in [
        "captureLevels",
        "baseline_db",
        "stress_db",
        "EXPECTED",
        "MEASURED",
        "MISMATCH",
        "TEST INVALID · LEVEL MISMATCH",
    ]:
        assert token in text
    assert "captureLevels[kind]=Number(db)" in text


def test_mic_loop_route_passes_expected_gain_from_recorded_levels():
    text = Path("runtime/mastering_mcp_server.py").read_text(encoding="utf-8")
    block = text[text.index("def api_calibration_mic_loop_analyze"):text.index("def api_health")]
    assert 'form.get("baseline_db")' in block
    assert 'form.get("stress_db")' in block
    assert "expected_gain_db" in block
