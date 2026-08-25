"""Athlete identity resolution.

None of the three source systems (GPS vendor, wellness app, medical system)
share an athlete ID with each other or with our schema — the roster file is
the identity anchor all three importers resolve against, by normalized name.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from normalize import clean_str, normalize_name, stable_id


@dataclass
class Roster:
    athletes: list[dict]
    by_normalized_name: dict[str, str] = field(default_factory=dict)

    def resolve(self, raw_name: str | None) -> str | None:
        """Normalized-name -> athlete id, or None if there's no match."""
        key = normalize_name(raw_name)
        if key is None:
            return None
        return self.by_normalized_name.get(key)


def load_roster(path: str | Path) -> Roster:
    athletes: list[dict] = []
    by_name: dict[str, str] = {}

    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            name = clean_str(row.get("full_name") or row.get("name"))
            if not name:
                continue
            key = normalize_name(name)
            athlete_id = stable_id("athlete", key)

            athlete: dict = {"id": athlete_id, "name": name}
            position = clean_str(row.get("position"))
            if position:
                athlete["position"] = position
            age_raw = clean_str(row.get("age"))
            if age_raw and age_raw.isdigit():
                athlete["age"] = int(age_raw)

            athletes.append(athlete)
            by_name[key] = athlete_id

    return Roster(athletes=athletes, by_normalized_name=by_name)
