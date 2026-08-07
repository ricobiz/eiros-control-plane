from __future__ import annotations

import re

import httpx

from runtime.rental_agent.scout.base import AdapterResult
from runtime.rental_agent.scout.common import classify_response, combine_statuses, fetch_listing, make_client
from runtime.rental_agent.scout.html import extract_page, filter_links


class KienGiangAgencyAdapter:
    name = "kiengiang_agency"
    DEFAULT_SEED = "https://batdongsan.kiengiang.vn/thue-shophouse-phu-quoc/"
    HOSTS = {"batdongsan.kiengiang.vn", "www.batdongsan.kiengiang.vn"}
    DETAIL_PATTERN = re.compile(
        r"/(?:"
        r"cho-thue-shophouse-the-center-phu-quoc|"
        r"cho-thue-can-shophouse-the-center-tai-du-an-hillside-phu-quoc|"
        r"cho-thue-shophouse-nha-pho-thuong-mai-nha-mat-pho-sun-grand-city-new-an-thoi|"
        r"cho-thue-shophouse-dia-trung-hai-sun-group-phu-quoc"
        r")/?$",
        re.I,
    )

    def __init__(self, *, client: httpx.Client | None = None, seed_url: str | None = None) -> None:
        self.client = client or make_client()
        self.seed_url = seed_url or self.DEFAULT_SEED

    def discover(self, limit: int = 10) -> AdapterResult:
        bounded = max(1, min(int(limit), 30))
        statuses: list[str] = []
        errors: list[str] = []
        try:
            response = self.client.get(self.seed_url, follow_redirects=True, timeout=12.0)
        except httpx.HTTPError as exc:
            return AdapterResult(
                source=self.name,
                status="source_error",
                listings=(),
                errors=(f"{type(exc).__name__}: {exc}",),
            )

        status = classify_response(response)
        statuses.append(status)
        if status != "ok":
            return AdapterResult(
                source=self.name,
                status=status,
                listings=(),
                errors=(f"HTTP {response.status_code}: {self.seed_url}",),
            )

        page = extract_page(response.text, str(response.url))
        detail_urls = filter_links(
            page,
            hosts=self.HOSTS,
            pattern=self.DETAIL_PATTERN,
            limit=bounded,
        )

        listings = []
        for url in detail_urls:
            detail_status, listing, error = fetch_listing(self.client, self.name, url)
            statuses.append(detail_status)
            if listing is not None:
                listings.append(listing)
            if error:
                errors.append(error)

        return AdapterResult(
            source=self.name,
            status=combine_statuses(statuses, len(listings)),
            listings=tuple(listings),
            errors=tuple(errors),
        )
