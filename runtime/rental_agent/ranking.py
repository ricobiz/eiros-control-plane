from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from runtime.rental_agent.normalize import NormalizedListing


@dataclass(slots=True, frozen=True)
class FitResult:
    total: float
    dimensions: dict[str, float]
    hard_reject: bool
    reasons: tuple[str, ...]


def _price_score(item: NormalizedListing, profile: dict[str, Any]) -> tuple[float, str | None, bool]:
    price = item.monthly_rent_vnd
    budget = profile["budget_vnd_month"]
    if price is None:
        return 25.0, "price_unknown", False
    if price > int(budget["stretch_max"]):
        return 0.0, "over_stretch_budget", True
    if int(budget["target_min"]) <= price <= int(budget["target_max"]):
        return 100.0, None, False
    if price < int(budget["target_min"]):
        return 85.0, "below_target_price", False
    return 65.0, "stretch_budget", False


def _location_score(item: NormalizedListing, profile: dict[str, Any]) -> float:
    project = item.project_name.lower()
    locality = item.locality.lower()
    zones = " ".join(str(zone).lower() for zone in profile.get("zones", []))
    if project and project in zones:
        return 100.0
    if project == "new an thoi" or locality == "an thoi":
        return 85.0
    if locality == "phu quoc":
        return 70.0
    return 20.0


def _building_score(item: NormalizedListing, profile: dict[str, Any]) -> tuple[float, str | None, bool]:
    if item.whole_building is False:
        return 0.0, "not_whole_building", True
    score = 45.0 if item.whole_building is None else 75.0
    floors = item.floors
    floor_profile = profile["floors"]
    if floors is None:
        return score, "floors_unknown", False
    if int(floor_profile["min"]) <= floors <= int(floor_profile["max"]):
        score += 25.0
        if floors in set(int(v) for v in floor_profile.get("preferred", [])):
            score += 10.0
        return min(score, 100.0), None, False
    return max(20.0, score - 25.0), "floors_outside_target", False


def _evidence_score(item: NormalizedListing) -> float:
    useful = {"price", "floors", "area", "project", "locality", "whole_building", "phone", "lease", "deposit"}
    count = len(useful.intersection(item.evidence))
    return min(100.0, count * 14.0)


def rank_listing(item: NormalizedListing, profile: dict[str, Any]) -> FitResult:
    reasons: list[str] = []
    price, price_reason, price_reject = _price_score(item, profile)
    if price_reason:
        reasons.append(price_reason)
    location = _location_score(item, profile)
    building, building_reason, building_reject = _building_score(item, profile)
    if building_reason:
        reasons.append(building_reason)
    evidence = _evidence_score(item)
    hard_reject = price_reject or building_reject
    total = price * 0.35 + location * 0.25 + building * 0.30 + evidence * 0.10
    if hard_reject:
        total = min(total, 35.0)
    return FitResult(
        total=round(total, 2),
        dimensions={
            "price": round(price, 2),
            "location": round(location, 2),
            "building": round(building, 2),
            "evidence": round(evidence, 2),
        },
        hard_reject=hard_reject,
        reasons=tuple(reasons),
    )
