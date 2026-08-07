from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

from runtime.rental_agent.config import DEFAULT_DB_PATH, DEFAULT_HOST, DEFAULT_PORT
from runtime.rental_agent.db import RentalDatabase
from runtime.rental_agent.service import RentalService

SERVER_NAME = "EIROS Rental Agent"
SERVER_HOST = DEFAULT_HOST
SERVER_PORT = DEFAULT_PORT
APP_URI = "ui://eiros-rental/app-v1.html"
APP_HTML_PATH = Path(__file__).resolve().parent / "ui" / "app.html"
APP_META: dict[str, Any] = {
    "ui": {
        "prefersBorder": True,
        "csp": {"connectDomains": [], "resourceDomains": []},
    },
    "openai/widgetDescription": "EIROS Rental Agent — shortlist, properties and discovery status.",
    "openai/widgetCSP": {"connect_domains": [], "resource_domains": []},
}

mcp = FastMCP(
    SERVER_NAME,
    instructions=(
        "Dedicated rental discovery connector. Use it to ingest, inspect and shortlist rental leads. "
        "Current authority is market discovery only: do not negotiate, schedule viewings, make commitments, "
        "agree deposits, send money or accept contracts."
    ),
    stateless_http=True,
    json_response=True,
    host=SERVER_HOST,
    port=SERVER_PORT,
    transport_security=TransportSecuritySettings(
        allowed_hosts=[
            "127.0.0.1",
            "127.0.0.1:*",
            "localhost",
            "localhost:*",
        ],
        allowed_origins=[
            "http://127.0.0.1",
            "http://127.0.0.1:*",
            "http://localhost",
            "http://localhost:*",
            "https://chatgpt.com",
            "https://chat.openai.com",
            "https://platform.openai.com",
        ],
    ),
)


@lru_cache(maxsize=1)
def _service() -> RentalService:
    return RentalService(RentalDatabase(Path(DEFAULT_DB_PATH)))


READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    openWorldHint=False,
    destructiveHint=False,
    idempotentHint=True,
)
WRITE_IDEMPOTENT = ToolAnnotations(
    readOnlyHint=False,
    openWorldHint=False,
    destructiveHint=False,
    idempotentHint=True,
)


@mcp.resource(
    APP_URI,
    name="EIROS Rental Agent App",
    title="EIROS Rental Agent",
    description="In-chat rental discovery status, shortlist and lead ingest.",
    mime_type="text/html;profile=mcp-app",
    meta=APP_META,
)
def rental_app_resource() -> str:
    return APP_HTML_PATH.read_text(encoding="utf-8")


@mcp.tool(
    name="rental_status",
    title="Rental Agent status",
    description="Read Rental Agent database and policy status.",
    annotations=READ_ONLY,
    structured_output=True,
)
def rental_status() -> dict[str, Any]:
    return _service().status()


@mcp.tool(
    name="rental_ingest_text",
    title="Ingest rental text lead",
    description="Persist a rental lead supplied as plain text without fetching external sources.",
    annotations=WRITE_IDEMPOTENT,
    structured_output=True,
)
def rental_ingest_text(text: str, context: str = "") -> dict[str, Any]:
    return _service().ingest_text(text, context=context)


@mcp.tool(
    name="rental_ingest_url",
    title="Ingest rental URL lead",
    description="Persist a rental listing URL and provenance. Autonomous fetching is added by Scout later.",
    annotations=WRITE_IDEMPOTENT,
    structured_output=True,
)
def rental_ingest_url(url: str, context: str = "") -> dict[str, Any]:
    return _service().ingest_url(url, context=context)


@mcp.tool(
    name="rental_ingest_phone",
    title="Ingest rental phone lead",
    description="Persist a phone/contact lead tied to rental discovery context.",
    annotations=WRITE_IDEMPOTENT,
    structured_output=True,
)
def rental_ingest_phone(phone: str, context: str = "") -> dict[str, Any]:
    return _service().ingest_phone(phone, context=context)


@mcp.tool(
    name="rental_property",
    title="Read rental property",
    description="Read one canonical rental property record by property id.",
    annotations=READ_ONLY,
    structured_output=True,
)
def rental_property(property_id: str) -> dict[str, Any]:
    record = _service().property(property_id)
    return {"found": record is not None, "property": record}


@mcp.tool(
    name="rental_shortlist",
    title="Rental shortlist",
    description="List canonical rental properties ordered by fit score and freshness.",
    annotations=READ_ONLY,
    structured_output=True,
)
def rental_shortlist(limit: int = 20) -> dict[str, Any]:
    rows = _service().shortlist(limit=max(1, min(int(limit), 100)))
    return {"count": len(rows), "properties": rows}


@mcp.tool(
    name="rental_policy",
    title="Rental authority policy",
    description="Read the current Rental Agent action and disclosure policy.",
    annotations=READ_ONLY,
    structured_output=True,
)
def rental_policy() -> dict[str, object]:
    return _service().policy()


@mcp.tool(
    name="rental_open_app",
    title="Open Rental Agent",
    description="Open the Rental Agent MCP App card inside ChatGPT.",
    annotations=READ_ONLY,
    meta={
        "ui": {"resourceUri": APP_URI, "visibility": ["model", "app"]},
        "openai/outputTemplate": APP_URI,
        "openai/toolInvocation/invoking": "Opening EIROS Rental Agent…",
        "openai/toolInvocation/invoked": "EIROS Rental Agent opened.",
    },
    structured_output=True,
)
def rental_open_app() -> dict[str, str]:
    return {"resource_uri": APP_URI, "status": "ready"}


if __name__ == "__main__":
    _service()
    mcp.run(transport="streamable-http")
