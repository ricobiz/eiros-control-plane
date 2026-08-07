from pathlib import Path

from runtime.rental_agent.db import RentalDatabase
from runtime.rental_agent.scout.base import AdapterResult, DiscoveredListing
from runtime.rental_agent.scout.service import ScoutService


class FakeAdapter:
    def __init__(self, name: str, listings: tuple[DiscoveredListing, ...], status: str = "ok") -> None:
        self.name = name
        self._result = AdapterResult(source=name, status=status, listings=listings)

    def discover(self, limit: int = 10) -> AdapterResult:
        return AdapterResult(
            source=self.name,
            status=self._result.status,
            listings=self._result.listings[:limit],
            errors=self._result.errors,
        )


def listing(source: str, url: str, text: str, *, title: str | None = None) -> DiscoveredListing:
    return DiscoveredListing(source=source, url=url, title=title or text.split(" giá ")[0], text=text)


def test_search_run_normalizes_dedups_ranks_and_persists(tmp_path: Path) -> None:
    db = RentalDatabase(tmp_path / "rental.db")
    db.initialize()
    first = FakeAdapter(
        "one",
        (
            listing("one", "https://a.test/1", "Nguyên căn Sunset Town Phú Quốc 5 tầng 120m2 giá 22 triệu/tháng", title="Sunset Town S5-12"),
            listing("one", "https://a.test/2", "Nguyên căn Primavera Phú Quốc 4 tầng 110m2 giá 45 triệu/tháng"),
        ),
    )
    second = FakeAdapter(
        "two",
        (listing("two", "https://b.test/9", "Sunset Town Phu Quoc whole building 5 floors 120 m2 rent 25 million VND/month", title="Sunset Town S5-12"),),
    )
    scout = ScoutService(db, adapters=(first, second))

    summary = scout.run(limit_per_source=10)

    assert summary["status"] == "ok"
    assert summary["discovered_count"] == 3
    assert summary["canonical_count"] == 2
    assert summary["merged_count"] == 1
    assert summary["qualified_count"] == 1
    assert summary["rejected_count"] == 1
    assert len(db.list_properties()) == 2
    assert db.list_search_runs(limit=1)[0]["run_id"] == summary["run_id"]


def test_search_can_select_source_subset(tmp_path: Path) -> None:
    db = RentalDatabase(tmp_path / "rental.db")
    db.initialize()
    one = FakeAdapter("one", (listing("one", "https://a.test/1", "Sunset Town Phú Quốc nguyên căn 5 tầng 120m2 giá 22 triệu/tháng"),))
    two = FakeAdapter("two", (listing("two", "https://b.test/1", "Primavera Phú Quốc nguyên căn 5 tầng 120m2 giá 23 triệu/tháng"),))
    scout = ScoutService(db, adapters=(one, two))

    summary = scout.run(sources=("two",), limit_per_source=5)
    assert summary["sources"] == [{"source": "two", "status": "ok", "count": 1, "errors": []}]
    assert len(db.list_properties()) == 1


def test_partial_source_failure_keeps_good_results(tmp_path: Path) -> None:
    db = RentalDatabase(tmp_path / "rental.db")
    db.initialize()
    good = FakeAdapter("good", (listing("good", "https://a.test/1", "Sunset Town Phú Quốc nguyên căn 5 tầng 120m2 giá 22 triệu/tháng"),))
    blocked = FakeAdapter("blocked", (), status="needs_browser")
    scout = ScoutService(db, adapters=(good, blocked))

    summary = scout.run(limit_per_source=5)
    assert summary["status"] == "partial"
    assert summary["canonical_count"] == 1
    assert summary["needs_browser_sources"] == ["blocked"]


def test_scout_escalates_needs_browser_adapter_when_browser_worker_is_available(tmp_path: Path) -> None:
    import re
    from runtime.rental_agent.browser import BrowserPage, BrowserWorker

    class BrowserOnlyAdapter(FakeAdapter):
        seed_urls = ("https://browser.test/search",)
        HOSTS = {"browser.test"}
        DETAIL_PATTERN = re.compile(r"/listing/\d+$")

    adapter = BrowserOnlyAdapter("browseronly", (), status="needs_browser")

    def loader(url: str) -> BrowserPage:
        if url.endswith("/search"):
            return BrowserPage(url=url, final_url=url, title="Search", html='<a href="/listing/1">listing</a>')
        return BrowserPage(
            url=url,
            final_url=url,
            title="Sunset",
            html="<html>Nguyên căn Sunset Town Phú Quốc 5 tầng 120m2 giá 22 triệu/tháng</html>",
        )

    db = RentalDatabase(tmp_path / "rental.db")
    db.initialize()
    worker = BrowserWorker(profile_dir=tmp_path / "profile", loader=loader)
    scout = ScoutService(db, adapters=(adapter,), browser_worker=worker)
    summary = scout.run(limit_per_source=3)
    assert summary["status"] == "ok"
    assert summary["canonical_count"] == 1
    assert summary["needs_browser_sources"] == []


def test_scout_reports_human_verification_source(tmp_path: Path) -> None:
    import re
    from runtime.rental_agent.browser import BrowserPage, BrowserWorker

    class BrowserOnlyAdapter(FakeAdapter):
        seed_urls = ("https://verify.test/search",)
        HOSTS = {"verify.test"}
        DETAIL_PATTERN = re.compile(r"/listing/\d+$")

    adapter = BrowserOnlyAdapter("verify", (), status="needs_browser")
    worker = BrowserWorker(
        profile_dir=tmp_path / "profile",
        loader=lambda url: BrowserPage(url=url, final_url=url, title="Verify", html="Verify you are human CAPTCHA"),
    )
    db = RentalDatabase(tmp_path / "rental.db")
    db.initialize()
    summary = ScoutService(db, adapters=(adapter,), browser_worker=worker).run(limit_per_source=3)
    assert summary["status"] == "needs_user_action"
    assert summary["needs_user_action_sources"] == ["verify"]


def test_scout_surfaces_browser_runtime_error_instead_of_hiding_it(tmp_path: Path) -> None:
    import re
    from runtime.rental_agent.browser import BrowserWorker

    class BrowserOnlyAdapter(FakeAdapter):
        seed_urls = ("https://broken.test/search",)
        HOSTS = {"broken.test"}
        DETAIL_PATTERN = re.compile(r"/listing/\d+$")

    adapter = BrowserOnlyAdapter("broken", (), status="needs_browser")

    def broken_loader(url: str):
        raise RuntimeError("chromium launch failed")

    worker = BrowserWorker(profile_dir=tmp_path / "profile", loader=broken_loader)
    db = RentalDatabase(tmp_path / "rental.db")
    db.initialize()
    summary = ScoutService(db, adapters=(adapter,), browser_worker=worker).run(limit_per_source=3)
    assert summary["status"] == "browser_error"
    assert summary["sources"][0]["status"] == "browser_error"
    assert "chromium launch failed" in summary["sources"][0]["errors"][0]
