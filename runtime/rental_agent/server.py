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
WIDGET_ORIGIN = "https://eiros.br-be.com"
APP_META: dict[str, Any] = {
    "ui": {
        "prefersBorder": True,
        "domain": WIDGET_ORIGIN,
        "csp": {
            "connectDomains": [WIDGET_ORIGIN],
            "resourceDomains": [WIDGET_ORIGIN],
        },
    },
    "openai/widgetDescription": "EIROS Rental Agent — shortlist, properties and discovery status.",
    "openai/widgetDomain": WIDGET_ORIGIN,
    "openai/widgetCSP": {
        "connect_domains": [WIDGET_ORIGIN],
        "resource_domains": [WIDGET_ORIGIN],
    },
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
SEARCH_WRITE = ToolAnnotations(
    readOnlyHint=False,
    openWorldHint=True,
    destructiveHint=False,
    idempotentHint=False,
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
    name="rental_search",
    title="Search rental market",
    description="Run a bounded autonomous public-market discovery pass, normalize, deduplicate and rank results.",
    annotations=SEARCH_WRITE,
    structured_output=True,
)
def rental_search(sources: list[str] | None = None, limit: int = 10) -> dict[str, Any]:
    return _service().search(sources=sources, limit=max(1, min(int(limit), 30)))


@mcp.tool(
    name="rental_sources",
    title="Rental property sources",
    description="Read all preserved source listings and provenance for one canonical property.",
    annotations=READ_ONLY,
    structured_output=True,
)
def rental_sources(property_id: str) -> dict[str, Any]:
    rows = _service().sources(property_id)
    return {"property_id": property_id, "count": len(rows), "sources": rows}


@mcp.tool(
    name="rental_refresh",
    title="Refresh rental property",
    description="Re-fetch known public listing URLs for one property and update normalized facts without contacting anyone.",
    annotations=SEARCH_WRITE,
    structured_output=True,
)
def rental_refresh(property_id: str) -> dict[str, Any]:
    return _service().refresh(property_id)


@mcp.tool(
    name="rental_browser_status",
    title="Rental source browser status",
    description="Read the isolated rental search browser handoff state and allowlisted verification sources.",
    annotations=READ_ONLY,
    structured_output=True,
)
def rental_browser_status() -> dict[str, object]:
    return _service().browser_status()


@mcp.tool(
    name="rental_browser_snapshot",
    title="Open rental source verification",
    description="Open an allowlisted rental source in the persistent search browser and return a screenshot for manual human verification.",
    annotations=SEARCH_WRITE,
    structured_output=True,
)
def rental_browser_snapshot(source: str) -> dict[str, object]:
    return _service().browser_snapshot(source)


@mcp.tool(
    name="rental_browser_click",
    title="Click rental source verification",
    description="Apply one user-chosen coordinate click only while an allowlisted source is showing a detected human-verification page.",
    annotations=SEARCH_WRITE,
    structured_output=True,
)
def rental_browser_click(source: str, x: float, y: float) -> dict[str, object]:
    return _service().browser_click(source, x, y)


@mcp.tool(
    name="rental_browser_open",
    title="Open rental remote browser",
    description="Create or reuse a persistent remote-browser session for an allowlisted rental source.",
    annotations=SEARCH_WRITE,
    structured_output=True,
)
def rental_browser_open(source: str) -> dict[str, object]:
    return _service().browser_open(source)


@mcp.tool(
    name="rental_browser_frame",
    title="Read rental remote browser frame",
    description="Read the latest changed frame and status from a persistent rental browser session.",
    annotations=READ_ONLY,
    structured_output=True,
)
def rental_browser_frame(session_id: str, after_seq: int = 0) -> dict[str, object]:
    return _service().browser_frame(session_id, after_seq=max(0, int(after_seq)))


@mcp.tool(
    name="rental_browser_input",
    title="Control rental remote browser",
    description=(
        "Send pointer, scroll, key, text, back or reload input to a persistent rental browser session. "
        "When explicit human verification is active, user_gesture must be true and must originate from the user-facing app gesture."
    ),
    annotations=SEARCH_WRITE,
    structured_output=True,
)
def rental_browser_input(
    session_id: str,
    event_type: str,
    x: float = 0.0,
    y: float = 0.0,
    delta_x: float = 0.0,
    delta_y: float = 0.0,
    key: str = "",
    text: str = "",
    user_gesture: bool = False,
) -> dict[str, object]:
    return _service().browser_input(
        session_id,
        event_type,
        x=x,
        y=y,
        delta_x=delta_x,
        delta_y=delta_y,
        key=key,
        text=text,
        user_gesture=user_gesture,
    )


@mcp.tool(
    name="rental_browser_close",
    title="Close rental remote browser",
    description="Close one remote browser page/session while preserving the persistent browser profile and cookies.",
    annotations=WRITE_IDEMPOTENT,
    structured_output=True,
)
def rental_browser_close(session_id: str) -> dict[str, object]:
    return _service().browser_close(session_id)



@mcp.tool(
    name="rental_contacts",
    title="Rental property contacts",
    description="Read public contact methods associated with one rental property and their provenance.",
    annotations=READ_ONLY,
    structured_output=True,
)
def rental_contacts(property_id: str) -> dict[str, Any]:
    rows = _service().contacts(property_id)
    return {"property_id": property_id, "count": len(rows), "contacts": rows}


@mcp.tool(
    name="rental_outreach_plan",
    title="Plan rental discovery outreach",
    description="Dry-run discovery outreach for qualified leads, grouped by contact to avoid duplicate messages. Sends nothing.",
    annotations=READ_ONLY,
    structured_output=True,
)
def rental_outreach_plan(property_ids: list[str] | None = None) -> dict[str, Any]:
    return _service().outreach_plan(property_ids)


@mcp.tool(
    name="rental_contact_qualified",
    title="Queue qualified rental contacts",
    description="Create durable draft threads and deduplicated outreach jobs for qualified leads. Does not send until a channel is authenticated.",
    annotations=WRITE_IDEMPOTENT,
    structured_output=True,
)
def rental_contact_qualified(property_ids: list[str] | None = None) -> dict[str, Any]:
    return _service().contact_qualified(property_ids)


@mcp.tool(
    name="rental_threads",
    title="Rental outreach threads",
    description="List durable rental conversation threads, optionally filtered by property or status.",
    annotations=READ_ONLY,
    structured_output=True,
)
def rental_threads(property_id: str = "", status: str = "", limit: int = 100) -> dict[str, Any]:
    rows = _service().threads(property_id=property_id, status=status, limit=max(1, min(int(limit), 500)))
    return {"count": len(rows), "threads": rows}


@mcp.tool(
    name="rental_thread",
    title="Rental outreach thread",
    description="Read one durable rental conversation thread including linked properties and message ledger.",
    annotations=READ_ONLY,
    structured_output=True,
)
def rental_thread(thread_id: str) -> dict[str, Any]:
    row = _service().thread(thread_id)
    return {"found": row is not None, "thread": row}

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
