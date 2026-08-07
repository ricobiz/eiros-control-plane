from pathlib import Path

import httpx

from runtime.rental_agent.scout.batdongsan import BatdongsanAdapter
from runtime.rental_agent.scout.html import extract_page
from runtime.rental_agent.scout.nhatot import NhaTotAdapter

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_extract_page_collapses_visible_text_and_title() -> None:
    page = extract_page(fixture("batdongsan_detail.html"), "https://batdongsan.com.vn/x")
    assert page.title == "Cho thuê shophouse tại khu Sunset Town"
    assert "22 triệu/tháng" in page.text
    assert "120 m²" in page.text


def test_batdongsan_adapter_discovers_and_fetches_detail() -> None:
    search_url = BatdongsanAdapter.DEFAULT_SEEDS[0]
    detail_url = "https://batdongsan.com.vn/cho-thue-shophouse-nha-pho-thuong-mai-phuong-an-thoi_1-the-sunset/cho-tai-khu-town-pr45993224"

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == search_url:
            return httpx.Response(200, text=fixture("batdongsan_search.html"), request=request)
        if str(request.url) == detail_url:
            return httpx.Response(200, text=fixture("batdongsan_detail.html"), request=request)
        return httpx.Response(404, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = BatdongsanAdapter(client=client, seed_urls=(search_url,)).discover(limit=5)
    assert result.status == "ok"
    assert len(result.listings) == 1
    assert result.listings[0].url == detail_url
    assert "22 triệu/tháng" in result.listings[0].text


def test_nhatot_adapter_discovers_detail_link_pattern() -> None:
    search_url = NhaTotAdapter.DEFAULT_SEEDS[0]
    detail_url = "https://www.nhatot.com/sang-nhuong-van-phong-mat-bang-kinh-doanh-thanh-pho-phu-quoc-kien-giang/133509529.htm"

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == search_url:
            return httpx.Response(200, text=fixture("nhatot_search.html"), request=request)
        if str(request.url) == detail_url:
            return httpx.Response(200, text=fixture("nhatot_detail.html"), request=request)
        return httpx.Response(404, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = NhaTotAdapter(client=client, seed_urls=(search_url,)).discover(limit=5)
    assert result.status == "ok"
    assert len(result.listings) == 1
    assert result.listings[0].url == detail_url
    assert "80 triệu/tháng" in result.listings[0].text


def test_adapter_marks_challenge_as_needs_browser() -> None:
    search_url = BatdongsanAdapter.DEFAULT_SEEDS[0]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="Verify you are human CAPTCHA", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = BatdongsanAdapter(client=client, seed_urls=(search_url,)).discover(limit=5)
    assert result.status == "needs_browser"
    assert result.listings == ()


def test_adapter_marks_429_as_rate_limited() -> None:
    search_url = NhaTotAdapter.DEFAULT_SEEDS[0]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="too many requests", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = NhaTotAdapter(client=client, seed_urls=(search_url,)).discover(limit=5)
    assert result.status == "rate_limited"
