from pathlib import Path

from runtime.rental_agent.config import DEFAULT_SEARCH_PROFILE
from runtime.rental_agent.db import RentalDatabase
from runtime.rental_agent.models import LeadInput
from runtime.rental_agent.normalize import normalize_listing
from runtime.rental_agent.ranking import rank_listing


def _property_with_phone(db: RentalDatabase, *, url: str, title: str, text: str):
    item = normalize_listing(text, title=title)
    return db.upsert_normalized_source(
        LeadInput("scout:test", url, url, {}),
        item,
        rank_listing(item, DEFAULT_SEARCH_PROFILE),
    ).property


def test_schema_v3_creates_outreach_ledger_tables(tmp_path: Path) -> None:
    db = RentalDatabase(tmp_path / "rental.db")
    db.initialize()
    health = db.health()
    assert health["schema_version"] == 3
    assert health["outreach_threads"] == 0
    assert health["messages"] == 0
    assert health["jobs"] == 0


def test_get_or_create_thread_is_idempotent(tmp_path: Path) -> None:
    db = RentalDatabase(tmp_path / "rental.db")
    db.initialize()
    prop = _property_with_phone(
        db,
        url="https://example.test/1",
        title="New An Thoi A",
        text="New An Thoi nguyên căn 5 tầng 120m2 giá 22 triệu/tháng, Zalo 0912345678",
    )
    contact = db.list_contacts(prop.property_id)[0]

    first = db.get_or_create_thread(prop.property_id, contact["contact_id"], "zalo")
    second = db.get_or_create_thread(prop.property_id, contact["contact_id"], "zalo")

    assert first["thread_id"] == second["thread_id"]
    assert first["status"] == "draft"
    assert len(db.list_threads(property_id=prop.property_id)) == 1


def test_message_ledger_preserves_direction_and_parsed_facts(tmp_path: Path) -> None:
    db = RentalDatabase(tmp_path / "rental.db")
    db.initialize()
    prop = _property_with_phone(
        db,
        url="https://example.test/1",
        title="The Center A",
        text="The Center Phu Quoc nguyên căn 5 tầng, Zalo 0912345678",
    )
    contact = db.list_contacts(prop.property_id)[0]
    thread = db.get_or_create_thread(prop.property_id, contact["contact_id"], "zalo")

    message = db.append_message(
        thread["thread_id"],
        direction="outbound",
        status="draft",
        raw_text="Căn này còn cho thuê không?",
        parsed={"asks": ["availability"]},
    )

    detail = db.get_thread(thread["thread_id"])
    assert message["direction"] == "outbound"
    assert detail is not None
    assert detail["messages"][0]["parsed"] == {"asks": ["availability"]}


def test_enqueue_job_deduplicates_same_intent(tmp_path: Path) -> None:
    db = RentalDatabase(tmp_path / "rental.db")
    db.initialize()
    first = db.enqueue_job(
        job_type="outreach_send",
        dedup_key="zalo:contact_1:inventory:phu-quoc",
        payload={"contact_id": "contact_1"},
    )
    second = db.enqueue_job(
        job_type="outreach_send",
        dedup_key="zalo:contact_1:inventory:phu-quoc",
        payload={"contact_id": "contact_1"},
    )
    assert first["job_id"] == second["job_id"]
    assert first["reused"] is False
    assert second["reused"] is True


def test_migrates_v2_database_without_losing_property_source_or_contact(tmp_path: Path) -> None:
    import sqlite3
    from runtime.rental_agent.db import SCHEMA_V1, MIGRATION_V2

    path = tmp_path / "rental-v2.db"
    connection = sqlite3.connect(path)
    connection.executescript(SCHEMA_V1)
    connection.executescript(MIGRATION_V2)
    connection.execute("PRAGMA user_version = 2")
    connection.execute(
        "INSERT INTO properties(property_id,status,title,created_at,updated_at,last_seen_at) VALUES ('prop_old','qualified','Old lead',1,1,1)"
    )
    connection.execute(
        "INSERT INTO listing_sources(source_id,property_id,source_kind,source_value,captured_at,last_seen_at) VALUES ('src_old','prop_old','url','https://example.test/old',1,1)"
    )
    connection.execute(
        "INSERT INTO contacts(contact_id,kind,value_normalized,display_value,created_at) VALUES ('contact_old','phone','+84912345678','0912345678',1)"
    )
    connection.execute(
        "INSERT INTO property_contacts(property_id,contact_id,provenance_source_id) VALUES ('prop_old','contact_old','src_old')"
    )
    connection.commit()
    connection.close()

    db = RentalDatabase(path)
    db.initialize()

    assert db.health()["schema_version"] == 3
    assert db.get_property("prop_old") is not None
    assert db.list_sources("prop_old")[0]["source_id"] == "src_old"
    assert db.list_contacts("prop_old")[0]["contact_id"] == "contact_old"
    assert db.list_threads(property_id="prop_old") == []
