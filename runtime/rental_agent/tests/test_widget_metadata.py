from runtime.rental_agent import server


def test_widget_metadata_has_submission_ready_domain_and_csp() -> None:
    origin = server.WIDGET_ORIGIN
    assert origin.startswith("https://")

    ui = server.APP_META["ui"]
    assert ui["domain"] == origin
    assert ui["csp"]["connectDomains"] == [origin]
    assert ui["csp"]["resourceDomains"] == [origin]

    assert server.APP_META["openai/widgetDomain"] == origin
    assert server.APP_META["openai/widgetCSP"] == {
        "connect_domains": [origin],
        "resource_domains": [origin],
    }
