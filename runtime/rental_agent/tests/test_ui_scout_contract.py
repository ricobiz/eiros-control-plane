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
