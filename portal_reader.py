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
    + r"\s*(GB|MB)\s*(?:\+?\s*1\s*GB\s*)?Inland\b",
    re.I,
)
REFERENCE_PATTERN = re.compile(
    r"Noch\s+" + AMOUNT + r"\s*(GB|MB)\s+von\s+" + AMOUNT
    + r"\s*(GB|MB)\s*(?:\+?\s*1\s*GB\b)?",
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
    readings = parse_portal_readings(text)
    if readings:
        # The responsive overview can render more than one domestic allowance
        # card. The exhausted card is the one relevant for a free refill.
        return min(readings, key=lambda reading: reading.remaining_mb or 0)
    return Reading(None, "UNVERIFIED")


def parse_portal_readings(text: str) -> list[Reading]:
    """Return every valid domestic allowance rendered by the overview."""
    normalized = re.sub(r"\s+", " ", text.replace("\u00a0", " "))
    matches = list(PATTERN.finditer(normalized))
    if not matches and not re.search(r"\bRoaming\b", normalized, re.I):
        reference = REFERENCE_PATTERN.search(normalized)
        matches = [reference] if reference else []

    readings = []
    for match in matches:
        remaining = to_mb(match.group(1), match.group(2))
        allowance = to_mb(match.group(3), match.group(4))
        if 0 <= remaining <= allowance <= 1000000:
            readings.append(Reading(remaining, "READ_ONLY"))
    return readings
