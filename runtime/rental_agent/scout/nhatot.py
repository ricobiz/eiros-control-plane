from __future__ import annotations

import re

import httpx

from runtime.rental_agent.scout.base import AdapterResult
from runtime.rental_agent.scout.common import classify_response, combine_statuses, fetch_listing, make_client
from runtime.rental_agent.scout.html import extract_page, filter_links


class NhaTotAdapter:
    name = "nhatot"
    DEFAULT_SEEDS = (
        "https://www.nhatot.com/thue-van-phong-mat-bang-kinh-doanh-thi-tran-an-thoi-thanh-pho-phu-quoc-kien-giang",
        "https://www.nhatot.com/thue-bat-dong-san-thi-tran-an-thoi-thanh-pho-phu-quoc-kien-giang",
    )
    DETAIL_PATTERN = re.compile(r"/[^/]+/\d+\.htm$", re.I)
    HOSTS = {"nhatot.com", "www.nhatot.com"}

    def __init__(self, *, client: httpx.Client | None = None, seed_urls: tuple[str, ...] | None = None) -> None:
        self.client = client or make_client()
        self.seed_urls = seed_urls or self.DEFAULT_SEEDS

    def discover(self, limit: int = 10) -> AdapterResult:
        bounded = max(1, min(int(limit), 50))
        detail_urls: list[str] = []
        statuses: list[str] = []
        errors: list[str] = []
        for seed in self.seed_urls:
            if len(detail_urls) >= bounded:
                break
            try:
                response = self.client.get(seed, follow_redirects=True, timeout=12.0)
            except httpx.HTTPError as exc:
                statuses.append("source_error")
                errors.append(f"{type(exc).__name__}: {exc}")
                continue
            status = classify_response(response)
            statuses.append(status)
            if status != "ok":
                errors.append(f"HTTP {response.status_code}: {seed}")
                continue
            page = extract_page(response.text, str(response.url))
            for url in filter_links(page, hosts=self.HOSTS, pattern=self.DETAIL_PATTERN, limit=bounded):
                if url not in detail_urls:
                    detail_urls.append(url)
                if len(detail_urls) >= bounded:
                    break
        listings = []
        for url in detail_urls[:bounded]:
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
