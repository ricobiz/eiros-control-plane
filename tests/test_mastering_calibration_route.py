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
