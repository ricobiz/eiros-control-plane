from pathlib import Path

from runtime.rental_agent.db import RentalDatabase
from runtime.rental_agent.models import LeadInput


def test_initialize_and_ingest_text_lead(tmp_path: Path) -> None:
    db = RentalDatabase(tmp_path / "rental.db")
    db.initialize()
    assert db.health()["schema_version"] == 1

    result = db.create_lead(
        LeadInput(
            source_kind="text",
            source_value="Sunset Town whole shophouse 5 floors 25m VND/month",
            context={"origin": "test"},
        )
    )
    record = db.get_property(result.property_id)
    assert record is not None
    assert record.property_id == result.property_id
    assert record.status == "new"


def test_create_lead_is_idempotent_for_same_source(tmp_path: Path) -> None:
    db = RentalDatabase(tmp_path / "rental.db")
    db.initialize()
    lead = LeadInput(source_kind="url", source_value="https://example.com/a")

    first = db.create_lead(lead)
    second = db.create_lead(lead)

    assert second.property_id == first.property_id
    assert db.health()["listing_sources"] == 1
