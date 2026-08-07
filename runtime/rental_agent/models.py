from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
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
    whole_building: bool | None
    fit_score: float
    fit_dimensions: dict[str, float]
    signature: str
    created_at: int
    updated_at: int


@dataclass(slots=True, frozen=True)
class UpsertResult:
    property: PropertyRecord
    source_id: str
    merged: bool


class AuthorityAction(str, Enum):
    SEARCH = "search"
    INGEST = "ingest"
    CONTACT_DISCOVERY = "contact_discovery"
    REQUEST_MEDIA = "request_media"
    COMPARE_RANK = "compare_rank"
    NEGOTIATE = "negotiate"
    SCHEDULE_VIEWING = "schedule_viewing"
    BINDING_COMMITMENT = "binding_commitment"
    AGREE_DEPOSIT = "agree_deposit"
    SEND_MONEY = "send_money"
    CONTRACT = "contract"


@dataclass(slots=True, frozen=True)
class ActionDecision:
    action: AuthorityAction
    allowed: bool
    reason: str
