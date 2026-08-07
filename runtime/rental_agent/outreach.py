from __future__ import annotations

from dataclasses import asdict
from typing import Any

from runtime.rental_agent.config import DEFAULT_SEARCH_PROFILE
from runtime.rental_agent.db import RentalDatabase
from runtime.rental_agent.models import AuthorityAction
from runtime.rental_agent.policy import RentalPolicy


class OutreachPlanner:
    def __init__(self, database: RentalDatabase, policy: RentalPolicy) -> None:
        self.database = database
        self.policy = policy

    @staticmethod
    def _channel_for_contact(contact: dict[str, Any]) -> str:
        kind = str(contact.get("kind") or "").strip().lower()
        # Vietnamese listing phone numbers are first attempted through Zalo once
        # the authenticated channel is connected. Until then jobs stay needs_channel.
        return "zalo" if kind == "phone" else kind

    @staticmethod
    def _label(record: Any) -> str:
        return str(record.project_name or record.title or record.locality or record.property_id).strip()

    @staticmethod
    def _message(labels: list[str]) -> str:
        budget = DEFAULT_SEARCH_PROFILE["budget_vnd_month"]
        target_min = int(budget["target_min"]) // 1_000_000
        target_max = int(budget["target_max"]) // 1_000_000
        places = " / ".join(labels)
        if len(labels) > 1:
            opening = (
                f"Chào anh/chị. Bên anh/chị hiện còn căn nguyên căn 3–6 tầng "
                f"(ưu tiên 5–6 tầng) ở {places} trong khoảng {target_min}–{target_max} triệu/tháng không?"
            )
        else:
            opening = f"Chào anh/chị. Căn/nguyên căn ở {places} này hiện còn cho thuê không?"
        return (
            opening
            + " Cho mình xin giá hiện tại, thời hạn thuê tối thiểu, tiền cọc và vị trí chính xác."
            + " Nếu có, gửi giúp mình thêm ảnh/video nhé. Cảm ơn."
        )

    def plan(self, property_ids: list[str] | None = None) -> dict[str, Any]:
        decision = self.policy.check(AuthorityAction.CONTACT_DISCOVERY)
        if not decision.allowed:
            return {
                "allowed": False,
                "reason": decision.reason,
                "message_count": 0,
                "messages": [],
                "skipped": [],
            }

        if property_ids is None:
            records = [record for record in self.database.list_properties(limit=500) if record.status == "qualified"]
        else:
            records = []
            for property_id in dict.fromkeys(property_ids):
                record = self.database.get_property(property_id)
                if record is not None:
                    records.append(record)

        skipped: list[dict[str, str]] = []
        grouped: dict[tuple[str, str], dict[str, Any]] = {}
        for record in records:
            if record.status != "qualified":
                skipped.append({"property_id": record.property_id, "reason": "not_qualified"})
                continue
            contacts = self.database.list_contacts(record.property_id)
            if not contacts:
                skipped.append({"property_id": record.property_id, "reason": "no_contact"})
                continue
            for contact in contacts:
                channel = self._channel_for_contact(contact)
                if not channel:
                    skipped.append({"property_id": record.property_id, "reason": "unsupported_contact"})
                    continue
                key = (str(contact["contact_id"]), channel)
                group = grouped.setdefault(
                    key,
                    {
                        "contact": contact,
                        "channel": channel,
                        "records": [],
                    },
                )
                if record.property_id not in {item.property_id for item in group["records"]}:
                    group["records"].append(record)

        messages: list[dict[str, Any]] = []
        for (contact_id, channel), group in sorted(grouped.items()):
            group_records = sorted(group["records"], key=lambda item: (-item.fit_score, item.property_id))
            labels: list[str] = []
            for record in group_records:
                label = self._label(record)
                if label and label not in labels:
                    labels.append(label)
            intent_key = "inventory:phu-quoc"
            messages.append(
                {
                    "contact_id": contact_id,
                    "contact_kind": str(group["contact"].get("kind") or ""),
                    "contact_value": str(group["contact"].get("display_value") or group["contact"].get("value_normalized") or ""),
                    "channel": channel,
                    "intent_key": intent_key,
                    "property_ids": [record.property_id for record in group_records],
                    "projects": labels,
                    "asks": ["availability", "current_price", "minimum_term", "deposit", "exact_location", "media"],
                    "text": self._message(labels),
                }
            )
        return {
            "allowed": True,
            "reason": decision.reason,
            "message_count": len(messages),
            "messages": messages,
            "skipped": skipped,
        }

    def enqueue(self, property_ids: list[str] | None = None) -> dict[str, Any]:
        plan = self.plan(property_ids=property_ids)
        if not plan["allowed"]:
            return {**plan, "queued_count": 0, "sent_count": 0, "items": []}

        items: list[dict[str, Any]] = []
        for message in plan["messages"]:
            thread = self.database.get_or_create_group_thread(
                property_ids=list(message["property_ids"]),
                contact_id=str(message["contact_id"]),
                channel=str(message["channel"]),
                intent_key=str(message["intent_key"]),
            )
            dedup_key = f"outreach:{message['channel']}:{message['contact_id']}:{message['intent_key']}"
            job = self.database.enqueue_job(
                job_type="outreach_send",
                dedup_key=dedup_key,
                payload={
                    "thread_id": thread["thread_id"],
                    "contact_id": message["contact_id"],
                    "channel": message["channel"],
                    "property_ids": message["property_ids"],
                    "text": message["text"],
                },
                status="needs_channel",
            )
            if not job["reused"]:
                self.database.append_message(
                    thread["thread_id"],
                    direction="outbound",
                    status="draft",
                    raw_text=str(message["text"]),
                    parsed={"asks": message["asks"], "property_ids": message["property_ids"]},
                )
            thread = self.database.set_thread_status(thread["thread_id"], "needs_channel")
            items.append(
                {
                    "thread_id": thread["thread_id"],
                    "job_id": job["job_id"],
                    "job_status": job["status"],
                    "reused": job["reused"],
                    "channel": message["channel"],
                    "contact_id": message["contact_id"],
                    "property_ids": message["property_ids"],
                }
            )
        return {
            "allowed": True,
            "reason": plan["reason"],
            "planned_count": plan["message_count"],
            "queued_count": len(items),
            "sent_count": 0,
            "items": items,
            "skipped": plan["skipped"],
        }
