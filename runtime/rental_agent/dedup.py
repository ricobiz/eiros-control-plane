from __future__ import annotations

import hashlib

from runtime.rental_agent.normalize import NormalizedListing


def property_signature(item: NormalizedListing) -> str:
    """Return a conservative identity signature; blank means evidence is insufficient."""
    parts: list[str] = []
    if item.project_name:
        parts.append(f"project={item.project_name.lower()}")
    if item.locality:
        parts.append(f"locality={item.locality.lower()}")
    if item.floors is not None:
        parts.append(f"floors={item.floors}")
    if item.area_m2 is not None:
        parts.append(f"area={round(item.area_m2 / 5.0) * 5:.0f}")
    if item.whole_building is True:
        parts.append("whole=1")
    # Require a location/project anchor plus at least two physical identity clues.
    has_anchor = bool(item.project_name or item.locality)
    physical = sum(value is not None for value in (item.floors, item.area_m2)) + int(item.whole_building is True)
    if not has_anchor or physical < 2:
        return ""
    raw = "|".join(sorted(parts))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
