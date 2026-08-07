from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
import asyncio
from typing import Callable

from runtime.rental_agent.scout.base import AdapterResult, DiscoveredListing
from runtime.rental_agent.scout.html import extract_page, filter_links


@dataclass(slots=True, frozen=True)
class BrowserPage:
    url: str
    final_url: str
    title: str
    html: str


@dataclass(slots=True, frozen=True)
class BrowserFetchResult:
    status: str
    url: str
    final_url: str
    title: str
    text: str
    html: str
    error: str = ""


class BrowserWorker:
    def __init__(
        self,
        *,
        profile_dir: Path,
        loader: Callable[[str], BrowserPage] | None = None,
        headless: bool = True,
    ) -> None:
        self.profile_dir = Path(profile_dir)
        self.loader = loader
        self.headless = headless

    def status(self) -> dict[str, object]:
        available = self.loader is not None or self._playwright_available()
        return {
            "available": available,
            "profile_dir": str(self.profile_dir),
            "headless": self.headless,
            "backend": "loader" if self.loader is not None else ("playwright" if available else "missing"),
        }

    @staticmethod
    def _playwright_available() -> bool:
        try:
            import playwright.sync_api  # noqa: F401
        except Exception:
            return False
        return True

    @staticmethod
    def _verification_required(html: str, title: str) -> bool:
        text = f"{title}\n{html}".lower()
        markers = (
            "captcha",
            "verify you are human",
            "verification required",
            "security check",
            "challenge-platform",
            "cf-chl-",
        )
        return any(marker in text for marker in markers)

    def _load_playwright_direct(self, url: str) -> BrowserPage:
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                headless=self.headless,
                viewport={"width": 1440, "height": 1200},
                locale="vi-VN",
                timezone_id="Asia/Ho_Chi_Minh",
                args=["--disable-dev-shm-usage"],
            )
            try:
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=25_000)
                try:
                    page.wait_for_load_state("networkidle", timeout=5_000)
                except Exception:
                    pass
                return BrowserPage(
                    url=url,
                    final_url=page.url,
                    title=page.title(),
                    html=page.content(),
                )
            finally:
                context.close()

    def _load_playwright(self, url: str) -> BrowserPage:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return self._load_playwright_direct(url)

        # Playwright's sync API cannot run on a thread that already owns an
        # asyncio event loop (FastMCP/ASGI does). Keep the public Scout API
        # synchronous, but isolate the browser driver in its own bounded thread.
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="rental-browser") as executor:
            future = executor.submit(self._load_playwright_direct, url)
            return future.result(timeout=40)

    def fetch(self, url: str) -> BrowserFetchResult:
        if self.loader is None and not self._playwright_available():
            return BrowserFetchResult(
                status="needs_browser_runtime",
                url=url,
                final_url=url,
                title="",
                text="",
                html="",
                error="playwright runtime is not installed",
            )
        try:
            page = self.loader(url) if self.loader is not None else self._load_playwright(url)
        except Exception as exc:
            return BrowserFetchResult(
                status="browser_error",
                url=url,
                final_url=url,
                title="",
                text="",
                html="",
                error=f"{type(exc).__name__}: {exc}",
            )
        if self._verification_required(page.html, page.title):
            return BrowserFetchResult(
                status="needs_user_action",
                url=url,
                final_url=page.final_url,
                title=page.title,
                text="",
                html=page.html,
                error="human verification required; no bypass attempted",
            )
        extracted = extract_page(page.html, page.final_url)
        return BrowserFetchResult(
            status="ok",
            url=url,
            final_url=page.final_url,
            title=page.title or extracted.title,
            text=extracted.text,
            html=page.html,
        )


def discover_adapter_with_browser(adapter: object, worker: BrowserWorker, *, limit: int = 10) -> AdapterResult:
    bounded = max(1, min(int(limit), 30))
    seed_urls = tuple(getattr(adapter, "seed_urls", ()))
    hosts = set(getattr(adapter, "HOSTS", set()))
    pattern = getattr(adapter, "DETAIL_PATTERN", None)
    source = str(getattr(adapter, "name", "browser"))
    if not seed_urls or not hosts or pattern is None:
        return AdapterResult(
            source=source,
            status="source_changed",
            listings=(),
            errors=("adapter does not expose browser discovery contract",),
        )

    detail_urls: list[str] = []
    errors: list[str] = []
    status = "ok"
    for seed in seed_urls:
        if len(detail_urls) >= bounded:
            break
        fetched = worker.fetch(seed)
        if fetched.status != "ok":
            status = fetched.status
            errors.append(f"{seed}: {fetched.error or fetched.status}")
            if fetched.status == "needs_user_action":
                break
            continue
        page = extract_page(fetched.html, fetched.final_url)
        for url in filter_links(page, hosts=hosts, pattern=pattern, limit=bounded):
            if url not in detail_urls:
                detail_urls.append(url)
            if len(detail_urls) >= bounded:
                break

    listings: list[DiscoveredListing] = []
    if status != "needs_user_action":
        for url in detail_urls[:bounded]:
            fetched = worker.fetch(url)
            if fetched.status != "ok":
                if status == "ok":
                    status = fetched.status
                errors.append(f"{url}: {fetched.error or fetched.status}")
                continue
            listings.append(
                DiscoveredListing(
                    source=source,
                    url=fetched.final_url,
                    title=fetched.title,
                    text=fetched.text,
                )
            )
    if listings:
        status = "ok"
    return AdapterResult(source=source, status=status, listings=tuple(listings), errors=tuple(errors))
