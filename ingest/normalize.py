"""Normalization helpers shared by every source-specific importer.

Real club exports don't agree on column names, date formats, or number
formatting between systems — this module is where that gets cleaned up
before anything reaches the graph.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime

# Tried in order; covers the three conventions the sample CSVs use
# (ISO, UK day/month, and "12 Jan 2025") plus a couple of other common
# real-world exports. First one that parses wins.
_DATE_FORMATS = [
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%d %b %Y",
    "%d %B %Y",
    "%d-%m-%Y",
]


def stable_id(prefix: str, *parts: str) -> str:
    """Deterministic id from a natural key — same key always yields the
    same id, so re-ingesting the same (or a corrected) row MERGEs onto the
    same node instead of creating a duplicate."""
    key = "|".join(str(p) for p in parts)
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]
    return f"{prefix}-{digest}"


def normalize_name(name: str | None) -> str | None:
    """Lowercase, strip accents/punctuation/extra whitespace — the join
    key used to match a CSV row's athlete reference against the roster."""
    if name is None:
        return None
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-z0-9\s]", "", text.lower())
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def parse_date(value: str | None) -> str | None:
    """Return an ISO 'YYYY-MM-DD' string, or None if unparseable/blank."""
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def parse_float(value: str | None) -> float | None:
    """Strip thousands separators / units / whitespace, return a float."""
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    cleaned = re.sub(r"[^0-9.\-]", "", text)
    if not cleaned or cleaned in {"-", "."}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def clean_str(value: str | None) -> str | None:
    """Strip whitespace, treat blank as missing."""
    if value is None:
        return None
    text = value.strip()
    return text or None


def row_get(row: dict, *aliases: str) -> str | None:
    """Case/whitespace-insensitive lookup across a csv.DictReader row for
    any of the given column-name aliases — every source names its columns
    differently, this is how each importer copes with that."""
    lookup = {re.sub(r"\s+", " ", k.strip().lower()): v for k, v in row.items() if k}
    for alias in aliases:
        key = re.sub(r"\s+", " ", alias.strip().lower())
        if key in lookup:
            return lookup[key]
    return None
