import re
from pathlib import Path

from runtime.rental_agent.browser import BrowserPage, BrowserWorker, discover_adapter_with_browser


class FakeAdapter:
    name = "fake"
    seed_urls = ("https://example.test/search",)
    HOSTS = {"example.test"}
    DETAIL_PATTERN = re.compile(r"/listing/\d+$")


def test_browser_worker_with_loader_uses_persistent_profile_and_returns_page(tmp_path: Path) -> None:
    def loader(url: str) -> BrowserPage:
        return BrowserPage(url=url, final_url=url, title="Listing", html="<html><body>whole building 22 million</body></html>")

    worker = BrowserWorker(profile_dir=tmp_path / "profile", loader=loader)
    status = worker.status()
    result = worker.fetch("https://example.test/listing/1")

    assert status["available"] is True
    assert status["profile_dir"] == str(tmp_path / "profile")
    assert result.status == "ok"
    assert "whole building" in result.text


def test_browser_worker_stops_at_human_verification(tmp_path: Path) -> None:
    def loader(url: str) -> BrowserPage:
        return BrowserPage(url=url, final_url=url, title="Verify", html="<html>Verify you are human CAPTCHA</html>")

    worker = BrowserWorker(profile_dir=tmp_path / "profile", loader=loader)
    result = worker.fetch("https://example.test/search")
    assert result.status == "needs_user_action"
    assert "verification" in result.error


def test_browser_discovers_detail_links_without_bypassing_challenges(tmp_path: Path) -> None:
    def loader(url: str) -> BrowserPage:
        if url.endswith("/search"):
            return BrowserPage(
                url=url,
                final_url=url,
                title="Search",
                html='<html><a href="/listing/1">one</a><a href="/help">help</a></html>',
            )
        return BrowserPage(
            url=url,
            final_url=url,
            title="Sunset Town",
            html="<html><body>Nguyên căn Sunset Town Phú Quốc 5 tầng 120m2 giá 22 triệu/tháng</body></html>",
        )

    worker = BrowserWorker(profile_dir=tmp_path / "profile", loader=loader)
    result = discover_adapter_with_browser(FakeAdapter(), worker, limit=5)
    assert result.status == "ok"
    assert len(result.listings) == 1
    assert result.listings[0].url == "https://example.test/listing/1"
