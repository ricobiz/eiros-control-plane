from runtime.rental_agent.normalize import normalize_listing


def test_normalizes_vietnamese_listing_facts() -> None:
    text = '''
    Cho thuê nguyên căn shophouse Sunset Town Phú Quốc.
    5 tầng, diện tích 120m2, giá 22 triệu/tháng.
    Cọc 2 tháng, hợp đồng tối thiểu 12 tháng.
    Liên hệ Zalo 0912 345 678.
    '''
    item = normalize_listing(text)
    assert item.monthly_rent_vnd == 22_000_000
    assert item.floors == 5
    assert item.area_m2 == 120.0
    assert item.deposit_months == 2.0
    assert item.lease_min_months == 12
    assert item.project_name == "Sunset Town"
    assert item.locality == "Phu Quoc"
    assert item.whole_building is True
    assert item.phones == ("+84912345678",)


def test_normalizes_compact_vietnamese_price_and_range() -> None:
    item = normalize_listing("Shophouse The Center An Thoi, 4 tầng, 105 m², thuê 25tr/tháng")
    assert item.monthly_rent_vnd == 25_000_000
    assert item.floors == 4
    assert item.area_m2 == 105.0
    assert item.project_name == "The Center"
    assert item.locality == "An Thoi"


def test_detects_whole_building_negative_clue() -> None:
    item = normalize_listing("Cho thuê 1 phòng trong khách sạn Sunset Town, tầng 3, 8 triệu/tháng")
    assert item.whole_building is False


def test_stable_fingerprint_ignores_whitespace_and_case() -> None:
    first = normalize_listing("SUNSET TOWN 5 tầng 120m2 giá 22 triệu/tháng")
    second = normalize_listing(" Sunset   Town 5 TẦNG 120 m2 GIÁ 22 TRIỆU / THÁNG ")
    assert first.text_fingerprint == second.text_fingerprint


def test_detects_floor_only_commercial_space_as_not_whole_building() -> None:
    item = normalize_listing("Cho Thuê Mặt Bằng Tầng 1 - Shophouse An Thoi 18 triệu/tháng 80m2")
    assert item.whole_building is False


def test_price_parser_ignores_per_square_meter_incentive() -> None:
    item = normalize_listing(
        "Cho thuê Shophouse The Center. Chủ đầu tư hỗ trợ hoàn thiện 3 triệu/m2 sàn. Hotline 0941235578"
    )
    assert item.monthly_rent_vnd is None


def test_price_parser_accepts_explicit_monthly_rent_context() -> None:
    item = normalize_listing("Nhà 5 tầng, giá thuê 25 triệu/tháng")
    assert item.monthly_rent_vnd == 25_000_000


def test_title_project_identity_wins_over_page_boilerplate() -> None:
    item = normalize_listing(
        "Sidebar mentions The Center and Sunset Town. Sun Grand City New An Thoi nhà phố 5 tầng.",
        title="Cho thuê Shophouse Sun Grand City New An Thới",
    )
    assert item.project_name == "New An Thoi"


def test_dia_trung_hai_title_maps_to_sunset_town() -> None:
    item = normalize_listing(
        "Trang có nhiều nội dung The Center và Primavera ở footer.",
        title="Cho thuê shophouse Địa Trung Hải Sun Group Phú Quốc",
    )
    assert item.project_name == "Sunset Town"


def test_multiple_distinct_monthly_prices_are_treated_as_ambiguous() -> None:
    item = normalize_listing(
        "Giỏ hàng: dãy AT giá thuê 35 triệu/tháng; dãy L1 giá thuê 25 triệu/tháng.",
        title="Giỏ hàng cho thuê New An Thới",
    )
    assert item.monthly_rent_vnd is None


def test_explicit_title_monthly_price_wins_over_ambiguous_body_portfolio_prices() -> None:
    item = normalize_listing(
        "Khu vực có căn 35 triệu/tháng và căn 25 triệu/tháng.",
        title="Cho thuê căn New An Thới giá 20 triệu/tháng",
    )
    assert item.monthly_rent_vnd == 20_000_000
