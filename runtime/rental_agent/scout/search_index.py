from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from runtime.rental_agent.scout.base import AdapterResult, DiscoveredListing
from runtime.rental_agent.scout.common import DEFAULT_HEADERS, classify_response, make_client


class _DuckDuckGoParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._capture_title = False
        self._capture_snippet = False
        self._title_parts: list[str] = []
        self._snippet_parts: list[str] = []
        self._href = ""

    @staticmethod
    def _classes(attrs: list[tuple[str, str | None]]) -> set[str]:
        value = dict(attrs).get("class") or ""
        return set(value.split())

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = self._classes(attrs)
        if tag == "a" and "result__a" in classes:
            self._capture_title = True
            self._title_parts = []
            self._href = dict(attrs).get("href") or ""
        if "result__snippet" in classes:
            self._capture_snippet = True
            self._snippet_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._capture_title:
            self.results.append({
                "href": self._href,
                "title": " ".join(self._title_parts).strip(),
                "snippet": "",
            })
            self._capture_title = False
            self._href = ""
            self._title_parts = []
        if self._capture_snippet and tag in {"a", "div", "span"}:
            if self.results:
                self.results[-1]["snippet"] = " ".join(self._snippet_parts).strip()
            self._capture_snippet = False
            self._snippet_parts = []

    def handle_data(self, data: str) -> None:
        value = " ".join(data.split())
        if not value:
            return
        if self._capture_title:
            self._title_parts.append(value)
        if self._capture_snippet:
            self._snippet_parts.append(value)


def _unwrap_ddg_url(href: str) -> str:
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if parsed.hostname in {"duckduckgo.com", "www.duckduckgo.com"} and parsed.path.startswith("/l/"):
        values = parse_qs(parsed.query).get("uddg") or []
        if values:
            return unquote(values[0])
    return href


def _is_detail_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path = parsed.path
    if host.endswith("batdongsan.com.vn"):
        return bool(re.search(r"-pr\d+$", path, flags=re.I))
    if host.endswith("nhatot.com"):
        return bool(re.search(r"/\d+\.htm$", path, flags=re.I))
    return False


class PublicWebSearchAdapter:
    name = "public_web"
    DDG_URL = "https://html.duckduckgo.com/html/"
    DEFAULT_QUERIES = (
        'site:batdongsan.com.vn "cho thuê" shophouse "Sunset Town" Phú Quốc',
        'site:batdongsan.com.vn "cho thuê" shophouse Primavera Phú Quốc',
        'site:batdongsan.com.vn "cho thuê" shophouse "The Center" "An Thới"',
        'site:batdongsan.com.vn "cho thuê" shophouse "New An Thới" Phú Quốc',
        'site:nhatot.com "cho thuê shophouse" "An Thới" "Phú Quốc"',
        'site:nhatot.com "Sunset Town" "Phú Quốc" "cho thuê"',
    )

    def __init__(self, *, client: httpx.Client | None = None, queries: tuple[str, ...] | None = None) -> None:
        self.client = client or make_client()
        self.queries = queries or self.DEFAULT_QUERIES

    def discover(self, limit: int = 10) -> AdapterResult:
        bounded = max(1, min(int(limit), 30))
        listings: list[DiscoveredListing] = []
        seen: set[str] = set()
        errors: list[str] = []
        statuses: list[str] = []
        for query in self.queries:
            if len(listings) >= bounded:
                break
            try:
                response = self.client.get(
                    self.DDG_URL,
                    params={"q": query},
                    headers=DEFAULT_HEADERS,
                    follow_redirects=True,
                    timeout=15.0,
                )
            except httpx.HTTPError as exc:
                statuses.append("source_error")
                errors.append(f"{type(exc).__name__}: {exc}")
                continue
            status = classify_response(response)
            statuses.append(status)
            if status != "ok":
                errors.append(f"HTTP {response.status_code}: search index")
                if status == "rate_limited":
                    break
                continue
            parser = _DuckDuckGoParser()
            parser.feed(response.text)
            for result in parser.results:
                target = _unwrap_ddg_url(result.get("href", ""))
                if not target or target in seen or not _is_detail_url(target):
                    continue
                seen.add(target)
                title = result.get("title", "").strip()
                snippet = result.get("snippet", "").strip()
                text = " ".join(part for part in (title, snippet) if part).strip()
                listings.append(
                    DiscoveredListing(source=self.name, url=target, title=title, text=text)
                )
                if len(listings) >= bounded:
                    break
        if listings:
            final_status = "ok"
        elif "rate_limited" in statuses:
            final_status = "rate_limited"
        elif "needs_browser" in statuses:
            final_status = "needs_browser"
        elif "source_error" in statuses:
            final_status = "source_error"
        else:
            final_status = "ok"
        return AdapterResult(
            source=self.name,
            status=final_status,
            listings=tuple(listings),
            errors=tuple(errors),
        )
