from __future__ import annotations

from collections.abc import Iterable

import httpx

from runtime.rental_agent.scout.base import AdapterResult, DiscoveredListing
from runtime.rental_agent.scout.html import extract_page


DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; EIROSRentalAgent/1.0; +market-discovery)",
    "Accept-Language": "vi,en;q=0.8",
}


def classify_response(response: httpx.Response) -> str:
    if response.status_code == 429:
        return "rate_limited"
    text = response.text.lower()
    if response.status_code in {401, 403}:
        return "needs_browser"
    if any(marker in text for marker in ("captcha", "verify you are human", "cloudflare challenge", "access denied")):
        return "needs_browser"
    if response.status_code >= 500:
        return "source_error"
    if response.status_code >= 400:
        return "source_changed"
    return "ok"


def fetch_listing(client: httpx.Client, source: str, url: str) -> tuple[str, DiscoveredListing | None, str | None]:
    try:
        response = client.get(url, headers=DEFAULT_HEADERS, follow_redirects=True, timeout=12.0)
    except httpx.HTTPError as exc:
        return "source_error", None, f"{type(exc).__name__}: {exc}"
    status = classify_response(response)
    if status != "ok":
        return status, None, f"HTTP {response.status_code}: {url}"
    page = extract_page(response.text, str(response.url))
    if len(page.text) < 40:
        return "source_changed", None, f"listing page too small: {url}"
    return "ok", DiscoveredListing(source=source, url=str(response.url), title=page.title, text=page.text), None


def combine_statuses(statuses: Iterable[str], listings_count: int) -> str:
    values = tuple(statuses)
    if listings_count:
        return "ok"
    for preferred in ("rate_limited", "needs_browser", "source_error", "source_changed"):
        if preferred in values:
            return preferred
    return "ok"


def make_client() -> httpx.Client:
    return httpx.Client(headers=DEFAULT_HEADERS, follow_redirects=True, timeout=12.0)
