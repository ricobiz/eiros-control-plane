import httpx

from runtime.rental_agent.scout.kiengiang_agency import KienGiangAgencyAdapter


INDEX_HTML = '''
<html><body>
<a href="https://batdongsan.kiengiang.vn/cho-thue-shophouse-the-center-phu-quoc/">Cho thuê Shophouse The Center Phú Quốc</a>
<a href="https://batdongsan.kiengiang.vn/cho-thue-shophouse-nha-pho-thuong-mai-nha-mat-pho-sun-grand-city-new-an-thoi/">Cho thuê Sun Grand City New An Thới</a>
<a href="https://batdongsan.kiengiang.vn/cho-thue-shophouse-dia-trung-hai-sun-group-phu-quoc/">Cho thuê shophouse Địa Trung Hải</a>
<a href="https://batdongsan.kiengiang.vn/cho-thue-sang-nhuong-cua-hang-ki-ot-shophouse-grand-world-phu-quoc/">Grand World</a>
</body></html>
'''

DETAILS = {
    "/cho-thue-shophouse-the-center-phu-quoc/": '''<html><head><title>Cho thuê Shophouse The Center Phú Quốc</title></head><body>
    Shophouse The Center Phú Quốc 5 tầng, An Thới, Phú Quốc. Liên hệ Hotline: 0941235578.
    </body></html>''',
    "/cho-thue-shophouse-nha-pho-thuong-mai-nha-mat-pho-sun-grand-city-new-an-thoi/": '''<html><head><title>Cho thuê Sun Grand City New An Thới</title></head><body>
    Sun Grand City New An Thới nhà phố 5 tầng nguyên căn. Dãy L1 L2 L3 giá thuê từ 25 triệu/tháng. Hotline 0941235578.
    </body></html>''',
    "/cho-thue-shophouse-dia-trung-hai-sun-group-phu-quoc/": '''<html><head><title>Cho thuê shophouse Địa Trung Hải Sun Group Phú Quốc</title></head><body>
    Shophouse Địa Trung Hải Sunset Town, An Thới, Phú Quốc, 5 tầng. Hotline: 0941235578.
    </body></html>''',
}


def _transport(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/thue-shophouse-phu-quoc/":
        return httpx.Response(200, text=INDEX_HTML, request=request)
    if request.url.path in DETAILS:
        return httpx.Response(200, text=DETAILS[request.url.path], request=request)
    return httpx.Response(404, text="missing", request=request)


def test_kiengiang_agency_discovers_only_relevant_south_phu_quoc_inventory() -> None:
    client = httpx.Client(transport=httpx.MockTransport(_transport))
    result = KienGiangAgencyAdapter(client=client).discover(limit=10)

    assert result.status == "ok"
    assert len(result.listings) == 3
    assert all(item.source == "kiengiang_agency" for item in result.listings)
    assert all("Grand World" not in item.title for item in result.listings)
    assert any("New An Thới" in item.title for item in result.listings)


def test_kiengiang_agency_preserves_phone_and_rental_facts_in_detail_text() -> None:
    client = httpx.Client(transport=httpx.MockTransport(_transport))
    result = KienGiangAgencyAdapter(client=client).discover(limit=10)
    new_an_thoi = next(item for item in result.listings if "New An Thới" in item.title)

    assert "25 triệu/tháng" in new_an_thoi.text
    assert "0941235578" in new_an_thoi.text
    assert "5 tầng" in new_an_thoi.text
