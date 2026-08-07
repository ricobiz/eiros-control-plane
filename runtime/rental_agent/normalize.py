from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class NormalizedListing:
    raw_text: str
    title: str
    project_name: str
    locality: str
    monthly_rent_vnd: int | None
    floors: int | None
    area_m2: float | None
    lease_min_months: int | None
    deposit_months: float | None
    whole_building: bool | None
    phones: tuple[str, ...]
    text_fingerprint: str
    evidence: tuple[str, ...]


def _ascii(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", unicodedata.normalize("NFKC", value))
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).lower()


def _canonical_text(value: str) -> str:
    text = _ascii(value)
    text = text.replace("đ", "d")
    text = re.sub(r"(?<=\d)\s+(?=m\s*2\b)", "", text)
    text = re.sub(r"m\s+2\b", "m2", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _parse_price(text: str) -> int | None:
    simple = _ascii(text).replace("đ", "d")
    patterns = (
        r"(?:gia|thue|rent)?\s*[:=-]?\s*(\d+(?:[.,]\d+)?)\s*(?:trieu|tr)\s*(?:/\s*(?:thang|month))?",
        r"(\d+(?:[.,]\d+)?)\s*(?:million)\s*(?:vnd|dong)?\s*(?:/\s*month)?",
    )
    for pattern in patterns:
        match = re.search(pattern, simple, flags=re.I)
        if match:
            amount = float(match.group(1).replace(",", "."))
            return int(round(amount * 1_000_000))
    match = re.search(r"(\d{7,9})\s*(?:vnd|dong|d)?(?:\s*/\s*(?:thang|month))?", simple, flags=re.I)
    if match:
        amount = int(match.group(1))
        if amount >= 1_000_000:
            return amount
    return None


def _parse_first_number(text: str, patterns: tuple[str, ...], *, as_float: bool = False):
    simple = _ascii(text).replace("đ", "d")
    for pattern in patterns:
        match = re.search(pattern, simple, flags=re.I)
        if match:
            raw = match.group(1).replace(",", ".")
            return float(raw) if as_float else int(float(raw))
    return None


def _normalize_phone(raw: str) -> str | None:
    value = re.sub(r"\D", "", raw)
    if value.startswith("84") and 10 <= len(value) <= 11:
        return "+" + value
    if value.startswith("0") and len(value) == 10:
        return "+84" + value[1:]
    if 9 <= len(value) <= 12:
        return "+" + value if raw.strip().startswith("+") else value
    return None


def _extract_phones(text: str) -> tuple[str, ...]:
    found: list[str] = []
    for match in re.finditer(r"(?:\+?84|0)[\s().-]*\d(?:[\s().-]*\d){8,9}", text):
        normalized = _normalize_phone(match.group(0))
        if normalized and normalized not in found:
            found.append(normalized)
    return tuple(found)


def _project_name(text: str) -> str:
    simple = _ascii(text).replace("đ", "d")
    if "sunset town" in simple:
        return "Sunset Town"
    if "primavera" in simple:
        return "Primavera"
    if "the center" in simple or "the centre" in simple:
        return "The Center"
    if "new an thoi" in simple:
        return "New An Thoi"
    return ""


def _locality(text: str) -> str:
    simple = _ascii(text).replace("đ", "d")
    if "phu quoc" in simple:
        return "Phu Quoc"
    if "an thoi" in simple:
        return "An Thoi"
    return ""


def _whole_building(text: str) -> bool | None:
    simple = _ascii(text).replace("đ", "d")
    negative = (
        "1 phong",
        "mot phong",
        "phong khach san",
        "mat bang tang 1",
        "cho thue tang 1",
        "ground floor only",
        "first floor only",
        "room for rent",
        "single room",
        "shared room",
    )
    if any(token in simple for token in negative):
        return False
    positive = (
        "nguyen can",
        "nguyen toa",
        "ca toa",
        "whole building",
        "entire building",
        "entire house",
        "whole house",
        "whole shophouse",
    )
    if any(token in simple for token in positive):
        return True
    if "shophouse" in simple and re.search(r"\b[3-9]\s*(?:tang|floors?)\b", simple):
        return True
    return None


def normalize_listing(text: str, *, title: str = "") -> NormalizedListing:
    raw = text.strip()
    floors = _parse_first_number(raw, (r"\b(\d{1,2})\s*(?:tang|floors?)\b",))
    area = _parse_first_number(
        raw,
        (r"\b(\d+(?:[.,]\d+)?)\s*(?:m2|m\s*2|sqm|m²)\b",),
        as_float=True,
    )
    deposit = _parse_first_number(
        raw,
        (r"(?:coc|deposit)\s*(?:[:=-]?\s*)?(\d+(?:[.,]\d+)?)\s*(?:thang|months?)",),
        as_float=True,
    )
    lease = _parse_first_number(
        raw,
        (
            r"(?:toi thieu|min(?:imum)?|hop dong toi thieu)[^\d]{0,18}(\d+)\s*(?:thang|months?)",
            r"(?:hop dong|lease)\s*(?:[:=-]?\s*)?(\d+)\s*(?:thang|months?)",
        ),
    )
    price = _parse_price(raw)
    project = _project_name(raw)
    locality = _locality(raw)
    whole = _whole_building(raw)
    phones = _extract_phones(raw)
    evidence: list[str] = []
    for key, value in (
        ("price", price),
        ("floors", floors),
        ("area", area),
        ("lease", lease),
        ("deposit", deposit),
        ("project", project),
        ("locality", locality),
        ("whole_building", whole),
        ("phone", phones),
    ):
        if value not in (None, "", (), False):
            evidence.append(key)
        elif key == "whole_building" and value is False:
            evidence.append(key)
    canonical = _canonical_text(raw)
    return NormalizedListing(
        raw_text=raw,
        title=title.strip(),
        project_name=project,
        locality=locality,
        monthly_rent_vnd=price,
        floors=floors,
        area_m2=area,
        lease_min_months=lease,
        deposit_months=deposit,
        whole_building=whole,
        phones=phones,
        text_fingerprint=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        evidence=tuple(evidence),
    )
