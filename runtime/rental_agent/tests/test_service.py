import json
from pathlib import Path

from runtime.rental_agent.db import RentalDatabase
from runtime.rental_agent.service import RentalService


def make_service(tmp_path: Path) -> RentalService:
    return RentalService(RentalDatabase(tmp_path / "rental.db"))


def test_ingest_url_creates_retrievable_property_and_source(tmp_path: Path) -> None:
    service = make_service(tmp_path)

    created = service.ingest_url("https://example.com/listing/1")
    record = service.property(created["property_id"])

    assert record is not None
    assert record["property_id"] == created["property_id"]
    assert service.status()["database"]["listing_sources"] == 1


def test_status_reports_schema_and_market_discovery_policy(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    status = service.status()

    assert status["ok"] is True
    assert status["database"]["schema_version"] == 1
    assert status["policy"]["mode"] == "market_discovery_only"


def test_shortlist_is_json_serializable_and_stable(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    first = service.ingest_text("Sunset Town whole shophouse")
    second = service.ingest_phone("+84 901 234 567", context="agent from listing")

    rows = service.shortlist(limit=10)

    assert {row["property_id"] for row in rows} == {first["property_id"], second["property_id"]}
    assert rows == sorted(rows, key=lambda row: (-row["fit_score"], -row["updated_at"], row["property_id"]))
    json.dumps(rows)
