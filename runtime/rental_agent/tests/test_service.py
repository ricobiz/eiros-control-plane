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
    assert status["database"]["schema_version"] == 3
    assert status["policy"]["mode"] == "market_discovery_only"


def test_shortlist_is_json_serializable_and_stable(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    first = service.ingest_text("Sunset Town whole shophouse")
    second = service.ingest_phone("+84 901 234 567", context="agent from listing")

    rows = service.shortlist(limit=10)

    assert {row["property_id"] for row in rows} == {first["property_id"], second["property_id"]}
    assert rows == sorted(rows, key=lambda row: (-row["fit_score"], -row["updated_at"], row["property_id"]))
    json.dumps(rows)


def test_status_exposes_active_search_profile_for_in_chat_app(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    status = service.status()

    assert status["profile"]["location"] == "Phu Quoc"
    assert "Sunset Town" in status["profile"]["zones"]
    assert status["profile"]["budget_vnd_month"]["target_max"] == 25_000_000


def test_ingest_text_normalizes_and_ranks_immediately(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    created = service.ingest_text("Nguyên căn Sunset Town Phú Quốc 5 tầng 120m2 giá 22 triệu/tháng")
    assert created["monthly_rent_vnd"] == 22_000_000
    assert created["floors"] == 5
    assert created["fit_score"] >= 80
    assert created["status"] == "qualified"


def test_sources_exposes_preserved_listing_provenance(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    created = service.ingest_text("Nguyên căn Sunset Town Phú Quốc 5 tầng 120m2 giá 22 triệu/tháng")
    sources = service.sources(created["property_id"])
    assert len(sources) == 1
    assert sources[0]["source_kind"] == "text"


def test_shortlist_includes_source_count(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    created = service.ingest_text("Nguyên căn Sunset Town Phú Quốc 5 tầng 120m2 giá 22 triệu/tháng")
    rows = service.shortlist(limit=10)
    row = next(item for item in rows if item["property_id"] == created["property_id"])
    assert row["source_count"] == 1


def test_service_wires_dedicated_search_browser_profile(tmp_path: Path) -> None:
    service = RentalService(RentalDatabase(tmp_path / "rental.db"), browser_profile_dir=tmp_path / "browser" / "search")
    worker = service.scout_engine.browser_worker
    assert worker is not None
    assert worker.status()["profile_dir"] == str(tmp_path / "browser" / "search")


def test_status_exposes_search_browser_state(tmp_path: Path) -> None:
    from runtime.rental_agent.browser import BrowserPage, BrowserWorker
    worker = BrowserWorker(
        profile_dir=tmp_path / "browser",
        loader=lambda url: BrowserPage(url=url, final_url=url, title="ok", html="<html>ok page</html>"),
    )
    service = RentalService(RentalDatabase(tmp_path / "rental.db"), browser_worker=worker)
    assert service.status()["browser"]["backend"] == "loader"


def test_service_exposes_contacts_and_outreach_wrappers(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    created = service.ingest_text(
        "Nguyên căn Sunset Town Phú Quốc 5 tầng 120m2 giá 22 triệu/tháng, Zalo 0912345678"
    )
    contacts = service.contacts(created["property_id"])
    assert len(contacts) == 1
    assert contacts[0]["value_normalized"] == "+84912345678"

    plan = service.outreach_plan([created["property_id"]])
    assert plan["message_count"] == 1
    queued = service.contact_qualified([created["property_id"]])
    assert queued["queued_count"] == 1
    assert queued["sent_count"] == 0

    threads = service.threads(property_id=created["property_id"])
    assert len(threads) == 1
    detail = service.thread(threads[0]["thread_id"])
    assert detail is not None
    assert detail["messages"][0]["status"] == "draft"
