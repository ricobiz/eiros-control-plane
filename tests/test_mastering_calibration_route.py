from pathlib import Path


def test_calibration_route_is_standalone_and_headless():
    text = Path("runtime/mastering_mcp_server.py").read_text(encoding="utf-8")
    assert '@mcp.custom_route("/api/calibration", methods=["GET"])' in text
    assert 'Path(__file__).with_name("mastering_calibration.html")' in text
    route_block = text[text.index('def api_calibration'):text.index('def api_health')]
    assert "HTMLResponse" in route_block
    assert "resourceUri" not in route_block
    assert "outputTemplate" not in route_block
