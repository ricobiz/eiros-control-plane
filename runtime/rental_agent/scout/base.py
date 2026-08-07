from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class DiscoveredListing:
    source: str
    url: str
    title: str
    text: str


@dataclass(slots=True, frozen=True)
class AdapterResult:
    source: str
    status: str
    listings: tuple[DiscoveredListing, ...]
    errors: tuple[str, ...] = ()
