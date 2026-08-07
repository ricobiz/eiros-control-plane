from __future__ import annotations

import httpx

from runtime.rental_agent.scout.base import AdapterResult
from runtime.rental_agent.scout.common import combine_statuses, fetch_listing, make_client


class SeedUrlAdapter:
    """Fetch explicitly configured public listing URLs outside first-class sources."""
    name = "public_web"

    def __init__(self, urls: tuple[str, ...], *, client: httpx.Client | None = None) -> None:
        self.urls = urls
        self.client = client or make_client()

    def discover(self, limit: int = 10) -> AdapterResult:
        listings = []
        statuses = []
        errors = []
        for url in self.urls[: max(1, min(int(limit), 50))]:
            status, listing, error = fetch_listing(self.client, self.name, url)
            statuses.append(status)
            if listing:
                listings.append(listing)
            if error:
                errors.append(error)
        return AdapterResult(
            source=self.name,
            status=combine_statuses(statuses, len(listings)),
            listings=tuple(listings),
            errors=tuple(errors),
        )
