from runtime.rental_agent.config import DEFAULT_SEARCH_PROFILE
from runtime.rental_agent.normalize import normalize_listing
from runtime.rental_agent.ranking import rank_listing


def test_good_sunset_town_whole_building_scores_high() -> None:
    item = normalize_listing("Cho thuê nguyên căn shophouse Sunset Town Phú Quốc 5 tầng 120m2 giá 22 triệu/tháng")
    result = rank_listing(item, DEFAULT_SEARCH_PROFILE)
    assert result.hard_reject is False
    assert result.total >= 80
    assert result.dimensions["price"] >= 90
    assert result.dimensions["location"] >= 90
    assert result.dimensions["building"] >= 90


def test_over_budget_listing_is_rejected() -> None:
    item = normalize_listing("Nguyên căn shophouse Sunset Town Phú Quốc 5 tầng giá 45 triệu/tháng")
    result = rank_listing(item, DEFAULT_SEARCH_PROFILE)
    assert result.hard_reject is True
    assert "over_stretch_budget" in result.reasons


def test_single_room_is_rejected_even_if_price_is_low() -> None:
    item = normalize_listing("Phòng khách sạn Sunset Town Phú Quốc tầng 5 giá 8 triệu/tháng")
    result = rank_listing(item, DEFAULT_SEARCH_PROFILE)
    assert result.hard_reject is True
    assert "not_whole_building" in result.reasons


def test_unknown_fields_do_not_fake_confidence() -> None:
    item = normalize_listing("Cho thuê nhà khu An Thoi, liên hệ để biết giá")
    result = rank_listing(item, DEFAULT_SEARCH_PROFILE)
    assert result.total < 70
    assert result.dimensions["price"] < 60
