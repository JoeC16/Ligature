"""Wellness survey export -> WellnessEntry.

One row per athlete per day. Keyed on (athlete, date), so a resynced
duplicate row (same athlete + date submitted twice) MERGEs onto the same
node instead of creating a second entry.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from normalize import missing_required_columns, parse_date, parse_float, row_get, stable_id  # noqa: E402

_EMPTY_RESULT = {
    "wellness_entries": [],
    "edges": {"reported": []},
    "stats": {"read": 0, "loaded": 0, "skipped": 0, "duplicate_rows_merged": 0},
    "skipped_rows": [],
}


def import_wellness(path: str | Path, roster) -> dict:
    entries: list[dict] = []
    reported: list[dict] = []
    skipped: list[dict] = []
    seen_ids: set[str] = set()
    read = 0
    duplicates = 0

    # utf-8-sig, not utf-8 -- see roster.py's load_roster for why (Excel's
    # BOM otherwise breaks the first column's row_get() lookup on every row).
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        missing = missing_required_columns(
            reader.fieldnames,
            [
                ("athlete name", ["athlete", "Player Name", "name"]),
                ("date", ["date", "Session Date"]),
            ],
        )
        if missing:
            found = ", ".join(reader.fieldnames or []) or "(no header row found)"
            return {
                **_EMPTY_RESULT,
                "file_error": f"Missing required column(s): {', '.join(missing)}. Found columns: {found}",
            }

        for line_no, row in enumerate(reader, start=2):
            read += 1

            athlete_name = row_get(row, "athlete", "Player Name", "name")
            athlete_id = roster.resolve(athlete_name)
            date = parse_date(row_get(row, "date", "Session Date"))

            if athlete_id is None:
                reason = f"unmatched athlete '{athlete_name}'"
                suggestion = roster.suggest(athlete_name)
                if suggestion:
                    reason += f" -- closest roster match: '{suggestion}' (not applied automatically)"
                skipped.append({"line": line_no, "reason": reason})
                continue
            if date is None:
                skipped.append({"line": line_no, "reason": "unparseable or missing date"})
                continue

            entry_id = stable_id("wellness", athlete_id, date)
            if entry_id in seen_ids:
                duplicates += 1
            seen_ids.add(entry_id)

            entries.append(
                {
                    "id": entry_id,
                    "date": date,
                    "sleep_hours": parse_float(row_get(row, "sleep_hrs", "sleep_hours")),
                    "sleep_quality": parse_float(row_get(row, "sleep_qual", "sleep_quality")),
                    "hrv": parse_float(row_get(row, "hrv_ms", "hrv")),
                    "soreness": parse_float(row_get(row, "soreness_0_10", "soreness")),
                    "mood": parse_float(row_get(row, "mood_1_5", "mood")),
                }
            )
            reported.append({"athlete_id": athlete_id, "wellness_id": entry_id})

    return {
        "wellness_entries": entries,
        "edges": {"reported": reported},
        "stats": {"read": read, "loaded": read - len(skipped), "skipped": len(skipped), "duplicate_rows_merged": duplicates},
        "skipped_rows": skipped,
        "file_error": None,
    }
