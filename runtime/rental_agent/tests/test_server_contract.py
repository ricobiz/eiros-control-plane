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
