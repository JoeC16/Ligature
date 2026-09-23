"""Medical/physio injury log -> Injury.

Keyed on (athlete, body part, onset date) — the closest thing to a natural
key a real injury register has, absent a source-system reference number.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from normalize import clean_str, missing_required_columns, parse_date, row_get, stable_id  # noqa: E402

_EMPTY_RESULT = {
    "injuries": [],
    "edges": {"sustained": []},
    "stats": {"read": 0, "loaded": 0, "skipped": 0},
    "skipped_rows": [],
    "warnings": [],
}

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

    # utf-8-sig, not utf-8 -- see roster.py's load_roster for why (Excel's
    # BOM otherwise breaks the first column's row_get() lookup on every row).
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        missing = missing_required_columns(
            reader.fieldnames,
            [
                ("athlete name", ["Athlete", "Player Name", "name"]),
                ("body part", ["Body Part", "body_part"]),
                ("date of onset", ["Date of Onset", "date"]),
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

            athlete_name = row_get(row, "Athlete", "Player Name", "name")
            athlete_id = roster.resolve(athlete_name)
            body_part = clean_str(row_get(row, "Body Part", "body_part"))
            date = parse_date(row_get(row, "Date of Onset", "date"))

            if athlete_id is None:
                reason = f"unmatched athlete '{athlete_name}'"
                suggestion = roster.suggest(athlete_name)
                if suggestion:
                    reason += f" -- closest roster match: '{suggestion}' (not applied automatically)"
                skipped.append({"line": line_no, "reason": reason})
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
        "file_error": None,
    }
