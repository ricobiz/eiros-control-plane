from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True, frozen=True)
class LeadInput:
    source_kind: str
    source_value: str
    source_url: str = ""
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class PropertyRecord:
    property_id: str
    status: str
    title: str
    project_name: str
    locality: str
    monthly_rent_vnd: int | None
    floors: int | None
    area_m2: float | None
    lease_min_months: int | None
    deposit_months: float | None
    fit_score: float
    created_at: int
    updated_at: int
