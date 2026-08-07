from runtime.rental_agent.dedup import property_signature
from runtime.rental_agent.normalize import normalize_listing


def test_property_signature_matches_same_building_with_price_change_when_title_identity_matches() -> None:
    first = normalize_listing(
        "Nguyên căn Sunset Town Phú Quốc 5 tầng 120m2 giá 22 triệu/tháng",
        title="Sunset Town S5-12",
    )
    second = normalize_listing(
        "Sunset Town Phu Quoc whole building 5 floors 120 m2 rent 25 million VND/month",
        title="Sunset Town S5-12",
    )
    assert property_signature(first)
    assert property_signature(first) == property_signature(second)


def test_property_signature_changes_for_materially_different_building() -> None:
    first = normalize_listing(
        "Nguyên căn Sunset Town Phú Quốc 5 tầng 120m2 giá 22 triệu/tháng",
        title="Sunset Town S5-12",
    )
    second = normalize_listing(
        "Nguyên căn Sunset Town Phú Quốc 3 tầng 80m2 giá 22 triệu/tháng",
        title="Sunset Town S5-12",
    )
    assert property_signature(first) != property_signature(second)


def test_property_signature_requires_enough_identity_evidence() -> None:
    item = normalize_listing("Nhà Phú Quốc giá 22 triệu/tháng", title="Nhà Phú Quốc")
    assert property_signature(item) == ""


def test_property_signature_does_not_merge_two_units_with_same_generic_geometry() -> None:
    first = normalize_listing(
        "The Center Phú Quốc 5 tầng 120m2 nguyên căn",
        title="Cho thuê căn The Center dãy Milan",
    )
    second = normalize_listing(
        "The Center Phú Quốc 5 tầng 120m2 nguyên căn",
        title="Cho thuê căn The Center dãy Amalfi",
    )
    assert property_signature(first) != property_signature(second)
