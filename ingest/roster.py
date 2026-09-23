"""Athlete identity resolution.

None of the three source systems (GPS vendor, wellness app, medical system)
share an athlete ID with each other or with our schema — the roster file is
the identity anchor all three importers resolve against, by normalized name.
"""

from __future__ import annotations

import csv
import difflib
from dataclasses import dataclass, field
from pathlib import Path

from normalize import clean_str, missing_required_columns, normalize_name, row_get, stable_id

# How close a misspelled/nickname athlete reference has to be to a real
# roster name before it's worth surfacing as a suggestion. 0.72 catches
# "Rob Smith" -> "Robert Smith" and single-letter typos without also
# matching two genuinely different short names against each other.
_FUZZY_CUTOFF = 0.72


@dataclass
class Roster:
    athletes: list[dict]
    by_normalized_name: dict[str, str] = field(default_factory=dict)
    stats: dict = field(default_factory=dict)
    skipped_rows: list[dict] = field(default_factory=list)
    file_error: str | None = None

    def resolve(self, raw_name: str | None) -> str | None:
        """Normalized-name -> athlete id, or None if there's no match."""
        key = normalize_name(raw_name)
        if key is None:
            return None
        return self.by_normalized_name.get(key)

    def suggest(self, raw_name: str | None) -> str | None:
        """Best-guess roster name for an unmatched reference -- e.g. a
        nickname or typo in a GPS/wellness/injury export that doesn't
        exactly match how this athlete is spelled in the roster. Never
        auto-applied (guessing wrong on medical data is worse than
        skipping the row): this only feeds a human-readable hint into a
        skip reason so whoever's reviewing the import report can fix the
        source file or the roster, not silently resolve on their behalf."""
        key = normalize_name(raw_name)
        if key is None or not self.by_normalized_name:
            return None
        matches = difflib.get_close_matches(key, self.by_normalized_name.keys(), n=1, cutoff=_FUZZY_CUTOFF)
        if not matches:
            return None
        matched_id = self.by_normalized_name[matches[0]]
        return next((a["name"] for a in self.athletes if a["id"] == matched_id), None)


def load_roster(path: str | Path) -> Roster:
    athletes: list[dict] = []
    by_name: dict[str, str] = {}
    skipped: list[dict] = []
    read = 0

    # utf-8-sig, not utf-8: Excel's "CSV UTF-8" export prepends a BOM that
    # plain utf-8 decoding leaves stuck to the first header cell (e.g.
    # '﻿full_name'), which silently breaks that one column's
    # row_get() lookup on every row. utf-8-sig strips a BOM when present
    # and is identical to utf-8 when it isn't, so this is safe either way.
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        missing = missing_required_columns(
            reader.fieldnames, [("athlete name", ["full_name", "full name", "name", "player name", "player", "athlete"])]
        )
        if missing:
            found = ", ".join(reader.fieldnames or []) or "(no header row found)"
            return Roster(
                athletes=[],
                stats={"read": 0, "loaded": 0, "skipped": 0},
                file_error=f"Missing required column: athlete name. Found columns: {found}",
            )

        for line_no, row in enumerate(reader, start=2):
            read += 1
            name = clean_str(row_get(row, "full_name", "full name", "name", "player name", "player", "athlete"))
            if not name:
                skipped.append({"line": line_no, "reason": "missing athlete name"})
                continue
            key = normalize_name(name)
            athlete_id = stable_id("athlete", key)

            athlete: dict = {"id": athlete_id, "name": name}
            position = clean_str(row_get(row, "position"))
            if position:
                athlete["position"] = position
            age_raw = clean_str(row_get(row, "age"))
            if age_raw and age_raw.isdigit():
                athlete["age"] = int(age_raw)

            athletes.append(athlete)
            by_name[key] = athlete_id

    return Roster(
        athletes=athletes,
        by_normalized_name=by_name,
        stats={"read": read, "loaded": len(athletes), "skipped": len(skipped)},
        skipped_rows=skipped,
    )
