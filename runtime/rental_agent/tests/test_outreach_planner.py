from pathlib import Path

from runtime.rental_agent.config import DEFAULT_SEARCH_PROFILE
from runtime.rental_agent.db import RentalDatabase
from runtime.rental_agent.models import LeadInput
from runtime.rental_agent.normalize import normalize_listing
from runtime.rental_agent.outreach import OutreachPlanner
from runtime.rental_agent.policy import RentalPolicy
from runtime.rental_agent.ranking import rank_listing


def _add(db: RentalDatabase, *, url: str, title: str, text: str):
    item = normalize_listing(text, title=title)
    return db.upsert_normalized_source(
        LeadInput("scout:agency", url, url, {}),
        item,
        rank_listing(item, DEFAULT_SEARCH_PROFILE),
    ).property


def test_planner_groups_same_agency_contact_into_one_inventory_message(tmp_path: Path) -> None:
    db = RentalDatabase(tmp_path / "rental.db")
    db.initialize()
    phone = "0941235578"
    one = _add(
        db,
        url="https://agency.test/new-an-thoi",
        title="Cho thuê Sun Grand City New An Thới",
        text=f"New An Thoi nguyên căn 5 tầng 120m2, Hotline {phone}",
    )
    two = _add(
        db,
        url="https://agency.test/the-center",
        title="Cho thuê căn Shophouse The Center",
        text=f"The Center Phu Quoc nguyên căn 5 tầng, Hotline {phone}",
    )

    plan = OutreachPlanner(db, RentalPolicy()).plan(property_ids=[one.property_id, two.property_id])

    assert plan["allowed"] is True
    assert plan["message_count"] == 1
    item = plan["messages"][0]
    assert set(item["property_ids"]) == {one.property_id, two.property_id}
    assert item["channel"] == "zalo"
    assert "New An Thoi" in item["text"]
    assert "The Center" in item["text"]
    assert "18–25" in item["text"]
    assert "giá hiện tại" in item["text"].lower()
    assert "thời hạn thuê tối thiểu" in item["text"].lower()
    assert "tiền cọc" in item["text"].lower()
    assert "ảnh/video" in item["text"].lower()


def test_planner_does_not_include_rejected_property(tmp_path: Path) -> None:
    db = RentalDatabase(tmp_path / "rental.db")
    db.initialize()
    rejected = _add(
        db,
        url="https://agency.test/too-expensive",
        title="Cho thuê Sunset Town",
        text="Sunset Town nguyên căn 5 tầng 120m2 giá 80 triệu/tháng, Hotline 0912345678",
    )
    assert rejected.status == "rejected"

    plan = OutreachPlanner(db, RentalPolicy()).plan(property_ids=[rejected.property_id])
    assert plan["message_count"] == 0
    assert plan["skipped"][0]["reason"] == "not_qualified"


def test_enqueue_plan_creates_draft_thread_and_job_without_sending(tmp_path: Path) -> None:
    db = RentalDatabase(tmp_path / "rental.db")
    db.initialize()
    prop = _add(
        db,
        url="https://agency.test/center",
        title="Cho thuê The Center",
        text="The Center nguyên căn 5 tầng 120m2, Hotline 0912345678",
    )
    planner = OutreachPlanner(db, RentalPolicy())
    result = planner.enqueue(property_ids=[prop.property_id])

    assert result["queued_count"] == 1
    assert result["sent_count"] == 0
    assert result["items"][0]["job_status"] == "needs_channel"
    thread = db.get_thread(result["items"][0]["thread_id"])
    assert thread is not None
    assert thread["status"] == "needs_channel"
    assert thread["messages"][0]["status"] == "draft"
