from __future__ import annotations

from dataclasses import asdict
from typing import Any

from runtime.rental_agent.db import RentalDatabase
from runtime.rental_agent.models import LeadInput
from runtime.rental_agent.policy import RentalPolicy


class RentalService:
    def __init__(self, database: RentalDatabase, policy: RentalPolicy | None = None) -> None:
        self.database = database
        self.policy_engine = policy or RentalPolicy()
        self.database.initialize()

    def status(self) -> dict[str, Any]:
        db_health = self.database.health()
        return {
            "ok": bool(db_health.get("ok")),
            "database": db_health,
            "policy": self.policy_engine.current(),
        }

    def ingest_text(self, text: str, context: str | None = None) -> dict[str, Any]:
        record = self.database.create_lead(
            LeadInput(
                source_kind="text",
                source_value=text,
                context=self._context_dict(context),
            )
        )
        return asdict(record)

    def ingest_url(self, url: str, context: str | None = None) -> dict[str, Any]:
        normalized = url.strip()
        record = self.database.create_lead(
            LeadInput(
                source_kind="url",
                source_value=normalized,
                source_url=normalized,
                context=self._context_dict(context),
            )
        )
        return asdict(record)

    def ingest_phone(self, phone: str, context: str | None = None) -> dict[str, Any]:
        record = self.database.create_lead(
            LeadInput(
                source_kind="phone",
                source_value=phone.strip(),
                context=self._context_dict(context),
            )
        )
        return asdict(record)

    def property(self, property_id: str) -> dict[str, Any] | None:
        record = self.database.get_property(property_id)
        return None if record is None else asdict(record)

    def shortlist(self, limit: int = 20) -> list[dict[str, Any]]:
        return [asdict(record) for record in self.database.list_properties(limit=limit)]

    def policy(self) -> dict[str, object]:
        return self.policy_engine.current()

    @staticmethod
    def _context_dict(context: str | None) -> dict[str, str]:
        value = (context or "").strip()
        return {} if not value else {"note": value}
