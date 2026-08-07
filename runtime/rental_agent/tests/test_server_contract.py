import asyncio

from runtime.rental_agent import server


EXPECTED_TOOLS = {
    "rental_status",
    "rental_ingest_text",
    "rental_ingest_url",
    "rental_ingest_phone",
    "rental_property",
    "rental_shortlist",
    "rental_policy",
    "rental_open_app",
    "rental_search",
    "rental_sources",
    "rental_refresh",
    "rental_browser_status",
    "rental_browser_snapshot",
    "rental_browser_click",
    "rental_contacts",
    "rental_outreach_plan",
    "rental_contact_qualified",
    "rental_threads",
    "rental_thread",
}


def test_dedicated_server_registers_foundation_tools() -> None:
    tools = asyncio.run(server.mcp.list_tools())
    assert {tool.name for tool in tools} == EXPECTED_TOOLS


def test_rental_app_uri_is_namespaced() -> None:
    assert server.APP_URI.startswith("ui://eiros-rental/")


def test_server_is_dedicated_streamable_http_configuration() -> None:
    assert server.SERVER_NAME == "EIROS Rental Agent"
    assert server.SERVER_HOST == "127.0.0.1"
    assert server.SERVER_PORT == 8794


def test_app_resource_registered_with_chatgpt_metadata() -> None:
    resources = asyncio.run(server.mcp.list_resources())
    assert server.APP_URI in {str(resource.uri) for resource in resources}
    assert server.APP_META["ui"] == {
        "prefersBorder": True,
        "domain": server.WIDGET_ORIGIN,
        "csp": {
            "connectDomains": [server.WIDGET_ORIGIN],
            "resourceDomains": [server.WIDGET_ORIGIN],
        },
    }
    assert server.APP_META["openai/widgetDescription"] == (
        "EIROS Rental Agent — shortlist, properties and discovery status."
    )

    open_tool = next(tool for tool in asyncio.run(server.mcp.list_tools()) if tool.name == "rental_open_app")
    assert open_tool.meta["ui"]["resourceUri"] == server.APP_URI
    assert open_tool.meta["openai/outputTemplate"] == server.APP_URI


def test_in_chat_app_contains_status_shortlist_and_ingest_controls() -> None:
    html = server.APP_HTML_PATH.read_text(encoding="utf-8")
    for marker in (
        "EIROS RENTAL AGENT",
        "Sunset Town",
        "rental_status",
        "rental_shortlist",
        "rental_ingest_text",
        "rental_ingest_url",
        "rental_ingest_phone",
    ):
        assert marker in html
