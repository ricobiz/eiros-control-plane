from runtime.rental_agent import server


def test_ui_exposes_scout_controls_and_status_markers() -> None:
    html = server.APP_HTML_PATH.read_text(encoding="utf-8")
    for marker in (
        'id="scout"',
        'id="searchStatus"',
        "rental_search",
        "latest_search",
        "fit_dimensions",
        "source_count",
    ):
        assert marker in html


def test_ui_exposes_human_verification_handoff_controls() -> None:
    html = server.APP_HTML_PATH.read_text(encoding="utf-8")
    for marker in (
        'id="browserPanel"',
        'id="browserShot"',
        'data-source="batdongsan"',
        'data-source="nhatot"',
        "rental_browser_snapshot",
        "rental_browser_click",
    ):
        assert marker in html
