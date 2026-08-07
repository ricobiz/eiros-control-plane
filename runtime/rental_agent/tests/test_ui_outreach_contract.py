from runtime.rental_agent import server


def test_ui_exposes_outreach_plan_queue_and_thread_state() -> None:
    html = server.APP_HTML_PATH.read_text(encoding="utf-8")
    for marker in (
        'id="outreachPlan"',
        'id="queueOutreach"',
        'id="outreachStatus"',
        'id="outreachPreview"',
        "rental_outreach_plan",
        "rental_contact_qualified",
        "rental_threads",
        "needs_channel",
    ):
        assert marker in html


def test_outreach_preview_uses_escaped_newlines_in_javascript() -> None:
    html = server.APP_HTML_PATH.read_text(encoding="utf-8")
    assert "join('\\n\\n')" in html
