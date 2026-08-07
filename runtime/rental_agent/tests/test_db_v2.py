import sqlite3
from pathlib import Path

from runtime.rental_agent.config import DEFAULT_SEARCH_PROFILE
from runtime.rental_agent.db import RentalDatabase, SCHEMA_V1
from runtime.rental_agent.models import LeadInput
from runtime.rental_agent.normalize import normalize_listing
from runtime.rental_agent.ranking import rank_listing


def test_migrates_v1_database_without_losing_existing_lead(tmp_path: Path) -> None:
    path = tmp_path / "rental.db"
    connection = sqlite3.connect(path)
    connection.executescript(SCHEMA_V1)
    connection.execute("PRAGMA user_version = 1")
    connection.execute(
        "INSERT INTO properties(property_id,status,title,created_at,updated_at) VALUES ('prop_old','new','Old lead',1,1)"
    )
    connection.execute(
        "INSERT INTO listing_sources(source_id,property_id,source_kind,source_value,captured_at) VALUES ('src_old','prop_old','url','https://example.test/old',1)"
    )
    connection.commit()
    connection.close()

    db = RentalDatabase(path)
    db.initialize()
    health = db.health()
    assert health["schema_version"] == 2
    assert db.get_property("prop_old") is not None
    assert db.list_sources("prop_old")[0]["source_value"] == "https://example.test/old"


def test_upsert_merges_different_sources_for_same_property_signature(tmp_path: Path) -> None:
    db = RentalDatabase(tmp_path / "rental.db")
    db.initialize()
    first_text = "Nguyên căn Sunset Town Phú Quốc 5 tầng 120m2 giá 22 triệu/tháng"
    second_text = "Sunset Town Phu Quoc whole building 5 floors 120 m2 rent 25 million VND/month"

    first = normalize_listing(first_text)
    second = normalize_listing(second_text)
    one = db.upsert_normalized_source(
        LeadInput("url", "https://a.test/1", "https://a.test/1", {"text": first_text}),
        first,
        rank_listing(first, DEFAULT_SEARCH_PROFILE),
    )
    two = db.upsert_normalized_source(
        LeadInput("url", "https://b.test/2", "https://b.test/2", {"text": second_text}),
        second,
        rank_listing(second, DEFAULT_SEARCH_PROFILE),
    )

    assert one.property.property_id == two.property.property_id
    assert two.merged is True
    assert len(db.list_sources(one.property.property_id)) == 2
    assert db.get_property(one.property.property_id).monthly_rent_vnd == 25_000_000


def test_upsert_merges_by_phone_even_when_property_signature_is_incomplete(tmp_path: Path) -> None:
    db = RentalDatabase(tmp_path / "rental.db")
    db.initialize()
    first_text = "Nhà khu An Thoi giá 20 triệu/tháng, Zalo 0912 345 678"
    second_text = "Cho thuê nhà An Thoi 21 triệu, liên hệ 0912345678"
    first = normalize_listing(first_text)
    second = normalize_listing(second_text)

    one = db.upsert_normalized_source(
        LeadInput("text", first_text, context={"text": first_text}),
        first,
        rank_listing(first, DEFAULT_SEARCH_PROFILE),
    )
    two = db.upsert_normalized_source(
        LeadInput("text", second_text, context={"text": second_text}),
        second,
        rank_listing(second, DEFAULT_SEARCH_PROFILE),
    )
    assert one.property.property_id == two.property.property_id
    assert len(db.list_contacts(one.property.property_id)) == 1


def test_search_run_lifecycle_is_persisted(tmp_path: Path) -> None:
    db = RentalDatabase(tmp_path / "rental.db")
    db.initialize()
    run_id = db.begin_search_run({"zones": ["Sunset Town"]})
    db.finish_search_run(run_id, status="ok", result_count=3, error_count=1)
    latest = db.list_search_runs(limit=1)[0]
    assert latest["run_id"] == run_id
    assert latest["status"] == "ok"
    assert latest["result_count"] == 3
    assert latest["error_count"] == 1
