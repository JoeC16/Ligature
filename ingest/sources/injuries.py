"""Medical/physio injury log -> Injury.

Keyed on (athlete, body part, onset date) — the closest thing to a natural
key a real injury register has, absent a source-system reference number.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from normalize import clean_str, parse_date, row_get, stable_id  # noqa: E402

_SEVERITY_ALIASES = {
    "minor": "minor",
    "mild": "minor",
    "moderate": "moderate",
    "mod": "moderate",
    "severe": "severe",
    "major": "severe",
}


def _normalize_severity(raw: str | None) -> tuple[str | None, bool]:
    """Returns (severity, was_unrecognized). Unrecognized values pass
    through as-is rather than being dropped — better a physio sees the
    club's own wording than the row silently disappearing."""
    if raw is None:
        return None, False
    key = raw.strip().lower()
    if key in _SEVERITY_ALIASES:
        return _SEVERITY_ALIASES[key], False
    return raw.strip(), True


def import_injuries(path: str | Path, roster) -> dict:
    injuries: list[dict] = []
    sustained: list[dict] = []
    skipped: list[dict] = []
    warnings: list[dict] = []
    read = 0

    with open(path, newline="", encoding="utf-8") as f:
        for line_no, row in enumerate(csv.DictReader(f), start=2):
            read += 1

            athlete_name = row_get(row, "Athlete", "Player Name", "name")
            athlete_id = roster.resolve(athlete_name)
            body_part = clean_str(row_get(row, "Body Part", "body_part"))
            date = parse_date(row_get(row, "Date of Onset", "date"))

            if athlete_id is None:
                skipped.append({"line": line_no, "reason": f"unmatched athlete '{athlete_name}'"})
                continue
            if date is None:
                skipped.append({"line": line_no, "reason": "unparseable or missing date of onset"})
                continue
            if not body_part:
                skipped.append({"line": line_no, "reason": "missing body part"})
                continue

            severity, unrecognized = _normalize_severity(row_get(row, "Severity", "severity"))
            if unrecognized:
                warnings.append({"line": line_no, "reason": f"unrecognized severity '{severity}', kept as-is"})

            injury_id = stable_id("injury", athlete_id, body_part, date)
            injuries.append(
                {
                    "id": injury_id,
                    "type": clean_str(row_get(row, "Injury Type", "type")),
                    "body_part": body_part,
                    "date": date,
                    "severity": severity,
                    "mechanism": clean_str(row_get(row, "Mechanism", "mechanism")),
                }
            )
            sustained.append({"athlete_id": athlete_id, "injury_id": injury_id})

    return {
        "injuries": injuries,
        "edges": {"sustained": sustained},
        "stats": {"read": read, "loaded": read - len(skipped), "skipped": len(skipped)},
        "skipped_rows": skipped,
        "warnings": warnings,
    }
