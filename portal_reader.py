"""Privacy-safe parsing helpers for the ALDI TALK customer portal."""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse


PORTAL_URL = "https://www.alditalk-kundenportal.de/portal/auth/uebersicht/"
PORTAL_HOST = "alditalk-kundenportal.de"


def is_portal_host(host_or_url: str | None) -> bool:
    """Allow only the real portal host and its subdomains."""
    value = host_or_url or ""
    if "://" in value:
        value = urlparse(value).hostname or ""
    host = value.lower().rstrip(".")
    return host == PORTAL_HOST or host.endswith("." + PORTAL_HOST)


@dataclass(frozen=True)
class Reading:
    remaining_mb: int | None
    status: str


AMOUNT = r"(\d{1,3}(?:[.,]\d{3})+|\d+(?:[.,]\d+)?)"
PATTERN = re.compile(
    r"Noch\s+" + AMOUNT + r"\s*(GB|MB)\s+von\s+" + AMOUNT
    + r"\s*(GB|MB)\s*(?:\+\s*1\s*GB\s*)?Inland\b",
    re.I,
)
REFERENCE_PATTERN = re.compile(
    r"Noch\s+" + AMOUNT + r"\s*(GB|MB)\s+von\s+" + AMOUNT
    + r"\s*(GB|MB)\s*(?:\+\s*1\s*GB\b)?",
    re.I,
)


def to_mb(raw: str, unit: str) -> int:
    if unit.upper() == "MB":
        value = float(raw.replace(".", "").replace(",", "."))
        return round(value)
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", raw):
        value = float(raw.replace(".", ""))
    else:
        value = float(raw.replace(",", "."))
    return round(value * 1000)


def parse_portal_text(text: str) -> Reading:
    normalized = re.sub(r"\s+", " ", text.replace("\u00a0", " "))
    match = PATTERN.search(normalized)
    if not match:
        if re.search(r"\bRoaming\b", normalized, re.I):
            return Reading(None, "UNVERIFIED")
        match = REFERENCE_PATTERN.search(normalized)
    if not match:
        return Reading(None, "UNVERIFIED")
    remaining = to_mb(match.group(1), match.group(2))
    allowance = to_mb(match.group(3), match.group(4))
    if not 0 <= remaining <= allowance <= 1000000:
        return Reading(None, "UNVERIFIED")
    return Reading(remaining, "READ_ONLY")
