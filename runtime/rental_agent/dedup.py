from __future__ import annotations

import hashlib
import re
import unicodedata

from runtime.rental_agent.normalize import NormalizedListing


def _identity_title(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", unicodedata.normalize("NFKC", value))
    asciiish = "".join(ch for ch in normalized if not unicodedata.combining(ch)).lower().replace("đ", "d")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", asciiish).split())


def property_signature(item: NormalizedListing) -> str:
    """Return a conservative identity signature; blank means evidence is insufficient."""
    title_identity = _identity_title(item.title)
    if not title_identity:
        return ""

    parts: list[str] = [f"title={title_identity}"]
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

    has_anchor = bool(item.project_name or item.locality)
    physical = sum(value is not None for value in (item.floors, item.area_m2)) + int(item.whole_building is True)
    if not has_anchor or physical < 2:
        return ""
    raw = "|".join(sorted(parts))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
