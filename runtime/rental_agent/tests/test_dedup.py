from runtime.rental_agent.dedup import property_signature
from runtime.rental_agent.normalize import normalize_listing


def test_property_signature_matches_same_building_with_price_change() -> None:
    first = normalize_listing("Nguyên căn Sunset Town Phú Quốc 5 tầng 120m2 giá 22 triệu/tháng")
    second = normalize_listing("Sunset Town Phu Quoc whole building 5 floors 120 m2 rent 25 million VND/month")
    assert property_signature(first) == property_signature(second)


def test_property_signature_changes_for_materially_different_building() -> None:
    first = normalize_listing("Nguyên căn Sunset Town Phú Quốc 5 tầng 120m2 giá 22 triệu/tháng")
    second = normalize_listing("Nguyên căn Sunset Town Phú Quốc 3 tầng 80m2 giá 22 triệu/tháng")
    assert property_signature(first) != property_signature(second)


def test_property_signature_requires_enough_identity_evidence() -> None:
    item = normalize_listing("Nhà Phú Quốc giá 22 triệu/tháng")
    assert property_signature(item) == ""
